from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Awaitable, Callable
from typing import Any

from .config import Settings
from .event_store import EventStore
from .formatters import shot_to_dict


VISUAL_PROMPT = """You are the visual perception layer for a developer copilot.
Describe the active application, terminal/editor state, visible errors, file names,
UI controls, and any text that helps debug the user's current workflow.
Prefer concise, factual observations. Include visible terminal output and stack traces."""

AUDIO_PROMPT = """Summarize the developer's spoken issue and intent.
Extract bug symptoms, expected behavior, observed behavior, filenames, commands,
error messages, and hypotheses. Keep the summary grounded in what was said."""


class VideoDBService:
    """Thin compatibility layer around the real VideoDB Python SDK."""

    def __init__(self, settings: Settings, store: EventStore) -> None:
        self.settings = settings
        self.store = store
        self._conn: Any | None = None
        self._coll: Any | None = None

    def _require_key(self) -> None:
        key = self.settings.video_db_api_key or os.getenv("VIDEO_DB_API_KEY") or os.getenv(
            "VIDEODB_API_KEY"
        )
        if not key:
            raise RuntimeError(
                "VideoDB API key is not configured. Set VIDEO_DB_API_KEY in the environment "
                "or in the project .env file."
            )

    def conn(self) -> Any:
        self._require_key()
        if self._conn is None:
            import videodb

            if self.settings.video_db_api_key:
                self._conn = videodb.connect(api_key=self.settings.video_db_api_key)
            else:
                self._conn = videodb.connect()
        return self._conn

    def collection(self) -> Any:
        if self._coll is None:
            conn = self.conn()
            collection_id = self.settings.videodb_collection_id
            try:
                self._coll = conn.get_collection(collection_id)
            except TypeError:
                self._coll = conn.get_collection()
        return self._coll

    async def create_capture_session(
        self,
        *,
        end_user_id: str,
        issue_text: str | None,
        metadata: dict[str, Any] | None,
        ws_connection_id: str | None,
        callback_url: str | None,
    ) -> dict[str, Any]:
        session, token = await asyncio.to_thread(
            self._create_capture_session_sync,
            end_user_id,
            issue_text,
            metadata or {},
            ws_connection_id,
            callback_url,
        )
        session_id = str(getattr(session, "id", None) or getattr(session, "session_id", None))
        record = self.store.upsert_session(
            session_id,
            end_user_id=end_user_id,
            collection_id=getattr(session, "collection_id", None)
            or self.settings.videodb_collection_id,
            status=getattr(session, "status", None) or "created",
            issue_text=issue_text,
            metadata=metadata or {},
            ws_connection_id=ws_connection_id,
            callback_url=callback_url,
        )
        return {
            "session_id": session_id,
            "client_token": token,
            "token_ttl_seconds": self.settings.client_token_ttl_seconds,
            "collection_id": record.get("collection_id"),
            "videodb_api_url": self.settings.videodb_api_url,
        }

    def _create_capture_session_sync(
        self,
        end_user_id: str,
        issue_text: str | None,
        metadata: dict[str, Any],
        ws_connection_id: str | None,
        callback_url: str | None,
    ) -> tuple[Any, str]:
        metadata = {
            "app": "screen-aware",
            "issue_text": issue_text or "",
            **metadata,
        }
        kwargs = {
            "end_user_id": end_user_id,
            "metadata": metadata,
        }
        if ws_connection_id:
            kwargs["ws_connection_id"] = ws_connection_id
        if callback_url:
            kwargs["callback_url"] = callback_url

        coll = self.collection()
        conn = self.conn()
        create_attempts: list[Callable[[], Any]] = [
            lambda: coll.create_capture_session(**kwargs),
            lambda: conn.create_capture_session(
                collection_id=self.settings.videodb_collection_id, **kwargs
            ),
            lambda: conn.create_capture_session(**kwargs),
        ]
        last_error: Exception | None = None
        for attempt in create_attempts:
            try:
                session = attempt()
                break
            except TypeError as exc:
                last_error = exc
        else:
            raise RuntimeError(f"Unable to create VideoDB CaptureSession: {last_error}") from last_error

        token_fn = conn.generate_client_token
        try:
            token = token_fn(expires_in=self.settings.client_token_ttl_seconds)
        except TypeError:
            try:
                token = token_fn(self.settings.client_token_ttl_seconds)
            except TypeError:
                token = token_fn()
        return session, str(token)

    async def start_ai_pipelines(self, session_id: str, rtstreams: list[dict[str, Any]]) -> None:
        await asyncio.to_thread(self._start_ai_pipelines_sync, session_id, rtstreams)

    def _start_ai_pipelines_sync(self, session_id: str, rtstreams: list[dict[str, Any]]) -> None:
        session = self.store.get_session(session_id) or {}
        existing_indexes = session.get("indexes") or []
        if existing_indexes:
            return

        ws_id = self.store.read_state().get("backend", {}).get("ws_connection_id")
        indexes: list[dict[str, Any]] = []
        for stream_info in rtstreams:
            rtstream_id = stream_info.get("rtstream_id") or stream_info.get("id")
            if not rtstream_id:
                continue
            media_types = [str(item).lower() for item in stream_info.get("media_types", [])]
            name = stream_info.get("name") or stream_info.get("rtstream_name")
            rtstream = self._get_rtstream(str(rtstream_id))

            if "audio" in media_types or (isinstance(name, str) and "mic" in name):
                transcript_status = self._call_supported(
                    rtstream.start_transcript,
                    ws_connection_id=ws_id,
                    engine=None,
                )
                audio_index = self._call_supported(
                    rtstream.index_audio,
                    prompt=AUDIO_PROMPT,
                    batch_config={"type": "word", "value": self.settings.audio_batch_words},
                    model_name=self.settings.visual_model,
                    name="screen_aware_audio",
                    ws_connection_id=ws_id,
                )
                indexes.append(
                    {
                        "kind": "audio",
                        "rtstream_id": rtstream_id,
                        "rtstream_name": name,
                        "transcript_status": self._safe_repr(transcript_status),
                        "index_id": self._index_id(audio_index),
                    }
                )

            if "video" in media_types or (isinstance(name, str) and "display" in name):
                visual_index = self._call_supported(
                    rtstream.index_visuals,
                    prompt=VISUAL_PROMPT,
                    batch_config={
                        "type": "time",
                        "value": self.settings.visual_batch_seconds,
                        "frame_count": self.settings.visual_frame_count,
                    },
                    model_name=self.settings.visual_model,
                    name="screen_aware_visual",
                    ws_connection_id=ws_id,
                )
                indexes.append(
                    {
                        "kind": "visual",
                        "rtstream_id": rtstream_id,
                        "rtstream_name": name,
                        "index_id": self._index_id(visual_index),
                    }
                )

        self.store.upsert_session(session_id, indexes=indexes, indexing_status="started")

    def _get_rtstream(self, rtstream_id: str) -> Any:
        conn = self.conn()
        if hasattr(conn, "get_rtstream"):
            return conn.get_rtstream(rtstream_id)
        coll = self.collection()
        return coll.get_rtstream(rtstream_id)

    @staticmethod
    def _call_supported(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            signature = None

        if signature:
            accepted = {}
            supports_var_kwargs = any(
                param.kind == inspect.Parameter.VAR_KEYWORD
                for param in signature.parameters.values()
            )
            for key, value in kwargs.items():
                if value is None:
                    continue
                if supports_var_kwargs or key in signature.parameters:
                    accepted[key] = value
            try:
                return fn(*args, **accepted)
            except TypeError:
                pass

        try:
            return fn(*args, **{key: value for key, value in kwargs.items() if value is not None})
        except TypeError:
            return fn(*args)

    @staticmethod
    def _index_id(index: Any) -> str | None:
        for name in ("rtstream_index_id", "rtstreamIndexId", "id", "index_id"):
            value = getattr(index, name, None)
            if value:
                return str(value)
        return None

    @staticmethod
    def _safe_repr(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool, dict, list)):
            return value
        return repr(value)

    async def search_session(
        self,
        *,
        query: str,
        session_id: str | None,
        modalities: set[str],
        limit: int,
        score_threshold: float,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        return await asyncio.to_thread(
            self._search_session_sync,
            query,
            session_id,
            modalities,
            limit,
            score_threshold,
        )

    def _search_session_sync(
        self,
        query: str,
        session_id: str | None,
        modalities: set[str],
        limit: int,
        score_threshold: float,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        session = self.store.get_session(session_id)
        warnings: list[str] = []
        if not session:
            return [], ["No active Screen-Aware session is recorded in local state."]

        candidates = self._matching_rtstreams(session, modalities)
        shots: list[dict[str, Any]] = []
        for stream in candidates:
            if len(shots) >= limit:
                break
            rtstream_id = stream.get("rtstream_id") or stream.get("id")
            if not rtstream_id:
                continue
            try:
                result = self._search_rtstream(str(rtstream_id), query, score_threshold, limit)
                for shot in result:
                    shot.setdefault("rtstream_id", rtstream_id)
                    shot.setdefault("rtstream_name", stream.get("name"))
                    shots.append(shot)
                    if len(shots) >= limit:
                        break
            except Exception as exc:  # VideoDB SDK exposes several runtime exceptions.
                warnings.append(f"VideoDB RTStream search failed for {rtstream_id}: {type(exc).__name__}: {exc}")

        if not shots and session.get("exported_video_id"):
            try:
                shots.extend(
                    self._search_exported_video(
                        str(session["exported_video_id"]), query, score_threshold, limit
                    )
                )
            except Exception as exc:
                warnings.append(f"VideoDB exported-video search failed: {type(exc).__name__}: {exc}")
        return shots[:limit], warnings

    @staticmethod
    def _matching_rtstreams(session: dict[str, Any], modalities: set[str]) -> list[dict[str, Any]]:
        result = []
        for stream in session.get("rtstreams") or []:
            media_types = {str(item).lower() for item in stream.get("media_types", [])}
            name = str(stream.get("name", "")).lower()
            include = False
            if "visual" in modalities and ("video" in media_types or "display" in name):
                include = True
            if "audio" in modalities and ("audio" in media_types or "mic" in name):
                include = True
            if include:
                result.append(stream)
        return result

    def _search_rtstream(
        self, rtstream_id: str, query: str, score_threshold: float, limit: int
    ) -> list[dict[str, Any]]:
        rtstream = self._get_rtstream(rtstream_id)
        try:
            result = rtstream.search(
                query=query,
                score_threshold=score_threshold,
                result_threshold=limit,
            )
        except TypeError:
            result = rtstream.search(
                {
                    "query": query,
                    "scoreThreshold": score_threshold,
                    "resultThreshold": limit,
                }
            )
        return self._shots_from_result(result)

    def _search_exported_video(
        self, video_id: str, query: str, score_threshold: float, limit: int
    ) -> list[dict[str, Any]]:
        video = self.collection().get_video(video_id)
        try:
            result = video.search(query=query, score_threshold=score_threshold, result_threshold=limit)
        except TypeError:
            result = video.search(query)
        return self._shots_from_result(result)

    @staticmethod
    def _shots_from_result(result: Any) -> list[dict[str, Any]]:
        if result is None:
            return []
        if hasattr(result, "get_shots"):
            raw = result.get_shots()
        elif hasattr(result, "getShots"):
            raw = result.getShots()
        else:
            raw = getattr(result, "shots", [])
        return [shot_to_dict(shot) if not isinstance(shot, dict) else shot for shot in raw]

    async def run_websocket_listener(
        self,
        on_event: Callable[[dict[str, Any]], Awaitable[None]],
        stop_event: asyncio.Event,
    ) -> None:
        backoff = 1.0
        while not stop_event.is_set():
            try:
                await self._listen_once(on_event, stop_event)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.store.update_backend(ws_status="error", last_error=f"{type(exc).__name__}: {exc}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _listen_once(
        self,
        on_event: Callable[[dict[str, Any]], Awaitable[None]],
        stop_event: asyncio.Event,
    ) -> None:
        wrapper = await asyncio.to_thread(self._connect_websocket)
        ws = await self._maybe_await(wrapper.connect())
        connection_id = getattr(ws, "connection_id", None) or getattr(wrapper, "connection_id", None)
        self.store.update_backend(
            ws_connection_id=connection_id,
            ws_status="connected",
            last_error=None,
        )
        async for event in self._event_stream(ws):
            if stop_event.is_set():
                break
            await on_event(event)

    def _connect_websocket(self) -> Any:
        conn = self.conn()
        try:
            return conn.connect_websocket(collection_id=self.settings.videodb_collection_id)
        except TypeError:
            return conn.connect_websocket()

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    async def _event_stream(self, ws: Any):
        stream = None
        if hasattr(ws, "stream"):
            stream = ws.stream()
        elif hasattr(ws, "receive"):
            stream = ws.receive()
        if stream is None:
            raise RuntimeError("VideoDB WebSocket object does not expose stream() or receive().")
        async for event in stream:
            yield event

