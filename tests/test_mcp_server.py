from __future__ import annotations

import asyncio
import time

from screen_aware.event_store import EventStore
from screen_aware.mcp_server import WatchLiveInput, _capture_stopped_after, _wait_for_live_watch_end


def test_capture_stopped_after_detects_session_stop(tmp_path):
    store = EventStore(tmp_path)
    started_at = time.time() - 1
    store.append_event(
        {
            "event": "capture.stopped",
            "capture_session_id": "cap-1",
            "data": {"text": "stopped"},
        }
    )

    assert _capture_stopped_after(store, session_id="cap-1", started_at=started_at)


def test_live_watch_wait_returns_when_capture_already_stopped(tmp_path):
    store = EventStore(tmp_path)
    started_at = time.time() - 1
    store.append_event(
        {
            "event": "capture.stopped",
            "capture_session_id": "cap-1",
            "data": {"text": "stopped"},
        }
    )

    result = asyncio.run(
        _wait_for_live_watch_end(
            store,
            session_id="cap-1",
            started_at=started_at,
            params=WatchLiveInput(duration_seconds=5),
        )
    )

    assert result == "capture_stopped"
