from __future__ import annotations

import atexit
import asyncio
import os
import time
from enum import Enum
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import get_settings
from .event_store import EventStore, utc_now_iso
from .formatters import compact_event, context_markdown, dumps, live_watch_markdown
from .videodb_service import VideoDBService


mcp = FastMCP("screen_aware_mcp")


class ResponseFormat(str, Enum):
    markdown = "markdown"
    json = "json"


class LiveWatchMode(str, Enum):
    diagnose = "diagnose"
    live_edit = "live_edit"


class AnalyzeScreenInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="The debugging question or visual issue to resolve.",
    )
    session_id: str | None = Field(default=None, description="Optional CaptureSession ID.")
    lookback_seconds: int = Field(
        default=900,
        ge=10,
        le=86400,
        description="How far back to include live context events.",
    )
    limit: int = Field(default=8, ge=1, le=25, description="Maximum matches/events to return.")
    score_threshold: float = Field(
        default=0.35,
        ge=0,
        le=1,
        description="Minimum VideoDB semantic relevance score for RTStream search.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.markdown)


class QueryWorkflowInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(..., min_length=1, max_length=500)
    session_id: str | None = None
    modalities: list[str] = Field(default_factory=lambda: ["visual", "audio"])
    limit: int = Field(default=12, ge=1, le=50)
    response_format: ResponseFormat = Field(default=ResponseFormat.markdown)

    @field_validator("modalities")
    @classmethod
    def normalize_modalities(cls, value: list[str]) -> list[str]:
        allowed = {"visual", "audio"}
        normalized = [item.lower() for item in value]
        unknown = sorted(set(normalized) - allowed)
        if unknown:
            raise ValueError(f"Unsupported modalities: {', '.join(unknown)}")
        return normalized or ["visual", "audio"]


class LiveContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    lookback_seconds: int = Field(default=300, ge=10, le=86400)
    response_format: ResponseFormat = Field(default=ResponseFormat.markdown)


class WatchLiveInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    objective: str = Field(
        default="Watch the active capture while the user reproduces a coding issue.",
        min_length=1,
        max_length=500,
        description="Natural language objective, e.g. 'watch while I reproduce the blank canvas bug'.",
    )
    mode: LiveWatchMode = Field(
        default=LiveWatchMode.diagnose,
        description=(
            "diagnose returns observations and asks before editing; live_edit returns evidence "
            "intended for the agent to immediately inspect and patch code."
        ),
    )
    duration_seconds: int = Field(
        default=45,
        ge=5,
        le=180,
        description="How long to keep the MCP call open while the user demonstrates the issue.",
    )
    settle_seconds: int = Field(
        default=3,
        ge=0,
        le=30,
        description="Extra time after the watch window for late transcript/index events.",
    )
    limit: int = Field(default=12, ge=1, le=30)
    response_format: ResponseFormat = Field(default=ResponseFormat.markdown)


def _service() -> tuple[EventStore, VideoDBService]:
    settings = get_settings()
    store = EventStore(settings.data_dir)
    return store, VideoDBService(settings, store)


def _agent_name() -> str:
    return (
        os.getenv("SCREEN_AWARE_AGENT_NAME")
        or os.getenv("MCP_CLIENT_NAME")
        or os.getenv("TERM_PROGRAM")
        or "MCP coding agent"
    )


def _mark_agent_seen(store: EventStore, tool_name: str) -> None:
    agent = _agent_name()
    store.update_backend(
        mcp_status="connected",
        mcp_agent=agent,
        mcp_last_seen=utc_now_iso(),
        mcp_tool=tool_name,
    )
    store.append_event(
        {
            "source": "mcp",
            "channel": "agent",
            "event": "mcp.tool_called",
            "data": {
                "agent": agent,
                "tool": tool_name,
                "text": f"{agent} used {tool_name}",
            },
        }
    )


def _mark_agent_offline() -> None:
    try:
        store, _ = _service()
        store.update_backend(
            mcp_status="offline",
            mcp_stopped_at=utc_now_iso(),
        )
    except Exception:
        pass


def _build_payload(
    *,
    query: str | None,
    session: dict[str, Any] | None,
    results: list[dict[str, Any]],
    recent_events: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "query": query,
        "session": session,
        "videodb_results": results,
        "recent_events": [compact_event(event) for event in recent_events],
        "warnings": warnings,
    }


@mcp.tool(
    name="screen_aware_watch_live_issue",
    annotations={
        "title": "Watch Live Issue",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def screen_aware_watch_live_issue(params: WatchLiveInput) -> str:
    """Keep the MCP call open while the user demonstrates a bug, then return evidence.

    Use this for simple user prompts like "use Screen-Aware live" or "watch while I show you".
    In `diagnose` mode, do not edit files after the tool returns; summarize what was observed,
    explain likely fixes, and ask for approval. In `live_edit` mode, use the returned evidence
    to start inspecting and patching the project immediately after the watch window ends.
    """

    store, service = _service()
    tool_name = f"screen_aware_watch_live_issue:{params.mode.value}"
    _mark_agent_seen(store, tool_name)
    session = store.get_session()
    session_id = (session or {}).get("session_id")
    started_at = time.time()
    store.update_backend(
        mcp_live_mode=params.mode.value,
        mcp_live_objective=params.objective,
        mcp_live_started_at=utc_now_iso(),
        mcp_live_duration_seconds=params.duration_seconds,
    )
    store.append_event(
        {
            "source": "mcp",
            "channel": "agent",
            "event": "mcp.live_watch_started",
            "capture_session_id": session_id,
            "data": {
                "agent": _agent_name(),
                "mode": params.mode.value,
                "duration_seconds": params.duration_seconds,
                "text": f"{_agent_name()} is watching live: {params.objective}",
            },
        }
    )

    await asyncio.sleep(params.duration_seconds)
    if params.settle_seconds:
        await asyncio.sleep(params.settle_seconds)

    session = store.get_session(session_id if isinstance(session_id, str) else None)
    recent = store.recent_events(
        limit=params.limit,
        since_unix=started_at,
        session_id=session_id if isinstance(session_id, str) else None,
    )
    results, warnings = await service.search_session(
        query=params.objective,
        session_id=session_id if isinstance(session_id, str) else None,
        modalities={"visual", "audio"},
        limit=params.limit,
        score_threshold=0.25,
    )
    payload = {
        "mode": params.mode.value,
        "objective": params.objective,
        "watched_seconds": params.duration_seconds,
        "session": session,
        "videodb_results": results,
        "recent_events": [compact_event(event) for event in recent],
        "warnings": warnings,
        "agent_instruction": (
            "Diagnostic mode: explain what you saw, likely root cause, proposed fix, and ask "
            "the user before editing."
            if params.mode == LiveWatchMode.diagnose
            else "Live edit mode: use this evidence to inspect code, patch the smallest likely "
            "fix, and run relevant verification."
        ),
    }
    store.update_backend(
        mcp_live_mode=None,
        mcp_live_completed_at=utc_now_iso(),
        mcp_tool=tool_name,
        mcp_last_seen=utc_now_iso(),
    )
    store.append_event(
        {
            "source": "mcp",
            "channel": "agent",
            "event": "mcp.live_watch_completed",
            "capture_session_id": session_id,
            "data": {
                "agent": _agent_name(),
                "mode": params.mode.value,
                "text": f"{_agent_name()} finished live watch.",
            },
        }
    )
    return dumps(payload) if params.response_format == ResponseFormat.json else live_watch_markdown(payload)


@mcp.tool(
    name="screen_aware_analyze_screen_context",
    annotations={
        "title": "Analyze Screen Context",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def screen_aware_analyze_screen_context(params: AnalyzeScreenInput) -> str:
    """Search the active VideoDB capture stream and recent live events for debugging context.

    Use this when the user asks the CLI agent to look at the screen, inspect a visible error,
    understand terminal/editor state, or combine spoken issue context with visual evidence.
    Returns VideoDB semantic RTStream matches plus recent transcript, visual, and audio events.
    """

    store, service = _service()
    _mark_agent_seen(store, "screen_aware_analyze_screen_context")
    session = store.get_session(params.session_id)
    results, warnings = await service.search_session(
        query=params.query,
        session_id=params.session_id,
        modalities={"visual", "audio"},
        limit=params.limit,
        score_threshold=params.score_threshold,
    )
    recent = store.recent_events(
        limit=params.limit,
        since_unix=time.time() - params.lookback_seconds,
        session_id=params.session_id or (session or {}).get("session_id"),
    )
    payload = _build_payload(
        query=params.query,
        session=session,
        results=results,
        recent_events=recent,
        warnings=warnings,
    )
    return dumps(payload) if params.response_format == ResponseFormat.json else context_markdown(payload)


@mcp.tool(
    name="screen_aware_query_workflow_history",
    annotations={
        "title": "Query Workflow History",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def screen_aware_query_workflow_history(params: QueryWorkflowInput) -> str:
    """Query VideoDB indexed RTStreams or exported capture video for prior workflow context.

    Use this when the agent needs to answer questions such as "what command did I run before
    the error?", "what file was visible?", or "what did I say the expected behavior was?".
    The tool searches VideoDB semantic indexes for visual/audio modalities and includes local
    event history as supporting evidence.
    """

    store, service = _service()
    _mark_agent_seen(store, "screen_aware_query_workflow_history")
    session = store.get_session(params.session_id)
    results, warnings = await service.search_session(
        query=params.query,
        session_id=params.session_id,
        modalities=set(params.modalities),
        limit=params.limit,
        score_threshold=0.3,
    )
    recent = store.recent_events(
        limit=params.limit,
        session_id=params.session_id or (session or {}).get("session_id"),
    )
    payload = _build_payload(
        query=params.query,
        session=session,
        results=results,
        recent_events=recent,
        warnings=warnings,
    )
    return dumps(payload) if params.response_format == ResponseFormat.json else context_markdown(payload)


@mcp.tool(
    name="screen_aware_get_live_context",
    annotations={
        "title": "Get Live Context",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def screen_aware_get_live_context(params: LiveContextInput) -> str:
    """Return the latest Screen-Aware events without running a semantic search."""

    store, _ = _service()
    _mark_agent_seen(store, "screen_aware_get_live_context")
    state = store.read_state()
    session = store.get_session()
    events = store.recent_events(
        limit=params.limit,
        since_unix=time.time() - params.lookback_seconds,
        session_id=(session or {}).get("session_id"),
    )
    payload = {
        "backend": state.get("backend", {}),
        "session": session,
        "recent_events": [compact_event(event) for event in events],
    }
    if params.response_format == ResponseFormat.json:
        return dumps(payload)
    lines = ["# Live Screen-Aware Context", ""]
    backend = payload["backend"] or {}
    lines.append(f"WebSocket: `{backend.get('ws_status', 'unknown')}`")
    if session:
        lines.append(f"Session `{session.get('session_id')}`: `{session.get('status', 'unknown')}`")
    lines.append("")
    lines.append("## Events")
    for event in payload["recent_events"]:
        lines.append(f"- `{event.get('ts')}` `{event.get('channel') or event.get('event')}`: {event.get('text')}")
    if not payload["recent_events"]:
        lines.append("- No live events in the selected window.")
    return "\n".join(lines)


@mcp.tool(
    name="screen_aware_get_capture_status",
    annotations={
        "title": "Get Capture Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def screen_aware_get_capture_status(response_format: ResponseFormat = ResponseFormat.markdown) -> str:
    """Return current CaptureSession, RTStream, and indexing status from local state."""

    store, _ = _service()
    _mark_agent_seen(store, "screen_aware_get_capture_status")
    state = store.read_state()
    session = store.get_session()
    payload = {"backend": state.get("backend", {}), "session": session}
    if response_format == ResponseFormat.json:
        return dumps(payload)
    lines = ["# Screen-Aware Capture Status", ""]
    backend = payload["backend"] or {}
    lines.append(f"- WebSocket status: `{backend.get('ws_status', 'unknown')}`")
    lines.append(f"- WebSocket ID: `{backend.get('ws_connection_id')}`")
    if not session:
        lines.append("- Session: none")
        return "\n".join(lines)
    lines.append(f"- Session: `{session.get('session_id')}`")
    lines.append(f"- Status: `{session.get('status', 'unknown')}`")
    lines.append(f"- Client status: `{session.get('client_status', 'unknown')}`")
    lines.append(f"- RTStreams: `{len(session.get('rtstreams') or [])}`")
    lines.append(f"- Indexes: `{len(session.get('indexes') or [])}`")
    if session.get("player_url"):
        lines.append(f"- Player: {session['player_url']}")
    return "\n".join(lines)


@mcp.resource("screen-aware://sessions/current")
def current_session_resource() -> str:
    """Expose current Screen-Aware CaptureSession state."""

    store, _ = _service()
    return dumps(store.get_session() or {})


@mcp.resource("screen-aware://events/recent")
def recent_events_resource() -> str:
    """Expose recent Screen-Aware live events."""

    store, _ = _service()
    return dumps([compact_event(event) for event in store.recent_events(limit=50)])


def main() -> None:
    store, _ = _service()
    store.update_backend(
        mcp_status="connected",
        mcp_agent=_agent_name(),
        mcp_started_at=utc_now_iso(),
        mcp_last_seen=utc_now_iso(),
        mcp_tool=None,
    )
    atexit.register(_mark_agent_offline)
    mcp.run()


if __name__ == "__main__":
    main()
