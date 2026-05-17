from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file_candidates() -> list[Path]:
    candidates: list[Path] = []
    explicit = os.getenv("SCREEN_AWARE_ENV_FILE")
    if explicit:
        candidates.append(Path(explicit).expanduser())

    candidates.append(Path.cwd() / ".env")

    data_dir = os.getenv("SCREEN_AWARE_DATA_DIR")
    if data_dir:
        data_path = Path(data_dir).expanduser()
        if not data_path.is_absolute():
            data_path = Path.cwd() / data_path
        candidates.append(data_path.parent / ".env")

    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve() if candidate.exists() else candidate.absolute()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(candidate)
    return unique


for env_file in _env_file_candidates():
    if env_file.exists():
        load_dotenv(env_file, override=False)


class Settings(BaseSettings):
    """Runtime configuration loaded from environment and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    video_db_api_key: str | None = Field(default=None, alias="VIDEO_DB_API_KEY")
    videodb_collection_id: str = Field(default="default", alias="VIDEODB_COLLECTION_ID")
    videodb_api_url: str = Field(default="https://api.videodb.io", alias="VIDEODB_API_URL")

    screen_aware_data_dir: Path = Field(default=Path(".screen-aware"), alias="SCREEN_AWARE_DATA_DIR")
    api_host: str = Field(default="127.0.0.1", alias="SCREEN_AWARE_API_HOST")
    api_port: int = Field(default=8787, alias="SCREEN_AWARE_API_PORT")
    frontend_origin: str = Field(
        default="http://127.0.0.1:5173", alias="SCREEN_AWARE_FRONTEND_ORIGIN"
    )
    public_webhook_url: str | None = Field(default=None, alias="SCREEN_AWARE_PUBLIC_WEBHOOK_URL")
    env_file: Path | None = Field(default=None, alias="SCREEN_AWARE_ENV_FILE")

    client_token_ttl_seconds: int = Field(
        default=3600, alias="SCREEN_AWARE_CLIENT_TOKEN_TTL_SECONDS"
    )
    visual_model: str = Field(default="basic", alias="SCREEN_AWARE_VISUAL_MODEL")
    visual_batch_seconds: int = Field(default=3, alias="SCREEN_AWARE_VISUAL_BATCH_SECONDS")
    visual_frame_count: int = Field(default=3, alias="SCREEN_AWARE_VISUAL_FRAME_COUNT")
    audio_batch_words: int = Field(default=50, alias="SCREEN_AWARE_AUDIO_BATCH_WORDS")
    max_recent_events: int = Field(default=200, alias="SCREEN_AWARE_MAX_RECENT_EVENTS")
    live_ai_api_key: str | None = Field(default=None, alias="SCREEN_AWARE_LIVE_API_KEY")
    live_ai_base_url: str = Field(
        default="https://api.openai.com/v1", alias="SCREEN_AWARE_LIVE_BASE_URL"
    )
    live_ai_model: str = Field(default="gpt-4.1-mini", alias="SCREEN_AWARE_LIVE_MODEL")
    live_ai_timeout_seconds: float = Field(default=20.0, alias="SCREEN_AWARE_LIVE_TIMEOUT_SECONDS")
    live_ai_context_timeout_seconds: float = Field(
        default=4.0, alias="SCREEN_AWARE_LIVE_CONTEXT_TIMEOUT_SECONDS"
    )
    live_ai_max_context_events: int = Field(
        default=14, alias="SCREEN_AWARE_LIVE_MAX_CONTEXT_EVENTS"
    )

    @field_validator("video_db_api_key", mode="before")
    @classmethod
    def accept_node_sdk_env_name(cls, value: str | None) -> str | None:
        return value or os.getenv("VIDEODB_API_KEY")

    @field_validator("live_ai_api_key", mode="before")
    @classmethod
    def accept_openai_env_name(cls, value: str | None) -> str | None:
        return value or os.getenv("OPENAI_API_KEY")

    @field_validator("screen_aware_data_dir")
    @classmethod
    def expand_data_dir(cls, value: Path) -> Path:
        return value.expanduser()

    @field_validator("public_webhook_url", mode="before")
    @classmethod
    def empty_string_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None

    @property
    def data_dir(self) -> Path:
        path = self.screen_aware_data_dir
        if not path.is_absolute():
            path = Path.cwd() / path
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
