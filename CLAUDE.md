## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

---

## Project: spotdl-web

A self-hosted, single-user web wrapper around the **spotdl** Python library. User submits Spotify
album/playlist/artist/track URLs; the app downloads everything in the background, treating
YouTube-Music rate limiting as an expected, permanent condition rather than a failure. Stated core
goal: **get everything by dodging rate limitations, even if it takes an extremely long time.**
Full roadmap and rationale: `plan/00-master-plan.md`. Per-version implementation detail:
`plan/v00-planning.md` … `plan/v13-settings-ui.md`.

### Workflow rules (do not deviate without asking)

- **One feature at a time.** Never implement auth + library usage + error handling in parallel.
  Work through `plan/vNN-*.md` in order. Subagents are used *within* a version, all focused on that
  version's single concern — not spread across versions.
- **Branch per version**: `dev-<feature-name>` (e.g. `dev-scaffold`, `dev-auth`), branched from
  the current dev line (started from `dev-init`). Every completed version opens a PR into `main`.
  A "version" is a feature slice, not a release.
- **Context comes from graphify, not exploration agents.** Run `graphify query "…"` /
  `graphify path "A" "B"` / `graphify explain "concept"` for codebase questions before searching
  manually. Run `graphify update .` after every code-modifying version.
- **This file is the durable memory.** Every decision, gotcha, and number below must stay current —
  a fresh session should be able to continue the project from `CLAUDE.md` + `plan/` alone, without
  re-deriving anything already settled here.

### Locked decisions

| Area | Decision |
|---|---|
| Backend | Python 3.12, FastAPI + Celery |
| Task queue | Celery + Redis (Redis dockerized) |
| Database | PostgreSQL, non-dockerized on the Debian 12 host |
| Frontend | SvelteKit + TypeScript |
| Live updates | SSE now, WebSocket later if needed |
| Ingress | Cloudflare Tunnel only — no port forwarding, ever |
| Auth | Proxy login to existing `vb2007.hu-api`, own session cookie |
| Rate-limit handling | Per-track ladder **+** global circuit breaker |
| Proxies | Plain file first (`proxies.txt`); UI management deferred to v13 |
| Proxy strategy | Direct first → on failure wait out the ladder → *then* proxy |
| Output config | Global env config first; UI override deferred to v13 |
| Dedup | DB table keyed on Spotify track ID + disk reconciliation |
| Extra levers (cookies file, own Spotify app creds, pacing delay) | None enabled initially; config hooks present, default off |
| Deployment | Docker Compose stack on Debian 12 |

### Auth API — `vb2007.hu-api` (verified from `/home/vb2007/code/vb2007.hu-api` source)

- `POST /auth/login`, body `{ email, password }` → `200` + `Set-Cookie: VB-AUTH=<sessionToken>;
  Domain=localhost; Path=/` (`src/controllers/authentication.ts:39`). Errors: `400` missing
  fields, `404` unknown email, `403` wrong password.
- `sessionToken = HMAC-SHA256(salt + "/" + userId, CRYPTO_SECRET_KEY)`, no expiry, stored in Mongo.
- `GET /user` behind `isAuthenticated` validates the `VB-AUTH` cookie — no `/auth/me` exists
  upstream.
- Public base URL: `https://api.vb2007.hu`.
- **Gotcha 1:** `Domain=localhost` is hardcoded on the upstream cookie — a browser on any other
  domain can never store it. Login must be **server-to-server**: spotdl-web's backend POSTs
  credentials, checks the upstream status code, and never forwards `VB-AUTH` to the browser.
  spotdl-web mints its own session cookie instead.
- **Gotcha 2:** `POST /auth/register` is public upstream, so a successful upstream login only
  proves "this is a real account," not "this person may use spotdl-web." An `ALLOWED_EMAILS` env
  allowlist, checked after upstream success, is the actual authorization gate. Allowlist rejection
  and wrong-password must return byte-identical responses so the two are indistinguishable.

### spotdl 4.5.2 — verified API surface actually used

- `Spotdl(client_id, client_secret, ..., downloader_settings: DownloaderOptions)`;
  lower-level: `Downloader(settings, loop)`.
- Relevant `DownloaderOptions` keys: `proxy`, `threads`, `output`, `format`, `bitrate`,
  `cookie_file`, `audio_providers`, `overwrite`, `archive`, `scan_for_songs`, `filter_results`,
  `only_verified_results`, `yt_dlp_args`, `max_filename_length`.
- `spotdl.utils.search.get_simple_songs(query, ...)` classifies and expands track/album/
  playlist/artist URLs into `List[Song]` — this is the URL-expansion primitive; never hand-roll
  Spotify Web API calls to replace it.
- `Downloader.search_and_download(song) -> Tuple[Song, Optional[Path]]` is the per-track unit.
  **It raises `DownloaderError` if called from a running asyncio event loop** — download tasks
  must be plain sync Celery tasks, not async.
- Errors: `AudioProviderError` (`spotdl.providers.audio.base`) = the rate-limit/yt-dlp-failure
  signal. `LookupError` = no result found on any provider (terminal, per user's explicit
  instruction — "it can't do much about it"). `DownloaderError` = config problems (bad proxy
  string, missing ffmpeg, wrong calling context).
- `Downloader.progress_handler.get_new_tracker(song)` + `notify_*` hooks are the live-progress
  source for SSE.
- spotdl ships default public Spotify credentials — `SPOTIFY_CLIENT_ID/SECRET` are optional
  overrides, not hard requirements.

### Architecture

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

**Critical rule: never use Celery `eta`/`countdown` for backoff delays.** With the Redis broker,
ETA tasks are prefetched into worker memory; a restart during a 24h wait loses or duplicates it.
`tracks.scheduled_at` in Postgres is the only source of truth for "when is this next eligible."
Celery Beat's `dispatch_due_tracks` (every 30s) selects due tracks (`FOR UPDATE SKIP LOCKED`) and
hands them to Celery, which is purely the executor. Backoff = `UPDATE tracks SET scheduled_at =
now() + interval`, fully inspectable with plain SQL, survives any restart.

Other notes: `worker-dl` runs `--concurrency=1 --prefetch-multiplier=1` (deliberate — concurrency
is rate-limit exposure); `worker-meta` handles expansion/reconciliation so long downloads never
block queue feedback; `Downloader` instances are cached per `(format, bitrate, proxy)` in the
worker process since construction initializes every provider; Postgres is reached from containers
via `extra_hosts: host.docker.internal:host-gateway`; SSE responses need `Cache-Control: no-cache`,
`X-Accel-Buffering: no`, and a `:heartbeat` comment every 15s or Cloudflare Tunnel closes the
idle connection — `EventSource` reconnects automatically, and the frontend refetches full state via
REST on every reconnect rather than replaying missed events.

### Track state machine

```
pending ──> queued ──> downloading ──> completed
                │            │
                │            ├─> AudioProviderError ─> waiting (scheduled_at = now + ladder)
                │            │                          └─> queued (via beat) ... ∞
                │            ├─> LookupError ──────────> lookup_failed  (terminal, notify, never retry)
                │            └─> other error ─────────> waiting (same ladder)
                └─> skipped_duplicate
any ──> cancelled
```

### Retry engine numbers

- **Per-track ladder** (`AudioProviderError`): `15m → 1h → 4h → 12h → 24h`, then 24h forever.
  Never gives up; track goes to the back of the queue each retry.
- **Global circuit breaker**: 5 consecutive `AudioProviderError`s (any track) trips a pause —
  `30m → 2h → 6h` escalating on successive trips; resets to zero on the first success afterward.
  While tripped, `dispatch_due_tracks` dispatches nothing.
- **Proxy escalation**: attempt 1 is always direct. On failure, wait out the ladder delay first —
  only the *following* attempt uses a proxy (the wait is the point; it avoids the switch looking
  like an evasion burst). A failing proxy gets its own `cooldown_until`.
- **`LookupError` is terminal** — recorded, surfaced in the UI, never retried automatically.
- **Pacing hook** (`PACING_MIN_SEC`/`PACING_MAX_SEC`, default 0): randomized inter-track delay,
  wired but off by default — the first dial to turn if 429s stay frequent after proxies.

### v01 deployment gotchas (learned deploying to the real host)

- **`pydantic-settings` auto-JSON-decodes any `list[...]`-typed field's raw env value before
  custom `field_validator`s run.** A plain comma-separated string (`ALLOWED_EMAILS=a@b.com,c@d.com`)
  is not valid JSON and crashes `Settings()` at import time with a `SettingsError` — the app never
  starts, `/api/health` gives no response at all. Fix: annotate the field
  `Annotated[list[str], NoDecode]` (from `pydantic_settings`) so the raw string reaches the
  before-validator unparsed. Applies today to `allowed_emails`/`ladder_seconds`; **any future
  list-typed config field (proxy list in v07, `audio_providers` override, etc.) needs the same
  annotation** or it will crash the same way.
- **Target host runs a shared Postgres instance, not a fresh install** — Postgres 18 via the PGDG
  apt repo (not Debian 12's bundled 15), already hosting roles for other self-hosted services
  (Matrix/Synapse, Vaultwarden). Don't assume `/etc/postgresql/15/main/`; get the real paths from
  `SHOW config_file` / `SHOW hba_file`. `pg_hba.conf` also already has entries for those other
  services — it's first-match-wins top-to-bottom, so an earlier broad rule can shadow anything
  appended for spotdl-web.
- **Don't hardcode `172.17.0.1`** (the default `docker0` bridge gateway) anywhere — `docker compose
  up` creates its own project-scoped bridge with a different subnet. A host-side `psql` test against
  `172.17.0.1` can succeed (the host has a direct interface there) while giving no information about
  whether a container can reach it. Always use `host.docker.internal` (resolved via
  `extra_hosts: host-gateway` in `docker-compose.yml`) in `DATABASE_URL`, never a literal IP.
- Full deploy runbook: `docs/DEPLOYMENT.md`.

### Version roadmap

| # | Branch | Scope |
|---|---|---|
| v00 | `dev-planning` | Plan files + this CLAUDE.md + initial graphify build |
| v01 | `dev-scaffold` | Repo layout, compose stack topology, config, `/api/health`, Alembic init |
| v02 | `dev-db-schema` | All SQLAlchemy models + one migration (no business logic) |
| v03 | `dev-auth` | Upstream login proxy, allowlist, own session cookie |
| v04 | `dev-url-expansion` | URL → `tracks` rows via `get_simple_songs` (no downloading) |
| v05 | `dev-downloader` | Real downloads, dedup, naive error handling |
| v06 | `dev-retry-engine` | Error classification, ladder, `scheduled_at`/beat dispatch, breaker |
| v07 | `dev-proxy-rotation` | `proxies.txt`, health/cooldown, direct-then-proxy escalation |
| v08 | `dev-live-progress` | spotdl progress hooks → Redis pub/sub → SSE `/api/stream` |
| v09 | `dev-frontend` | SvelteKit login, submit form, live queue table |
| v10 | `dev-queue-controls` | Cancel, retry-now, pause/resume worker + breaker |
| v11 | `dev-priority` | Reorder/prioritize jobs in dispatch order |
| v12 | `dev-deploy-hardening` | cloudflared config, prod compose, backups, restart survival |
| v13 | `dev-settings-ui` | *Final:* proxy management UI + output-config override UI |

Full detail for each row lives in `plan/vNN-*.md`. Do not start a version out of order without
asking the user first — the sequencing (e.g. auth before expansion, retry engine before proxy
rotation, everything before the settings UI) is intentional.
