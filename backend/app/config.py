from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_LADDER_SECONDS = [900, 3600, 14400, 43200, 86400]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core infra
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")

    # Auth (v03)
    allowed_emails: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="ALLOWED_EMAILS"
    )
    upstream_auth_base_url: str = Field(
        default="https://api.vb2007.hu", alias="UPSTREAM_AUTH_BASE_URL"
    )
    session_secret: str = Field(alias="SESSION_SECRET")

    # spotdl / download behavior
    spotify_client_id: str | None = Field(default=None, alias="SPOTIFY_CLIENT_ID")
    spotify_client_secret: str | None = Field(default=None, alias="SPOTIFY_CLIENT_SECRET")
    download_output_dir: str = Field(default="/downloads", alias="DOWNLOAD_OUTPUT_DIR")
    default_format: str = Field(default="mp3", alias="DEFAULT_FORMAT")
    default_bitrate: str = Field(default="320k", alias="DEFAULT_BITRATE")
    cookie_file: str | None = Field(default=None, alias="COOKIE_FILE")

    # Retry engine (v06) — override hook for tests, comma-separated seconds
    ladder_seconds: Annotated[list[int], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_LADDER_SECONDS), alias="LADDER_SECONDS"
    )

    # Pacing hook (v07) — off by default
    pacing_min_sec: int = Field(default=0, alias="PACING_MIN_SEC")
    pacing_max_sec: int = Field(default=0, alias="PACING_MAX_SEC")

    @field_validator("allowed_emails", mode="before")
    @classmethod
    def _split_allowed_emails(cls, value: object) -> object:
        if isinstance(value, str):
            return [email.strip() for email in value.split(",") if email.strip()]
        return value

    @field_validator("ladder_seconds", mode="before")
    @classmethod
    def _split_ladder_seconds(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
