from __future__ import annotations

import json
from typing import Any

import httpx

from .config import Settings
from .event_store import event_text
from .formatters import compact_event


class LiveAssistant:
    """Low-latency companion replies for the desktop overlay.

    This is deliberately separate from MCP. MCP lets a coding agent pull context and edit files;
    the live assistant gives the human a short reply inside the overlay while capture is running.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.live_ai_api_key)

    async def respond(
        self,
        *,
        user_message: str,
        session: dict[str, Any] | None,
        agent_name: str | None,
        recent_events: list[dict[str, Any]],
        search_results: list[dict[str, Any]],
        warnings: list[str],
    ) -> dict[str, Any]:
        if not self.configured:
            return {
                "ok": False,
                "status": "not_configured",
                "provider": "openai-compatible",
                "model": self.settings.live_ai_model,
                "text": (
                    "Live replies need a model key. Add SCREEN_AWARE_LIVE_API_KEY "
                    "or OPENAI_API_KEY to .env, restart screen-aware-api, then ask again."
                ),
                "warnings": warnings,
            }

        prompt = self._build_prompt(
            user_message=user_message,
            session=session,
            agent_name=agent_name,
            recent_events=recent_events,
            search_results=search_results,
            warnings=warnings,
        )
        response = await self._chat_completion(prompt)
        text = response.strip()
        if not text:
            text = "I did not get a usable live reply from the model. Try that once more."
        return {
            "ok": True,
            "status": "answered",
            "provider": "openai-compatible",
            "model": self.settings.live_ai_model,
            "text": text,
            "warnings": warnings,
        }

    def _build_prompt(
        self,
        *,
        user_message: str,
        session: dict[str, Any] | None,
        agent_name: str | None,
        recent_events: list[dict[str, Any]],
        search_results: list[dict[str, Any]],
        warnings: list[str],
    ) -> list[dict[str, str]]:
        compact_events = [self._compact_live_event(event) for event in recent_events]
        payload = {
            "connected_agent": agent_name or "coding agent",
            "session_id": (session or {}).get("session_id"),
            "user_message": user_message,
            "recent_live_events": compact_events,
            "relevant_videodb_matches": search_results[:5],
            "context_warnings": warnings,
        }
        return [
            {
                "role": "system",
                "content": (
                    "You are Screen-Aware Live, a concise debugging companion inside a desktop "
                    "screen-share overlay. Reply to the human in 1-3 short sentences. Ground the "
                    "reply only in the supplied live events and VideoDB matches. If visual/audio "
                    "evidence is delayed or missing, say that plainly and ask the user to keep "
                    "showing or pointing. If a fix is likely, name the fix target and ask whether "
                    "to hand it to the connected coding agent. Do not claim to edit files yourself."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            },
        ]

    @staticmethod
    def _compact_live_event(event: dict[str, Any]) -> dict[str, Any]:
        compact = compact_event(event)
        text = compact.get("text") or event_text(event)
        data = compact.get("data")
        if isinstance(data, dict):
            data = {key: data[key] for key in sorted(data)[:8]}
        return {
            "ts": compact.get("ts"),
            "event": compact.get("event"),
            "channel": compact.get("channel"),
            "text": text,
            "data": data,
        }

    async def _chat_completion(self, messages: list[dict[str, str]]) -> str:
        base_url = self.settings.live_ai_base_url.rstrip("/")
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.live_ai_api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.settings.live_ai_model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 220,
        }
        async with httpx.AsyncClient(timeout=self.settings.live_ai_timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message")
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        return content if isinstance(content, str) else ""
