# v01 — Repo & Compose Scaffold

Branch: `dev-scaffold` → PR into `main`

## Scope

Lay down the skeleton every later version builds on: directory layout, the Docker Compose stack
topology (containers exist and start, but do almost nothing yet), config loading, and a health
endpoint. No business logic, no auth, no downloading.

## Tasks

1. Create the repository layout from the master plan's "Repository layout" section:
   - `backend/` — `pyproject.toml`, `app/main.py`, `app/config.py`, `app/db.py`, empty
     `app/models/`, `app/routers/`, `app/services/`, `app/tasks/`, `alembic/` (env only, no
     revisions yet — that's v02).
   - `frontend/` — bare SvelteKit + TS skeleton (`npm create svelte@latest` equivalent config),
     no real pages yet beyond a placeholder.
2. `docker-compose.yml` services: `api` (FastAPI/uvicorn), `worker-dl` (Celery, `-Q downloads
   --concurrency=1 --prefetch-multiplier=1`), `worker-meta` (Celery, `-Q meta`), `beat` (Celery
   beat), `redis`, `web` (SvelteKit build served statically or via `vite preview` in dev),
   `cloudflared`. `docker-compose.override.yml` for dev conveniences (bind mounts, hot reload).
   Postgres is **not** a compose service — it runs on the Debian host; containers reach it via
   `extra_hosts: ["host.docker.internal:host-gateway"]`.
3. `app/config.py` — pydantic-settings `Settings` class reading every env var named in
   `CLAUDE.md`'s env var table (added in this version): `DATABASE_URL`, `REDIS_URL`,
   `ALLOWED_EMAILS`, `UPSTREAM_AUTH_BASE_URL`, `SESSION_SECRET`, `SPOTIFY_CLIENT_ID/SECRET`
   (optional), `DOWNLOAD_OUTPUT_DIR`, `DEFAULT_FORMAT`, `DEFAULT_BITRATE`, `LADDER_SECONDS`
   (override hook), `PACING_MIN_SEC`/`PACING_MAX_SEC`.
4. `.env.example` documenting every one of the above with safe placeholder values.
5. `GET /api/health` — checks DB connectivity and Redis connectivity, returns `{status: "ok"}` or
   `503` with the failing dependency named.
6. Root `README.md` update: how to run the stack locally (`docker compose up`), where the plan
   lives.
7. `graphify update .` after the scaffold exists.

## Files touched (new)

`backend/pyproject.toml`, `backend/app/main.py`, `backend/app/config.py`, `backend/app/db.py`,
`backend/app/routers/health.py`, `backend/alembic/env.py`, `backend/alembic.ini`,
`frontend/` (SvelteKit skeleton), `docker-compose.yml`, `docker-compose.override.yml`,
`.env.example`, `README.md` (updated).

## Done when

- `docker compose up` brings up every service without crash-looping.
- `curl http://localhost:<api-port>/api/health` (or through the dev tunnel) returns `200
  {"status":"ok"}` with both Postgres and Redis reachable.
- `cd backend && alembic upgrade head` runs cleanly with zero revisions (proves Alembic wiring
  works before v02 adds real migrations).
- No feature logic beyond health/config exists yet — reviewers should see a skeleton, not features.
