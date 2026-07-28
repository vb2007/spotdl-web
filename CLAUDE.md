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
- **A PR isn't merge-ready until every change on it has actually been re-tested — not just unit
  tests.** After any fix (including ones made in response to a review pass), re-run the real
  verification for what changed: the local `docker compose` stack against a real network/DB
  where that's what the code touches, not only `pytest`. Unit tests can pass while a fix still
  fails against the real dialect/runtime (e.g. a Postgres-specific error path a SQLite test
  fixture can't exercise) — confirmed necessary in v04, where a post-review fix was re-verified
  end-to-end against the real Postgres instance and the real docker-compose stack before being
  called merge-ready, not just left at "pytest passes."
- **The plan file's "Done when" section is a literal checklist, not a vibe — every bullet needs
  its own concrete evidence (a log line, a command's output, a file listing) before a PR is called
  merge-ready, not an extrapolation from a similar or partial test.** Testing one scenario and
  assuming a differently-shaped one "probably" also works is exactly how regressions reach
  "merge-ready" status undetected. Confirmed necessary in v05: real-stack testing covered a
  single-track download, dedup, and disk reconciliation, but skipped the plan's explicit "a small
  real album" bullet — and a real album turned out to fail 100% of the time on the very first
  attempt (a cross-process `SpotifyClient` bug that only album-shaped songs trigger, invisible
  from single-track testing). The PR had already been called merge-ready before that gap was
  caught — by the user re-reading the plan file, not by this workflow. Before saying "merge-ready"
  or "done when criteria met," re-read the plan's "Done when" list fresh and check off each line
  against what was *actually run this session*, not what seems like it should generalize.
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

### v04 URL-expansion gotchas (learned building `get_simple_songs` wrapper + `/api/jobs`)

- **spotdl 4.5.2 hard-pins `fastapi<0.104` and `uvicorn<0.24` as unconditional (non-extra)
  dependencies**, for its own bundled web UI (`spotdl.web`) that this project never imports or
  runs — but `import spotdl` (triggered transitively by `from spotdl.utils.search import
  get_simple_songs`) always runs `spotdl/__init__.py` → `spotdl.console` →
  `spotdl.console.entry_point`, which unconditionally does `from spotdl.console.web import web`
  at module level. So spotdl.web's fastapi/uvicorn imports execute on every process that touches
  spotdl at all, and its pins directly conflict with our own `fastapi>=0.115`/
  `uvicorn[standard]>=0.32`. Fixed with `uv`'s resolver override, not a version downgrade:
  ```toml
  [tool.uv]
  override-dependencies = ["fastapi>=0.115", "uvicorn>=0.32"]
  ```
  Verified (don't just trust the resolver) that `spotdl.web`'s code actually still imports
  cleanly against the newer pinned versions — confirmed via `import spotdl.utils.search` in the
  built venv/image; only a handful of harmless `DeprecationWarning`s (`on_event` vs lifespan)
  come out of it. **Plain `pip install .` does not read `[tool.uv]` at all** and will hit the
  original conflict — `backend/Dockerfile` was changed from `pip install .` to `pip install uv
  && uv pip install --system .` for this reason. Any future bump of spotdl, fastapi, or uvicorn
  needs this override re-verified the same way (real import check), not assumed.
- **`SpotifyClient` (`spotdl.utils.spotify`) is a process-wide singleton whose `.init()` raises
  `SpotifyError` if called a second time** — a real risk here since `worker-meta` runs with
  Celery's default prefork concurrency (multiple task executions can reuse the same worker
  process) and every `expand_job` call otherwise would re-call `expansion.expand()`.
  `app/services/expansion.py`'s `_ensure_spotify_client()` does a double-checked-lock pattern
  (`SpotifyClient()` to probe, catch `SpotifyError`, lock, probe again, then `.init()`) so init
  runs at most once per worker process. **Any future spotdl entry point added outside
  `expansion.py` must go through `_ensure_spotify_client()` too**, never call
  `SpotifyClient.init()` directly.
- Default Spotify app credentials (used when `SPOTIFY_CLIENT_ID`/`SECRET` are unset, per the
  v01 locked decision) are spotdl's own published defaults —
  `spotdl.utils.config.DEFAULT_CONFIG["client_id"/"client_secret"]`. Hardcoded as
  `expansion._DEFAULT_CLIENT_ID`/`_DEFAULT_CLIENT_SECRET` rather than imported, since
  `spotdl.utils.config` pulls in the full CLI arg-parsing surface for one dict lookup.
- **`sqlalchemy.dialects.postgresql.JSONB` has no SQLite compiler**, so
  `Track.__table__.create(engine)` on the SQLite in-memory test engine (see v02/v03 gotchas)
  raises `UnsupportedCompilationError` — `tests/conftest.py` registers
  `@compiles(JSONB, "sqlite")` returning plain `"JSON"` to work around this; a no-op against real
  Postgres. **Any future JSONB column added to a model needs this same fixture already in place
  to be testable** — it now lives in `conftest.py` once, not per-test.
- `get_simple_songs` raises different, inconsistent exception types for malformed input
  depending on *how* it's malformed — confirmed empirically: a syntactically-valid but
  nonexistent track ID raises a bare `KeyError('uri')` from deep inside spotdl's Spotify-response
  parsing, not a clean `QueryError`/`SpotifyError`. `expand_job`'s `except Exception` catch-all
  in `app/tasks/expand.py` is deliberately broad for exactly this reason — narrowing it to
  specific spotdl exception types would miss cases like this.
- Verified against the real network (not mocked) during this version: a track URL, an album URL
  (13 tracks), and an artist URL (390 tracks across every album) all expand correctly end-to-end
  through `POST /api/jobs` → `worker-meta` → `GET /api/jobs/{id}/tracks`, every track landing and
  staying in `pending`. `worker-dl` also registers `expand_job` in its task list (it imports the
  same `celery_app` module) but never runs it — `task_routes` still confines it to the `meta`
  queue only worker-meta consumes.
- **The `except Exception` in `expand_job` originally only wrapped `expansion.expand()` itself,
  not the per-song `Track` insert loop or the final `db.commit()`.** Caught by an independent
  review pass: a song with `spotify_track_id=None` (e.g. a malformed list-expansion entry —
  `Track.spotify_track_id` is `nullable=False`) raised an uncaught `IntegrityError` at commit
  time, crashing the task with no `job.error` set and no state transition — the job would sit in
  `expanding` forever with nothing in the UI explaining why (Celery's default ack-on-receipt means
  no retry either). Fixed by widening the `try` to cover the insert loop + commit, with a
  `db.rollback()` before recording the failure. Regression test:
  `test_expand_job_db_error_during_insert_marks_job_failed` (confirmed it fails against the
  pre-fix code). **Any future code added to `expand_job` between "call expansion.expand()" and
  "commit" must stay inside that same `try`** — the whole point is that nothing about turning
  Songs into Track rows should be able to leave a job stuck silently.
- Two lower-severity items surfaced by that same review, deliberately **not** fixed in v04 —
  noted here so they aren't re-discovered from scratch later:
  - `job.source_url` reaches spotdl's `get_simple_songs` raw, which has branches beyond Spotify/
    YouTube URL parsing: a string ending in `.spotdl` is opened as a **local file** and JSON-
    parsed, and a `spotify.link/...` string triggers an outbound `requests.head(..., allow_redirects=True)`.
    Low impact today — single-user, allowlisted — but worth knowing before this endpoint's trust
    model changes. (As of v05, `worker-meta` *does* have the `downloads` volume mounted — see
    below — so this is no longer mitigated by that container being read-only-by-omission either.)
  - `GET /api/jobs` runs one grouped-count query per job (N+1) via `_track_counts` — fine at
    current scale, revisit if job history grows large (no pagination either).

### v05 downloader gotchas (learned building real downloads + dedup ledger + disk reconciliation)

- **`worker-meta` needed the `downloads` named volume added in this version** — it didn't have
  one before (v04 note above, now stale) since expansion never touched disk. `reconcile_disk()`
  runs there on boot (see next point), so it needs read/write access to the same
  `DOWNLOAD_OUTPUT_DIR` `worker-dl` writes to. Compose list-merge behavior (v01 gotcha) meant
  adding `downloads:/downloads` to the base `docker-compose.yml` service was enough — the
  override file's separate `./backend/app:/app/app` bind mount for the same service concatenates
  with it rather than replacing it; verified with `docker compose config` rather than assumed.
- **`reconcile_disk()` on worker-meta boot is gated by an explicit `RUN_DISK_RECONCILE=true` env
  var set only on that service in `docker-compose.yml`, not by introspecting which Celery queue
  the process consumes.** `celery_app.py`'s `worker_ready` signal handler fires identically in
  every process that imports the module (api, beat, both workers) since `-Q meta`/`-Q downloads`
  is a `celery worker` CLI arg invisible to the importing module; reflecting on that from inside
  `celery_app.py` would mean digging into `Consumer`/`Worker` internals for something an env var
  says explicitly. **Any future worker-boot-only hook needs the same explicit env-var gate**,
  not queue introspection.
- **`spotdl.types.song.Song.from_dict(data)` / `song.json` round-trip cleanly** (`from_dict` is
  just `cls(**data)`, `.json` is `dataclasses.asdict(self)`) — confirmed by reading the source,
  not assumed. This is what lets `download_track` turn `Track.song_json` (stored by `expand_job`
  in v04) back into a real `Song` for `Downloader.search_and_download` without re-querying
  Spotify.
- **`Downloader.__init__` fills any keys missing from the passed `DownloaderOptions` dict from
  spotdl's own defaults** (`create_settings_type(..., DOWNLOADER_OPTIONS)`) — `get_downloader()`
  only needs to pass `format`/`bitrate`/`output`/`cookie_file`(+`proxy` when given), not the full
  ~45-key `TypedDict`. Verified against the real installed 4.5.2 source
  (`Downloader.__init__`), not just the plan's key list.
- **No fixed output path template exists anywhere in config** — `DOWNLOAD_OUTPUT_DIR` is a bare
  directory. `get_downloader()` joins it with spotdl's own default filename pattern
  (`"{artists} - {title}.{output-ext}"`, read from `spotdl.utils.config.DEFAULT_CONFIG["output"]`)
  to build the `output` option. Per-template override is v13's job (locked decision: global
  output config first, UI override deferred); don't add a `DEFAULT_OUTPUT_TEMPLATE` env var ahead
  of that version without asking.
- **`Downloader.search_and_download` needs a live `SpotifyClient` in the *same process*, not just
  in whichever process expanded the job** — missed on the first pass and only surfaced by
  actually downloading a real album (single-track jobs happened to not trigger it). Internally it
  "reinitializes" the song (re-fetches metadata via `reinit_song`/`Song.from_url`) whenever any of
  `genres`/`disc_count`/`tracks_count`/`track_number`/`album_id`/`album_artist` is `None` — common
  for album/playlist-expanded songs, not for the single-track expansion path that happened to work
  in initial testing. `worker-dl` is a separate OS process from `worker-meta`; the `SpotifyClient`
  singleton `expansion._ensure_spotify_client()` initializes there never exists in `worker-dl`
  unless something in that process calls it too. Every album track failed with `"Error occurred
  while reinitializing song: Spotify client not created"` until `downloads.download_one()` was
  changed to call `expansion._ensure_spotify_client()` before `search_and_download` — exactly the
  "any future spotdl entry point must go through `_ensure_spotify_client()`" rule the v04 gotcha
  above already called out; this is why. **Any future code path that calls into spotdl anywhere
  outside `expansion.py` needs the same call**, not just ones that look like they touch Spotify
  directly.
- Verified against the real network and the real docker-compose stack (not mocked) in this
  version: a real track URL downloads to `DOWNLOAD_OUTPUT_DIR` with the correct filename and
  embedded `artist`/`album`/`track` tags; re-submitting the same URL immediately lands
  `skipped_duplicate` with a sub-10ms task duration (no network call — confirmed via
  `worker-dl` logs); deleting the file and restarting `worker-meta` drops the
  `downloaded_tracks` row (`reconcile_disk: checked 1 ledger rows, removed 1 with missing files`
  in the logs) and the next submission of the same URL re-downloads it from scratch; a real
  15-track album (Muse — *Absolution*, `open.spotify.com/album/0HcHPBu9aaF1MxOiZmUQTl`) downloaded
  14/15 tracks successfully with correct filenames/tags for each, while the 15th hit a real
  transient `"Could not get client token"` Spotify API error and landed `failed` — the other 14
  tracks in the same job were entirely unaffected, confirming task isolation for real rather than
  only structurally. (That transient failure is exactly what v06's retry ladder exists for — it's
  expected to succeed on a later attempt, not a bug to chase here.)
- **Local dev's `downloads` folder is a host bind mount (`./downloads` at the project root, in
  `docker-compose.override.yml` for `worker-dl`/`worker-meta`), not the base file's named Docker
  volume** — lets downloaded files be inspected directly from the host during testing.
  `docker-compose.yml` (the prod-like base) still declares `downloads` as a named volume; the
  override's `!override` tag replaces the service's `volumes:` list rather than merging with it
  (same v01 gotcha as the `web` service's `ports:` override), since simply adding a bind mount
  entry would otherwise sit alongside the named-volume mount at the same `/downloads` target.
  `/downloads/` is gitignored at the project root.

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
