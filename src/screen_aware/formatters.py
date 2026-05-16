from __future__ import annotations

import json
from typing import Any

from .event_store import event_text


def dumps(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)


def compact_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": event.get("ts"),
        "channel": event.get("channel"),
        "event": event.get("event"),
        "capture_session_id": event.get("capture_session_id"),
        "rtstream_id": event.get("rtstream_id"),
        "rtstream_name": event.get("rtstream_name"),
        "text": event_text(event),
        "data": event.get("data"),
    }


def shot_to_dict(shot: Any) -> dict[str, Any]:
    return {
        "rtstream_id": getattr(shot, "rtstream_id", None) or getattr(shot, "rtstreamId", None),
        "video_id": getattr(shot, "video_id", None) or getattr(shot, "videoId", None),
        "start": getattr(shot, "start", None),
        "end": getattr(shot, "end", None),
        "text": getattr(shot, "text", None),
        "score": getattr(shot, "search_score", None) or getattr(shot, "searchScore", None),
        "stream_url": getattr(shot, "stream_url", None) or getattr(shot, "streamUrl", None),
        "player_url": getattr(shot, "player_url", None) or getattr(shot, "playerUrl", None),
        "scene_index_id": getattr(shot, "scene_index_id", None)
        or getattr(shot, "sceneIndexId", None),
    }


def context_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    query = payload.get("query")
    if query:
        lines.append(f"# Screen-Aware Context: {query}")
    else:
        lines.append("# Screen-Aware Context")

    session = payload.get("session") or {}
    if session:
        lines.append("")
        lines.append(
            f"Session `{session.get('session_id')}` status: `{session.get('status', 'unknown')}`"
        )

    search_results = payload.get("videodb_results") or []
    lines.append("")
    lines.append("## VideoDB Matches")
    if search_results:
        for item in search_results:
            start = item.get("start")
            end = item.get("end")
            text = item.get("text") or "(no text)"
            source = item.get("rtstream_id") or item.get("video_id") or "unknown"
            lines.append(f"- `{source}` [{start} - {end}]: {text}")
            if item.get("player_url"):
                lines.append(f"  Player: {item['player_url']}")
            elif item.get("stream_url"):
                lines.append(f"  Stream: {item['stream_url']}")
    else:
        lines.append("- No VideoDB semantic matches returned for this query.")

    recent = payload.get("recent_events") or []
    lines.append("")
    lines.append("## Recent Live Events")
    if recent:
        for event in recent:
            label = event.get("channel") or event.get("event") or "event"
            text = event.get("text") or "(no text)"
            lines.append(f"- `{event.get('ts')}` `{label}`: {text}")
    else:
        lines.append("- No recent events in the selected window.")

    warnings = payload.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("## Warnings")
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines)

