from __future__ import annotations

import asyncio

from screen_aware.config import Settings
from screen_aware.live_assistant import LiveAssistant


def test_live_assistant_reports_missing_model_key(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("SCREEN_AWARE_LIVE_API_KEY", raising=False)
    settings = Settings(
        VIDEO_DB_API_KEY="video-key",
        SCREEN_AWARE_DATA_DIR=tmp_path,
        SCREEN_AWARE_LIVE_API_KEY=None,
    )
    assistant = LiveAssistant(settings)

    reply = asyncio.run(
        assistant.respond(
            user_message="Can you see the broken button?",
            session={"session_id": "cap-1"},
            agent_name="Codex",
            recent_events=[],
            search_results=[],
            warnings=[],
        )
    )

    assert reply["ok"] is False
    assert reply["status"] == "not_configured"
    assert "SCREEN_AWARE_LIVE_API_KEY" in reply["text"]


def test_live_assistant_uses_openrouter_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    settings = Settings(
        VIDEO_DB_API_KEY="video-key",
        SCREEN_AWARE_DATA_DIR=tmp_path,
        SCREEN_AWARE_LIVE_API_KEY=None,
    )
    assistant = LiveAssistant(settings)

    assert assistant.configured is True
    assert settings.live_ai_api_key == "openrouter-key"
    assert settings.live_ai_base_url == "https://openrouter.ai/api/v1"
    assert assistant._model_candidates() == [
        "google/gemini-3-flash-preview",
        "google/gemini-3.1-flash-lite",
        "google/gemini-3.1-flash-lite-preview",
    ]
