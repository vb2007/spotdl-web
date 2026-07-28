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
- **Develop and debug locally first, deploy to verify.** The user's PC (`docs/LOCAL_DEV.md`) is the
  primary iteration loop — Docker already installed there, hot reload via
  `docker-compose.override.yml`, fast to fix and re-test. The Debian production host
  (`docs/DEPLOYMENT.md`) is a final-verification target for a version that's already working
  locally, not a place to chase build errors interactively — a pull/rebuild/SSH-log-check round
  trip per fix doesn't scale as a dev loop. Only fall back to debugging directly on the Debian
  host for issues that are genuinely host-specific (the shared Postgres instance, tunnel/ingress,
  restart survival) and can't reproduce locally.

### Development environments

Two separate environments, sharing the physical Postgres server **and, for now, the same
database on it too** — there's no real user data yet worth protecting from a local dev run, so
the extra ceremony of a separate `spotdl_web_dev` database isn't worth it yet. Revisit once the
app holds anything worth not wiping out (realistically once v09+/frontend makes it easy to
generate real-looking state) — switch local dev's `DATABASE_URL` to a dedicated database at that
point, everything else about the split stays the same.

| | Local dev (`docs/LOCAL_DEV.md`) | Debian host (`docs/DEPLOYMENT.md`) |
|---|---|---|
| Purpose | Day-to-day iteration | Final per-version verification + eventual real deployment |
| `.env` template | `.env.dev.example` | `.env.example` |
| Compose invocation | `docker compose up` (override applies — hot reload) | `docker compose -f docker-compose.yml up` (override excluded) |
| Postgres | Same physical server, reached over LAN by its real address | Same physical server, reached via `host.docker.internal` (same host as the containers) |
| Database | `spotdl_web` — same one the Debian host uses, for now | `spotdl_web` (or whatever was created) |
| Redis, other containers | Fully local, independent per environment | Fully local, independent per environment |

`DATABASE_URL`'s host is the one thing that's genuinely different between the two `.env`
templates — never copy `host.docker.internal` into the local one (Postgres isn't on the same
host as the local containers, that would resolve to the wrong machine entirely) or a hardcoded
LAN IP into the production one (fragile if the Debian host's address ever changes;
`host.docker.internal` is already correct there since Postgres and the containers share a host).

### Locked decisions

| Area | Decision |
|---|---|
| Backend | Python 3.12, FastAPI + Celery |
| Task queue | Celery + Redis (Redis dockerized) |
| Database | PostgreSQL, non-dockerized on the Debian 12 host; local dev and the deployed instance currently share one database (see Development environments) — split once there's real data to protect |
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

### v01 deployment gotchas (learned deploying to the real host and local dev)

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
- **On the local dev PC (rolling-release Arch): a pending kernel update blocks all Docker container
  networking**, not just this project's. Symptom is every container failing at startup with
  `failed to add the host <=> sandbox pair interfaces: operation not supported` — the `veth` kernel
  module (and everything else) for the *currently running* kernel has already been deleted from
  disk in favor of a newer installed one, and modules can't be loaded for a kernel that's no longer
  on disk. Check `uname -r` against `pacman -Q linux` and whether `/lib/modules/$(uname -r)/`
  exists; fix is a reboot, nothing project-specific.
- **`docker-compose.override.yml`'s list-type keys merge with `docker-compose.yml` instead of
  replacing it** — `ports`, `volumes`, etc. combine across files; only keys like `command`/`build`
  replace outright. `web`'s override used to add a second `ports` entry instead of replacing the
  base file's, so both `127.0.0.1:5173:80` (base, stale — dev serves via `vite dev` on 5173, not
  nginx on 80) and `127.0.0.1:5173:5173` (override, correct) got programmed as separate host
  bindings on the same address, causing `Bind for 127.0.0.1:5173 failed: port is already allocated`
  at container start. Fixed with the `!override` merge tag on that `ports:` key. **Any new
  override list value that's meant to replace rather than extend the base file needs the same
  tag** — verify with `docker compose config` rather than assuming a plain list "just works."
- Full deploy runbook: `docs/DEPLOYMENT.md`; local dev runbook: `docs/LOCAL_DEV.md`.

### v02 schema gotchas (learned building the SQLAlchemy models + initial migration)

- **`sqlalchemy.Enum(SomePyEnum, ...)` stores member *names* in the database by default, not
  member *values*.** A Python enum with lowercase string values (matching the plan's exact
  wording, e.g. `TRACK = "track"`) still produces a Postgres `ENUM('TRACK', 'ALBUM', ...)` unless
  the column is declared with `values_callable=lambda cls: [e.value for e in cls]`. Applies to
  every enum column in this schema (`job_source_type`, `job_state`, `track_state`,
  `track_error_type`, `proxy_source`) — **any future enum column needs the same
  `values_callable`** or the DB values silently drift from what every plan doc and downstream
  service code assumes.
- **`op.drop_table()` does not drop the native Postgres `ENUM` type it implicitly created** —
  after `alembic downgrade base`, the tables were gone but `\dT` still showed all 5 enum types,
  failing the "downgrade cleanly drops everything" check. Fixed by adding explicit
  `op.execute("DROP TYPE ...")` calls at the end of `downgrade()` for every enum type the revision
  creates. **Any future revision that adds a new native enum column needs the same explicit drop
  in its `downgrade()`** — autogenerate never emits this on its own.
- The partial index (`tracks (scheduled_at) WHERE state = 'waiting'`) that the v02 plan warned
  might need hand-fixing actually came out of `alembic revision --autogenerate` correctly on a
  from-scratch DB (verified: `\d tracks` shows `WHERE state = 'waiting'::track_state`) — the
  known autogenerate limitation is about *diffing* an existing partial index on a later
  `--autogenerate` run, not initial creation. Still worth a manual eyeball on every future
  partial-index revision rather than trusting the diff blindly.
- The `sessions` table's model class is named `UserSession` (`app/models/session.py`), not
  `Session` — `sqlalchemy.orm.Session` is the DB-session type FastAPI routes depend-inject
  everywhere (`db: Session = Depends(get_db)`), so a same-named ORM model would force an import
  alias at every call site touching both. v03's `app/services/sessions.py` should import
  `UserSession`, not shadow-name it.
- `app/db.py`'s `Base` now declares a `type_annotation_map` (`datetime` → `DateTime(timezone=True)`,
  `uuid.UUID` → `PgUUID(as_uuid=True)`) so every model just writes `Mapped[datetime]` /
  `Mapped[uuid.UUID]` and gets the right Postgres type — every timestamp in this schema must be
  `timestamptz`, and repeating `DateTime(timezone=True)` on ~15 columns individually was the
  alternative. **Any future timestamp/uuid column added outside this mapping needs an explicit
  type override**, not a bare `Mapped[...]`, or it'll get the wrong (naive/non-UUID-typed) column.
- Verified against a scratch `postgres:17-alpine` container (not the shared dev/prod Postgres —
  no reason to touch real data for a schema-only version): `upgrade head` → `downgrade base` →
  `upgrade head` round-trips cleanly, `worker_state` seed row (id=1) survives, and every field
  referenced by v04–v13's plan docs (`jobs.priority`, `tracks.attempt_count`/`scheduled_at`/
  `used_proxy_id`, `proxies.*`, `worker_state.*`) already exists here — no ad-hoc migration should
  be needed until v13's possible new `settings` table.

### v03 auth gotchas (learned building the upstream login proxy + session cookie)

- **The session cookie is set with `Secure=True`, which conflicts with local dev's plain
  `http://localhost` — except it doesn't**: modern browsers (Chrome, Firefox) treat
  `http://localhost` as a secure context and will store/send `Secure` cookies over it without
  real TLS. No dev-only exception was needed. The same is *not* true for `httpx`'s cookie jar
  (used by FastAPI's `TestClient`) — it enforces the `Secure` flag literally by scheme, so tests
  must use `TestClient(app, base_url="https://testserver")` or the session cookie silently never
  round-trips on the next request. Any future test hitting a cookie-authenticated route needs the
  same `https://` base_url.
- **`UserSession.last_seen_at` can come back timezone-naive** even though the column is
  `timestamptz` (via `Base.type_annotation_map`, see v02) — only true against real Postgres/psycopg;
  SQLite (used for fast in-process auth tests, `UserSession.__table__.create()` on an in-memory
  engine rather than spinning up Postgres) returns a naive datetime for `func.now()` server
  defaults. `sessions.py`'s idle-timeout check normalizes with `.replace(tzinfo=timezone.utc)` if
  `tzinfo is None` before comparing — needed purely for the SQLite test path, a no-op against real
  Postgres, but removing it breaks every session-validating test.
- SQLite in-memory (`sqlite:///:memory:`) needs `poolclass=StaticPool` +
  `connect_args={"check_same_thread": False}` for FastAPI test fixtures — the default per-thread
  pool gives the request-handling thread (TestClient dispatches through Starlette's thread pool) a
  *different, empty* in-memory database than the one the fixture created tables on, surfacing as a
  confusing "no such table" error rather than an obvious connection-pooling one.
- `httpx` moved from `dev` to core `pyproject.toml` dependencies — `upstream_auth.py` needs it at
  runtime to call `vb2007.hu-api`, not just in tests.
- `SESSION_SECRET` (env var, scaffolded since v01) is still unused — sessions are opaque random
  tokens (`secrets.token_hex(32)`) looked up in Postgres, not signed/stateless, so nothing in v03
  needed it. Leave it wired in `config.py` for whichever future version wants signed cookies or
  CSRF tokens rather than removing it as dead config.
- **The live `https://api.vb2007.hu` has been having issues as of 2026-07-28.** Until it's
  healthy again, local dev's `UPSTREAM_AUTH_BASE_URL` points at a local instance of
  `vb2007.hu-api` running on the host machine's port 3000 instead — set in local `.env`
  (gitignored, never committed) as `UPSTREAM_AUTH_BASE_URL=http://host.docker.internal:3000`,
  **not** `http://localhost:3000` (the `api` container has its own network namespace;
  `localhost` there means the container itself — same class of gotcha as the `DATABASE_URL`
  note in v01). Test account is `balazs@vb2007.hu` (user `vb2007`) in `ALLOWED_EMAILS`; the
  password lives only in the local `.env` — **this repo is public on GitHub, never write that
  password into `CLAUDE.md`, a plan doc, or any other tracked file.** Switch both settings back
  once the live API is confirmed working again.
- **Adding a new core runtime dependency (e.g. `httpx` for `upstream_auth.py`) to
  `pyproject.toml` does not take effect in an already-running container** —
  `docker compose restart <service>` reuses the existing image, so the container keeps crash-
  looping on `ModuleNotFoundError` for the new import. Needs `docker compose build <service>`
  (or `up -d --build`) to actually rebuild the image. Applies to every future version that adds
  a new backend dependency, not just this one.

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
