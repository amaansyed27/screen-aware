from __future__ import annotations

from screen_aware.event_store import EventStore, event_text


def test_event_store_records_session_and_events(tmp_path):
    store = EventStore(tmp_path)
    store.upsert_session("cap-1", status="created")
    event = store.append_event(
        {
            "capture_session_id": "cap-1",
            "channel": "visual_index",
            "data": {"text": "Terminal shows pytest failure"},
        }
    )
    store.update_session_from_event(
        {
            "capture_session_id": "cap-1",
            "event": "capture_session.active",
            "data": {"rtstreams": [{"rtstream_id": "rts-1", "media_types": ["video"]}]},
        }
    )

    session = store.get_session("cap-1")
    assert session is not None
    assert session["status"] == "active"
    assert session["rtstreams"][0]["rtstream_id"] == "rts-1"
    assert event_text(event) == "Terminal shows pytest failure"
    assert len(store.recent_events(limit=10)) == 1

