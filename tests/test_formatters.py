from __future__ import annotations

from screen_aware.formatters import compact_event, context_markdown, live_watch_markdown


def test_context_markdown_includes_videodb_match_and_event():
    payload = {
        "query": "why is the test failing?",
        "session": {"session_id": "cap-1", "status": "active"},
        "videodb_results": [
            {
                "rtstream_id": "rts-1",
                "start": 1.0,
                "end": 4.0,
                "text": "The terminal shows AssertionError",
            }
        ],
        "recent_events": [
            compact_event(
                {
                    "ts": "2026-05-16T00:00:00Z",
                    "channel": "transcript",
                    "data": {"text": "The login test is failing"},
                }
            )
        ],
        "evidence_frames": [
            {"source_label": "Game window", "sequence": 3, "path": "C:/tmp/frame.jpg"}
        ],
        "warnings": [],
    }

    rendered = context_markdown(payload)
    assert "AssertionError" in rendered
    assert "login test" in rendered
    assert "Visual Evidence Frames" in rendered
    assert "C:/tmp/frame.jpg" in rendered


def test_live_watch_markdown_includes_stop_reason():
    rendered = live_watch_markdown(
        {
            "mode": "diagnose",
            "objective": "watch the app",
            "watched_seconds": 12,
            "stop_reason": "capture_stopped",
            "videodb_results": [],
            "recent_events": [],
            "warnings": [],
        }
    )

    assert "Stop reason: `capture_stopped`" in rendered
