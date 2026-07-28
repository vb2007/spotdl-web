# spotdl-web — Master Development Plan

> This is the master roadmap, approved by the user and committed verbatim as the project's
> permanent record. Individual version plans (`plan/v00-*.md` … `plan/v13-*.md`) expand on the
> roadmap table below with implementation-level detail. `CLAUDE.md` carries the durable summary
> that every future session should read first.

## Context

`/home/vb2007/code/spotdl-web` is currently empty (LICENSE, README, CLAUDE.md only, branch `dev-init`).
The goal is a self-hosted, single-user web wrapper around the **spotdl** Python library that accepts
Spotify album/playlist/artist/track URLs and downloads *everything*, treating YouTube Music rate
limiting as an expected condition rather than a failure.

The defining requirement: **get everything by dodging rate limits, even if it takes an extremely long
time.** That inverts normal web-app priorities — throughput and responsiveness matter far less than
durability. A track may legitimately sit in the queue for days. This drives almost every decision
below (Postgres as the scheduling source of truth, serialized single-track downloads, infinite
retries, deliberate waiting before proxy switches).

This document is the roadmap. It is deliberately *not* the implementation. Version `v00` below
creates the per-version plan files in `plan/` and writes `CLAUDE.md`, so all of this survives
across sessions.

---

## Locked decisions

| Area | Decision |
|---|---|
| Backend | Python 3.12, FastAPI + Celery |
| Task queue | **Celery + Redis** (Redis dockerized) |
| Database | **PostgreSQL**, non-dockerized on the Debian 12 host |
| Frontend | **SvelteKit + TypeScript** |
| Live updates | **SSE** now, WebSocket later if needed |
| Ingress | **Cloudflare Tunnel only** — no port forwarding, ever |
| Auth | Proxy login to existing `vb2007.hu-api`, own session cookie |
| Rate-limit handling | Per-track ladder **+** global circuit breaker |
| Proxies | Plain file first; UI management as the *final* version |
| Proxy strategy | Direct first → on failure wait out the ladder → *then* proxy |
| Output config | Global env config first; UI override as a *final* version |
| Dedup | DB table keyed on Spotify track ID + disk reconciliation |
| Extra levers | None enabled initially (config hooks present, default off) |
| Deployment | Docker Compose stack on Debian 12 |

---

## Auth API — verified findings

Read directly from `/home/vb2007/code/vb2007.hu-api`:

- `POST /auth/login`, body `{ email, password }` → `200` + `Set-Cookie: VB-AUTH=<sessionToken>; Domain=localhost; Path=/`
  (`src/controllers/authentication.ts:39`). Errors: `400` missing fields, `404` unknown email, `403` wrong password.
- `sessionToken = HMAC-SHA256(salt + "/" + userId, CRYPTO_SECRET_KEY)`, regenerated on every login,
  persisted in Mongo, **no expiry** (`src/helpers/index.ts`).
- `GET /user` behind `isAuthenticated` (`src/router/users.ts:6`) reads the `VB-AUTH` cookie —
  this is our token-validation endpoint. There is no `/auth/me`.
- Public base URL `https://api.vb2007.hu` (`production/vb2007-api.conf`), app listens on `:3000`.

Two consequences that shape the auth version:

1. **`Domain=localhost` is hardcoded** on the upstream `Set-Cookie`, so a browser on
   `spotdl.<domain>` can never use it. Login must therefore be **server-to-server**: our backend
   POSTs the credentials, reads `VB-AUTH` out of the response headers, and mints its *own* session.
   `VB-AUTH` never reaches the browser.
2. **`POST /auth/register` is public** (`src/router/authentication.ts:6`). Anyone who registers on
   `vb2007.hu-api` would otherwise get into spotdl-web. An **email allowlist**
   (`ALLOWED_EMAILS` env) is mandatory, checked *after* upstream login succeeds.

---

## spotdl 4.5.2 — verified API surface

- `Spotdl(client_id, client_secret, ..., downloader_settings: DownloaderOptions)`;
  `Downloader(settings, loop)`.
- `DownloaderOptions` includes exactly the keys we need: `proxy`, `threads`, `output`, `format`,
  `bitrate`, `cookie_file`, `audio_providers`, `overwrite`, `archive`, `scan_for_songs`,
  `filter_results`, `only_verified_results`, `yt_dlp_args`, `max_filename_length`.
- `spotdl.utils.search.get_simple_songs(query, ...)` expands track/album/playlist/artist URLs into
  `List[Song]`; `parse_query(...)` additionally enriches metadata across threads. **This is our URL
  expansion step — do not hand-roll Spotify API calls.**
- `Downloader.search_and_download(song) -> Tuple[Song, Optional[Path]]` is the per-track unit.
- Errors: `AudioProviderError` (`spotdl.providers.audio.base`) — raised by the yt-dlp logger and by
  `get_download_metadata`; this is the rate-limit signal. `LookupError` — raised by
  `AudioProvider.search` when no result is found on any provider. `DownloaderError` — config
  problems (bad proxy string, missing ffmpeg, **called from a running event loop**).
- `Downloader.progress_handler` exposes `get_new_tracker(song)` and `notify_*` hooks — our live
  progress source.
- spotdl ships default public Spotify credentials, so `SPOTIFY_CLIENT_ID/SECRET` are optional
  overrides rather than hard requirements.

---

## Architecture

```
Cloudflare Tunnel ──> cloudflared (container)
                          │
                          ├─> web (SvelteKit, static adapter)
                          └─> api (FastAPI: auth, jobs, SSE)
                                   │
      ┌────────────────────────────┼─────────────────────────┐
      │                            │                         │
  PostgreSQL                    Redis                   worker-meta (Celery, -Q meta)
 (host, source of truth)   (broker + pub/sub)           worker-dl  (Celery, -Q downloads,
      │                            │                            --concurrency=1)
      └──── scheduled_at ──── beat (dispatch_due_tracks, every 30s)
```

### The single most important design point

**Do not use Celery `eta`/`countdown` for the backoff delays.** With the Redis broker, ETA tasks are
prefetched into worker memory and a worker restart loses or duplicates them. A 24-hour delay held in
RAM is unacceptable for a queue meant to survive weeks.

Instead:

- Postgres `tracks.scheduled_at` is the **only** source of truth for when a track is next eligible.
- Celery Beat runs `dispatch_due_tracks` every 30s: selects tracks with
  `state='waiting' AND scheduled_at <= now()` (`FOR UPDATE SKIP LOCKED`), flips them to `queued`,
  and sends them to the `downloads` queue.
- Celery is therefore purely the **executor**; the schedule is durable, inspectable with plain SQL,
  and survives any restart. Backoff becomes `UPDATE ... SET scheduled_at = now() + interval`.

### Other architectural notes

- **Two Celery workers.** `worker-dl` runs `--concurrency=1 --prefetch-multiplier=1 -Q downloads`
  so exactly one track downloads at a time (deliberate: concurrency is rate-limit exposure).
  `worker-meta -Q meta` handles URL expansion and disk reconciliation so a long download never
  blocks the UI's feedback on a freshly submitted playlist.
- **Prefork, not async.** `search_and_download` raises `DownloaderError` if called from a running
  event loop, so download tasks must be plain sync Celery tasks.
- **Cache `Downloader` instances** in the worker process keyed by `(proxy, format, bitrate)`.
  Construction initializes all audio/lyrics providers; rebuilding per track is wasteful, but a
  proxy change *requires* a new instance because `proxy` lives in immutable settings.
- **Postgres from containers:** `extra_hosts: ["host.docker.internal:host-gateway"]`, plus
  `listen_addresses` and a `pg_hba.conf` entry for the Docker bridge subnet.
- **Redis** with AOF persistence, `requirepass`, bound to the internal compose network only.
- **ffmpeg** must be in the worker image.
- **Cloudflare Tunnel + SSE:** set `Cache-Control: no-cache` and `X-Accel-Buffering: no`, and emit a
  `:heartbeat` comment every 15s — cloudflared closes idle streams. `EventSource` reconnects
  automatically; on reconnect the UI refetches full state via REST, then resumes streaming. This
  makes SSE gap-tolerant without needing `Last-Event-ID` replay.

### Track state machine

```
pending ──> queued ──> downloading ──> completed
                │            │
                │            ├─> AudioProviderError ─> waiting (scheduled_at = now + ladder)
                │            │                          └─> queued (via beat) ... ∞
                │            ├─> LookupError ──────────> lookup_failed  (terminal, notify, never retry)
                │            └─> other error ─────────> waiting (short ladder) / failed after N
                └─> skipped_duplicate
any ──> cancelled
```

### Retry engine

- **Per-track ladder** on `AudioProviderError`: `15m → 1h → 4h → 12h → 24h`, then 24h forever.
  Never gives up. Track goes to the back of the queue so healthy tracks keep flowing.
- **Global circuit breaker** in a `worker_state` row: 5 consecutive `AudioProviderError`s across any
  tracks trips a pause — `30m`, then `2h`, then `6h` on successive trips; resets on first success.
  While tripped, `dispatch_due_tracks` dispatches nothing. Checked again at task start (a task may
  have been queued just before the trip) and re-queued if tripped.
- **Proxy escalation**: attempt 1 always direct. After a failure the track waits out its ladder
  delay *first*, and only the following attempt uses a proxy — the wait is the point, so the switch
  doesn't read as an evasion burst. A proxy that fails gets its own `cooldown_until`.
- **`LookupError` is terminal**: recorded, surfaced in the UI, never retried automatically.
- **Pacing hook** (`PACING_MIN_SEC` / `PACING_MAX_SEC`, default `0`): randomized sleep between
  tracks. Off per your choice, but wired in — it's the first dial to turn if 429s stay frequent.

---

## Repository layout

```
plan/                      v00…v12 plan files (created in v00)
CLAUDE.md                  all decisions, persisted across sessions
docker-compose.yml
docker-compose.override.yml   dev-only
.env.example
backend/
  pyproject.toml
  app/
    main.py                FastAPI app
    config.py              pydantic-settings
    db.py                  engine, session
    models/                SQLAlchemy models
    routers/               auth.py, jobs.py, stream.py, health.py
    services/
      upstream_auth.py     vb2007.hu-api client
      sessions.py          own session issue/validate
      expansion.py         get_simple_songs wrapper
      downloads.py         Downloader cache + search_and_download
      retry.py             ladder + circuit breaker
      proxies.py           proxy pool + health
      dedup.py             track-id + disk reconciliation
      events.py            Redis pub/sub -> SSE
    tasks/                 celery_app.py, expand.py, download.py, beat.py
  alembic/
frontend/                  SvelteKit + TS
```

---

## Version roadmap

Each version = one focused feature = one `dev-<feature>` branch = one PR into `main`.
No two versions are implemented in parallel. Subagents are used *within* a version, all focused on
that version's single concern.

| # | Branch | Scope | Done when |
|---|---|---|---|
| **v00** | `dev-planning` | `plan/v00…v12` files, `CLAUDE.md`, initial graphify build | Plans + CLAUDE.md committed |
| **v01** | `dev-scaffold` | Repo layout, compose stack (api/worker/beat/redis/web/cloudflared), config module, `.env.example`, `/api/health`, Alembic init | `docker compose up` → health returns OK |
| **v02** | `dev-db-schema` | All SQLAlchemy models + one Alembic migration. No business logic | `alembic upgrade head` clean; schema review |
| **v03** | `dev-auth` | Upstream login proxy, email allowlist, own session table + cookie, `require_session` dep, `/api/auth/{login,logout,me}` | Login with real creds works; non-allowlisted email rejected |
| **v04** | `dev-url-expansion` | `POST /api/jobs` → `expand_job` task via `get_simple_songs` → track rows. No downloading | Submit a playlist URL, see every track as `pending` |
| **v05** | `dev-downloader` | `download_track` task, Downloader cache, dedup check, `downloaded_tracks`, files on disk. Naive error handling | An album downloads end to end with correct tags/paths |
| **v06** | `dev-retry-engine` | Error classification, per-track ladder, `scheduled_at` + `dispatch_due_tracks` beat, global circuit breaker, terminal `LookupError` | Injected `AudioProviderError` produces correct ladder; breaker trips and recovers; survives worker restart |
| **v07** | `dev-proxy-rotation` | `proxies.txt` loader + validation, DB health/cooldown, direct-first-then-proxy escalation | Failing direct then succeeding via proxy, verified in logs/DB |
| **v08** | `dev-live-progress` | spotdl `ProgressHandler` hook → Redis pub/sub → `/api/stream` SSE with heartbeats | `curl -N` on the stream shows live per-track progress |
| **v09** | `dev-frontend` | SvelteKit: login, submit form, live queue table, countdown timers, failed/lookup-failed views | Full flow usable in a browser through the tunnel |
| **v10** | `dev-queue-controls` | Pause/resume worker (+ breaker countdown & early release), cancel job/track, retry-now | Each control verified against DB state |
| **v11** | `dev-priority` | Reorder / prioritize jobs in the queue | Reordered job downloads first |
| **v12** | `dev-deploy-hardening` | cloudflared config, prod compose, logging, healthchecks, Postgres backups, restart policies | Survives host reboot with queue intact |
| **v13** | `dev-settings-ui` | *Final:* proxy management UI + global output-config override UI | Proxies and output settings editable without redeploy |

Note on v10/v11 ordering: your answer put reorder/priority on a different footing from the rest, so
it's split into its own version. If you'd rather have priority *before* the other controls, v10 and
v11 simply swap — say so at approval.

---

## Workflow rules (also written into CLAUDE.md)

- **Context comes from graphify, not exploration agents.** Initial build in v00; `graphify update .`
  after every code-modifying version; `graphify query "…"` / `path` / `explain` for all
  codebase questions thereafter.
- **One feature at a time.** Never implement auth + library usage + error handling together.
  Subagents run in parallel only on facets of the *same* version.
- **Every completed version opens a PR** from `dev-<feature>` into `main`. A version is a feature,
  not a release.
- **`CLAUDE.md` is the durable memory.** Decisions, env vars, the state machine, and the ladder
  values live there so nothing is re-litigated next session.
- **Develop and debug locally, added after v01.** A pull/rebuild/SSH-log-check loop per fix against
  the Debian production host doesn't scale as a development loop. The user's own PC
  (`docs/LOCAL_DEV.md`, `.env.dev.example`) is the primary iteration environment — Docker already
  installed there, hot reload via `docker-compose.override.yml`, reaching the same physical
  Postgres server the Debian host uses — currently the *same* database too, since there's no real
  data yet worth protecting from a local run; split to a dedicated dev database once that's no
  longer true. The Debian host
  (`docs/DEPLOYMENT.md`, `.env.example`) is for final per-version verification of something that
  already works locally, and for anything genuinely host-specific (the shared Postgres instance,
  Cloudflare Tunnel, restart survival) that can't be reproduced on a dev machine. See `CLAUDE.md`'s
  "Development environments" section for the full comparison.

---

## Verification

Per-version acceptance criteria are in the table above and expanded in each `plan/vNN-*.md`.
Cross-cutting checks:

1. **Durability** — the real test of this app. With tracks in `waiting` state:
   `docker compose restart worker-dl beat` and confirm via SQL that nothing is lost, duplicated, or
   fires early. Repeat with a full host reboot in v12.
2. **Rate-limit simulation** — an env-gated fault injector (`FAULT_INJECT=audio_provider:0.5`) so
   the ladder and circuit breaker are testable without waiting for real 429s. Combined with
   temporarily shortened ladder intervals (`LADDER_SECONDS` override) so a 5-step ladder runs in
   under a minute in tests.
3. **Auth** — real login against `https://api.vb2007.hu`; then confirm a valid upstream account that
   is *not* in `ALLOWED_EMAILS` is rejected, and that `VB-AUTH` never appears in any response to the
   browser.
4. **Tunnel behaviour** — SSE held open >5 minutes through cloudflared without dropping; verify
   reconnect-then-refetch recovers state after a forced disconnect.
5. **Unit tests** (pytest) on the pure logic: ladder arithmetic, breaker transitions, proxy
   selection, dedup, URL classification. Integration tests against a scratch Postgres schema.
6. **End-to-end** — submit a real multi-album artist URL, let it run, confirm every track ends in
   `completed`, `skipped_duplicate`, or `lookup_failed` with nothing stuck.
