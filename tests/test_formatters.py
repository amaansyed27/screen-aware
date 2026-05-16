from __future__ import annotations

from screen_aware.formatters import compact_event, context_markdown


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
        "warnings": [],
    }

    rendered = context_markdown(payload)
    assert "AssertionError" in rendered
    assert "login test" in rendered

