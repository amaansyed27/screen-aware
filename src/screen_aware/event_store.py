from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def event_text(event: dict[str, Any]) -> str:
    data = event.get("data")
    if isinstance(data, dict):
        text = data.get("text") or data.get("message") or data.get("explanation")
        if isinstance(text, str):
            return text
    text = event.get("text") or event.get("message")
    return text if isinstance(text, str) else ""


class EventStore:
    """Small JSON/JSONL store shared by the API and MCP stdio process."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / "state.json"
        self.events_path = self.data_dir / "events.jsonl"
        self._lock = threading.RLock()
        if not self.state_path.exists():
            self._write_state_unlocked(self._default_state())
        if not self.events_path.exists():
            self.events_path.touch()

    @staticmethod
    def _default_state() -> dict[str, Any]:
        return {
            "version": 1,
            "current_session_id": None,
            "sessions": {},
            "backend": {
                "ws_connection_id": None,
                "ws_status": "not_started",
                "last_error": None,
                "updated_at": None,
                "mcp_status": "not_connected",
                "mcp_agent": None,
                "mcp_last_seen": None,
                "mcp_tool": None,
                "mcp_live_mode": None,
                "mcp_live_objective": None,
            },
        }

    def read_state(self) -> dict[str, Any]:
        with self._lock:
            try:
                with self.state_path.open("r", encoding="utf-8") as handle:
                    state = json.load(handle)
            except (FileNotFoundError, json.JSONDecodeError):
                state = self._default_state()
                self._write_state_unlocked(state)
            state.setdefault("sessions", {})
            state.setdefault("backend", {})
            return state

    def write_state(self, state: dict[str, Any]) -> None:
        with self._lock:
            self._write_state_unlocked(state)

    def _write_state_unlocked(self, state: dict[str, Any]) -> None:
        state["updated_at"] = utc_now_iso()
        tmp_path = self.state_path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
        tmp_path.replace(self.state_path)

    def update_backend(self, **fields: Any) -> dict[str, Any]:
        with self._lock:
            state = self.read_state()
            backend = state.setdefault("backend", {})
            backend.update(fields)
            backend["updated_at"] = utc_now_iso()
            self._write_state_unlocked(state)
            return backend

    def upsert_session(self, session_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            state = self.read_state()
            sessions = state.setdefault("sessions", {})
            session = sessions.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "created_at": utc_now_iso(),
                    "status": "created",
                    "rtstreams": [],
                    "indexes": [],
                    "client_events": [],
                },
            )
            session.update({key: value for key, value in fields.items() if value is not None})
            session["updated_at"] = utc_now_iso()
            state["current_session_id"] = session_id
            self._write_state_unlocked(state)
            return session

    def append_session_item(
        self, session_id: str, field: str, item: dict[str, Any], *, max_items: int = 100
    ) -> dict[str, Any]:
        with self._lock:
            state = self.read_state()
            sessions = state.setdefault("sessions", {})
            session = sessions.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "created_at": utc_now_iso(),
                    "status": "created",
                    "rtstreams": [],
                    "indexes": [],
                    "client_events": [],
                },
            )
            values = session.setdefault(field, [])
            values.append({**item, "ts": utc_now_iso()})
            if max_items > 0:
                del values[:-max_items]
            session["updated_at"] = utc_now_iso()
            state["current_session_id"] = session_id
            self._write_state_unlocked(state)
            return session

    def get_session(self, session_id: str | None = None) -> dict[str, Any] | None:
        state = self.read_state()
        target = session_id or state.get("current_session_id")
        if not target:
            return None
        session = state.get("sessions", {}).get(target)
        return session if isinstance(session, dict) else None

    def record_client_event(self, session_id: str, event: dict[str, Any]) -> None:
        enriched = {
            "source": "companion",
            "capture_session_id": session_id,
            "event": event.get("event") or event.get("type") or "companion.event",
            "data": event.get("data", event),
        }
        self.append_event(enriched)
        with self._lock:
            state = self.read_state()
            session = state.setdefault("sessions", {}).setdefault(
                session_id, {"session_id": session_id, "client_events": []}
            )
            events = session.setdefault("client_events", [])
            events.append({**event, "ts": utc_now_iso()})
            del events[:-50]
            session["updated_at"] = utc_now_iso()
            self._write_state_unlocked(state)

    def append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(event)
        normalized.setdefault("ts", utc_now_iso())
        normalized.setdefault("unix_ts", time.time())
        with self._lock:
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(normalized, ensure_ascii=False, sort_keys=True) + "\n")
        return normalized

    def recent_events(
        self,
        *,
        limit: int = 50,
        since_unix: float | None = None,
        channels: set[str] | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        with self._lock:
            try:
                lines = self.events_path.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                return []

        result: list[dict[str, Any]] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if since_unix is not None and float(event.get("unix_ts", 0)) < since_unix:
                continue
            if channels and str(event.get("channel") or event.get("event")) not in channels:
                continue
            if session_id and event.get("capture_session_id") != session_id:
                continue
            result.append(event)
            if len(result) >= limit:
                break
        result.reverse()
        return result

    def update_session_from_event(self, event: dict[str, Any]) -> None:
        session_id = event.get("capture_session_id")
        if not isinstance(session_id, str) or not session_id:
            return
        lifecycle_event = event.get("event")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        updates: dict[str, Any] = {}
        if isinstance(lifecycle_event, str) and lifecycle_event.startswith("capture_session."):
            updates["status"] = lifecycle_event.rsplit(".", 1)[-1]
        if "rtstreams" in data:
            updates["rtstreams"] = data["rtstreams"]
        for key in ("exported_video_id", "stream_url", "player_url", "error"):
            if key in data:
                updates[key] = data[key]
        if updates:
            self.upsert_session(session_id, **updates)
