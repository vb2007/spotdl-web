from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

DEFAULT_LADDER_SECONDS = [900, 3600, 14400, 43200, 86400]

# v32: database names a dev-marked process (SPOTDL_ENV=dev, set only by
# docker-compose.override.yml) must never connect to. `spotdlweb` is the real production
# database on the shared Postgres server; `spotdl_web` is the name .env.example and
# docs/DEPLOYMENT.md document for a fresh install. Keyed on "is it production", never on the
# dev database's own name (spotdlwebtest), so renaming the dev database never breaks this.
PRODUCTION_DATABASE_NAMES = ("spotdlweb", "spotdl_web")

DEV_ENV_MARKER = "dev"

_DEV_DB_FIX = "point DATABASE_URL at spotdlwebtest, see docs/LOCAL_DEV.md"


def check_not_production_database(database_url: str, spotdl_env: str | None) -> None:
    """Refuses a dev-marked process pointed at the production database. Fails closed: in
    dev, a URL whose database name can't be determined is refused too, since "can't tell"
    must never read as "safe". Without the dev marker (production) this is a no-op. The
    error names the database only, never the URL -- it carries the password."""
    marker = (spotdl_env or "").strip().lower()
    if not marker:
        return
    if marker != DEV_ENV_MARKER:
        raise ValueError(
            f"SPOTDL_ENV={spotdl_env!r} is not a recognized environment marker "
            f"(expected {DEV_ENV_MARKER!r} or unset); refusing to start"
        )
    try:
        url = make_url(database_url)
    except (ArgumentError, ValueError) as exc:
        raise ValueError(
            f"SPOTDL_ENV=dev but DATABASE_URL can't be parsed ({type(exc).__name__}); "
            f"refusing to start -- {_DEV_DB_FIX}"
        ) from None
    # libpq also accepts the database as a `?dbname=` query parameter, which wins over the
    # path component -- check both, so the guard can't be sidestepped that way.
    query_dbname = url.query.get("dbname") or ()
    if isinstance(query_dbname, str):
        query_dbname = (query_dbname,)
    names = [n for n in (url.database, *query_dbname) if n]
    if not names:
        raise ValueError(
            f"SPOTDL_ENV=dev but DATABASE_URL names no database; refusing to start -- "
            f"{_DEV_DB_FIX}"
        )
    production = {n.lower() for n in PRODUCTION_DATABASE_NAMES}
    for name in names:
        if name.strip().lower() in production:
            raise ValueError(
                f"SPOTDL_ENV=dev but DATABASE_URL points at the production database "
                f"{name!r}; refusing to start -- {_DEV_DB_FIX}"
            )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core infra
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")

    # Environment marker (v32) -- "dev" is set only by docker-compose.override.yml on every
    # backend service; production never sets it. See check_not_production_database().
    spotdl_env: str | None = Field(default=None, alias="SPOTDL_ENV")

    # Auth (v03)
    allowed_emails: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="ALLOWED_EMAILS"
    )
    upstream_auth_base_url: str = Field(
        default="https://api.vb2007.hu", alias="UPSTREAM_AUTH_BASE_URL"
    )
    session_secret: str = Field(alias="SESSION_SECRET")

    # Multi-user (v17) -- the one account services.users.get_or_create_user grants
    # is_admin to. Required, not optional: an admin nobody can log in as is a
    # deployment that silently has no working settings/proxies/worker controls, which
    # is worse than a loud crash-loop at boot.
    admin_email: str = Field(alias="ADMIN_EMAIL")

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

    # YouTube player client selection (v31.1) -- yt-dlp's own default client selection for
    # this app's URLs currently lands on android_vr, which 403s outright while android/web/
    # mweb all still succeed from the same IP (proven with real CLI tests against the
    # deployed host -- see docs/GOTCHAS.md's v31.1 entry). Forwarded to yt-dlp's own
    # `--extractor-args youtube:player_client=...` on every attempt, unconditionally --
    # this is a client-selection concern, independent of network_path/proxy forcing.
    # Configurable rather than hardcoded because this is exactly the kind of yt-dlp/
    # YouTube arms-race surface that needs retuning without a redeploy, same reasoning
    # LADDER_SECONDS/PACING_*_SEC above already get.
    youtube_player_clients: str = Field(default="android,web,mweb", alias="YOUTUBE_PLAYER_CLIENTS")

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

    @model_validator(mode="after")
    def _check_dev_not_on_production_database(self) -> "Settings":
        """get_settings() runs at import in every backend process (db.py, main.py,
        celery_app.py, alembic/env.py), so every one of them -- api, both workers, beat and
        migrate -- refuses at boot, before a single query. Under a plain `docker compose up`
        only migrate visibly fails; the rest never start (depends_on migrate)."""
        check_not_production_database(self.database_url, self.spotdl_env)
        return self

    @model_validator(mode="after")
    def _check_admin_email_is_allowlisted(self) -> "Settings":
        """ADMIN_EMAIL gates who services.users.get_or_create_user marks is_admin;
        ALLOWED_EMAILS gates who may log in at all. If the admin's own address isn't
        allowlisted, the deployment has an admin who can never log in -- exactly the
        kind of silent misconfiguration that should crash-loop at boot (get_settings()
        runs at import, per _check_pacing_window's same reasoning) rather than surface
        only when someone notices settings/proxies/worker are unreachable."""
        allowed = {e.strip().lower() for e in self.allowed_emails}
        if self.admin_email.strip().lower() not in allowed:
            raise ValueError(
                f"ADMIN_EMAIL ({self.admin_email!r}) must also appear in "
                f"ALLOWED_EMAILS ({self.allowed_emails!r})"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
