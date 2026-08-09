from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
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

    # Frontend (v09) — origin(s) the SvelteKit static site is served from, for CORS. As of
    # v12, both production (nginx's /api/ proxy inside the `web` container) and local dev
    # (Vite's dev-server /api proxy) are same-origin by default, so this middleware's
    # allowlist normally never actually gets exercised by a real cross-origin browser
    # request — it's a fallback for whoever bypasses the proxy (e.g. hitting the api
    # container's published port directly). A list because local dev is reachable as both
    # localhost and 127.0.0.1 (different origins to a browser even though they're the same
    # machine); the default covers both. Production sets this to the real Cloudflare
    # Tunnel hostname (see .env.example).
    frontend_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        alias="FRONTEND_ORIGINS",
    )

    # spotdl / download behavior. default_format/default_bitrate/download_output_dir are
    # only the *seed* for app_settings (v13) on its first read in a fresh DB — after that,
    # app.services.app_settings's DB-backed row is the source of truth, editable from the
    # settings UI without a redeploy. cookie_file has no UI override; still env-only.
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

    # Durability (v12) — how long a track can sit in DOWNLOADING/QUEUED before beat's
    # stale-track reclaim sweep (app/tasks/beat.py) resets it back to WAITING. Same
    # "shorten for local/verification testing" pattern as LADDER_SECONDS above — the
    # 1800s (30min) production default would make manually verifying the reclaim sweep a
    # 30-minute wait otherwise.
    stale_track_after_seconds: int = Field(default=1800, alias="STALE_TRACK_AFTER_SECONDS")

    # Pacing hook (declared since v07, actually consumed by download_track as of v15) — a
    # randomized inter-track delay. PACING_MAX_SEC=0 (the default) means off: the sleep
    # path in download_track doesn't run at all, not sleep(0). Raising this means also
    # raising STALE_TRACK_AFTER_SECONDS -- pacing lengthens how long a dispatched batch's
    # tail sits QUEUED before its own attempt, and beat's stale-track sweep doesn't know
    # the difference between "paced" and "stuck".
    pacing_min_sec: int = Field(default=0, alias="PACING_MIN_SEC")
    pacing_max_sec: int = Field(default=0, alias="PACING_MAX_SEC")

    # Proxy rotation (v07) — plain file; v13 adds UI-managed (source=manual) proxies
    # alongside these file-sourced ones, both drawn from equally by pick_proxy().
    proxy_file: str = Field(default="/app/proxies.txt", alias="PROXY_FILE")

    @field_validator("allowed_emails", "frontend_origins", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("ladder_seconds", mode="before")
    @classmethod
    def _split_ladder_seconds(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def _check_pacing_window(self) -> "Settings":
        """Rejects a pacing window that can't mean what it says. random.uniform happily
        samples a reversed range, so MIN=5/MAX=0 would silently read as "pace by up to
        5s" while actually meaning "off" -- the exact silent-no-op shape v15 exists to
        eliminate. get_settings() runs at import (celery_app.py), so a bad pair
        crash-loops visibly at boot instead of misbehaving quietly at runtime."""
        if self.pacing_min_sec < 0 or self.pacing_max_sec < 0:
            raise ValueError("PACING_MIN_SEC/PACING_MAX_SEC must not be negative")
        if self.pacing_min_sec > self.pacing_max_sec:
            raise ValueError(
                f"PACING_MIN_SEC ({self.pacing_min_sec}) must not exceed "
                f"PACING_MAX_SEC ({self.pacing_max_sec})"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
