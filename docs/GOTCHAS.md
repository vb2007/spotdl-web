# spotdl-web — Accumulated Gotchas (master v1, v01–v13)

Hard-won findings from building master v1, kept **verbatim** as they were written when each
version shipped. These were originally in `CLAUDE.md`; they were moved here once that file grew
past 1,700 lines, because a rule an agent must follow and a war story an agent might need are
different kinds of document and only the first belongs in every context window.

**How to use this file:** don't read it top to bottom. Find your topic in the index below, read
that section, move on. `CLAUDE.md` carries the rules that always apply; this carries the specifics
of *why* — and the failure modes that will otherwise be rediscovered the expensive way.

**A caveat that matters:** these describe the codebase as it was at each version's merge. Master v2
(v14+) changes schema, endpoints, and the frontend substantially. **Verify a referenced file,
function, or flag still exists before acting on it.** A gotcha that turns out to be stale should be
corrected in place with a dated note — the way v12 corrected v09's false "no nginx SPA-fallback
needed" claim — rather than silently deleted.

---

## Index by topic

**Config & environment**
- `pydantic-settings` auto-JSON-decodes `list[...]` fields; any new list-typed setting needs
  `Annotated[list[str], NoDecode]` or the app won't start → *v01*
- Adding a runtime dependency needs `docker compose build`, not `restart` → *v03*
- `DATABASE_URL` host differs between local dev and the Debian host; never cross them → *v01*
- A `BaseSettings` field omitted from a test's constructor kwargs still resolves from
  `os.environ` — a test asserting "missing X is rejected" must `monkeypatch.delenv(X)` first, or
  it silently passes via a value some *other* test's `conftest.py` setdefault already set → *v17*

**Database, migrations & enums**
- `Enum(...)` stores member *names* unless `values_callable` is set → *v02*
- `op.drop_table()` doesn't drop the native enum type; needs explicit `DROP TYPE` in `downgrade()`
  → *v02*
- Adding a *value* to a shipped enum needs `ALTER TYPE ... ADD VALUE` + a type-swap downgrade;
  autogenerate never detects it → *v10*
- **Removing** a value from a shipped enum via the type-swap technique breaks any partial index
  whose `WHERE` clause embeds a literal of that type — drop the index before the swap, recreate
  after → *v16*
- Partial indexes: autogenerate emits them on first creation but not on later diffs → *v02*
- `Base.type_annotation_map` gives `timestamptz`/`PgUUID`; columns outside it need explicit types
  → *v02*
- The model class is `UserSession`, not `Session` (collides with `sqlalchemy.orm.Session`) → *v02*
- `JSONB` has no SQLite compiler; `conftest.py` registers a `@compiles` shim for tests → *v04*
- v16 landed `jobs.user_id`/`sessions.user_id` as **NOT NULL with no application code populating
  them yet** — deliberate, and fixed in v17 by wiring `get_or_create_user` into login → *v16, v17*
- `Track.song_json[key].astext` extracts JSONB text portably on both Postgres and SQLite, including
  for array-valued keys (returns the array's JSON text form on both) — `.op("->>")(...)` instead
  fails at execution on SQLite → *v18*
- A pg_trgm GIN index is only used when the query's expression is structurally identical to the
  one it was built on, not merely equivalent — keep the migration's raw SQL a hand-verified copy of
  the query-builder's compiled output → *v18*
- Row-value tuple comparison (`(a, b) > (c, d)`) breaks the moment any element can be `NULL` (SQL's
  three-valued logic silently drops rows); keyset-paginate a nullable sort key with an explicit
  two-branch WHERE instead → *v18*
- A correlated scalar subquery's (implicit or explicit) correlation target must be the statement's
  *actual* enclosing `FROM`, not the table the subquery conceptually belongs to — passing an
  aggregated-subquery's column while asking to correlate against the raw table it was built from
  silently produces an uncorrelated subquery instead of an error → *v18*

**Docker Compose & deployment**
- Override files **merge** list keys (`ports`, `volumes`) and **replace** mapping keys
  (`command`, `healthcheck`, `build`); use `!override` when a list must replace → *v01, v05, v12*
- Never hardcode `172.17.0.1`; use `host.docker.internal` via `extra_hosts` → *v01*
- `localhost` resolves to IPv6 first in these images and nothing binds it — healthchecks must use
  `127.0.0.1` → *v12*
- Compose interpolation escaping is *opposite* for the redis vs. worker healthchecks (`$` vs `$$`)
  → *v12*
- The `migrate` one-shot service must override the shared anchor's `depends_on` or it deadlocks on
  itself → *v12*
- Redis as a Celery broker needs `maxmemory-policy noeviction`; `allkeys-lru` silently drops queued
  tasks → *v12*
- Arch local dev: a pending kernel update breaks all container networking (not project-specific)
  → *v01*

**Auth, cookies & sessions**
- Upstream `vb2007.hu-api` hardcodes `Domain=localhost`; login must be server-to-server → *v03*
- `Secure` cookies work over `http://localhost` in browsers but **not** in `httpx`/`TestClient` —
  tests need `base_url="https://testserver"` → *v03*
- SQLite returns naive datetimes for `func.now()`; session/breaker checks normalize to UTC → *v03,
  v06*
- SQLite in-memory test engines need `StaticPool` + `check_same_thread=False` → *v03*
- `localhost` and `127.0.0.1` are different CORS origins *and* cross-site for `SameSite` cookies —
  produced a 200-then-401 login bug → *v09*
- A `catch` block must distinguish "the backend said no" from "the request never arrived" → *v09*
- **Standing rule: real-stack verification of login must exercise the actual upstream
  `vb2007.hu-api` for at least one identity**, local instance preferred, live
  `https://api.vb2007.hu` as fallback — the direct-session-mint fallback alone is not enough
  → *v17*
- Splitting session-lookup from user-resolution (`current_session` → `require_session`) adds one
  query per request: `current_session`'s own `db.commit()` expires the `UserSession` ORM object
  (SQLAlchemy's default `expire_on_commit=True`), so `require_session`'s next attribute read
  (`session.user_id`) triggers an implicit re-`SELECT` by primary key before the `User` lookup can
  even run. Constant overhead (proven by a query-count *differential*, not the absolute), not an
  N+1 — left as is rather than restructured, since avoiding it would mean either deferring the
  session's idle-timeout commit past the point every downstream dependency has already read from
  the request, or duplicating the idle-timeout bump logic → *v17*

**spotdl library**
- spotdl pins `fastapi<0.104`/`uvicorn<0.24` for a web UI we never run; resolved via `[tool.uv]
  override-dependencies` (so the Dockerfile must use `uv pip install`, not `pip install`) → *v04*
- `SpotifyClient` is a process-wide singleton that raises on second `.init()`; every spotdl entry
  point must go through `expansion._ensure_spotify_client()` → *v04, v05*
- `search_and_download` re-fetches metadata for album-shaped songs and needs a live `SpotifyClient`
  **in the same process** — invisible when testing single tracks → *v05*
- `Downloader` accepts only `http(s)://` proxies with a literal IPv4 host — no hostnames, no
  `socks5://` → *v07*
- `Downloader` builds a `rich` Live display by default and `rich` allows one per process; always
  pass `simple_tui: True` → *v07*
- Progress hooks are reached by setting `downloader.progress_handler.update_callback` on the
  instance — there is no `DownloaderOptions` key → *v08*
- `import spotdl` writes to `~/.spotdl` at import time; the non-root container user needs a real
  home directory → *v12*
- Valid `--format`/`--bitrate` values are introspected live from spotdl's own argparse rather than
  hardcoded → *v13*

**Celery, tasks & durability**
- `record_failure` computes the ladder delay **before** incrementing `attempt_count`; reversing it
  skips the first rung → *v06*
- Only real `AudioProviderError`s feed the circuit breaker; the "other" bucket shares the ladder but
  never trips it → *v06*
- Importing `app.tasks.*` directly hits a circular import — import `app.tasks.celery_app` first
  → *v06*
- Worker-boot hooks are gated by explicit env vars (`RUN_DISK_RECONCILE`, `RUN_PROXY_SYNC`), never
  by introspecting the consumed queue → *v05, v07*
- `task_acks_late` + `task_reject_on_worker_lost` + a DB-level stale-track reclaim sweep are what
  make a mid-download crash recoverable → *v12*
- Connecting the `setup_logging` signal disables Celery's own logging setup entirely — `-l info`
  becomes documentation, not the level source → *v12*
- The pacing hook sat declared-but-unwired for four versions because nothing ever asserted it had
  an effect; raising it also requires raising `STALE_TRACK_AFTER_SECONDS` → *v15*
- `download_track` only gates on `CANCELLED` — a redelivered message for an already-`COMPLETED`
  track can regress it to `SKIPPED_DUPLICATE` (found, documented, not fixed) → *v15*
- Verifying a new hourly (or longer) `beat_schedule` entry actually fires doesn't require waiting
  out the real interval — temporarily edit the schedule literal to a few seconds, `docker compose
  restart beat`, confirm `Scheduler: Sending due task ...` in real container logs, then revert the
  literal and restart again before committing → *v19*

**Live progress & SSE**
- SSE needs `Cache-Control: no-cache`, `X-Accel-Buffering: no`, and a 15s heartbeat or Cloudflare
  Tunnel closes the connection → *v08*
- `get_message(ignore_subscribe_messages=True)` returns `None` immediately after subscribe, so the
  first heartbeat fires early (harmless) → *v08*
- Never drive a real infinite SSE generator through `TestClient.stream(...)` — it hangs; use a
  finite fake generator + plain `.get()` → *v08*
- `EventSource` auto-reconnects only on network-level failure; a `502`/`401` kills the stream
  permanently, so the frontend needs manual backoff reconnect → *v12*
- A slow uninterruptible operation can publish stale state *after* the true outcome — re-publish
  the real final state last, **and** guard the client store against applying events to
  truly-terminal tracks (two independent fixes, at two layers) → *v10*
- Channels went from one global `spotdl:events` to per-user `spotdl:events:{user_id}` — every
  `publish_*_event`/`make_progress_callback` call now takes the owning user as a **required**
  first positional argument (no default), specifically so a forgotten call site is a loud
  `TypeError` in tests, not a silent broadcast-to-nobody. `get_message(ignore_subscribe_messages=
  True)` filters `PSUBSCRIBE` confirmations exactly like `SUBSCRIBE` ones, and a `pmessage`'s
  payload lands at the same `message["data"]` key — the SSE forward loop needed no change for the
  admin pattern-subscribe path, only the subscribe call itself → *v17*

**Proxies & secrets**
- Any proxy URL that is logged or persisted must go through `proxies.redact()`; spotdl's own error
  messages echo credentials → *v07*
- `JsonFormatter` adds an independent regex redaction pass as a safety net, not a replacement for
  the call-site fix → *v12*
- `sync_from_file()` deliberately does not hard-validate proxy format; the manual-add UI form does
  → *v07, v13*
- Deleting a proxy is source-conditional: `manual` rows hard-delete, `file` rows soft-disable →
  *v13*

**Frontend (SvelteKit)**
- `adapter-static` can't run a server load; routes use `ssr = false` + `prerender = true` **and**
  each needs its own explicit nginx `location` block (missing the second half shipped a `/login`
  404 for three versions) → *v09, v12*
- `goto()` must wrap its destination in `resolve()`; `redirect()`/`error()` must not be prefixed
  with `throw` → *v09*
- Use `SvelteSet`/`SvelteMap` from `svelte/reactivity`, not plain `Set`/`Map` → *v09*
- Live-updating sorted rows need `updatedAt` as a tiebreaker or completing rows appear to vanish
  → *v09*
- Mobile table collapse: one cell per line below 640px; pairing cells on shared grid tracks lets one
  row's long value truncate another's → *v09, v13*
- `transform-origin` alone doesn't stop sub-pixel bleed; the clipping container is the real
  guarantee → *v09*
- `--signal` (amber) marks things live *right now*, never permanent chrome → *v09*
- A REST fetch that resolves out of order can clobber fresher state; store fetches carry a sequence
  guard → *v09*
- A job with no tracks yet has nothing to render — hence `IncomingJobs` → *v09*
- `+layout.ts`'s `load` widening from `{email}` to the full session object needs the type kept
  nullable (`SessionInfo | null`) even though the redirect logic guarantees non-null by the time
  `+page.svelte` renders — TypeScript can't see across that boundary, so consumers read
  `data.session?.field` rather than asserting non-null → *v17*
- A new toggle/tab control that reuses the `role="group"` + `aria-pressed` Filter-tabs pattern
  (DESIGN.md §6) must **not** also reuse its `--signal` amber pressed-border by default — that
  color is reserved for genuinely-live state (§2); a persistently-pressed view-scope toggle is
  exactly the "permanent chrome" the rule exists to prevent. Use a neutral token
  (`--line-bright`/`--text-primary`) instead → *v17*

**Testing & verification technique**
- Ad-hoc verification scripts go in `/app/`, **never `/tmp/`** — `/tmp` puts the script's own dir
  first on `sys.path` and silently imports the stale baked-in `site-packages` copy of `app` → *v11*
- A local venv for running pytest outside Docker must be installed with `-e`, or edits are
  invisible → *v10*
- Direct-DB tests of beat behavior race the real `beat` container; pause the real worker in the DB
  while monkeypatching the guard off inside the script's own process → *v11*
- Any test track left in `WAITING` gets picked up for real by the running stack — always clean up to
  a terminal state in the same script run, in a `finally` → *v07*
- An ad-hoc script that creates a `Job` must also terminalize it, or it resurfaces as a phantom row
  once something finally renders that field → *v09*
- Mocked verification is not verification: v07's proxy work passed fully mocked, then a real
  credentialed run immediately exposed a credential leak → *v07*
- `~/.cache/ms-playwright/` may already hold a working Chromium; launch it via `executablePath`
  rather than assuming a fresh install is needed (the download is what's blocked here) → *v13*
- No query-counting utility existed before v15; a `before_cursor_execute` listener on
  `db_session.get_bind()` is the pattern now — that engine is the only one the `client` fixture's
  requests can possibly use → *v15*
- When the real upstream login server is unreachable from a sandboxed dev network, create a session
  row directly via `sessions.create_session()` and use its token as a manual cookie — identical
  session mechanics to a real login, only the external auth hop is bypassed → *v15*
- A test needing **two live identities on one `TestClient`** (e.g. proving user B 404s on user A's
  job) can't just call the real `/login` twice — the second call overwrites the first session's
  cookie in the client's shared jar. Minting the second identity's session directly and switching
  the client to it (`client.cookies.clear(); client.cookies.update(token)`) works; passing the
  cookie per-request (`client.get(url, cookies=...)`) also works but is deprecated on httpx's
  `TestClient` and prints a warning every call → *v17*
- No project skill exists yet for driving the frontend in a real browser — verification used an
  ad-hoc Playwright script against the cached Chromium at `~/.cache/ms-playwright/` (see v13's
  gotcha above) rather than a repo-committed driver. Candidate for `/run-skill-generator` → *v17*
- SQLite's `CURRENT_TIMESTAMP` (what `func.now()`/a model's `server_default=func.now()` compiles
  to) has one-second resolution — a fast test loop creating several rows can give them all an
  identical timestamp, so a test asserting sort order on that column needs explicit, strictly
  increasing values rather than relying on real insert timing → *v18*
- A UUID cursor/token value must round-trip as an actual `uuid.UUID` on decode, not a string that
  merely looks like one, or a bind parameter against a UUID-typed column fails; encode it
  self-describing (like a datetime) rather than as a bare string indistinguishable from real text
  → *v18*
- `job_to_dict` never actually exposed `archived_at`, even after v18 wired `include_archived`
  filtering — the gap only surfaced hitting the real running API with `curl`, not from unit tests
  (which never assert exact response-body equality against every field) → *v19*

**CI**
- An unquoted colon in a workflow step's `name:` fails the **whole file** at parse time — the run
  vanishes from PR checks rather than showing as failed → *v12*
- `docker compose config` needs a real `.env` on disk, separate from `${VAR}` interpolation → *v12*
- `npm run check` runs `svelte-kit sync` first, so `PUBLIC_*` vars must be set job-wide, not per
  step → *v12*
- Extend the existing workflow file; don't add a second one (`docs/CI_SELF_HOSTED_RUNNER.md` said
  so, and v12 ignored it and had to undo it) → *v12*

**Performance**
- Never load "everything the queue needs" with a per-job (or per-row) request loop; one bulk
  request, always → *v12*
- Removing the `Session` parameter from a serializer, not just adding a bulk query, is what makes
  the N+1 impossible to silently reintroduce → *v15*
- Filter jobs *before* aggregating their tracks, not after — a search/archived/source_type filter
  that excludes a huge job should never pay to aggregate it → *v18*

**Reference (not a gotcha)**
- Upstream `vb2007.hu-api` endpoint shapes, token scheme, and the two constraints they impose →
  *Verified external API contracts*, below
- spotdl 4.5.2's actually-used API surface: constructor, `DownloaderOptions` keys, the expansion
  primitive, the error taxonomy, the progress hook → *Verified external API contracts*, below

---
## Verified external API contracts

Reference material established during master v1 and confirmed against real source, kept here
so it never has to be re-derived. Re-verify before relying on it if the dependency was bumped.

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

---

## Version log


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
- **The live `https://api.vb2007.hu` was unhealthy as of 2026-07-28 — resolved 2026-08-11.**
  (Corrected in place per this file's own stale-gotcha rule, not deleted: this entry originally
  said to switch back once healthy, which happened, but local dev still runs the local instance
  by choice — see the standing rule below, not because the live one is still broken.) Local dev's
  `UPSTREAM_AUTH_BASE_URL` still points at a local instance of `vb2007.hu-api` running on the host
  machine's port 3000 — set in local `.env` (gitignored, never committed) as
  `UPSTREAM_AUTH_BASE_URL=http://host.docker.internal:3000`, **not** `http://localhost:3000` (the
  `api` container has its own network namespace; `localhost` there means the container itself —
  same class of gotcha as the `DATABASE_URL` note in v01). Test account is `balazs@vb2007.hu`
  (user `vb2007`) in `ALLOWED_EMAILS`; the password lives only in the local `.env` — **this repo is
  public on GitHub, never write that password into `CLAUDE.md`, a plan doc, or any other tracked
  file.**
- **Standing rule (added 2026-08-11, v17): a version's "Done when" verification must exercise the
  real upstream login for at least one identity before being called done, not only the direct-
  session-mint fallback below.** Check `http://host.docker.internal:3000` (from inside a container)
  or `http://localhost:3000` (from the host) first; if that local instance isn't running, fall back
  to the live `https://api.vb2007.hu` (point `UPSTREAM_AUTH_BASE_URL` at it, confirmed healthy again
  as of 2026-08-11) rather than skipping real-login verification entirely. Registering a fresh test
  account (`POST /auth/register {username, email, password}` on either instance) is fine and
  expected — v17 did exactly this for its second identity. One caught gotcha while doing so: the
  register endpoint 500s on a hyphenated `username` (an upstream bug, not spotdl-web's); a plain
  alphanumeric username works. The direct-session-mint fallback (two entries below) remains correct
  for *additional* identities beyond the first, or when neither upstream is reachable at all.
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
    **[Corrected by v15]** A week of real use took this past "fine at current scale."
    `job_to_dict` no longer takes a `Session` at all — `serializers.track_counts_by_job()` runs one
    bulk grouped aggregate over every job in the response, and the caller passes each job's counts
    in. Query count is now constant regardless of job count (asserted directly in
    `test_jobs.py` via a `before_cursor_execute` listener, not inferred from timing). Pagination is
    still v18's job — this fix only collapses the N+1, it doesn't bound the result set.

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

### v06 retry-engine gotchas (learned building error classification + ladder + breaker + beat dispatch)

- **`app/services/retry.py`'s `next_delay(attempt_count)` reads `attempt_count` as "failures
  *before* this one" (0 on the very first failure), not the post-increment count.**
  `record_failure` computes the delay before incrementing `track.attempt_count`, then increments
  and stores `scheduled_at`. Doing it in the other order (increment first, then look up the delay
  with the new count) silently skips the ladder's first rung — first failure would jump straight
  to the 1h step instead of 15m, contradicting the sequence this file's own "Retry engine numbers"
  section documents. Any future change to `record_failure`'s ordering needs to preserve
  compute-delay-then-increment, not the reverse.
- **The "other" error bucket shares the ladder with `audio_provider` but never touches
  `worker_state.consecutive_failures` or calls `maybe_trip_breaker()`.** Only a real
  `AudioProviderError` feeds the breaker — it exists specifically for YT-Music rate-limit
  detection, and letting unrelated exceptions (a bad proxy string, a transient KeyError) count
  toward it would trip a rate-limit-shaped pause for a problem that isn't rate-limiting.
- **`WorkerState.breaker_tripped_until` needs the same naive-vs-aware normalization as the v03
  `UserSession.last_seen_at` gotcha, but this time it also matters against real Postgres-shaped
  *application* logic, not just SQLite tests** — `retry.breaker_active()` explicitly
  `.replace(tzinfo=timezone.utc)`s a naive value before comparing against `datetime.now(timezone.utc)`,
  needed purely for the SQLite test path (`db_session` fixture); a no-op against real
  Postgres/psycopg. Any future code comparing `breaker_tripped_until` directly (rather than through
  `breaker_active()`) needs the same guard.
- **A fresh Python process that imports `app.tasks.download` (or anything else under `app.tasks`)
  directly, instead of importing `app.tasks.celery_app` first, hits a circular `ImportError`:**
  `download.py` imports `celery_app`, whose own module-bottom import order is
  `download` → `expand` → `beat`; if `download` is still mid-import when that chain re-enters it,
  `expand.py`'s `from app.tasks.download import download_track` fails because `download_track`
  isn't defined on the partially-initialized module yet. This is pre-existing since v04/v05 (`expand.py`
  already imported `download_track` this way) and wasn't introduced by v06's `beat.py`, but it
  surfaced while writing ad-hoc fault-injection scripts for this version's real-stack verification.
  Fix: any one-off script reaching into `app.tasks.*` must `import app.tasks.celery_app` (or run
  via the real `celery -A app.tasks.celery_app ...` entry point) before importing any task module
  directly — this is also simply the realistic way the app is ever actually entered.
- **`dispatch_due_tracks` needs no `task_routes` entry** — it has no download-shaped work of its
  own (only enqueues `download_track`, which *is* routed to `downloads`), so it's fine falling
  into the existing `task_default_queue="meta"`, consumed by `worker-meta` alongside
  expansion/reconciliation — matches the architecture doc's meta/downloads split.
- **No `FAULT_INJECT` env var or equivalent hook exists** — the plan's "Done when" checklist
  assumed one might be needed; in practice, verifying the ladder/breaker/restart-survival/
  terminal-lookup behaviors against the real stack was done by `docker compose cp`-ing small
  ad-hoc scripts into `worker-dl` that monkeypatch `app.services.downloads.download_one` /
  `app.services.dedup.is_already_downloaded` in-process and call `download_task.download_track(...)`
  and `beat_task.dispatch_due_tracks()` directly against the real Postgres instance (not through
  Celery's broker) — real DB, real schema, real enum/timestamptz behavior, deterministic fault
  triggering, no dependency on actual YouTube-Music rate limiting timing. Verified this way: full
  ladder progression 5s→10s→15s→20s→30s (with `LADDER_SECONDS` shortened) settling at the final
  step forever after breaker-clear; breaker trips at exactly 5 consecutive `AudioProviderError`s
  and `dispatch_due_tracks` dispatches nothing while tripped; a manual `record_success` call clears
  the trip and resets the counter, after which dispatch resumes; a `LookupError` track lands
  `lookup_failed` with `scheduled_at` staying `NULL` and is never touched by later
  `dispatch_due_tracks` runs; and — the specific "verified via SQL, not logs" bullet — a track
  scheduled 90s out had `docker compose restart worker-dl beat` run mid-wait, with `scheduled_at`
  confirmed byte-identical via a direct SQL/ORM query taken immediately before and immediately
  after the restart (proving Postgres's `scheduled_at`, not Celery/Redis, is what survived), before
  beat resumed dispatching it on schedule once due.

### v07 proxy-rotation gotchas (learned building `proxies.txt` sync + pick/cooldown + wiring)

- **spotdl 4.5.2's `Downloader.__init__` only accepts `http`/`https` proxies with a literal
  IPv4 host** — `re.match(r"^(http|https)://(?:(\w+)(?::(\w+))?@)?(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?$", proxy)`,
  checked in the real installed source, not assumed. Hostnames and `socks5://` — both
  explicitly named in this plan's original task list as accepted formats — raise
  `DownloaderError: Invalid proxy server: ...` at `Downloader()` construction time, caught
  during real-stack testing (a hostname-based test entry crashed on the very first proxied
  attempt). `proxies.txt.example`'s format guidance was corrected to `http(s)://[user:pass@]<IPv4>[:port]`
  only. `sync_from_file()` deliberately does **not** hard-validate this format at ingest —
  spotdl's own regex could loosen in a later version, and duplicating it here would just go
  stale — a malformed entry is instead caught (and cooled down) the same way any other
  real download failure is, the first time it's actually tried.
- **`Downloader.__init__` builds a real `rich` Live TUI display by default
  (`simple_tui=False` in spotdl's own `DEFAULT_CONFIG`), and `rich` allows only one Live
  display per process, ever** — harmless through v05/v06 since exactly one `Downloader`
  was ever constructed per worker-dl process's lifetime (single cache key, no proxy
  variation). v07 is the first version where a worker-dl process can construct a *second*,
  differently-keyed `Downloader` (direct first, then one per distinct proxy — see
  `get_downloader`'s cache key), which crashed every single time with
  `rich.errors.LiveError: Only one live display may be active at once` — this is a real,
  100%-reproducible break of proxy rotation in production, not a test-harness artifact,
  caught only by real-stack verification (unit tests fake out `get_downloader` entirely and
  never construct a real `Downloader`). Fixed by always passing `simple_tui: True` in
  `downloads.get_downloader`'s options — also simply the correct call for a headless
  Celery worker with no terminal to render to (progress goes through
  `progress_handler`/`notify_*` hooks per the v08 plan, never this TUI). **Any future code
  path that constructs a real spotdl `Downloader` must keep `simple_tui: True`** or the
  very next differently-keyed one built in that process will crash the same way.
- **The always-running local dev stack (`beat` + `worker-dl` on their normal schedule) will
  auto-retry any test `Track` row left in `WAITING` state** — a real risk when hand-crafting
  fault-injection scripts (same technique as v06) that create tracks and leave them
  mid-ladder: `dispatch_due_tracks` only filters on `state == WAITING`, so a script that
  fails to reach its cleanup line (e.g. an assertion error) leaves the track live for the
  *actual* background loop to keep retrying indefinitely, potentially against the real
  network with real spotdl calls if the test track's `song_json` happens to be a real,
  resolvable song (confirmed happening during this version's testing — a synthetic test
  track reusing a real song's metadata got for-real downloaded by the background loop
  between two manual verification steps). Any future ad-hoc verification script must set
  the test track to a terminal state (`CANCELLED` is used elsewhere in the state machine as
  is; not a new one) in the *same* script run, immediately after its assertions, not as a
  separate follow-up step — a script that can fail its assertions must still be written so
  cleanup happens (e.g. in a `finally`), or a failed assertion leaves the track live for
  beat to keep picking up.
- Verified against the real docker-compose stack and real Postgres instance (not mocked),
  via the same `docker compose cp` ad-hoc-script technique v06 established: `sync_from_file()`
  on `worker-meta` restart correctly added 2 new file entries, then (after editing
  `proxies.txt` and restarting again) soft-disabled the one removed from the file while
  leaving its `consecutive_failures` stat untouched, then re-enabled it on a later re-add
  with that same stat still intact (never reset). A track with `attempt_count=0` never
  calls `pick_proxy` (direct only); a track with `attempt_count>=1` picks a healthy proxy,
  downloads through it (mocked `download_one`, real everything else), and gets
  `used_proxy_id` + a real `download_track: track ... attempting via proxy <url>` log line
  from the actual running worker-dl process (not just the ad-hoc script) confirming the
  proxy used; a proxy failure sets `cooldown_until` and increments `consecutive_failures`,
  and an immediate next `pick_proxy()` call correctly skips it in favor of a still-healthy
  one; and with every proxy disabled, the track still completes via a direct attempt
  (`used_proxy_id` stays `NULL`) rather than stalling.
- **The verification above mocked `download_one` throughout — no real proxy had ever been
  used, which the user correctly flagged before accepting the version as done.** A
  follow-up pass with 5 real, live, credentialed proxies (`http://user:pass@ip:port`,
  spread across several countries) in `proxies.txt`, run against real Spotify tracks with
  nothing mocked, confirmed: real downloads succeed through a real proxy end-to-end
  (ffmpeg-tagged mp3 on disk, correct size); `pick_proxy`'s LRU rotates across distinct
  real proxies on successive tracks; a genuine real failure (spotdl returned no output —
  not every provider match works through every proxy/region) correctly set that proxy's
  cooldown and the very next retry picked a different real proxy and succeeded. This run
  caught a real credential leak that the mocked pass couldn't have: the
  `attempting via proxy <url>` log line and the `DownloaderError` message for a malformed
  proxy (which spotdl formats as `f"Invalid proxy server: {proxy}"`, echoing the full
  credentialed URL) both put the proxy's plaintext username:password into worker logs and,
  via `record_failure`, into `tracks.last_error` — a column a future UI (v09+) will
  display. Fixed with `proxies.redact(url)` (scheme + host + port only): used for the
  "attempting via proxy" log line, and `download_track`'s except-block substitutes the
  redacted form into both the logged traceback (`exc_info=(type, redacted_exc, tb)` —
  keeps the real traceback's file/line info, only swaps the final message) and the
  `last_error` string before it's persisted. **Any future code that logs or persists a
  proxy URL must go through `proxies.redact()`** — never log/store `proxy.url` or a raw
  exception message directly when a proxy was involved.

### v08 live-progress gotchas (learned building the Redis pub/sub event bus + SSE stream)

- **spotdl 4.5.2's `Downloader.__init__` hardcodes `self.progress_handler =
  ProgressHandler(self.settings["simple_tui"])` — there is no `DownloaderOptions` key for a
  progress callback at all.** Verified against the real installed source
  (`spotdl/download/progress_handler.py` + `downloader.py`): `ProgressHandler.__init__` does
  accept an `update_callback` parameter, and every `SongTracker.notify_*` method
  (searching/getting-meta/downloading/converting/complete) ends by calling
  `self.parent.update_callback(self, message)` if one is set — but the *only* way to reach
  it is setting `downloader.progress_handler.update_callback = fn` directly on the
  already-constructed instance, after `get_downloader()` returns it. `fn` receives the live
  `SongTracker` (`.progress` is 0-100) and a status string on every update, including the
  intermediate yt-dlp/ffmpeg phases — exactly the hook `events.make_progress_callback` uses.
- **`get_downloader()` caches one `Downloader` (and its `ProgressHandler`) per
  `(format, bitrate, proxy)` key across every track that reuses that combination** (see v05
  gotcha) — so `update_callback` is shared, mutable state on a long-lived object, not
  per-track. `download_track` rebinds it to a fresh closure (capturing the *current*
  track/job id) immediately before every `download_one` call. This is only safe because
  worker-dl runs `--concurrency=1 --prefetch-multiplier=1` (one track at a time, per the
  locked architecture decision) — **raising worker-dl's concurrency in any future version
  would make this a real race** (track A's progress events attributed to track B) and needs
  revisiting together, not independently.
- **`redis.asyncio`'s `PubSub.get_message(ignore_subscribe_messages=True, timeout=...)`
  returns `None` almost immediately after `subscribe()`, not after the full timeout** — the
  subscribe confirmation message arrives instantly, gets filtered by
  `ignore_subscribe_messages`, and the call returns `None` for that (filtered) message rather
  than continuing to wait out the remaining timeout. `app/routers/stream.py` treats any
  `None` as "time to emit a heartbeat," so every stream connection emits one spurious extra
  heartbeat right at connect time, before the real ~15s idle cadence kicks in. Confirmed via
  real-stack testing (heartbeat appeared ~2s after connecting, not 15s). Harmless — `:
  heartbeat` is a plain SSE comment line `EventSource` ignores — but worth knowing so a
  slightly-early first heartbeat isn't mistaken for a timing bug.
- **Starlette's `StreamingResponse` sends the ASGI `http.response.start` (status + headers)
  before the body generator produces its first chunk** — confirmed both by real curl testing
  (`GET /api/stream` immediately after an API restart returns `200` with correct headers
  even though no event has been published yet) and by the unit test design in
  `test_stream.py`. This is what lets a client (or a health-style check) confirm the
  connection is live without needing an actual event to arrive first.
- **A hung pytest run, once, from testing SSE the wrong way**: driving a real infinite
  async generator through `TestClient.stream(...)` and trying to bound the test by reading
  only the first N lines does not reliably terminate — the ASGI transport can keep the
  generator spinning (a fake `pubsub.get_message` with no genuine `await`-suspending I/O
  loops as fast as the interpreter allows) independent of what the test actually consumes,
  pegging a CPU core indefinitely until killed. Had to `kill -9` a stuck `pytest` process
  during this version. Fixed by monkeypatching `stream_router._event_stream` itself to a
  short, finite async generator and using a plain (fully-buffered) `client.get(...)` instead
  of `client.stream(...)` — the actual subscribe/forward/heartbeat loop against a real Redis
  instance is covered by real-stack verification, not a unit test. **Any future test of a
  genuinely infinite SSE/streaming generator must use this finite-fake-generator +
  plain-`.get()` pattern**, never drive the real generator through `TestClient.stream(...)`
  bounded only by "stop after reading N lines."
- **Every pre-v08 `test_download_task.py` fake for `get_downloader` returned a bare string
  (`"fake-downloader"`)** — broke the instant `download_track` needed
  `downloader.progress_handler.update_callback = ...`, since a string has no such attribute.
  Fixed with a minimal `_FakeDownloader`/`_FakeProgressHandler` pair exposing just that one
  settable attribute. **Any future code path that reaches further into the real
  `Downloader`'s surface needs the same fake-object treatment**, not a bare string return.
- Verified against the real docker-compose stack (not mocked), both directly and through a
  real Cloudflare Tunnel (`cloudflared` brought up manually for this check only — the
  compose service stays behind the `tunnel` profile and is not part of normal local dev; see
  v01's locked-decision table): a real track download produced a live, ordered
  `job.state`(expanding→expanded) then `track.state`(downloading with real intermediate
  `progress` values 0→25→40→70×many→95→100, then completed) sequence over `GET
  /api/stream`, both directly (`http://localhost:8000`) and through the tunnel
  (`https://sdwtest.vb2007.hu`, ingress `service` pointed at `http://api:8000` — the
  docker-compose service name, since `cloudflared` reaches `api` over the compose network,
  never `localhost`). A 320-second idle connection emitted exactly 21 heartbeats 15 seconds
  apart with zero drops, confirmed both directly and through the tunnel (raw output
  timestamps, not just "it didn't error"). Restarting the `api` container mid-stream cleanly
  terminated the old connection (no hang, no zombie subscription) and a fresh connection
  immediately after returned `200` with a working stream, with `GET /api/jobs` REST resync
  also confirmed working post-restart — the server-side half of the v09 reconnection
  contract this plan documents (full `EventSource` auto-reconnect behavior is a browser
  guarantee, not testable until the frontend exists).

### v09 frontend gotchas (learned building the SvelteKit login/dashboard UI)

- **`GET /api/jobs/{id}/tracks`'s `_track_to_dict` never projected `job_id`, `attempt_count`,
  `scheduled_at`, `last_error`, or `last_error_type`, and `publish_track_event` never included
  `attempt_count` in its SSE payload** — a real gap only visible once an actual frontend needed
  to render the plan's explicit "live countdown to `scheduled_at`" and "current `attempt_count`"
  requirements; nothing before v09 read these fields outside the backend itself. Fixed by adding
  all four to `_track_to_dict` and adding an optional `attempt_count` kwarg to
  `publish_track_event`, populated at every real call site in `download.py`/`beat.py`. **Any
  future REST/SSE consumer needing a `Track` field not already in `_track_to_dict` needs the same
  treatment** — the dict is a deliberate projection, not the ORM row, and stays that way.
- **No `CORSMiddleware` existed anywhere in `main.py` before this version** — harmless while
  nothing but tests and curl called the API, but the SPA and API are different origins (different
  port locally, different subdomain once v12 wires the real tunnel), so cookie-authenticated
  `fetch()` calls need explicit CORS with `allow_credentials=True` (which forbids a wildcard
  origin). Added `FRONTEND_ORIGINS` (`Settings`, a list — see next gotcha) and wired
  `CORSMiddleware` off it. **v12 must set `FRONTEND_ORIGINS` to the real production frontend
  origin(s) once the tunnel ingress topology (single hostname with path routing vs. separate
  subdomains) is decided** — nothing here assumes either shape yet.
- **`localhost` and `127.0.0.1` are different CORS origins to a browser even though they're the
  same machine** — first shipped as a single `FRONTEND_ORIGIN=http://localhost:5173`, which broke
  login (and every other API call) 100% of the time for real-user testing done at
  `http://127.0.0.1:5173` instead: the browser's CORS preflight (`OPTIONS /api/auth/login`) got a
  real `400 Disallowed CORS origin` from Starlette's `CORSMiddleware`, the browser blocked the
  actual `POST` before it ever reached the server, and the login page's `catch` block — written to
  show a deliberately generic "Invalid credentials." for the backend's real non-disclosure between
  wrong-password and not-allowlisted — caught this network-level failure too and showed the exact
  same misleading message, making a CORS misconfiguration look identical to a wrong password. Two
  fixes, not one: (1) `Settings.frontend_origins` is now `Annotated[list[str], NoDecode]` (same
  `ALLOWED_EMAILS`/`LADDER_SECONDS` comma-separated pattern), defaulting to **both**
  `http://localhost:5173` and `http://127.0.0.1:5173` for local dev; (2)
  `login/+page.svelte`'s error handling now only shows "Invalid credentials." for a real
  `ApiError` with `status === 401` (the backend's genuine non-disclosed auth rejection) and a
  distinct "Could not reach the server..." message for everything else (network down, CORS
  blocked, a 5xx). **Any future error-handling `catch` block that maps every exception to one
  user-facing string must keep this same split** — "the backend said no" and "the request never
  arrived" are not the same failure and must not read as the same message to the user.
  **The CORS fix alone was not sufficient** — a third, deeper bug in the same family surfaced
  immediately after: with the CORS origin allowed, login itself (`POST /api/auth/login`) started
  succeeding (`200 OK`, cookie set), but the very next request (`GET /api/auth/me`) still came
  back `401` every time, because `frontend/.env`'s `PUBLIC_API_BASE_URL=http://localhost:8000` is
  a *hardcoded* hostname independent of whichever loopback hostname the page itself was opened
  with. A page on `127.0.0.1:5173` calling an API hardcoded to `localhost:8000` is a **cross-site**
  request to a browser's `SameSite=Lax` cookie logic (`localhost` and `127.0.0.1` share no
  registrable domain, unlike two subdomains of a real production domain) — receiving a cookie from
  a cross-site response is allowed, but *sending* it back on a later cross-site fetch/XHR is not,
  which is exactly the confusing 200-then-401 pattern this produced. Fixed in `frontend/src/lib/
  api.ts` with `resolveApiBase()`: when both the configured API host and the page's own
  `window.location.hostname` are loopback addresses (`localhost`/`127.0.0.1`), the API base URL is
  rewritten at runtime to reuse whichever loopback hostname the page was actually loaded with
  (same port), keeping every request same-site regardless of which one the user opened. **This
  rewrite must never fire in production** — there the API and web app are genuinely different
  real hosts/subdomains on purpose, where cross-subdomain cookies work by a different rule
  (same registrable domain = same-site), so the loopback-only guard is load-bearing, not
  incidental. Any future change to how the frontend resolves its API base URL must preserve this
  loopback-aware behavior instead of reverting to a single fixed absolute URL.
- **A job between "submitted" and "its tracks exist" had nothing in the UI to represent it** —
  the plan's own "Done when" criteria and a real user's first manual test both surfaced this:
  `expand_job` genuinely takes several real seconds (a Spotify metadata round trip, not something
  to fake away), and during that window nothing rendered for the job at all (`QueueTable` only
  ever reads from `tracks`, and a job with no tracks yet is invisible), so a real click looked
  like it had done nothing — enough that a user's natural next move was to submit again, thinking
  the first click hadn't registered. Fixed with `queue.ts`'s `incomingJobs` derived store (jobs in
  `expanding` or `failed` state) and `IncomingJobs.svelte`, rendered above the waterfall. **Any
  future state a `Job` can reach that has no tracks of its own needs the same treatment** — this
  store is the one place job-level (not track-level) state gets surfaced at all.
- **A stale/overlapping REST fetch can resolve after a fresher one and clobber newer state** —
  `queue.ts`'s `refreshJobTracks`/`refreshJobs` are called from multiple places that can overlap
  (an `expanded` SSE event, an `EventSource` reconnect's `loadAll()`, the initial mount) with no
  guarantee the fetch that started first also resolves first. Real manual testing reported "the
  log doesn't update after a download completes, I need F5" and "submitting an already-downloaded
  track gives no UI response at all" — extensive automated reproduction attempts (raw job
  creation, real UI-driven submission, fresh downloads, genuine duplicates, in five separate
  scenarios) could not force either symptom to recur as a deterministic bug; every attempt showed
  correct live updates in 300ms–16s. Since the exact failure window couldn't be pinned down, the
  fix applied is defensive rather than a targeted repro-driven fix: both functions now capture a
  per-resource sequence number at call time and discard their own result if a newer call for the
  same resource has started since — this is the direct class of bug the symptom describes, whether
  or not this specific codebase was ever actually hitting it. **Any future store function that
  fetches-then-merges REST state must keep this sequence-guard pattern**, not assume requests
  resolve in the order they were sent. If either symptom recurs after this fix, the next step is
  capturing real DevTools console/network output during an actual reproduction, since automated
  headless testing could not manufacture the user's exact conditions (long-lived tab, possible
  backend hot-reload mid-session, or something else not yet identified).
- **Fixing the above indicator immediately surfaced 15 stale `Job` rows already sitting in the
  shared local dev database** — pre-dating this fix, left in `expanding`/`failed` state forever by
  earlier ad-hoc DB fault-injection scripts (the v06/v07-established technique) that manually
  created `Job`+`Track` rows to test the retry ladder/proxy logic without going through the real
  `expand_job` flow, and never bothered to also flip the parent `Job` to a terminal state since
  their focus was the `Track` row. These were invisible before this version (nothing rendered a
  job with no tracks) and suddenly appeared as a wall of fake "tuning in" rows the moment the new
  indicator shipped. Deleted after confirming every attached `Track` was already terminal
  (`cancelled`/`completed`) and none were live — pure historical test debris, not a code bug. **Any
  future ad-hoc DB fault-injection script that creates a `Job` row directly should also set it to
  a terminal state (or `cancelled`) before the script exits**, not just its `Track` rows — this
  gotcha is exactly why: an invisible loose end can resurface as a visible bug in a much later
  version once something finally renders off the field nobody was watching.
- **`transform: scaleY(...)` on an element flex-anchored to a container's bottom edge grows from
  the element's own center by default, not from that visual bottom edge** — the idle waterfall's
  noise-floor bars visibly dipped below the container's baseline as they grew (reported as "the
  soundbars move in both vertical directions instead of just their top part moving"). Fixed with
  `transform-origin: bottom` on `.noise-bar`. **Any future `scale`-based CSS animation on an
  element that's positioned by its layout box (flex/grid alignment, not `position: absolute`)
  needs an explicit `transform-origin` matching whichever edge the layout anchors** — the default
  center origin only looks correct for an element with no anchored edge at all.
  **`transform-origin` alone did not fully close this** — re-tested after the fix shipped, 1-3
  bars still dipped below the baseline by a few px, a different subset on every reload. Root
  cause: these bars are only a few px tall (random height, `min-height: 2px`), and sub-pixel
  antialiasing bleed on a `scaleY`-transformed element of that size can still render very
  slightly past the mathematically exact edge on some displays, independent of `transform-origin`
  being correct. Fixed by adding `overflow: hidden` to the `.noise-floor` container itself, which
  clips any such bleed at the true baseline regardless of the rendering-level cause. Confirmed via
  `getBoundingClientRect()` sampled across 6 frames of the animation cycle post-fix: zero bars
  exceeding the container's bottom edge. **Any future short/thin `transform`-animated element
  needs its clipping container treated as the actual guarantee, not `transform-origin` alone** —
  the math being correct doesn't guarantee the rasterizer respects it exactly at sub-pixel sizes.
- **Live SSE-updated rows can jump far enough down a long, mixed-state sorted list to look like
  they vanished, even though nothing was ever removed from the store** — reported as "the track
  appears while downloading, then completely disappears when the download finishes; F5 shows it
  as completed." `queue.ts`'s `trackList` sorted purely by `TRACK_STATE_ORDER`
  (`downloading`=0 … `completed`=6), with equal-priority ties falling back to plain
  `Object.values()` insertion order — and a track that only just joined the `tracks` record via
  its own live SSE events is *always* inserted after every track from the initial bulk
  `loadAll()` fetch, so completing sent it to the very end of the `completed` tier. Verified via
  real-stack testing (not assumed): a live completion measurably jumped from index 0 of 38 rows
  (fully visible, while `downloading`) to index 25 of 38 (below the fold) the instant its state
  flipped — nothing was actually missing from the DOM, it was just sorted somewhere the user
  wasn't scrolled to. A **fresh reload** showed it much closer to the top purely because
  `GET /api/jobs` orders newest-created-job-first and `Promise.all`-driven concurrent
  `refreshJobTracks` calls tend to resolve close to that same order — a completely different,
  coincidental position, not evidence the live version was "wrong" and the reloaded version
  "right." Fixed by adding an `updatedAt: number` (`Date.now()`) to every `LiveTrack`, set on
  every REST fetch and every applied SSE event, and sorting each state-priority tier by that
  descending as a secondary key — a track that just changed state now surfaces at the top of its
  new tier instead of wherever insertion order happened to leave it. Re-verified live: a
  completion stayed at index 0 through the entire transition. **Any future field added to the
  sort comparator must keep `updatedAt` as the tiebreaker** — dropping it silently reintroduces
  this exact "vanishing" perception for every state transition, not just completion.
- **`@sveltejs/adapter-static` cannot run a `+layout.server.ts` at request time** — there is no
  Node server in the static build, so the plan's literal `+layout.ts`/`+layout.server.ts` session
  guard had to be a universal `+layout.ts` with `export const ssr = false` (the session check —
  `GET /api/auth/me` — runs client-side, in the browser, against the live cookie) and `export
  const prerender = true` (fine here since the app has exactly two fixed routes, `/` and
  `/login`, each getting its own prerendered empty shell that hydrates into the real check — no
  nginx SPA-fallback config was needed for this reason). **Any future route added to this app
  needs the same two exports** unless the route count grows enough to need a real `fallback:
  'index.html'` + nginx `try_files` setup instead — revisit if v10+ adds routes beyond a small
  fixed set.
  **Correction (v12): this claim was wrong, caught by v12's real-stack pressure-testing, not
  by anything before it.** "No nginx SPA-fallback config was needed" was true only because
  nothing before v12 put nginx in front of the app at all in a way that mattered — `web`'s
  container has run `nginx:alpine` since v01, but every pre-v12 test of `/login` reached it
  via client-side routing (`goto()`/`redirect()` inside the already-loaded SPA), never a
  cold/hard navigation. Stock nginx has no route for the extensionless path `/login` to the
  prerendered file `login.html`, so any hard nav (a bookmark, a page refresh, a fresh
  Cloudflare-Tunnel hit) 404'd for real, in production, the entire time — v12's own
  same-origin nginx redesign is what finally surfaced it, not a coincidence of that redesign
  introducing a new bug. Fixed in `frontend/nginx.conf` with explicit
  `location = /login { try_files /login.html =404; }` (and `location = /` similarly) rather
  than a wildcard SPA fallback — see that file's own comment for why a wildcard was
  deliberately avoided. **Any future route added to this app needs both the two SvelteKit
  exports above AND its own explicit nginx `location` block**, not just one or the other.
- **SvelteKit 2.63's `goto()` calls are lint-enforced (`svelte/no-navigation-without-resolve`) to
  wrap their destination in `resolve()` from `$app/paths`** — a bare `goto('/login')` fails lint
  even though it works at runtime; every `goto()` in this codebase goes through
  `goto(resolve('/login'))`. Also as of this SvelteKit version, `redirect()`/`error()` from
  `@sveltejs/kit` throw internally when called and must NOT be prefixed with `throw` (the older
  `throw redirect(...)` pattern from SvelteKit 1.x is stale for this project's pinned version).
- **A `SvelteSet`/`SvelteMap` from `svelte/reactivity` is required instead of a plain mutable
  `Set`/`Map` behind `$state`** — `eslint-plugin-svelte`'s `svelte/prefer-svelte-reactivity` rule
  catches this; a plain `Set` reassigned wholesale on every mutation (`expanded = new
  Set(expanded)`) works but is exactly the pattern the rule exists to replace. `QueueTable.svelte`'s
  row-expansion state uses `const expanded = new SvelteSet<string>()`, mutated in place
  (`.add`/`.delete`), no reassignment needed.
- **Mobile responsive collapse of a multi-column data table has a two-layer failure mode, not
  one** — first attempt (squeezing all 5 columns proportionally onto one line) produced
  zero-width columns and fully invisible text at 390px, caught only by an actual Playwright
  screenshot (`svelte-check`/`eslint` saw nothing wrong, since this is a pure runtime CSS layout
  failure). Second attempt (state+job sharing one grid row, title on its own full-width row)
  fixed that but introduced a *different* bug one level down: pairing unrelated cells onto shared
  grid columns across multiple stacked rows (title+job on one row, artist+album on another, same
  two-column track definition) let one row's long `album` value size an `auto` column wide enough
  to silently truncate a *different* row's `title`/`artist` in that same column — real tracks with
  long album names (e.g. "Whenever You Need Somebody") starved short-artist rows ("Rick Astley")
  in ways a short-album row never triggered, making the bug look content-dependent rather than
  structural. **The fix that actually holds**: on the mobile breakpoint, every cell (`state`,
  `title`, `artist`, `album`, `job`) gets its own full-width flex line via `order`, never sharing
  a grid track with anything else. Confirmed only by re-screenshotting a real populated table with
  a mix of short and long titles/albums after each attempt — neither failure was visible from
  short test data or from `svelte-check`/`eslint`/`detect.mjs` alone. **Any future dense-table
  mobile collapse in this codebase should default straight to one-cell-per-line and only pair
  cells on a shared row after confirming with real, varied-length data that nothing can starve
  anything else.**
- **The one committed "live" accent color (`--signal`, phosphor amber) must never appear as
  permanent chrome** — round 1 of finish review shipped a constant amber top border on the
  waterfall panel (to mark it as the "hero" panel); the review correctly flagged this as spending
  the single live-signal color's exclusive meaning ("something is active right now") on pure
  decoration, present identically whether 0 or 5 tracks were downloading. Fixed by making the
  border neutral (`--line-bright`) by default and switching to `--signal-dim` only via a
  `.waterfall.live` class bound to `tracks.length > 0`. **Any future component that wants amber for
  emphasis must first ask whether the thing it's marking is genuinely live right now** — if not,
  a different token is correct, full stop; this rule and its rationale are recorded in
  `frontend/src/DESIGN.md` §2 specifically so it survives past this session.
- **The intended "matte charcoal chassis" panel material (a perceptibly recessed/lifted surface,
  not a flat card) was never made clearly perceptible against the near-black page background,
  across two full finish-review correction rounds** — first a 1px inset hairline (invisible at
  normal viewing distance), then a stronger compound shadow (`inset 0 2px 5px`, `inset 0 -1px 0`,
  `0 8px 20px -10px`), still not confirmed legible as "recessed housing" vs. "bordered card" by the
  reviewer's final verdict. Per the finish process's two-round ceiling, this was **deliberately
  left as an open, accepted gap** rather than pursued further — recorded in
  `frontend/src/DESIGN.md` §6/§8 for whoever picks up visual polish next (candidate for v10+).
  **Do not spend more `box-shadow` layers chasing this without first checking real-device
  legibility**, and do not describe the chassis material as "done" without new evidence.
- Verified against the real docker-compose stack (not mocked), via a headless Playwright driver
  (`chromium-cli` was unavailable in this environment; `npx playwright` + a local scratch
  `node_modules` install was the working substitute — see the `run` skill's fallback guidance) and
  the project's real local dev credentials/database: full login (including a deliberate
  wrong-password attempt showing the generic non-disclosing error) → real track submission → live
  `pending`→`downloading`→`completed`/`skipped_duplicate` states with no manual refresh → page
  reload mid-flight preserving state (proving the REST-resync + SSE-resume contract from v08 for
  real, not just structurally) → a track force-set to `waiting` via the same ad-hoc
  `docker compose exec` DB-script technique v06/v07 established (cleaned up to `cancelled`
  immediately after, per the v07 gotcha about never leaving a live test track for the real beat
  loop) showing a countdown that measurably ticked down across a real 3-second wait and survived
  a reload → logout clearing the session and redirecting → direct navigation to `/` while logged
  out redirecting to `/login` without ever rendering queue data. Keyboard-only navigation
  (PRODUCT.md's confirmed hard requirement) was separately verified end-to-end: login completed
  using only `Tab`/`type`/`Enter` with no mouse interaction, and the focus ring was confirmed
  visible via screenshot on both the login submit button and a dashboard filter button reached by
  tabbing alone. Real Cloudflare Tunnel verification was explicitly declined for this version
  (user's call, given the real `CLOUDFLARE_TUNNEL_TOKEN` already sitting in local `.env` makes
  that a public-exposure action, not just a local one) — v08 already proved the SSE/tunnel
  contract, and v12 (deploy hardening) owns real tunnel-based verification going forward.

### v10 queue-controls gotchas (learned building cancel/retry-now/pause/breaker-release)

- **A cancelled track's live SSE view could get stuck showing a stale `downloading` state
  forever, even though the DB and every REST endpoint were already correct** — caught only by
  the user watching the actual running UI during this version's real-stack verification, not by
  any REST-polling check (REST always showed the true `cancelled` state; only the live view was
  wrong). Root cause: spotdl's `ProgressHandler.update_callback` hook (wired in v08,
  `events.make_progress_callback`) publishes `state: "downloading"` events purely from its own
  internal tracker — it has no idea a cancel happened. Since `search_and_download` is
  synchronous and not interruptible (the whole reason cancel-mid-download works by discarding the
  result rather than stopping it), the real download kept running for several more seconds after
  `DELETE /api/tracks/{id}`/`DELETE /api/jobs/{id}` had already committed `cancelled`, and its
  progress callback kept firing `downloading` events (up to `progress: 100`) the entire time —
  all published *after* the `cancelled` event the cancel endpoint itself sent, silently
  overwriting it in every connected browser. Fixed by having `download_track` **re-publish the
  `cancelled` state a second time**, right after it detects the discard (both the success path
  and the failure-after-cancel path) — since nothing else publishes for that track once
  `download_one` has returned, this re-publish is provably the last message on the wire. Verified
  by raw-capturing `GET /api/stream` (`curl -s -N`) during a real cancel-mid-download of a real
  track end to end: the wire order was `downloading(progress:100) → cancelled`, `cancelled` last,
  confirmed byte-for-byte from the captured SSE stream, not inferred. **Any future code path that
  can leave a track in a different final state than its last-published live event needs the same
  "re-publish the true outcome as the last message" treatment** — this is a general race between
  a slow, uninterruptible background operation and any concurrent state change, not specific to
  cancellation.
- **The backend re-publish above was not sufficient on its own** — a second, real user re-test
  after that fix shipped (manual: submit → wait for download to start → click "cancel track")
  found the track visibly disappear from the waterfall instantly, then **reappear in the active
  waterfall for a moment**, before finally settling on `cancelled`. Backend-side, this is entirely
  correct and expected (exactly the stray-progress-event race documented above, now provably
  ending in the right state) — the remaining bug was purely in how the frontend applied events:
  `queue.ts`'s `applyTrackEvent` blindly overwrote a track's state with whatever event arrived
  most recently, with no notion that some states are truly terminal and nothing legitimately
  transitions a track back out of them. The optimistic local update from clicking "cancel"
  (`mergeTrack` off the `DELETE` response) set the store to `cancelled` immediately, but a stray
  `downloading` event from the still-running real download landed right after and flipped it back
  before the backend's eventual re-published `cancelled` caught up — a purely client-side replay of
  the same race, invisible to any backend-only test (curl/SSE-capture, unit tests) since the *wire*
  order was already correct; only the *frontend's interpretation* of receiving events out of causal
  order was wrong. Fixed with a `TRULY_TERMINAL_STATES` guard (`completed`/`skipped_duplicate`/
  `cancelled` — deliberately **not** `lookup_failed`/`failed`, since retry-now can legitimately
  revive those back to `waiting`): once a track's stored state is one of these three,
  `applyTrackEvent` ignores every further event for that track id outright rather than applying
  it, since nothing else in this app's model ever transitions a track back out of them. Confirmed
  fixed by the same user, live, after a page refresh (a plain non-component `.ts` module needs a
  full reload to pick up Vite HMR, not just a hot-swap) — no reappearance, straight to `cancelled`.
  **Any future store logic that applies incoming live events on top of existing state needs the
  same "is the current state one nothing ever legitimately exits" check** before blindly
  overwriting — this is a second, independent instance of the same class of bug as the backend
  fix above (a slow/uninterruptible operation's stale signal arriving after the true outcome is
  already known), just at a different layer, and neither fix would have caught the other's gap.
  No frontend unit-test framework exists in this project yet (v09 relied on backend `pytest` +
  manual/Playwright-driven verification only) — this fix was verified by the user manually
  re-testing the live UI, not by an automated frontend test; introducing Vitest/Jest purely to
  cover this one case was judged out of scope for this version.
- **`uv pip install ".[dev]"` (no `-e`/`--editable`) copies `app/` into `.venv/site-packages` as a
  frozen snapshot** — every further edit to `backend/app/*.py` is invisible to a local
  `.venv/bin/pytest` run until the package is reinstalled, silently testing stale code with zero
  error or warning. Caught only because a fix made *after* the initial `uv pip install` (the SSE
  re-publish fix above) kept failing its updated unit test with the *old* behavior even though the
  source clearly had the new code — the traceback's own file path
  (`.venv/lib/python3.12/site-packages/app/tasks/download.py`) was the tell. Fixed for this
  session with `uv pip install --python .venv/bin/python -e .`; the real docker-compose stack was
  never affected (its containers bind-mount `backend/app` directly, per `docker-compose.override.yml`,
  so they always run live source) — this trap is specific to a local venv used for fast
  `pytest`-only iteration outside Docker. **Any future local venv set up for running pytest
  directly (outside `docker compose exec`) must use `-e`/`--editable`**, or re-verify after every
  reinstall that source edits are actually reflected before trusting a "tests pass" result.
- **Adding a new `JobState` member to an existing native Postgres enum needs `ALTER TYPE ... ADD
  VALUE`, not the `values_callable` treatment alone** — `JobState.CANCELLED` required a hand-written
  migration (`ALTER TYPE job_state ADD VALUE IF NOT EXISTS 'cancelled'`); Alembic's autogenerate
  does not detect this at all (unlike a brand-new enum type, which v02 already covers). Downgrade
  has no `DROP VALUE` equivalent — the migration's `downgrade()` remaps any `cancelled` row to
  `failed`, renames the old type, recreates it without the new value, and swaps the column over via
  `USING state::text::job_state`, mirroring v02's enum-type gotchas but for a value instead of a
  whole type. Verified with a real `upgrade head` → `downgrade -1` → `upgrade head` round-trip
  against the real shared Postgres instance (not a scratch container this time, since this is an
  additive change to an existing type already holding real rows) — confirmed via `pg_enum` that the
  value is present after upgrade and gone after downgrade. **Any future new enum member on an
  already-shipped native enum type needs this same explicit `ADD VALUE` + type-swap-on-downgrade
  pattern**, not just a Python-side enum change.
- **A job cancelled while still `expanding` could have its cancellation silently undone** —
  `expand_job`'s own multi-second Spotify round trip means a `DELETE /api/jobs/{id}` can commit
  `cancelled` while `expand_job` is still mid-flight holding a stale in-memory `job.state ==
  expanding`; the original code's `job.state = JobState.EXPANDED; db.commit()` at the end of
  expansion would have blindly overwritten that cancel back to `expanded`, with the job's newly
  inserted tracks then dispatched for real via `expand_job`'s own `download_track.delay(...)` calls
  as if nothing had happened. Fixed with a conditional `UPDATE ... WHERE state = 'expanding'`
  instead of a plain attribute assignment (a no-op if the row already moved on), followed by
  `db.refresh(job)` to read the row's real current state rather than trusting the in-memory object —
  if it comes back `cancelled`, the newly-inserted tracks are set `cancelled` too and dispatch never
  happens. Verified with a real-stack-style test simulating the race (`expansion.expand`'s fake
  commits the cancel mid-call, matching the timing a real concurrent request would produce):
  confirmed zero `download_track.delay` calls and every inserted track landing `cancelled`, not
  `pending`. **Any future write to `job.state` after an `await`-shaped gap (a network call, a slow
  loop) needs the same conditional-UPDATE-then-refresh pattern**, not a bare assignment, if a
  concurrent cancel must never be undoable.
- The shared `app/services/serializers.py` (`job_to_dict`/`track_to_dict`/`track_counts`) replaces
  what used to be private, jobs-router-only helpers — needed once `tracks.py`'s new retry/cancel
  endpoints also had to serialize a `Track`. No behavior change, pure extraction.
  **[Updated by v15]** `job_to_dict`'s signature changed from `(db, job)` to `(job, counts)` — it no
  longer takes a `Session`. See the v15 section below.
- Verified against the real docker-compose stack, real Postgres, and the real network (not
  mocked), beyond the SSE re-publish fix above: pausing the worker held a real due `waiting` track
  undispatched across 5 consecutive beat ticks (~2 minutes), confirmed via `worker-dl` logs showing
  zero invocations for that track's id; resuming dispatched it on the very next tick with no
  duplicate dispatch (`attempt_count` advanced by exactly one); `POST /api/tracks/{id}/retry` on a
  track scheduled 12 hours out reset it to due immediately but `breaker_held: true` correctly held
  it back while the breaker was tripped, then it dispatched on the first tick after release;
  `POST /api/worker/breaker/release` cleared `breaker_tripped_until` immediately while leaving
  `consecutive_failures`/`breaker_trip_count` untouched, and a subsequent simulated
  `AudioProviderError` re-tripped the breaker straight to the *second* escalation delay (~2h), never
  resetting to the first (~30m); and cancelling a track genuinely mid-download (a real, uncached
  Spotify track picked specifically to avoid the dedup ledger) let the real download finish on disk
  (confirmed the mp3 was actually written, then deleted as test cleanup) while the track's own
  final state stayed `cancelled` with no `DownloadedTrack` ledger row ever created for it.

### v11 priority gotchas (learned building job-priority-ordered dispatch + bump/priority endpoints)

- **A one-off verification script copied to `/tmp` and run as `python /tmp/script.py`
  inside any backend container silently imports the *stale* `pip install .` copy of the
  `app` package from `site-packages`, not the fresh bind-mounted source at `/app/app`.**
  Every backend image has both: the Dockerfile's `pip install uv && uv pip install
  --system .` (v04 gotcha) bakes a real, non-editable snapshot into
  `/usr/local/lib/python3.12/site-packages/app/...` at build time, while
  `docker-compose.yml`/`.override.yml` separately bind-mounts `backend/app` to
  `/app/app` for hot reload. Both are real, importable copies of the same package name.
  `python -c "import ..."` puts `''` (cwd, `/app` per the image's `WORKDIR`) first on
  `sys.path`, correctly resolving to the fresh bind mount — but `python
  /tmp/script.py` puts the *script's own directory* (`/tmp`) first instead, `''` never
  appears, and the next match is the stale site-packages install. This produced a
  100%-reproducible, silently-wrong result while verifying this version's priority-ordered
  dispatch query: the exact same query, run via `-c`, returned the correct
  priority-ordered rows; the identical logic, reached by calling the real
  `dispatch_due_tracks()` through a copied `/tmp` script, silently ran the *pre-v11*
  compiled-in version with no join/order-by at all (creation-order results) — and a
  later cleanup line in the same script referencing `JobState.CANCELLED` (added in v10)
  threw `AttributeError`, because the site-packages snapshot predates v10 too. No
  exception, no warning, no visible sign anything was wrong until the row order and a
  seemingly unrelated `AttributeError` didn't match what the current source plainly
  says. **Any future ad-hoc verification script (the `docker compose cp` + direct
  in-process call technique established in v06/v07) must be copied to `/app/` inside
  the container, not `/tmp/`** — `python /app/script.py` puts `/app` itself first on
  `sys.path`, matching cwd, and resolves the same fresh bind-mounted source the real
  services run. Confirmed by re-running the identical script from `/app/`: correct
  priority-ordered result, no `AttributeError`, matching what direct SQL inspection
  already proved the query does.
- **Testing `dispatch_due_tracks()` by directly inserting `WAITING`, already-due `Track`
  rows into the real shared Postgres instance races the real `beat` container**, which
  fires the actual Celery task every 30s straight into the *persistent* worker-meta
  process (not the one-off verification script's own process) — a real, observed hazard
  here, not a theoretical one, since the very first attempt hit it. Isolated by setting
  `worker_state.paused = True` directly in the DB before inserting test rows (the
  persistent process's own `retry.breaker_active()` check honors this and no-ops on
  every tick during the test window) while monkeypatching `retry.breaker_active` to
  always return `False` *only inside the verification script's own process*, so its own
  direct call to `dispatch_due_tracks()` still runs unblocked. **Any future direct-DB
  test of beat-dispatched behavior against the real stack needs this same pause-the-real-
  process-but-not-my-script isolation**, not just the v07 "clean up to a terminal state
  before the script exits" precaution alone — that precaution only protects rows *after*
  the script's own dispatch call, not the query itself from racing a concurrent real tick.
- Verified against the real docker-compose stack and real Postgres instance (not
  mocked), via the corrected `/app/`-rooted script technique above: with a low-priority
  job's track due 10 minutes ago and a high-priority job's track due only 1 minute ago
  (both currently due), `dispatch_due_tracks()` dispatched the high-priority job's track
  first — confirmed via the real compiled SQL statement and the real row order returned
  by Postgres, not a mock. With a low-priority job's track due and a high-priority job's
  track not yet due (`scheduled_at` an hour out), only the low-priority track dispatched
  and the high-priority one was left completely untouched in `waiting` — confirming
  priority reorders only among currently-due tracks, never pulls a track forward out of
  its ladder wait, exactly as the plan's "Done when" specifies. `PATCH
  /api/jobs/{id}/priority` and `POST /api/jobs/{id}/bump` were confirmed wired and
  session-gated (`401` unauthenticated) against the real running `api` container after a
  clean hot-reload with no import errors. The plan's first "Done when" bullet says
  *bumping* a job causes its tracks to dispatch first — an initial pass had only tested
  the dispatch-ordering query with priorities set directly via the ORM, which exercises
  the ordering logic but not the actual bump codepath the plan describes. Closed that gap
  with a follow-up real-stack run calling `app.routers.jobs.bump_job()` itself (the real
  production function, not a reimplementation) against two same-priority, simultaneously-due
  tracks: the bumped (newer) job's priority came back `12` (one above the real pre-existing
  max in the shared DB, not a hardcoded value), and its track dispatched first on the next
  `dispatch_due_tracks()` call — the literal scenario the plan specifies, not just its
  underlying mechanism.

### v12 deploy-hardening gotchas (learned building durability fixes, same-origin nginx, non-root, JSON logging, backups)

- **The plan's own "Done when" wording for restart survival could pass while the actual
  bug shipped.** `docker compose down && up -d` leaving a `waiting` track's
  `scheduled_at`/`attempt_count` untouched was never at risk — it's a pure Postgres row,
  already proven safe at the unit level since v06. The property that genuinely needed
  fixing is a track **actively `downloading`** when the stack goes down: with Celery's
  default `task_acks_late=False`, the broker message is acked *before* `download_track`'s
  body runs, so a `docker compose down`/OOM-kill/host crash mid-download loses that
  message entirely and strands the track in `downloading` forever — nothing before v12
  ever reclaimed a track out of that state. Fixed with three independent layers, not one:
  `task_acks_late=True` + `task_reject_on_worker_lost=True` +
  `broker_transport_options={"visibility_timeout": 3600}` (`celery_app.py`) so a killed
  worker's message gets redelivered; `worker-dl`'s `stop_grace_period: 300s` so a real
  in-flight download gets a chance to finish cleanly before SIGKILL; and an independent
  DB-level reclaim sweep in `beat.py`'s `dispatch_due_tracks` (`_reclaim_stale_tracks`)
  that resets any `DOWNLOADING`/`QUEUED` track past `STALE_TRACK_AFTER_SECONDS` (env var,
  default 1800s — shortened for testing the same way `LADDER_SECONDS` already is) back to
  `WAITING`, as the safety net for cases the Celery-level redelivery doesn't cover (e.g. a
  message already acked by a pre-fix worker). Verified locally: a track force-set to
  `DOWNLOADING` with a stale `updated_at` gets reclaimed to `WAITING` and — since the
  reclaim's own `scheduled_at=now` is immediately due — re-dispatched to `QUEUED` in the
  *same* `dispatch_due_tracks` tick, not the next one.
- **Cutting `downloads` over from a named volume to a host bind mount (for `docker-compose.prod.yml`) can silently wipe the entire dedup ledger on first boot.** `reconcile_disk()`
  (`dedup.py`) deletes every `downloaded_tracks` row whose file doesn't exist on disk — if
  the new bind-mount directory is empty or not yet populated (a skipped migration step, a
  typo'd `DOWNLOADS_DIR`), every row looks "missing" and gets pruned, forcing every
  previously-downloaded track to re-download from scratch. Fixed with a guard: if the
  ledger has rows but the output directory is missing or genuinely empty, `reconcile_disk`
  logs an error and refuses to prune rather than assuming the worst. `docs/DEPLOYMENT.md`
  documents the actual one-time volume-copy step this guard is protecting against skipping.
- **A same-origin nginx reverse proxy (`frontend/nginx.conf`, new in v12) surfaced a real,
  previously-shipped production bug that had nothing to do with the proxy itself: `GET
  /login` 404s on any hard navigation.** `@sveltejs/adapter-static` prerenders `/login` to
  a file named `login.html`, and stock nginx has no route from the extensionless path
  `/login` to that filename. This bug existed since v09 — masked the entire time because
  every prior test of `/login` went through client-side routing (`goto()`/`redirect()`
  inside an already-loaded SPA), never a cold nav (a bookmark, a refresh, a fresh
  Cloudflare-Tunnel hit). See the correction note on v09's frontend gotchas above — that
  section's original claim that "no nginx SPA-fallback config was needed" was simply
  wrong. Fixed with explicit per-route `location` blocks (`location = /login { try_files
  /login.html =404; }`, same for `/`) rather than a wildcard SPA-shell fallback
  (`try_files $uri /index.html`) — a wildcard would silently return `200` + HTML for a
  genuinely missing asset chunk too, turning an honest 404 into a confusing "Unexpected
  token '<'" JS error. **Any future route added to this app needs its own explicit nginx
  `location` block matching adapter-static's emitted filename**, not just the SvelteKit
  `+layout.ts` exports v09 already requires.
- **The same nginx redesign would have silently killed SSE auto-reconnect if shipped
  without a corresponding frontend fix.** `EventSource` only auto-reconnects on a
  network-level failure (a raw TCP reset); a response with a non-2xx status or wrong
  content-type "fails the connection" *permanently* per spec. Before v12, an `api`
  container restart gave the browser a raw reset directly (auto-reconnect handled it
  fine) — after routing through nginx, the same restart makes nginx answer with a real
  `502 text/html` while `api` is down, which is exactly the terminal-failure case
  `EventSource` never retries on its own. This also silently existed as a *different* bug
  before v12 (a `401` after session expiry already killed the stream the same way) — never
  caught because nobody left a tab open through an expiring session during testing. Fixed
  in `+page.svelte` with a manual `onerror` handler + capped exponential-backoff
  reconnect, gated on `readyState === EventSource.CLOSED` (a `CONNECTING` readyState means
  the browser is already retrying on its own — reconnecting again on top of that would
  double the retry storm).
- **nginx resolving `api` in a literal `proxy_pass http://api:8000;` is resolved once at
  config-parse time and cached for the process's lifetime** — this both crashes nginx at
  boot if `api` isn't resolvable yet (a real startup race, since Compose starts services
  concurrently) and keeps proxying to `api`'s *old* IP forever after any `docker compose
  up -d --build` recreates it. Fixed with Docker's embedded DNS resolver
  (`resolver 127.0.0.11 ipv6=off valid=10s;`) plus a `set $api_upstream api; proxy_pass
  http://$api_upstream:8000$request_uri;` indirection — routing `proxy_pass` through a
  variable forces per-request re-resolution instead of a one-time lookup.
- **This image's `/etc/hosts` resolves `localhost` to `::1` (IPv6) before `127.0.0.1`, and
  neither nginx (`listen 80;`, no `listen [::]:80;`) nor Vite's dev server bind IPv6** — a
  healthcheck or verification command using `http://localhost/` gets a misleading
  connection-refused failure even though the service is genuinely up and reachable on
  IPv4. Caught for real: `web`'s healthcheck reported `unhealthy` with `wget: can't
  connect to remote host: Connection refused` despite `curl 127.0.0.1` working fine from
  inside the same container. Every healthcheck/verification command in this project now
  uses `127.0.0.1` explicitly, never `localhost`.
- **The dev (`docker-compose.override.yml`) and prod (`docker-compose.yml`) `web`
  containers run genuinely different processes on different ports — nginx on `:80` in
  prod, Vite's dev server on `:5173` in dev — so they need separate healthchecks, not one
  shared one.** A single healthcheck targeting `:80` reports the dev container permanently
  unhealthy (nothing listens there in dev). Fixed with the override providing its own
  `healthcheck:` block targeting `:5173` — a full sub-key replacement, not a merge,
  confirmed via `docker compose config` (mapping-valued healthcheck keys like `test:`
  replace wholesale between files, they don't concatenate the way top-level list keys
  like `volumes:`/`ports:` do).
- **`docker compose config`'s interpolation escaping rules are opposite for the redis
  healthcheck vs. the worker healthchecks, and getting it backwards produces a silent
  permanently-failing/permanently-passing check with no error.** `redis`'s healthcheck
  uses `${REDIS_PASSWORD}` **unescaped** — Compose-level interpolation from the root
  `.env` is the only mechanism that works, since `redis` has no `env_file: .env` (it isn't
  part of the `x-backend` anchor) and so has no container-side env var for a `$$`-escaped
  form to read. `worker-dl`/`worker-meta`'s healthchecks use `$$HOSTNAME` **escaped** —
  the opposite is needed there, since `$HOSTNAME` unescaped would have Compose
  interpolate the *host machine's* hostname (from the shell running `docker compose`, not
  the container) at config-parse time, silently pinging a Celery node name that will
  never exist.
- **A non-root container user for the backend needs a real home directory, not just
  `--no-create-home` for a "service account" — `import spotdl` breaks otherwise, for every
  process that imports it, with no warning.** `spotdl.utils.config` runs module-level code
  at import time that unconditionally `os.makedirs()`s a `~/.spotdl` cache/config
  directory — `api`, `worker-dl`, `worker-meta`, and `beat` (via `celery_app.py`
  importing every task module at startup) all import this transitively. Building the
  non-root user with `--no-create-home` (the initially "obviously correct" choice for a
  service account with no shell) crashed every one of these four services on their very
  first `import spotdl` with a bare `PermissionError: [Errno 13] Permission denied:
  '/home/spotdl'` — caught only by actually starting every service locally after
  switching to non-root, not assumed from the Dockerfile change looking correct.
  `useradd --create-home` (not `--no-create-home`) is required. **Any future spotdl
  4.5.2-importing process added to this project, containerized or not, needs a real,
  writable home directory** — this is a real constraint of the spotdl library itself, not
  specific to how this project happens to invoke it.
- **`docker-compose.prod.yml`'s downloads bind mount needs the same `!override` YAML tag
  the dev override already established (CLAUDE.md's v01 gotcha) for exactly the same
  reason** — `volumes:` is a list key that merges across `-f` files by default; without
  `!override` the prod file's host bind mount would sit alongside the base file's named
  `downloads` volume as a second, conflicting mount at the same `/downloads` target.
  `${DOWNLOADS_DIR:?...}` (required-variable interpolation, not a default) is deliberate
  too — a typo'd/unset path silently creating an empty directory is exactly the setup for
  the `reconcile_disk()` ledger-wipe hazard above.
- **Redis's `maxmemory-policy` must be `noeviction`, not `allkeys-lru`, when Redis is
  acting as a Celery broker rather than a cache** — `allkeys-lru` (redis's own default
  policy once any `maxmemory` is set) would silently *evict queued task messages* under
  memory pressure, which is real, silent task loss. `noeviction` instead makes Redis
  reject new writes loudly once full — a real, actionable signal instead of a silent one.
  `docker-compose.prod.yml`'s `--maxmemory 256mb` must stay comfortably under `redis`'s
  own `deploy.resources.limits.memory` (384M) — if the two aren't kept in that
  relationship, the OOM killer reaps the whole container before Redis's own limit ever
  engages, defeating the point of setting one.
- **A new `migrate` one-shot service (runs `alembic upgrade head`, then exits 0) now
  gates every other backend service's startup** via `depends_on: migrate: condition:
  service_completed_successfully`, added to the shared `x-backend` anchor — `api`,
  `worker-dl`, `worker-meta`, and `beat` all wait for it. `migrate` itself must override
  the anchor's `depends_on` back down to just `redis` (not the anchor's redis+migrate
  combination), or it depends on itself and deadlocks — YAML's `<<:` merge key replaces a
  child mapping's explicitly-redefined top-level key wholesale, it doesn't recursively
  merge nested content under that key, so this override needed to be explicit. Verified
  with a real `docker compose down && up -d`: `redis` starts → becomes healthy →
  `migrate` starts → exits 0 → *only then* do `beat`/`worker-dl`/`worker-meta`/`api` start,
  confirmed from real compose event ordering, not inferred from the YAML alone. This also
  removes the old manual "confirm Alembic wiring" verification step from earlier versions
  of `docs/DEPLOYMENT.md` — it happens automatically on every `up` now.
- **`backend/Dockerfile` copying `app/` before running `uv pip install` meant every
  source-only edit re-resolved and re-downloaded the full dependency tree (incl.
  spotdl/yt-dlp) on every build** — reordered so `pyproject.toml` + a new committed
  `requirements.txt` lock (`uv pip compile pyproject.toml -o requirements.txt`, re-run
  after any dependency change) install *before* `COPY app`, caching that layer across
  source edits. The lock file matters independently of the reordering too: this
  project's dependencies were previously all floating `>=` bounds with no
  dependency-freshness check in CI, so an unpinned rebuild months from now could
  silently install a different yt-dlp/spotdl than whatever was last actually verified
  working.
- **`frontend/Dockerfile`'s `COPY . .` with no `.dockerignore` anywhere in the repo shipped
  111MB of `node_modules` (including mismatched-libc native binaries — glibc bindings
  from the host copied over an Alpine/musl `npm ci` result) and the untracked
  `frontend/.env` into every build context.** Since `PUBLIC_API_BASE_URL` moved to a
  Dockerfile `ARG` (default `""`, same-origin — see below) that no longer depends on
  `frontend/.env` existing at all, a fresh clone can now `docker compose build web` with
  zero frontend-specific config; `frontend/.dockerignore` (`node_modules`, `build`,
  `.svelte-kit`, `.env`, `.env.*`, `.git`) makes that both correct and fast.
- **`PUBLIC_API_BASE_URL` moved from an untracked `frontend/.env` file to a
  Dockerfile `ARG PUBLIC_API_BASE_URL=""` (with a matching default in the Dockerfile),
  wired via `docker-compose.yml`'s `build.args` — both dev and prod now default to `""`
  (same-origin) rather than the pre-v12 split-origin setup.** `resolveApiBase()`
  (`api.ts`) simplified to a single empty-string check (`new URL('')` throws, so this
  must be checked before constructing a `URL`) — the old loopback-hostname SameSite-cookie
  rewrite hack from v09 is now dead code for the default path, superseded by same-origin
  being the actual fix rather than working around split-origin's cookie implications.
  Local dev gets the same same-origin treatment via a new Vite `server.proxy` rule for
  `/api` → `http://api:8000` (`vite.config.ts`) — the dev server runs *inside* the `web`
  container (`docker-compose.override.yml`), so `api` resolves as a compose service name,
  not a host-side address.
- **`celery inspect ping` is real, non-trivial work — a fresh interpreter importing
  `app.tasks.*`, which transitively drags in spotdl/yt-dlp — and must not be run every
  few seconds forever as a healthcheck.** `worker-dl`/`worker-meta`'s healthchecks use a
  120s interval and 90s `start_period` specifically to keep this cost rare. It does
  respond promptly even mid-download despite `--concurrency=1`, since control/pidbox
  messages are handled by the worker's MainProcess consumer loop, not the (possibly busy)
  prefork child. `beat` deliberately has **no** healthcheck at all — it's a single
  foreground process at PID 1, so a crash already produces a container exit
  `restart: unless-stopped` handles with no extra signal needed, and a `pgrep`-style
  check would only prove the process is scheduled, not that it's actually ticking, so it
  wouldn't add real information.
- **`health.py`'s per-request `Redis.from_url(...)` (never closed) mattered more once
  Docker's own healthcheck started polling it every 30s** — 2,880 fresh connection
  pools/sockets a day, previously harmless under only occasional manual/curl checks.
  Fixed with a context manager (`with Redis.from_url(...) as redis_client:`) — three
  lines, no behavior change otherwise.
- **Taking over Celery's logging via the `setup_logging` signal disables Celery's *entire*
  own logging setup the moment any receiver is connected — this is deliberate, not a side
  effect to work around, but it means `-l info` on every `celery` CLI command becomes
  documentation only, not the actual level source.** `logging_config.py`'s
  `@setup_logging.connect` handler is the one place now responsible for the root logger's
  handler/formatter in `worker-dl`/`worker-meta`/`beat`; `api` (uvicorn, not Celery) is
  wired separately via `--log-config logging.json` referencing the same
  `app.logging_config.JsonFormatter` class by dotted path. **Both wirings needed
  independently updating in `docker-compose.override.yml`'s dev command overrides too** —
  `command:` replaces rather than merges (same as `build:`, per the v01 gotcha), so the
  dev override's own `--reload` uvicorn command silently dropped `--log-config
  logging.json` (and would have silently lost any future flag the same way) until the
  override was updated to repeat the full flag set.
- **`python-json-logger` renamed its importable module from `pythonjsonlogger.jsonlogger`
  to `pythonjsonlogger.json` in a recent major version** (a deprecation warning fires on
  the old path, still functional but not for long) — `logging_config.py` imports from
  `pythonjsonlogger.json` directly to avoid building on a path already flagged for
  removal.
- **JSON logging is new exposure surface for the v07 proxy-redaction contract, not just a
  formatting change.** `proxies.redact()` is only reliably applied at the one call site in
  `download.py` that already knows a proxy was involved — nothing before v12 guaranteed a
  credentialed URL couldn't reach a log record through some *other* route (a raw exception
  message from a library that isn't ours, a stray `extra=` field). `logging_config.py`'s
  `JsonFormatter` adds an independent regex-based redaction pass
  (`://[^/@\s]+:[^/@\s]+@` → `://[redacted]@`) over both the message and any formatted
  exception, as a safety net on top of the existing call-site fix, not a replacement for
  it. Covered by `test_logging_config.py` — including a real fabricated
  `RuntimeError("Invalid proxy server: http://baduser:badpass@...")`, formatted through
  the real formatter, asserting the credentials don't survive into the emitted JSON.
- **Docker's own `json-file` log driver needs `max-size`/`max-file` set explicitly per
  service (or via a shared block) — there is no global default that bounds it**, and nothing
  in this project set one before v12. All 8 services (5 via the `x-backend` anchor,
  `redis`/`web`/`cloudflared` individually) now cap at `max-size: "10m"`, `max-file: "5"` —
  bounded regardless of how long the stack runs unattended.
- **Verified against the real, shared production/dev Postgres instance (not a fixture)
  during this version**: `scripts/pg_backup.sh`'s `pg_dump -Fc` + retention pruning ran
  for real (confirmed a synthetic 20-day-old dump file was correctly deleted by a 14-day
  retention run, while dumps under that window survived); a restore of the real dump into
  a scratch `postgres:18-alpine` container reconstructed all 7 tables with matching real
  row counts (73 `jobs` / 138 `tracks` / 9 `proxies` / 87 `downloaded_tracks` / 48
  `sessions` / 1 `worker_state` / 1 `alembic_version` row, at the time of the test) — the
  literal "Done when" bullet the original v12 plan specifies, run for real rather than
  assumed from the script reading correctly.
- The public production hostname is `spotdl.vb2007.hu`, routed through Cloudflare's
  dashboard-managed (token-based) tunnel — **not** a repo-tracked `cloudflared/config.yml`
  — with a single public-hostname rule pointing at `web:80`. This was a deliberate,
  explicit choice over a `cloudflared/config.yml` + path-split approach specifically
  *because* the same-origin nginx design collapses the routing decision to one hostname,
  one service, no path rules to get wrong in the dashboard.
- **`queue.ts`'s `loadAll()` fired one `GET /api/jobs/{id}/tracks` request *per job* via
  `Promise.all` — harmless with a handful of jobs (true since v09), but a real, felt bug
  the moment real usage (across every dev/testing session sharing one database) pushed
  the job count past ~100.** That many concurrent requests queues up behind the
  browser's/server's concurrent-stream limit, and any *other* request issued around the
  same time — a worker pause/resume click, specifically what surfaced this — gets stuck
  waiting behind the flood for 30–40+ seconds instead of resolving in its own normal
  ~250ms. Caught via a live user report against the deployed production stack, not
  local testing (local's job count happened to stay under the threshold). Fixed with a
  single new `GET /api/tracks` endpoint (`tracks.py`) returning every track across every
  job in one query — `loadAll()` now fires exactly 2 requests total regardless of job
  count. Verified with a real headless-browser regression test (Playwright, real login,
  real click) against the actual local stack with 141 real tracks: zero per-job
  requests, exactly 2 bulk requests, table still renders all 141 rows correctly, and the
  pause→"resume" label flip dropped from the previously-reported 30–40s to 68ms.
  **Any future "load everything the queue needs" addition must stay a single bulk
  request, never re-introduce a per-job (or otherwise per-row) loop** — this is the
  concrete failure mode that pattern produces once the data volume this app is
  explicitly designed to accumulate (it never deletes history) grows past a small
  number.
- **A brand-new `docker-compose.prod.yml`/CI addition was proven fully working in this
  session's own local verification, then still failed for three independent reasons the
  instant it hit the real self-hosted-runner CI — none of them a runner environment
  problem, all three real bugs in the workflow file itself:**
  1. `docker compose ... config` needs an actual `.env` file to exist on disk for the
     `env_file: .env` directive on the `x-backend` anchor to resolve, separately from
     the three `${VAR}`-interpolated values (`DOWNLOADS_DIR`/`REDIS_PASSWORD`/
     `CLOUDFLARE_TUNNEL_TOKEN`) already supplied via job-level `env:` — CI's checkout
     has no `.env` (gitignored), so `config` failed immediately with "env file ... not
     found" before ever reaching the interpolation it was actually meant to validate.
     Fixed with a `cp .env.example .env` step before validation; the file's *contents*
     are irrelevant here since nothing in this job starts a real container.
  2. `npm run check` runs `svelte-kit sync` *before* `svelte-check`, which generates
     `$env/static/public`'s module exports from whatever `PUBLIC_*` env vars are present
     **at that moment** — `PUBLIC_API_BASE_URL: ""` was only set on the later `Build`
     step, so `check`'s own `import { PUBLIC_API_BASE_URL }` failed first. Fixed by
     moving the env var to the *job* level so every step sees it, not just one.
  3. An unquoted colon inside a step's own `name:` field
     (`Create placeholder .env (file must exist for env_file: .env to resolve)`) parsed
     as an unintended nested YAML mapping key, failing the **entire workflow file** at
     parse time. A workflow that fails to parse creates zero jobs, so this didn't show
     up as a failed check in the PR UI at all — it just silently vanished from the
     checks list, which looked indistinguishable from a UI glitch until traced back via
     `gh run view <id>` ("This run likely failed because of a workflow file issue.") and
     confirmed with a real local PyYAML parse. **Any step `name:` containing a literal
     colon must be quoted** — this is the second time in this project a bare colon in
     YAML has caused a real, non-obvious failure (see the `env_file:`/`$$HOSTNAME`
     interpolation-escaping gotchas above), and now the specific new failure mode is:
     silent disappearance from PR checks, not a visible error.
  All three were reproduced and confirmed fixed **locally** before pushing again
  (a scratch `git clone` with no `.env`, and a `web` container stopped so a bind-mounted
  `.svelte-kit/` write-back didn't get root-owned mid-test) — not just inferred from the
  CI log and pushed on faith.
- **`docs/CI_SELF_HOSTED_RUNNER.md` already explicitly warned against exactly the
  mistake made when this version added its CI checks**: "extend the `pytest` job with a
  second matrix entry (or a sibling job) once [the frontend has tests], rather than
  standing up a separate workflow preemptively." `deploy-checks.yml` was created as a
  second, separate workflow file anyway (for the new `compose-config`/`frontend` jobs),
  splitting one PR's checks across two differently-named workflow groups in the GitHub
  UI for no real reason — both files shared identical triggers and both existed purely
  to gate the same PRs. Fixed by merging everything into a single `.github/workflows/
  ci.yml` (`pytest` + `publish-report` + `compose-config` + `frontend` as four sibling
  jobs, one shared `concurrency` group) and deleting the two predecessor files. **Read
  this doc's own accumulated advice before adding a new workflow file**, not just before
  editing an existing one — this is exactly the kind of already-recorded lesson this
  file's "durable memory" premise exists to make available on the next read, not
  something to re-discover the same way twice.

### v13 settings-UI gotchas (learned building proxy management + output-config override UI)

- **Per-job output override was explicitly scoped out**, per the plan's own instruction
  to confirm before building it: the v00 master plan's locked decision is "global env
  config first; UI override deferred to v13" — per-job override was only ever a "possible
  future step," never a locked decision. v13 ships global-only, matching the locked
  decision as written; nothing about this needs revisiting unless the user asks for
  per-job overrides in a future, unplanned version.
- **A settings change must invalidate `get_downloader`'s cache without a separate version
  counter** — `output_dir`/`output_template` moved from a module-level constant sourced
  from env `Settings` (v05) into a new singleton `app_settings` table (get-or-create,
  same shape as `worker_state`/`retry.get_worker_state`), and `get_downloader`'s cache key
  simply grew to `(format, bitrate, output_dir, output_template, proxy)` — every field the
  UI can now edit is *in* the key, so a settings change can never hit a stale cached
  `Downloader` by construction, no version counter needed. Verified for real (not just
  unit tests): in a single `worker-dl` process, building a `Downloader` for the
  pre-change settings, then calling the real `PATCH /api/settings/output`-equivalent
  (`app_settings.update_output_settings` + commit) and building again with the freshly
  re-read settings produced a second, distinct cached instance in the same process —
  proving "affects the next download without a container restart" concretely rather than
  by code-reading alone.
- **`download_track` no longer touches env `Settings` for format/bitrate/output at all** —
  it fetches `app_settings.get_output_settings(db)` once per task execution (the same
  place `settings = get_settings()` used to sit) and reads everything from that row
  instead. `default_format`/`default_bitrate`/`download_output_dir` env vars are now only
  the *seed* for `app_settings`'s row on its very first read against a fresh DB — after
  that first read, editing the env vars does nothing; the DB row is authoritative. Any
  future code that needs the download format/bitrate/output must go through
  `app_settings.get_output_settings(db)`, never `get_settings().default_format` directly,
  or it'll silently read the stale, pre-v13 source.
- **Proxy URLs are redacted in the settings UI too, not just in logs/`last_error`** —
  `GET/POST/PATCH/DELETE /api/proxies` all return `proxies.redact(proxy.url)` (scheme://
  host:port only), never the plaintext `user:pass`. This extends the v07 redaction
  discipline (logs, `last_error`) to a third surface (the authenticated owner's own
  screen) on the theory that a screenshot or shoulder-surf shouldn't leak a credential
  either, even though the user already knows their own proxy passwords. Consistent with
  the project's existing paranoia about this one specific leak vector; **any future
  code that displays a `Proxy.url` anywhere must go through `redact()`**, matching every
  other place a proxy URL is ever shown.
- **`pick_proxy()` needed no changes at all for "both pools drawn from equally"** — it
  already filtered purely on `Proxy.enabled`/`cooldown_until`, with no `source` filter
  anywhere in the query (confirmed by reading `app/services/proxies.py` before writing
  any v13 code, not assumed from the plan's wording alone). `POST /api/proxies` simply
  inserts a `source=manual` row using the same table `sync_from_file()` (v07) already
  populates with `source=file` rows; verified for real via the established
  `docker compose cp` + `/app/`-rooted ad-hoc-script technique (v06/v07/v11): a
  UI-added manual proxy with no `last_used_at` was picked first by a real `pick_proxy()`
  call in the running `worker-meta` process (LRU prefers never-used), and disabling it
  through `PATCH /api/proxies/{id}` made the very next `pick_proxy()` call skip it and
  fall through to a real file-sourced proxy instead.
- **`DELETE /api/proxies/{id}` is a soft delete (`enabled=false`) for every proxy
  regardless of `source`, deliberately not restricted to `source=manual` rows** — matches
  v07's never-hard-delete stance (preserves `consecutive_failures`/`last_success_at`
  history). Disabling a `source=file` row through the UI is not surprising or
  inconsistent: the next `sync_from_file()` run (worker-meta boot) simply re-enables it
  as long as it's still listed in `proxies.txt`, identical to the existing
  remove-then-re-add-the-line behavior v07 already documented — the UI control and the
  file are just two paths to the same `enabled` flag on the same row.
- Settings UI verified end-to-end against the real docker-compose stack, real Postgres,
  and a real logged-in session (not mocked): `alembic upgrade head` → `downgrade -1` →
  `upgrade head` round-tripped `app_settings` cleanly against the real shared Postgres
  instance; all four backend processes (`api`, `worker-dl`, `worker-meta`, `beat`)
  restarted cleanly with zero import errors after the new model/service/routers landed;
  `GET/PATCH /api/settings/output` persisted a real change across requests; the frontend
  `/settings` route builds and prerenders to `settings.html` (`svelte-check`/`eslint`/
  `vite build` all clean) with its own explicit nginx `location` block added alongside
  `/` and `/login`, per the v09/v12 gotcha that every route needs one. The plan's third
  "Done when" bullet ("`proxies.txt` and the UI-added proxies coexist without either
  overwriting the other's rows") was closed with its own dedicated real-stack check, not
  inferred from `sync_from_file`'s source-scoped query alone: added a `source=manual` row
  via `POST /api/proxies`, restarted the real `worker-meta` container (which runs
  `sync_from_file()` on boot), and confirmed via `GET /api/proxies` afterward that the
  manual row survived untouched (`source` still `manual`, stats unchanged) while the log
  line read `sync_from_file: 5 in file, 0 added, 0 re-enabled, 0 disabled` — proving the
  file-sync pass never even looked at it, not just that it happened not to change it.
- **A real manual click-through (by the user, not a headless pass) of the first
  `/settings` build found four real gaps that no automated check in this session had
  caught** — the automated Playwright browser pass never ran at all (see below), and
  `svelte-check`/`eslint`/`vite build`/pytest passing is exactly the kind of "correctness
  verified, feature not" gap CLAUDE.md's own top-level rules warn about. Fixed in a
  follow-up round, same version/branch:
  1. **Format/bitrate were plain free-text inputs with zero validation** — a typo'd
     format silently reached `get_downloader` and would only fail once a track actually
     tried to download with it. Fixed with a live-introspected set of valid choices
     rather than a hand-maintained guess: `downloads.get_supported_output_options()`
     calls `spotdl.utils.arguments.create_parser()` (builds argparse groups only, no
     argv parsing or I/O — safe/cheap to call purely for introspection) and reads the
     real `--format`/`--bitrate` `choices` off the parser's `_option_string_actions` map
     — there's no public argparse API for "give me this flag's choices" short of
     parsing `--help` text, and a `KeyError` here (spotdl renaming/removing a flag) is
     preferable to silently falling back to a stale hardcoded list. New
     `GET /api/settings/output/options` backs the settings UI; `PATCH
     /api/settings/output` now 400s server-side too if a submitted format/bitrate isn't
     in that live set (defense in depth beyond the UI, verified for real: `{"default_
     format": "wma"}` → `400 Unsupported format: 'wma'` against the real running `api`).
     Format renders as the same `role="group"`/`aria-pressed` toggle-button convention
     `QueueTable.svelte`'s filter tabs already established (DESIGN.md §6) — reused
     rather than inventing a second pattern for the same "one active choice" interaction.
     Bitrate uses a native `<select>` instead: ~28 values in a button row would be an
     unreadable wall of buttons, a real cardinality difference from format's 6, not a
     consistency compromise.
  2. **The output-directory field was editable but meaningless** — the directory a
     running container can actually write to is fixed by its volume mount at deploy
     time (`DOWNLOAD_OUTPUT_DIR`), not by an app-level setting, so letting the UI edit
     it just recorded a value nothing downstream would ever honor. Walked back
     entirely rather than left half-working: `output_dir` dropped from `app_settings`
     (migration `e92ed5ccf419`, round-tripped clean against the real shared Postgres
     instance), removed from `UpdateOutputSettingsRequest` (pydantic silently ignores
     the extra key if sent — verified `{"output_dir": "/hacked"}` has zero effect via a
     real PATCH), and `download_track` now reads it straight from
     `get_settings().download_output_dir` (env) like every version before v13 did. The
     settings UI still shows it as a plain read-only field (informational — GET still
     returns it, sourced live from env) with a hint explaining why it's not editable
     there, rather than removing it from view entirely.
  3. **A manually-added proxy could never actually be removed** — `DELETE
     /api/proxies/{id}` originally soft-disabled every proxy regardless of source
     (matching the plan's literal wording), which for a `source=manual` row is a dead
     end: nothing (no `proxies.txt` line) will ever re-enable it, so the row just sits
     forever as a permanently-disabled entry with its own "remove" button now disabled
     too (since it was gated on `!proxy.enabled` under the mistaken assumption that
     "disable" and "remove" were sequential steps of the same action). Fixed with a
     source-conditional split: `source=manual` is now genuinely hard-deleted (`204`, row
     gone from the table); `source=file` keeps the original soft-disable (`200`,
     `enabled=false`) since the file is still that row's real source of truth and
     `sync_from_file()`'s next run re-enables it exactly like removing then re-adding
     the proxies.txt line, preserving its health stats. **Any future change to proxy
     deletion needs to preserve this asymmetry** — it's not an inconsistency, the two
     sources have genuinely different "what does delete even mean" answers. Verified for
     real: a fresh manual proxy → `DELETE` → `204` → gone from `GET /api/proxies`; a
     real, currently-healthy file-sourced proxy from earlier v07 testing → `DELETE` →
     `200` + `enabled: false`, stats intact → re-enabled via `PATCH` afterward to restore
     the shared dev DB's state. The settings UI's "remove" button is now only rendered
     for `source=manual` rows at all (no confusing always-disabled button for file rows
     — the enable/disable toggle already fully covers what "delete" would mean there).
  4. **Manual proxy entries accepted literally any string** — `sync_from_file()`
     deliberately never hard-validates (see its own docstring: a malformed `proxies.txt`
     line is instead caught, and cooled down, the first time it's actually tried, since
     duplicating spotdl's regex there risks drifting from an unattended background
     process's actual behavior). The manual-add UI form is a different context — a
     human typing into a live form benefits from immediate feedback instead of a
     silent future failure — so `POST /api/proxies` now validates against
     `proxies.PROXY_URL_RE`, spotdl's real accepted-proxy pattern (re-verified against
     the currently-installed source, `spotdl.download.downloader.Downloader.__init__`,
     not assumed from the v07 note alone — unchanged since then). The frontend mirrors
     the same regex for instant feedback before the request even fires; the backend
     check is the one that actually matters if the two ever drift. Verified for real: a
     hostname (`http://proxy.example.com:8080`) and a `socks5://` URL — both real formats
     spotdl's own Downloader rejects — both 400 against the real running `api`, no row
     created.
  All four fixes re-verified against the real docker-compose stack and real Postgres
  instance (not mocked): `alembic upgrade head`/`downgrade -1`/`upgrade head`
  round-tripped the `output_dir` column drop cleanly; all four backend processes
  restarted with zero import errors; every endpoint above was exercised with real curl
  calls against the real running `api` container, not just pytest. `svelte-check`/
  `eslint`/`vite build` all still clean after the frontend rewrite.
- **The Playwright browser click-through gap was finally closed, but not by getting the
  Chromium *download* to work — the download itself still stalls the same way every
  time.** The actual fix: `~/.cache/ms-playwright/chromium-1234/` turned out to already
  contain a fully-downloaded, working Chromium binary from some earlier, unrelated
  session/setup — `playwright-core`'s `chromium.launch({ executablePath:
  '.../chromium-1234/chrome-linux64/chrome' })` launches it directly, completely
  bypassing the revision-matching lookup (and thus the download) that a bare
  `chromium.launch()` would trigger. **Any future session that needs a real headless
  browser in this sandboxed environment should check `~/.cache/ms-playwright/` for an
  already-present revision and launch it via `executablePath` first**, rather than
  assuming a fresh `npx playwright install` is required — the download is what's
  actually blocked here, not browser automation itself.
- **A real browser click-through (finally possible via the trick above) immediately
  found two real mobile-responsive defects that no prior check caught** — confirmed via
  actual screenshots at 390px width, not assumed: (1) `.output-form`'s `grid-template-
  columns: repeat(2, 1fr)` had no mobile breakpoint at all, squeezing the format
  toggle-button group and the bitrate select into two cramped columns instead of
  QueueTable.svelte's own established "one field per line below 640px" convention
  (DESIGN.md §6) — fixed with a matching `@media (max-width: 640px)` collapsing it to
  `1fr`. (2) Both the add-proxy input's placeholder and the filename-template input's
  real value clipped mid-string at 390px with no ellipsis or visual cue anything was
  cut off — fixed by shortening the placeholder to "Proxy URL" and moving the full
  format spec into the panel's own wrapping hint paragraph (placeholders don't wrap,
  visible text does), plus a mobile-only `font-size` reduction on text inputs so the
  34-character default filename template fits without clipping. **Any future narrow
  input holding real (not placeholder) content this project ships should get the same
  "does the real default value actually fit at 390px" check** — `svelte-check`/`eslint`/
  a clean build proved nothing about this; only an actual rendered screenshot did.
- **The output-directory field was removed from the settings page entirely** (not just
  made read-only, per a later, more decisive user call) — showing it at all, even
  read-only, was confusing UI real estate for a value nothing about the page can ever
  change. `app.services.app_settings`/the `AppSettings` model were already output-dir-
  free from the validation-fixes round above; this was a frontend-only removal (the
  `<div class="field wide">` block and its now-dead `input[readonly]` CSS). The
  `OutputSettings.output_dir` TypeScript field stays (the API still returns it for any
  other consumer), just unrendered — not the same as removing it from the API contract.
- **Manually clicking "remove" on the two stray disabled manual-proxy rows left over
  from the validation-fixes round's own real-stack testing (`198.51.100.42:8080`,
  `198.51.100.55:9090`) is what surfaced that they were still sitting there at all** —
  they'd been soft-disabled under the *pre-fix* delete semantics, before `DELETE
  /api/proxies/{id}` started hard-deleting manual rows, and nothing had gone back to
  actually remove them since. Cleaned up via real UI clicks (confirmed gone from
  `GET /api/proxies` afterward), not a curl call — **closing this out through the same
  browser path a real user would use is what caught it**; a curl-only pass would have
  "worked" without ever noticing the leftover rows looked wrong on the real page.

### v15 gap-fixes gotchas (learned closing v14's audit findings — pacing hook, N+1, stale docs)

- **The pacing hook drifted for four versions (v07→v14) because nothing ever asserted it had an
  effect.** `PACING_MIN_SEC`/`PACING_MAX_SEC` were declared in `config.py` since v07, documented in
  `00-master-plan.md` as "wired but off by default," and never once read by `download_track`. This
  is exactly why the gap survived four full "Done when" review passes: `git grep` for the settings'
  *names* would have found them fine, sitting right there in `config.py` — what nobody checked was
  whether anything downstream actually *consumed* them. **The reusable lesson: a config field
  passing review because it exists and has a sane default is not the same claim as a config field
  having an effect** — the second claim needs its own test asserting the observable behavior
  changes when the value changes, not just that the field parses. The regression test added here
  (`test_pacing_delay_is_zero_when_unconfigured`) is deliberately about the *default* case, not the
  configured one — the gap was "off never means off," not "the math is wrong."
- **Fix, real-stack verified**: `download.py`'s `pacing_delay()` samples `[PACING_MIN_SEC,
  PACING_MAX_SEC]` and is called in `download_track` right after the dedup early-return and before
  `get_output_settings` — after every gate that means "this track was never going to touch the
  network," so a `skipped_duplicate` or breaker-deferred track never pays the delay. `db.commit()`
  runs immediately before the `time.sleep()` so a pooled Postgres connection isn't held
  `idle in transaction` for the whole window, and `db.refresh(track)` after the sleep re-checks
  `CANCELLED` so a cancel landing mid-wait doesn't still trigger a real download. A `.env` value of
  `PACING_MIN_SEC=8`/`PACING_MAX_SEC=12` against a real 5-track album showed explicit
  `download_track: pacing N.Ns before track ...` log lines in `worker-dl` for every track
  (samples: 10.1s, 9.8s, 11.9s, 10.0s, 11.7s, all inside the window), with total per-task runtime
  (~21-24s) matching pacing-delay + real-download time. Restoring both values to `0` and
  re-submitting the same album showed **zero** pacing log lines and every task completing in
  single-digit milliseconds. `Settings` gained a `model_validator(mode="after")` rejecting
  `min_sec > max_sec` and negative values — `random.uniform` silently samples a reversed range,
  which would otherwise make `MIN=5, MAX=0` read as "pace by up to 5s" while meaning "off."
- **Raising pacing means also raising `STALE_TRACK_AFTER_SECONDS`, and this is not obvious from
  either setting's own docstring.** `dispatch_due_tracks` marks an entire due batch `QUEUED` in one
  commit, but `worker-dl` drains it serially (`--concurrency=1`), so the k-th track's `updated_at`
  is frozen for `k × (pacing + download time)`. Push per-track time up via pacing without also
  raising the stale threshold and `_reclaim_stale_tracks` starts falsely reclaiming a batch's tail —
  worse, a reclaimed-then-redelivered message for a track that's actually still running (or has
  already `COMPLETED`) can regress it to `SKIPPED_DUPLICATE` via the dedup branch, since
  `download_track` only gates on `CANCELLED` (see the new finding below). Local dev's
  `STALE_TRACK_AFTER_SECONDS=20` was raised to `120` for the pacing verification run above and
  restored afterward — this is the concrete failure mode that comment now documents inline in both
  `.env` templates.
- **New finding, documented not fixed**: `download_track` (`download.py`) returns early only for
  `TrackState.CANCELLED`. A redelivered Celery message for an already-`COMPLETED` track (via
  `task_acks_late` on a worker crash, or via `_reclaim_stale_tracks` sweeping a track that's
  actually still running) passes that gate, falls into the dedup branch, and overwrites the row to
  `SKIPPED_DUPLICATE` — a state-accuracy bug (both states are terminal/successful in v2's rollup),
  not data loss. Real, but not a v14 remediation item and not small enough to fold into a fixes PR
  per the admission rules — appended to the v2 roadmap as its own item.
- **The `list_jobs` N+1 fix works by removing the `Session` parameter from `job_to_dict`, not just
  by adding a bulk query alongside it.** A `job_to_dict(db, job)` signature with an internal
  `track_counts(db, job.id)` call is exactly the shape that let the N+1 exist unnoticed for four
  versions — anyone who forgot to route through a bulk pre-fetch just got a working-but-slow
  request, no error, no test failure. `job_to_dict(job, counts)` has nothing left to query *with*,
  so a caller that forgets is a `TypeError` on the very first request, not a silent regression.
  `serializers.track_counts_by_job(db, job_ids)` runs one `GROUP BY (job_id, state)` aggregate over
  every requested job; `track_counts(db, job_id)` is now a thin single-job wrapper over it, kept so
  the five single-job routes (`create_job`, `get_job`, `cancel_job`, `set_job_priority`, `bump_job`)
  didn't need their own bulk-fetch boilerplate.
- **The response body was never byte-identical, before or after this fix, and the v15 plan's own
  wording claiming so was wrong.** `track_counts`'s key order follows `GROUP BY` result order, which
  Postgres doesn't guarantee across query plans — grouping by `(job_id, state)` instead of `state`
  alone reorders it further. The regression tests assert parsed-JSON equality (exact key/value
  correctness, including a job with zero tracks correctly serializing to `{}`), not literal bytes.
  If literal byte stability is ever wanted, that needs an explicit `ORDER BY` and is a separate,
  larger decision.
- **A query-counting fixture (`count_queries` in `conftest.py`) is new to this repo** — there was
  previously no way to assert "this endpoint issues N queries" directly; every prior "at current
  scale" note in this file (see the v04/v05 entries above, corrected here) was a judgment call with
  no regression guard behind it. It's a `contextmanager` wrapping
  `sqlalchemy.event.listen(engine, "before_cursor_execute", ...)`, attached to
  `db_session.get_bind()` — the only engine the `client` fixture's requests can possibly reach,
  since `get_db` is overridden to yield that exact session.
- **The local sandboxed dev network can reach the general internet (confirmed: spotdl's Spotify
  calls worked) but specifically cannot reach `UPSTREAM_AUTH_BASE_URL`** (`api.vb2007.hu`), so the
  real `/api/auth/login` flow 401s here even with correct credentials — `httpx.ConnectError: All
  connection attempts failed` in the `api` container's logs, not a credentials problem. Creating a
  session row directly via `app.services.sessions.create_session()` and using its token as a manual
  cookie (`-b "SPOTDL_SESSION=<token>"`) produces a session indistinguishable from a real login for
  every downstream purpose, since it's the exact same table and the exact same `require_session`
  check — only the external auth hop is bypassed. Useful for any future real-stack verification run
  from this same environment.
- **`spotdl`'s own `SpotifyClient.search()` is not a literal-match catalog search** — it hits an
  internal/undocumented Spotify endpoint (response shape includes `coverArt.extractedColors`, not
  the public Web API's fields) that returns personalized/localized results almost unrelated to the
  query string, and `total_tracks` comes back `0` for every album. Don't use it to programmatically
  discover fixture URLs (e.g. "find a short 3-track album") — it doesn't do what the name suggests.
  Real playlist/album URLs for this version's real-stack verification were supplied directly by the
  project owner instead.
- **`frontend/.svelte-kit/` and `frontend/build/` had root-owned files left over from a prior
  `docker compose --build` run** that wrote into these bind-mounted, gitignored directories as
  root — `npm run check`/`npm run build` both failed with `EACCES` until they were removed
  (`sudo rm -rf` was needed for `build/`; `.svelte-kit/` came back with a plain `rm -rf` once its
  top-level dir ownership allowed descending into it). Both are pure build output with nothing
  tracked in git, so deleting and letting the next `npm run check`/`build` regenerate them is always
  safe — if this recurs, it means a container ran a build command against these bind mounts again.
- **Verified against the real docker-compose stack** for every finding above: a real 5-track album
  download+re-download for the pacing hook and dedup, a real 17-track playlist submission
  (`expanding` → `expanded`, exact track count and titles confirmed via `GET /jobs/{id}/tracks`,
  then cancelled to bound the real-download footprint once expansion was confirmed), and a real
  headless-Chromium session (Playwright, cookie-authenticated via the session-row technique above)
  navigating to `/settings`, screenshotting a proxy row, mutating its `consecutive_failures` directly
  in Postgres, and confirming the rendered row updated within ~7s with **no page reload** — the
  proxy-polling fix's actual "Done when" claim, not just its code existing.

### v16 users-schema gotchas (learned building `users`/`user_settings` and ownership columns)

- **The v16 plan's own text is self-contradictory, and the user resolved it by choosing to break
  things on purpose.** The plan specifies `jobs.user_id`/`sessions.user_id` as NOT NULL and says
  `sessions.user_id` *replaces* the `email` column outright — but also promises "no behavior change"
  and "existing test suite passes unchanged." Those can't both hold: no `User` row exists until v17
  wires login to create one, so `create_session(db, email)` and every direct `Job(...)` construction
  in a task/router immediately violate the new NOT NULL constraints. Asked directly, the user chose
  to apply the schema literally now and accept the breakage rather than soften it (e.g. nullable
  `user_id` until v17) or pull user-creation logic into v16. **This was a deliberate, approved
  decision — not a bug introduced this session and not something a future session should "fix" by
  reverting to nullable columns.**
- **Concrete blast radius, measured**: `python -m pytest tests/ -q` → **80 failed, 71 passed** (was
  137/137 passing at v15). Every failure traces to exactly two causes, confirmed by reading tracebacks
  rather than assumed from the diff: (1) `TypeError: 'email' is an invalid keyword argument for
  UserSession` — `services/sessions.create_session` and `routers/auth.py`'s `/me` still read/write
  the now-removed column; (2) `sqlalchemy.exc.IntegrityError: NOT NULL constraint failed:
  jobs.user_id` — every direct `Job(...)` construction in `tests/test_*_task.py`/`test_retry.py` and
  every router test that authenticates via the `client` fixture (which logs in, which hits cause 1).
  Zero failures came from the `TrackState.FAILED` removal (grepped `tests/*.py` for it first — no
  test ever referenced it) or from any other source; the 71 passing tests are exactly the ones
  touching neither `Job` nor a session-authenticated `client` call.
- **v17's actual unblock-the-suite task list, so it isn't rediscovered from scratch**: (a)
  `routers/auth.py`'s `login` must create-or-load a `User` row (matched case-insensitively against
  the normalized email) and call `create_session(db, user.id)` instead of `create_session(db,
  email)`; (b) `create_session`'s signature and `UserSession`'s `.email` read in `/me` need to follow
  the `user_id` → `User.email` relationship instead; (c) `routers/jobs.py`'s `create_job` needs the
  authenticated user's id to populate `Job.user_id`; (d) every direct `Job(...)`/`UserSession(...)`
  construction across `tests/test_beat_task.py`, `test_download_task.py`, `test_expand_task.py`,
  `test_retry.py`, `test_jobs.py`, `test_tracks.py`, `test_auth.py` needs a `user_id`/relies on a
  `client` fixture that logs in — both need a `User` row to exist first, so `conftest.py`'s
  `db_session` fixture needs `User.__table__.create(engine)` added and probably a
  `test_user`/`authenticated_client` fixture that creates one and logs in through it, replacing the
  ad-hoc `Job(source_url=..., source_type=...)` calls with a version that also passes `user_id`.
- **Enum-value removal via the type-swap technique (v02/v10's pattern) breaks a dependent partial
  index in a way the existing gotcha didn't cover.** `ix_tracks_scheduled_at_waiting`'s `WHERE state
  = 'waiting'` clause was parsed at index-creation time and bound to the enum type's OID; renaming
  that type to `track_state_old` mid-swap doesn't change the OID, so by the time `ALTER TABLE tracks
  ALTER COLUMN state TYPE track_state USING state::text::track_state` runs, Postgres is comparing the
  new-typed column against an old-typed literal with no `=` operator between the two distinct types
  — `psycopg.errors.UndefinedFunction: operator does not exist: track_state = track_state_old`. Any
  future enum-value removal/rename on a column with a partial (or other predicate-bearing) index must
  `DROP INDEX` before the `RENAME TYPE`/`CREATE TYPE`/`ALTER COLUMN` sequence and recreate it
  afterward — confirmed by reproducing the failure once, fixing it this way, then verifying a full
  `upgrade head → downgrade -1 → upgrade head` round-trip against the real shared Postgres.
- **Verified against the real shared Postgres, not a scratch container** (per the user's explicit
  go-ahead, since this instance also backs the live deployed app): row counts before the migration
  were 81 `jobs` / 168 `tracks` / 72 `sessions`, all deleted by design (no backward compatibility
  required — see `CLAUDE.md`). `\d`-equivalent output (via `information_schema`/`pg_indexes`/
  `pg_constraint`, since the `api` image has no `psql`) confirmed every column, FK, and index matches
  the plan exactly, including `ix_jobs_user_id_created_at_active`'s `WHERE (archived_at IS NULL)`
  clause and `track_state`'s enum values with `failed` absent. `upgrade head → downgrade -1 → upgrade
  head` round-tripped cleanly, with the downgrade step confirmed to fully restore `sessions.email`,
  `track_state`'s `failed` value, and `ix_tracks_scheduled_at_waiting` before re-upgrading. All four
  backend processes (`api`, `worker-dl`, `worker-meta`, `beat`) restarted healthy with zero import
  errors against the new models.

### v17 multi-user-auth gotchas (learned wiring user-creation-on-login + owner scoping + per-user SSE)

- **`services.users.get_or_create_user` reconciles `is_admin` on *every* login, not just at row
  creation, and demotes every other admin row in the same call.** Deriving `is_admin` once at
  creation would mean changing `ADMIN_EMAIL` in `.env` needs manual SQL to take effect for an
  already-existing user; reconciling only the logging-in user's own flag would leave a *previous*
  admin privileged indefinitely if they simply don't happen to log in again after the env var
  changes. One extra `UPDATE ... WHERE is_admin AND email != :new_admin` per login is what actually
  makes "exactly one admin exists" true, not just "the current admin is correct."
- **`require_session` returns the `User`, not the `UserSession`** — every route that used to take
  `_: UserSession = Depends(require_session)` and discard it now takes `user: User` and actually
  uses `user.id`/`user.is_admin`. Splitting `current_session` (resolves + bumps the session) from
  `require_session` (resolves the owning `User`) costs one extra query per request from
  `expire_on_commit` forcing a re-`SELECT` on the first post-commit attribute read — see the Auth
  index entry above. Accepted as a small, constant cost rather than restructured.
- **Ownership lives on `jobs` only, never denormalized onto `tracks`** (the locked v2 decision) —
  every track-owner check (`tracks.py`'s `_get_track_or_404`, `download_track`'s owner-id lookup,
  `beat.py`'s reclaim-sweep owner resolution) is a join through `Track.job_id → Job.user_id`, never
  a stored column. `download_track` captures the resolved `owner_id` as a **plain `uuid.UUID`
  before any work starts**, specifically because the failure branch's `db.rollback()` would expire
  an ORM-attached `Job`/`Track` reference — a plain value survives the rollback, an attribute access
  on an expired object would trigger a surprise re-`SELECT` (or worse, silently read stale data if
  something upstream detached it).
- **Direct-id ownership checks filter in the same query, not after loading the row** —
  `_get_job_or_404`/`_get_track_or_404` add `.filter(Job.user_id == user.id)` (skipped for admins)
  to the same `SELECT` that fetches the row, rather than loading it unconditionally and then
  checking `.user_id` in Python. Functionally equivalent for a non-admin, but the query-level filter
  is what makes "admin sees this row unconditionally" and "non-admin never even receives it" the
  same code path, not two branches that can drift apart.
- **`beat.py`'s `_reclaim_stale_tracks` needed a second bulk query, not a per-row one, to resolve
  owners** — its `UPDATE ... RETURNING(Track.id, Track.job_id)` has no `Job.user_id` to offer
  directly (an `UPDATE` can't join out an unrelated table's column into its own `RETURNING`
  clause), so the fix is one extra `SELECT Job.id, Job.user_id WHERE Job.id IN (...)` over the
  distinct `job_id`s from the first query's results — still exactly two queries regardless of how
  many tracks were reclaimed, never N+1.
- **`test_config.py`'s `_REQUIRED` dict silently stopped being "the required fields"** the moment
  `ADMIN_EMAIL` became a real required setting — `Settings(**_REQUIRED)` still constructed fine
  because `conftest.py`'s `os.environ.setdefault("ADMIN_EMAIL", ...)` (set for the *other* 150+
  tests in the suite) filled the gap silently. A test asserting "missing `ADMIN_EMAIL` is rejected"
  must `monkeypatch.delenv("ADMIN_EMAIL")` first or it doesn't actually test anything — caught by
  the test failing with "DID NOT RAISE" rather than by inspection.
- **The `list_jobs`/`list_tracks` N+1 guard's absolute query-count ceiling needed raising, not just
  its differential check** — v15's test asserted `<= 4` statements regardless of job count; v17
  adds one `JOIN users` to the list query and one `User` lookup to `require_session`, both still
  O(1), pushing the real count to 6. The *differential* assertion (5-job page costs the same as a
  1-job page) is the actual N+1 regression guard and needed no change; the absolute number is a
  loose sanity ceiling that legitimately moves when auth/ownership overhead changes, and the test's
  own comment already said as much.
- **The local upstream `vb2007.hu-api` instance (`host.docker.internal:3000`, per the v03 gotcha)
  was not running earlier in this session** — real-upstream login failed with a `ConnectError`,
  not a 401, confirmed from `api`'s logs before assuming a code bug. Initial verification used the
  documented v15 fallback for *both* identities: `services.users.get_or_create_user` +
  `services.sessions.create_session` called directly inside the running `api` container to mint two
  real DB-backed users (one matching `ADMIN_EMAIL`, one not) and real session tokens, used as
  `Cookie: SPOTDL_SESSION=...` headers against the real running stack. This exercised every line of
  v17's actual code under test (ownership queries, admin gating, per-user Redis channels) — only
  the external password-check HTTP call itself was bypassed. **Once the local upstream instance was
  started (and the live `https://api.vb2007.hu` confirmed healthy too, see the corrected v03 note
  above), the full real-login path was re-verified end to end** — see the next entry.
- **Real-upstream-login verification, both identities, following this file's new standing rule**:
  logged in for real against the local `vb2007.hu-api` as the existing `balazs@vb2007.hu` test
  account (now the v17 admin) and as a freshly `POST /auth/register`ed second account
  (`spotdlwebtest@example.com`, plain alphanumeric username — the hyphenated one 500'd, an upstream
  bug), added to `ALLOWED_EMAILS`. Both `/api/auth/login` calls returned real `Set-Cookie` headers
  and correct `is_admin`; `get_or_create_user` correctly created the second identity's `users` row
  on its first real login. Re-ran the core cross-user sweep with these real cookie jars (not
  minted tokens): list isolation, all direct-id 404s, admin gating, and a raw `curl -N /api/stream`
  capture — identical clean results to the fallback-identity run, confirming the fallback and the
  real login path exercise the same downstream code (as expected, since v17 never touches
  `upstream_auth.login` itself).
- **Verified against the real docker-compose stack** (`ADMIN_EMAIL` added to the shared `.env`;
  `docker compose up -d` recreated all four backend containers, which also picked up the code
  changes `worker-dl`/`worker-meta`/`beat` don't hot-reload on their own): two real, DB-backed
  identities (one admin, one not) each submitted a real Spotify track through the real
  expand→download pipeline. List isolation confirmed both directions; all seven direct-id
  endpoints individually returned 404 for the non-owner and 200 for the real owner; admin reached
  and mutated (bump) the non-owner's job successfully; `all_users=true` from the non-admin session
  was silently ignored (still only its own row) while the admin's `all_users=true` revealed both.
  **SSE proven from two concurrent raw `curl -N /api/stream` captures, not the UI**: creating and
  cancelling a job on the admin's own channel produced three real events (`job.state` ×2,
  `track.state` ×1) captured on the admin's own stream in the same window a second, concurrently-
  capturing non-admin stream received only heartbeats — zero of the admin's ids. A second run
  proved the reverse-direction admin `all_users=true` pattern-subscribe positively receives a
  non-admin's real events (same job-lifecycle sequence, captured on the admin's `?all_users=true`
  stream). Admin gating swept from a real non-admin session: 403 on every `settings`/`proxies`/
  `worker` mutation endpoint, 200 on `GET /api/worker/status`. Browser pass (Playwright against a
  cached Chromium, no project driver existed yet — candidate for `/run-skill-generator`): the
  non-admin session shows no settings link, no worker pause/resume button, no scope toggle, zero
  console errors; the admin session shows all three, reaches `/settings` and loads real proxy/
  output data, and the mine/all-users toggle switches both directions with zero console errors and
  the job count changing from the caller's own jobs to every user's.

### v18 job-centric-api gotchas (learned building cursor pagination, rollup status, and search)

- **The plan's own endpoint list put a `scope=job|track` parameter on `GET /api/jobs`, but the
  master plan's "Tracks mode" (search/filter/sort operate on tracks; pagination is over tracks, not
  jobs) is only representable as a list of *track* rows with their parent job embedded — which is
  exactly `GET /api/tracks`'s shape, not a job-shaped one.** Read literally, there is no coherent
  third response shape for `/api/jobs?scope=track` distinct from `/api/tracks`. Resolved by
  treating `scope=track` as a genuine alias: `GET /api/jobs?scope=track` shares its entire
  implementation with `GET /api/tracks` (`services.track_listing.list_tracks`), returning the
  track-shaped `{items, next_cursor}` body, not a job-shaped one. `GET /api/jobs?scope=job`
  (default) is the normal job listing. This is a judgment call on an underspecified corner, not a
  contradiction requiring a stop-and-ask like v16's — the *response shape* for scope=track was
  never ambiguous (the design notes spell it out), only *which URL* reaches it, and that detail is
  cheap for v20 to adjust either way since both paths already exist and agree.
- **`Job` has no title column, and nothing in v14–v17 needed one.** v18's `sort=title` and the
  listing response both need *some* per-job display string. `rollup.derive_job_title`/
  `rollup.job_title_expr` use the first-created track's `list_name` (playlist/album name, present on
  spotdl `Song` objects — verified via `dataclasses.fields(Song)` inside the running `api`
  container, not assumed) if present, else that track's own `name`, else the job's `source_url` for
  a job with zero tracks (`expanding`/`failed`). Not a stored column, by the same "don't add a
  second source of truth" reasoning as rollup status itself.
- **`Track.song_json[key].astext` (not `.op("->>")`) is the portable way to extract JSONB text, and
  it works identically for a scalar field *and* a JSON array field on both Postgres and the test
  suite's SQLite** — confirmed by direct execution against both engines (SQLite 3.40.1, which has
  native `->`/`->>` operators as of 3.38). `.astext` on an array key (e.g. `song_json['artists']`)
  returns the array's own JSON text form (`'["Queen","Bowie"]'`) on *both* backends, which is exactly
  what substring search wants — no separate `cast(..., String)` needed. `.op("->>")('key')` instead
  fails at execution on SQLite (`JSONDecodeError`) because it bypasses the path-building `.astext`
  normally does internally.
- **A correlated scalar subquery's `.correlate(...)` argument must name the actual enclosing
  `FROM`, not the table the subquery conceptually "belongs to."** `job_title_expr`'s first draft
  called `.correlate(Job)` on a subquery referencing `agg.c.id` (an aggregated subquery built *from*
  `Job`, not `Job` itself) — since `Job` was never in the outer statement's `FROM` list, SQLAlchemy
  silently produced an *uncorrelated* subquery that returned the same (arbitrary, ORDER-BY-first)
  track's title for every single row. Caught by a fixture cross-check (zero-track jobs all showing
  the same non-empty title, which should be impossible) before it reached a router. Fix: no
  explicit `.correlate()` call at all — SQLAlchemy's default auto-correlation finds whichever
  enclosing `FROM` actually provides the referenced columns, working correctly whether the caller's
  outer query FROMs `Job` directly or an aggregate built from it.
- **Row-value tuple comparison (`(a, b) > (c, d)`) cannot be the basis for keyset pagination once
  any tuple element is nullable** — SQL's three-valued logic makes any comparison touching a `NULL`
  evaluate to `NULL` (neither true nor false), which silently drops rows instead of including them.
  `services.pagination` deliberately does NOT use `tuple_(...)` row comparison at all; nullable sort
  keys (`sort=next_retry`) get their own explicit two-branch WHERE (already-in-the-NULL-partition vs
  still-in-the-non-NULL-partition) rather than trying to force one generic comparison to handle both.
  Caught by a fixture test pairing two NULL-valued rows across a page boundary before it reached
  production code.
- **A cursor's UUID component must round-trip as an actual `uuid.UUID`, not a string that merely
  looks like one** — `pagination.encode_cursor` originally rendered a UUID via bare `str(value)`,
  indistinguishable on decode from a genuine string sort key (e.g. a title). The decoded plain
  string, used as a bind parameter against the `id` column, failed with `AttributeError: 'str'
  object has no attribute 'hex'` (SQLAlchemy's cross-dialect `Uuid` type's bind processor calls
  `.hex` on what it assumes is a real `UUID` instance). Fixed by making the UUID encoding
  self-describing (`{"$uuid": "..."}`), mirroring how datetimes were already handled
  (`{"$dt": "..."}`) — decode must distinguish "this looked like text" from "this needs
  reconstructing into a real object," and can't infer that from the string's contents alone.
- **SQLite's `CURRENT_TIMESTAMP` (what `func.now()` compiles to, and what `Job.created_at`'s
  `server_default` uses) has one-second resolution** — a tight test loop creating several jobs
  within the same wall-clock second gives them all an *identical* `created_at`, silently falling
  back to `id` (an unordered UUID) as the only real sort key and making "sort=created_at" tests
  flaky rather than reliably wrong. `test_pagination.py`'s fixtures set `created_at` explicitly with
  strictly increasing values instead of relying on real insert timing.
- **pg_trgm GIN indexes only get used by Postgres's planner if the query's expression is
  structurally identical to the one the index was built on** — not merely equivalent. The
  `ix_tracks_search_trgm` migration's raw-SQL expression is a hand-copied match of
  `search.track_search_text()`'s compiled output (verified via `.compile(dialect=postgresql.dialect())`
  at migration-authoring time, and again via `EXPLAIN` with `SET enable_seqscan = off` to prove the
  index is at least reachable). At real ~3,000-row scale in this dev database, Postgres's planner
  still chose a sequential scan over the index (7.9ms either way) — a correct, cost-based decision
  at this size, not a sign the index doesn't work; it becomes the chosen plan once a table is large
  enough that a full scan actually costs more.
- **Re-confirmed v11's "ad-hoc scripts go in `/app/`, never `/tmp/`" the hard way**: a `/tmp`-staged
  seeding script failed on `app.services.users` specifically (added after this dev image was last
  built) while `app.services.sessions` imported fine — the stale `site-packages` copy of `app` isn't
  simply *missing*, it's a real but outdated snapshot, so only symptoms touching what changed since
  the last image build surface, making the failure look like a real bug in the new code rather than
  a stale-import artifact. `PYTHONPATH=/app python3 /tmp/script.py` also works if a script must stay
  outside `/app`.
- **Query count for the new `GET /api/jobs` is a fixed 8 statements** (session lookup, the owner-
  joined+aggregated base query, `counts_by_status`, the capped `total_estimate` count, the page
  itself, and the page's bulk `track_counts_by_job`) **regardless of how many jobs exist or how many
  are returned** — proven with the existing `count_queries` fixture (differential: a 5-job page
  costs the same as a 1-job page) plus an absolute ceiling, same pattern as v15/v17's N+1 guards.
- **Verified against the real docker-compose stack, real Postgres, real ~3,000-track volume**: a
  job with 3,000 tracks (2,700 `completed` / 300 `lookup_failed`, realistic `song_json` incl.
  `list_name`) seeded directly (not through 3,000 individual API calls) via `bulk_save_objects`.
  Against the real running server: `GET /api/jobs` first page 85ms with correct `track_counts`
  (`{"completed": 2700, "lookup_failed": 300}`), correct rollup (`settled`/`partial`), and correct
  derived title (`list_name`); `GET /api/jobs/{id}/tracks` first page 73ms with correct
  `counts_by_state`; a substring search across the 3,000 tracks 84ms, returning exactly the 11
  correct matches (`Load Test Song 42`, `420`–`429`); `scope=track` via both URLs 72ms. A second,
  independent user (session minted directly per the documented v15 fallback, real stack) confirmed
  zero visibility into any of it across `/api/jobs`, `/api/jobs?q=...`, `/api/tracks?q=...`, and
  `all_users=true` — the v18-specific extension of v17's cross-user sweep the project's own
  "new query paths, new chances to drop the filter" invariant calls for. All seeded rows and both
  test users deleted afterward (this is the shared dev database).

### v19 archive-retention gotchas (learned building soft-archive lifecycle + per-user retention)

- **Eligibility is re-derived from real track states via the exact same `rollup.lifecycle_case`/
  `active_count_expr`/`waiting_count_expr` building blocks the v18 listing uses, not a second,
  differently-shaped check.** `services.archive._eligible_job_ids` builds its own small aggregate
  (base `Job` columns + `active_n`/`waiting_n` + `coalesce(max(Track.updated_at), Job.updated_at)`
  for the age comparison) rather than reusing `rollup.aggregate_jobs` directly, because that
  function's output has no "last track activity" column at all — but the lifecycle-determining
  `case()` expressions themselves are the identical shared functions, so archive eligibility and
  listing-page rollup status can't silently drift apart the way two independently-written
  `settled`/`failed`/`cancelled` checks could.
- **The age cutoff is `coalesce(max(Track.updated_at), Job.updated_at)`, never `Job.created_at`** —
  covers both a job with tracks (the common case, and the whole reason this version exists: a
  `waiting` job's newest track activity, not its creation date, is what must block the sweep) and a
  zero-track `failed` expansion (falls back to the job row's own `updated_at`, which `onupdate=
  func.now()` keeps current even though the job has no tracks to derive activity from).
- **`job_to_dict` never actually exposed `Job.archived_at` in the response body, even after v18
  added `include_archived` query-param filtering** — the field simply wasn't in the returned dict,
  so a caller had no way to tell *which* rows in an `include_archived=true` response were archived
  without a direct DB check. Every existing call site already had a real `Job.archived_at` (or the
  equivalent aggregate-row column, already selected by `job_listing.py`'s base query) in hand, so
  the fix was a one-line addition inside `job_to_dict` itself with zero call-site changes — none of
  the 228 existing tests asserted an exact response-body dict that would have caught the field's
  absence, and it only surfaced hitting the real running `api` container with `curl` during this
  version's own end-to-end pass. Worth remembering for v20: any future "the API returns everything
  the frontend needs" assumption should be spot-checked against a real request, not just against
  what the router *code* looks like it returns.
- **Confirming the new hourly `archive-due-jobs` `beat_schedule` entry actually fires does not
  require waiting an hour**: temporarily changed `celery_app.py`'s `"schedule": 3600.0` to `15.0`,
  `docker compose restart beat`, and captured two real `Scheduler: Sending due task archive-due-jobs
  (app.tasks.beat.archive_due_jobs)` lines in the container's own logs within a 20s window — then
  reverted the literal to `3600.0` and restarted `beat` again before committing anything. Confirmed
  via `git diff` that the reverted file is byte-identical to the intended final state (no stray
  verification value left behind).
- **Verified against the real docker-compose stack, real Postgres, real Redis, real `beat`
  container** (not the unit-test SQLite suite, which separately covers the same logic — 228 tests,
  all passing): seeded a seven-job mixed set directly via a script staged in `/app/` (the v11
  convention, not `/tmp/`) covering every lifecycle — `active` (a `pending` track), `waiting` (a
  `waiting` track, `scheduled_at` ten days out so the real running `dispatch_due_tracks` never
  touched it mid-test), `settled`, zero-track `failed`, `cancelled`, and a second real user's
  `settled` job. `POST /api/jobs/archive {"all_settled": true}` against the real running `api`
  container (sessions minted directly, the documented v15 fallback) archived exactly the caller's
  three eligible jobs, left `active`/`waiting` and the other user's job untouched, and — confirmed
  by raw SQL, not the API — left all 12 `jobs` rows in place and `downloaded_tracks` at exactly 92
  rows before and after. `POST /api/jobs/unarchive` restored a job to the default view; archiving a
  second user's job id via the first user's session silently no-op'd (`archived_ids: []`), never
  touching the row. `GET`/`PATCH /api/settings/retention` confirmed per-user isolation (one user's
  `retention_days=1` invisible to another) and rejected `retention_days<=0` with `400`. Separately
  aged a fresh job's track `updated_at` to a year old, set the owner's `retention_days=1`, and ran
  the real `archive_due_jobs()` task function against the real stack from inside `worker-meta`: the
  aged `settled` job was archived, the `waiting` job (also aged a year on both `job.created_at` and
  its track's `updated_at`) was **not** — the specific failure mode this version's design exists to
  prevent — and the second user's `settled` job was untouched because that user has no
  `retention_days` set. All seeded rows, minted sessions, and both users' `user_settings` rows
  deleted afterward (shared dev database); confirmed job/track/`downloaded_tracks` counts identical
  to their pre-test values.
