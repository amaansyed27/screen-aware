from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from .config import get_settings
from .event_store import EventStore
from .formatters import compact_event
from .live_assistant import LiveAssistant
from .videodb_service import VideoDBService


settings = get_settings()
store = EventStore(settings.data_dir)
videodb_service = VideoDBService(settings, store)
live_assistant = LiveAssistant(settings)


class LiveClients:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            clients = list(self._clients)
        stale: list[WebSocket] = []
        for client in clients:
            try:
                await client.send_json(message)
            except RuntimeError:
                stale.append(client)
        if stale:
            async with self._lock:
                for client in stale:
                    self._clients.discard(client)


live_clients = LiveClients()


async def handle_videodb_event(event: dict[str, Any]) -> None:
    normalized = store.append_event(event)
    store.update_session_from_event(normalized)
    await live_clients.broadcast({"type": "videodb_event", "event": compact_event(normalized)})

    lifecycle = normalized.get("event")
    if lifecycle == "capture_session.active":
        session_id = normalized.get("capture_session_id")
        data = normalized.get("data") if isinstance(normalized.get("data"), dict) else {}
        rtstreams = data.get("rtstreams") if isinstance(data.get("rtstreams"), list) else []
        if isinstance(session_id, str) and rtstreams:
            await videodb_service.start_ai_pipelines(session_id, rtstreams)
            session = store.get_session(session_id)
            await live_clients.broadcast({"type": "status", "state": public_state(session)})


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop_event = asyncio.Event()
    task = asyncio.create_task(videodb_service.run_websocket_listener(handle_videodb_event, stop_event))
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Screen-Aware API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:5173", "http://localhost:5173"],
    allow_origin_regex=r"^(http://(127\.0\.0\.1|localhost):\d+|tauri://localhost|https://tauri\.localhost)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    end_user_id: str = Field(default="local-developer", min_length=1, max_length=120)
    issue_text: str | None = Field(default=None, max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClientEventRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str
    event: str
    data: dict[str, Any] = Field(default_factory=dict)


class LiveMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    session_id: str
    message: str = Field(..., min_length=1, max_length=1600)
    source: str = Field(default="typed", max_length=40)


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(..., min_length=1, max_length=500)
    session_id: str | None = None
    modalities: list[str] = Field(default_factory=lambda: ["visual", "audio"])
    limit: int = Field(default=8, ge=1, le=25)
    lookback_seconds: int = Field(default=900, ge=10, le=86400)
    score_threshold: float = Field(default=0.35, ge=0, le=1)


def safe_path_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip(".-") or "unknown"


def public_state(session: dict[str, Any] | None = None) -> dict[str, Any]:
    state = store.read_state()
    current = session if session is not None else store.get_session()
    return {
        "backend": state.get("backend", {}),
        "current_session_id": state.get("current_session_id"),
        "session": current,
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "state": public_state()}


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return public_state()


@app.get("/api/events")
async def events(limit: int = 50) -> dict[str, Any]:
    limit = min(max(limit, 1), settings.max_recent_events)
    return {"events": [compact_event(event) for event in store.recent_events(limit=limit)]}


@app.post("/api/sessions")
async def create_session(request: CreateSessionRequest) -> dict[str, Any]:
    ws_id = store.read_state().get("backend", {}).get("ws_connection_id")
    callback_url = settings.public_webhook_url
    result = await videodb_service.create_capture_session(
        end_user_id=request.end_user_id,
        issue_text=request.issue_text,
        metadata=request.metadata,
        ws_connection_id=ws_id,
        callback_url=callback_url,
    )
    await live_clients.broadcast({"type": "status", "state": public_state()})
    return result


@app.post("/api/capture/client-event")
async def client_event(request: ClientEventRequest) -> dict[str, Any]:
    normalized = store.record_client_event(
        request.session_id,
        {
            "event": request.event,
            "data": request.data,
        },
    )
    if request.event in {"capture.started", "capture.stopped"}:
        status_value = "client_capturing" if request.event == "capture.started" else "client_stopped"
        store.upsert_session(request.session_id, client_status=status_value)
    await live_clients.broadcast({"type": "videodb_event", "event": compact_event(normalized)})
    await live_clients.broadcast({"type": "status", "state": public_state()})
    return {"ok": True}


async def _search_live_context(
    *,
    session_id: str,
    message: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    try:
        results, search_warnings = await asyncio.wait_for(
            videodb_service.search_session(
                query=message,
                session_id=session_id,
                modalities={"visual", "audio"},
                limit=5,
                score_threshold=0.2,
            ),
            timeout=settings.live_ai_context_timeout_seconds,
        )
        warnings.extend(search_warnings)
        return results, warnings
    except TimeoutError:
        warnings.append("VideoDB context search timed out; using recent live events only.")
    except Exception as exc:  # noqa: BLE001 - live replies should degrade, not fail the overlay.
        warnings.append(f"VideoDB context search failed: {exc}")
    return [], warnings


@app.post("/api/live/messages")
async def live_message(request: LiveMessageRequest) -> dict[str, Any]:
    session = store.get_session(request.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    user_event = store.record_client_event(
        request.session_id,
        {
            "event": "user.live_message",
            "data": {
                "text": request.message,
                "source": request.source,
            },
        },
    )
    await live_clients.broadcast({"type": "videodb_event", "event": compact_event(user_event)})

    search_results, warnings = await _search_live_context(
        session_id=request.session_id,
        message=request.message,
    )
    recent = store.recent_events(
        limit=settings.live_ai_max_context_events,
        session_id=request.session_id,
    )
    agent_name = store.read_state().get("backend", {}).get("mcp_agent")
    try:
        reply = await live_assistant.respond(
            user_message=request.message,
            session=session,
            agent_name=agent_name if isinstance(agent_name, str) else None,
            recent_events=recent,
            search_results=search_results,
            warnings=warnings,
        )
    except Exception as exc:  # noqa: BLE001 - report the failure in-band to the overlay.
        reply = {
            "ok": False,
            "status": "error",
            "provider": settings.live_ai_provider,
            "model": settings.live_ai_model,
            "text": f"Live reply failed: {exc}",
            "warnings": warnings,
        }

    assistant_event = store.record_client_event(
        request.session_id,
        {
            "event": "assistant.live_reply",
            "data": {
                "text": reply["text"],
                "ok": reply.get("ok", False),
                "status": reply.get("status"),
                "provider": reply.get("provider"),
                "model": reply.get("model"),
                "source": request.source,
                "warnings": reply.get("warnings", []),
            },
        },
    )
    compact_reply = compact_event(assistant_event)
    await live_clients.broadcast({"type": "assistant_reply", "message": compact_reply})
    await live_clients.broadcast({"type": "videodb_event", "event": compact_reply})
    await live_clients.broadcast({"type": "status", "state": public_state(session)})
    return {"ok": True, "reply": compact_reply, "warnings": reply.get("warnings", [])}


@app.post("/api/window-capture/segments")
async def window_capture_segment(
    background_tasks: BackgroundTasks,
    session_id: str = Form(...),
    sequence: int = Form(...),
    source_label: str = Form("Selected window"),
    contains_audio: bool = Form(False),
    store_capture: bool = Form(True),
    started_at_ms: int | None = Form(None),
    ended_at_ms: int | None = Form(None),
    segment: UploadFile = File(...),
) -> dict[str, Any]:
    if sequence < 0:
        raise HTTPException(status_code=400, detail="sequence must be non-negative")

    session_dir = settings.data_dir / "window-captures" / safe_path_part(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    file_path = session_dir / f"segment-{sequence:04d}.webm"
    bytes_written = 0
    with file_path.open("wb") as handle:
        while chunk := await segment.read(1024 * 1024):
            bytes_written += len(chunk)
            handle.write(chunk)
    queued = store_capture and bytes_written > 0

    store.record_client_event(
        session_id,
        {
            "event": "window.segment.received",
            "data": {
                "sequence": sequence,
                "source_label": source_label,
                "file_path": str(file_path),
                "bytes": bytes_written,
                "contains_audio": contains_audio,
                "store": store_capture,
                "started_at_ms": started_at_ms,
                "ended_at_ms": ended_at_ms,
                "text": (
                    f"Received window capture segment {sequence} from {source_label}; "
                    + ("VideoDB indexing queued." if queued else "not queued for storage.")
                ),
            },
        },
    )
    store.append_session_item(
        session_id,
        "window_segments",
        {
            "sequence": sequence,
            "source_label": source_label,
            "file_path": str(file_path),
            "bytes": bytes_written,
            "contains_audio": contains_audio,
            "store": store_capture,
            "started_at_ms": started_at_ms,
            "ended_at_ms": ended_at_ms,
        },
    )
    if queued:
        background_tasks.add_task(
            videodb_service.ingest_window_capture_segment,
            session_id=session_id,
            file_path=file_path,
            sequence=sequence,
            source_label=source_label,
            contains_audio=contains_audio,
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
        )
        store.upsert_session(session_id, indexing_status="window_segment_queued")
    await live_clients.broadcast({"type": "status", "state": public_state()})
    return {"ok": True, "path": str(file_path), "bytes": bytes_written, "queued": queued}


@app.post("/api/query")
async def query(request: QueryRequest) -> dict[str, Any]:
    session = store.get_session(request.session_id)
    results, warnings = await videodb_service.search_session(
        query=request.query,
        session_id=request.session_id,
        modalities={item.lower() for item in request.modalities},
        limit=request.limit,
        score_threshold=request.score_threshold,
    )
    recent = [
        compact_event(event)
        for event in store.recent_events(
            limit=request.limit,
            since_unix=None,
            session_id=request.session_id or (session or {}).get("session_id"),
        )
    ]
    return {
        "query": request.query,
        "session": session,
        "videodb_results": results,
        "recent_events": recent,
        "warnings": warnings,
    }


@app.post("/webhooks/videodb")
async def videodb_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    await handle_videodb_event(payload)
    return {"ok": True}


@app.websocket("/api/live")
async def live(websocket: WebSocket) -> None:
    await live_clients.connect(websocket)
    try:
        await websocket.send_json({"type": "status", "state": public_state()})
        await websocket.send_json(
            {
                "type": "events",
                "events": [compact_event(event) for event in store.recent_events(limit=25)],
            }
        )
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await live_clients.disconnect(websocket)


def main() -> None:
    uvicorn.run(
        "screen_aware.api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
