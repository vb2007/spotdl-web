# spotdl-web — Accumulated Gotchas (v01–v70+, every master)

Hard-won findings from building every master so far (v1 from v01, through v5 and on), kept
**verbatim** as they were written when each version shipped. These were originally in `CLAUDE.md`; they were moved here once that file grew
past 1,700 lines, because a rule an agent must follow and a war story an agent might need are
different kinds of document and only the first belongs in every context window.

**How to use this file:** don't read it top to bottom. Find your topic in the index below, read
that section, move on. `CLAUDE.md` carries the rules that always apply; this carries the specifics
of *why* — and the failure modes that will otherwise be rediscovered the expensive way.

**A caveat that matters:** each entry describes the codebase as it was at its own version's merge,
and every later master has changed schema, endpoints, workflows and the frontend since (master v2
alone reworked most of v1's). **Verify a referenced file, function, flag or line number still
exists before acting on it.** A gotcha that turns out to be stale should be
corrected in place with a dated note — the way v12 corrected v09's false "no nginx SPA-fallback
needed" claim — rather than silently deleted.

---

## Index by topic

**Config & environment**
- `pydantic-settings` auto-JSON-decodes `list[...]` fields; any new list-typed setting needs
  `Annotated[list[str], NoDecode]` or the app won't start → *v01*
- Adding a runtime dependency needs `docker compose build`, not `restart` → *v03*
- `DATABASE_URL` host differs between local dev and the Debian host; never cross them → *v01*
- Local dev's `DATABASE_URL` must name the dev database (`spotdlwebtest`); `SPOTDL_ENV=dev` makes
  every backend service refuse production's name (`spotdlweb`, also `spotdl_web`) or an
  unparseable URL. Production's real database name is `spotdlweb`, not the templates'
  `spotdl_web` → *v32*
- A `BaseSettings` field omitted from a test's constructor kwargs still resolves from
  `os.environ` — a test asserting "missing X is rejected" must `monkeypatch.delenv(X)` first, or
  it silently passes via a value some *other* test's `conftest.py` setdefault already set → *v17*

**Database, migrations & enums**
- A loaded row written back (`track.state = X; commit`) overwrites a concurrent commit; a
  conditional `UPDATE … WHERE state IN (…)` is re-checked by Postgres after the row lock → *v56*
- A proxy FK without `ondelete` made a used manual proxy undeletable (500); history now stores
  the redacted label with the row → *v56*
- `ALTER TYPE ... ADD VALUE` in a migration that also *uses* the value must run in
  `op.get_context().autocommit_block()`; a v35 migration that rewrites data says so and needs a
  `pg_backup` → *v35*
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
  *(2026-10-24, v51: the suite runs on Postgres; the shim is gone.)*
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
- A correlated subquery that references the *same mapped table* the outer statement already selects
  raw (not through an aggregate) needs `.correlate_except(Track)` even with no explicit
  `.correlate(...)` elsewhere — SQLAlchemy's auto-correlation matches by FROM-clause identity, not by
  whether the subquery's WHERE actually reaches into the outer row, and silently strips the subquery
  down to zero FROM clauses (`InvalidRequestError`) when both statements happen to share the same
  table object → *v20*
- A brand-new native enum column added via a bare `op.add_column` (not inside `create_table`) needs
  an explicit `.create(op.get_bind(), checkfirst=True)` first, or `ALTER TABLE ... ADD COLUMN` fails
  against real Postgres with "type does not exist" — every prior enum here was created as a
  `create_table` side effect, never standalone → *v29*
- A custom SQLAlchemy `FunctionElement` with constructor attributes (inlined literals) needs
  `inherit_cache = False`, or one compiled statement serves another's values → *v44*

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
- `image:`/`build: !reset null` must repeat on every service inheriting `build:` from a shared
  anchor — a bare `image:` alongside an *inherited* `build:` still builds locally → *v21*
- `git clean -fd`, never `-fdx`, in an automated deploy — `-x` deletes gitignored `.env`/secrets
  along with build junk → *v21*
- Documented deploy-host paths drift from reality; verify against the real host before wiring an
  automated workflow that acts on them → *v21*
- A persistent self-hosted runner's `docker login` credential outlives the job and poisons later
  pulls (even of public images) until an explicit `docker logout` → *v21*; and every repo's
  runner on the host shares that file, so jobs use a private `DOCKER_CONFIG` (2026-10-19)
- `host.docker.internal` doesn't resolve from the host's own DNS on Linux — a script meant to run
  on the host itself (not in a container) needs `localhost` instead → *v21*
- `git checkout --detach` still needs `--force` to survive local drift on a tracked file, even
  once resolved to an unambiguous commit SHA → *v21*
- A service with no explicit Celery `--concurrency` defaults to `os.cpu_count()` prefork
  children — reliably OOMs a heavy-dependency worker on a resource-limited container → *v21*
- A hardcoded absolute path in a script/doc is a claim about the real host's layout — verify it
  against the host, since a stray `mkdir -p` into a "normal-looking" path (e.g. `/srv`) is easy
  to miss and can land on the wrong disk entirely → *v21*
- A generated-data directory (backups, logs, caches) placed inside a git-managed deploy checkout
  must be gitignored, or the next `git clean -fd` silently deletes it → *v21*
- `docker compose ps`'s `CREATED`/`Up` columns show when a container last (re)started, not
  whether the most recent deploy did anything — an idempotency-skipped, content-identical deploy
  looks identical to a stuck one from that output alone → *v21*
- The deploy host's on-disk git checkout can drift behind the release it's actually running
  (containers come from the pulled GHCR image, independent of the working tree) — host-level
  scripts invoked directly can silently run stale, already-fixed-on-GitHub code. A stale *local*
  tag left over from pre-merge `workflow_dispatch` testing can also shadow the real tag of the
  same name, rejecting `git fetch --tags` with "would clobber existing tag" → *v22*
- Local dev's default `docker compose up` (with `docker-compose.override.yml` applied) runs Vite
  (`npm run dev`) for `web`, not nginx — any feature whose correctness depends specifically on
  nginx behavior (an `internal` location, a new `location` block) is untestable through that
  default stack and needs either `docker compose -f docker-compose.yml up` (bypassing the
  override) or a standalone container built from the same image, run alongside the existing stack
  (see the Testing entry below) → *v27*. **Corrected same version, same day**: for
  `X-Accel-Redirect` specifically, this was fixed rather than left as a standing gap — see the
  Frontend entry below (`vite.config.ts`'s `devFileDownloadFallback`). The general point (Vite
  ≠ nginx, a *new* nginx-only mechanism won't automatically work through the dev override) still
  holds for anything that isn't file-download-shaped.
- Editing a service's `volumes:`/`build:` mid-session and running `docker compose up -d` recreates
  the container but does **not** rebuild it — if that service's image tag was ever built a
  *different* way before (e.g. a plain prod-style build reusing the same tag a dev `target:` build
  also uses), the recreated container silently runs the stale image instead of the one the current
  compose file describes. Confirmed live: a `web` container recreated for a new bind mount
  crash-looped with `exec: npm: not found` because it picked up an old final-nginx-stage image under
  the same `spotdl-web-web` tag. `docker compose build <service>` (respecting the override's own
  `target:`), then `docker compose up -d <service>`, not just `up -d` alone → *v28*
- Changing a compose network's own config (e.g. enabling IPv6) recreates the network; any running
  container `docker compose up -d` doesn't *also* recreate is left with broken embedded-DNS
  service-name resolution (`redis` → `gaierror`) even though it still looks "running"/"healthy" —
  needs a full `down` then `up`, never just another `up -d` → *v29*
- `docker compose` echoes interpolated `.env` values in some render errors
  (`invalid containerPort: <value>`), so even `config --quiet`'s stderr isn't secret-free → *v33*
- `docker compose ps <svc>` exits 0 with empty output when the service has no container, and
  non-zero on a compose error, so its exit status separates "not up yet" from "broken". But it
  also writes WARNs to stderr on a *successful* call, so never `2>&1` it into a compared value
  → *v33*
- A pipeline script run from the deploy job's workspace comes from the ref being *deployed*: a
  dispatch of an older tag doesn't have scripts newer than that tag → *v33*
- Cloudflare in front of this host's Synapse rejects Python `urllib`'s default User-Agent (HTTP
  403, `error code: 1010`) before Synapse sees the request → *v33*
- A pending run in a concurrency group is replaced by any newer one (only the *running* one is
  protected), so a queued scratch dispatch can be silently cancelled by an unrelated push → *v33*
- Under `bash -e`, an assignment whose `$(...)` ends in a false `[ ] && echo` aborts the script.
  Test extracted Actions scripts with `bash -eo pipefail`, not plain `bash` → *v33.1*
- On the host, every compose command needs `-f docker-compose.yml -f docker-compose.prod.yml`
  (plus `--profile tunnel` for `up`/`down`). `up` without the overlay stops the app, creates empty
  named volumes and fails on the network cloudflared holds → *v38*

- The dev `web` container's `node_modules` and `src/lib/paraglide` are anonymous volumes: they
  outlive a rebuild, so a dependency change needs `up -d --renew-anon-volumes` → *v46*.
  **Corrected 2026-10-24 (v52):** named volumes now, and `npm ci` runs on its own when
  `package-lock.json` changed; `docker compose restart web` is all it takes

- `uvicorn --reload` waits forever for open SSE streams before restarting: edit a backend file
  while a browser tab (or `curl -N`) holds `/api/stream` and `api` goes unhealthy with
  "Waiting for connections to close" until `docker compose restart api` → *v48*.
  **Fixed 2026-10-24 (v52):** `--timeout-graceful-shutdown 3` in the dev command
- A deploy recreates every container, so `docker compose logs` on the host only reaches back to
  the last deploy; anything older (an alert that never arrived) can't be reconstructed → *v48*
  **Fixed 2026-10-27 (v60):** production logs to journald; `scripts/prod_logs.sh` reads across
  deploys (json-file lines from before that are gone) → *v60*
- The rollback guard's `compose run` with the *old* files fails ("network ... has active
  endpoints") after a release that changed `networks:`, while plain `up` recreates a changed
  network without complaint; the guard probes on the live network as `external` → *v60*
- Compose echoes a *piece* of a `.env` value in a port-spec error (split at `:`, so a URL comes
  back cut short), which whole-value masking misses; the redactor also masks URL userinfo → *v60*
- A different `logging.driver` in an overlay replaces the base file's json-file `options` rather
  than merging them (journald refuses `max-size`); the journald driver's `labels` option turns
  `com.docker.compose.project` into a `COM_DOCKER_COMPOSE_PROJECT` field → *v60*
- Docker's journald entries sit in the system journal: reading them takes `systemd-journal`/`adm`
  (or root), which this host's `vb2007` doesn't have → *v60*
- `.git/info/exclude` isn't versioned, so it protects a file from every version's `git clean -fd`,
  including an old workflow copy that checks out a commit whose `.gitignore` lacks it → *v60*
- Two stacks on one machine collide on more than ports: the dev override pins the network's IPv6
  subnet, Postgres 18's image refuses the old `/var/lib/postgresql/data` volume path, and a
  fresh worktree's bind-mount sources get created root-owned; `scripts/agent_stack.sh` handles
  each → *v50*
- An agent slot's e2e run needs `worker-dl` (seeds settle there) and the owner's dev history
  (ledger rows, three pages of admin jobs, an album, a network-path attempt); it runs under the
  realdl lock after `scripts/agent_seed.py` recreates them → *v50*
- Chromium aborts every in-flight request with `ERR_NETWORK_CHANGED` when the host's interfaces
  churn (another stack's crash-looping containers): an e2e failure on a blank page is that → *v50*
- Bash reads a script as it runs it: editing (or rebasing) `scripts/agent_stack.sh` under a running
  `realdl`/`e2e` would execute whatever lands at its offset, so it runs from a `main()` function → *v50*
- Postgres's Alpine image sorts text by codepoint (musl); production's Debian 18.6 uses glibc
  `en_US.UTF-8`, so a slot runs `postgres:18.6-bookworm` → *v50*
- Cookies ignore ports: two stacks on `localhost` in one browser profile overwrite each other's
  session cookie → *v50*
- Labelling an existing named volume makes Compose ask "Recreate (data will be lost)?" on a
  terminal (silently skipped without one) → *v50*
- `trap '' INT` doesn't protect a `docker compose` child (Go re-enables SIGINT); bash defers a
  trapped SIGTERM until the foreground child exits → *v50*
- `pg_isready` without `-h` passes against the image's socket-only init server → *v50*
- Celery as PID 1 drops SIGTERM until its handlers exist: a `worker-dl` stopped in its first
  seconds waits out the 300 s grace period (slot overlay: `init: true`) → *v50*
- A cleanup that writes to a dead stderr (closed terminal, a `| tee` killed by the same Ctrl-C)
  dies of SIGPIPE before it acts, bash's own messages and the docker CLI's alike → *v50*
- `agent_stack.sh` reads a `.env`'s `DATABASE_URL` with SQLAlchemy's URL grammar (path and
  `?dbname=`), not a string cut: a cut let `?`-in-password, `%77` or socket URLs past it → *v50*
- `--profile '*'` enables every profiled service, `worker-dl` and `cloudflared` included: a guard on
  service names alone misses it → *v50*
- `uvicorn --reload` waits for every in-flight response before restarting and SSE never ends:
  the dev `api` runs with `--timeout-graceful-shutdown 3` → *v52*
- The backend image has no `watchfiles` (the uv override pins plain `uvicorn`), so the dev workers reload
  through the stdlib `scripts/dev/reload.py`, wrapped as their `entrypoint` so each `command`
  stays production's word for word → *v52*
- The dev `web` runs as uid 1000 from the Dockerfile's deps-only `dev` stage, with named volumes
  for `node_modules` (reinstalled when `package-lock.json` changes), the compiled messages and
  `.svelte-kit`; `up -d` doesn't restart an unchanged container, so a lockfile change needs
  `docker compose restart web` → *v52*

**Auth, cookies & sessions**
- Admin routes: 404 (`require_admin_hidden`) where the path names an id, 403 elsewhere → *v56*
- A `failed` job's cancel is the incoming overlay's "dismiss": a cancel rule must keep it → *v56*
- A Firefox MV3 extension's background fetch carries the session cookie (loopback HTTP and HTTPS
  production, TCP on and off); a key is the fallback, valid only on job create, reading its own
  job and `me` (an admin's key gets 401 everywhere else) → *v53*
- Rate limits (logins per email + address and per address, IPv6 by /64; creates per user and
  key) fail open at once on a Redis error (no retries); low limits on a slot go in `.env.agent`
  plus a `run … --force-recreate api` → *v53*
- FastAPI's default 422 echoes the body (a surrogate there was a 500 logging a password); a
  stored task result made `.delay()` wait ~19 s on a dead Redis → *v53*
- Upstream `vb2007.hu-api` hardcodes `Domain=localhost`; login must be server-to-server → *v03*
- `Secure` cookies work over `http://localhost` in browsers but **not** in `httpx`/`TestClient` —
  tests need `base_url="https://testserver"` → *v03*
- SQLite returns naive datetimes for `func.now()`; session/breaker checks normalize to UTC → *v03,
  v06*
- SQLite in-memory test engines need `StaticPool` + `check_same_thread=False` → *v03*
  *(2026-10-24, v51: the suite runs on Postgres; no SQLite engine is left.)*
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
- **httpx's own cookie jar cannot be trusted to forward the `VB-AUTH` token to a follow-up
  request** — the local upstream instance's `COOKIE_TARGET_DOMAIN=localhost` means the login
  response's `Set-Cookie` carries `Domain=localhost`, which fails RFC 6265 domain-matching against
  any other request host (`host.docker.internal`, `api.vb2007.hu`), so a client relying on the jar
  to auto-replay it on a second call gets silently unauthenticated. Fixed by extracting the token
  from the raw `Set-Cookie` header text and forwarding it explicitly, which works regardless of
  what `COOKIE_TARGET_DOMAIN` is set to → *v25*

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
- `search_and_download` can swallow a real `AudioProviderError` (e.g. YouTube's PO-token bot-check)
  entirely internally and return `(song, None)` instead of raising — the caller sees a bare missing
  output path, not the underlying error → *v23*
- Without a JS runtime, `spotdl.utils.deno.get_local_deno()` finds nothing and
  `get_local_deno_yt_dlp_options()` wires no `js_runtimes`, so YouTube's PO-token challenge can never
  be solved — every extraction that needs one fails via the swallowed-error path above. The
  production Docker image never installed Deno; `spotdl --download-deno` (run once, baked into the
  image as the `spotdl` user so it lands under that user's own config dir) fixes it → *v23*
- `yt-dlp-ejs` (yt-dlp's companion package for solving YouTube's newer JS challenges, central to
  the PO-token fix above) stayed **pinned** via `requirements.txt` even though `yt-dlp` itself
  floated to latest at build time (`backend/Dockerfile`'s `uv pip install --upgrade yt-dlp`, bare —
  no `[default]` extra, so it couldn't cascade an upgrade to `yt-dlp-ejs` or anything else). This was
  within the letter of "yt-dlp floats, everything else stays pinned," but was a real fragility: a
  future yt-dlp release needing a newer `yt-dlp-ejs` than what was locked could have silently
  reintroduced a variant of this exact outage. **Fixed in v23.1** — the Dockerfile step now upgrades
  both in the same `uv pip install --upgrade yt-dlp yt-dlp-ejs`, and the scheduled `yt-dlp-freshness`
  CI job (`ci.yml`) now compares both against PyPI's latest, each as its own step so a yt-dlp-ejs-only
  drift can't be masked by the yt-dlp check passing → *v23, v23.1*
- `spotdl.utils.metadata.embed_metadata`/`get_file_metadata` (both public, `__all__`-exported) are
  a real read/write round-trip over mutagen that already handles mp3/flac/ogg/opus/m4a/wav — reuse
  them rather than hand-rolling per-format mutagen calls. Two real gaps found by reading the source
  and confirmed against real downloaded files, not assumed: **(1)** neither function writes/reads a
  distinct "year" tag for flac/ogg/opus — only "date" (the full ISO string) — since `embed_metadata`
  only special-cases `year` for mp3 (`TYER`) and m4a (`year` and `date` share the same `\xa9day`
  atom); flac/ogg/opus need a direct one-line patch alongside the call. **(2)** `get_file_metadata`'s
  read path for `.wav` reuses the generic Vorbis-comment-style key lookup, which never matches
  WAVE's real ID3 frame ids — it reports every field missing on a `.wav` file regardless of what was
  actually embedded, making WAV unusable as a "verify tags" target even though `embed_metadata` can
  write WAV tags fine → *v26*
- yt-dlp's own default player-client selection for the URLs this app hits can land on a client
  that's currently outright blocked (`android_vr` returning a bare `403 Forbidden`, even via the
  `android_vr` client specifically — the one client that historically *doesn't* need a PO-token at
  all) while other clients (`android`, `web`, `mweb`) succeed cleanly from the exact same IP, same
  proxy, same everything. Proven by direct CLI tests on the deployed host: raw `yt-dlp` cycling
  through every real client one at a time, and `spotdl --yt-dlp-args '--extractor-args
  "youtube:player_client=..."'` against the two real albums that were failing in production.
  **Not an IP-reputation block** — that was the first, wrong theory (three different clients
  succeeding from the same IP in the same test run rules it out) — it's yt-dlp's own client
  *choice* being the broken option, not the network. Fixed by always forwarding
  `--extractor-args youtube:player_client=...` via `yt_dlp_args` (`downloads.py`'s
  `get_downloader`), independent of family/proxy forcing. The client list is a configurable
  setting (`YOUTUBE_PLAYER_CLIENTS`, default `android,web,mweb`), not hardcoded — this is exactly
  the kind of yt-dlp/YouTube arms-race surface that will need retuning again without a redeploy,
  same reasoning `LADDER_SECONDS`/`PACING_*_SEC` already get → *v31.1*. *(2026-10-26: the forced
  list later lost every audio-only stream to YouTube's SABR-only experiment, so the default is now
  yt-dlp's own `default`. See v54.2.)*
- spotdl's `search_and_download` swallows **every** exception and returns a `None` path, so a
  search with no match, an age-gated video and a real 403 all used to look like the same retryable
  `no_output` (and all fed the breaker). `download_one` now captures the swallowed exception from
  the song tracker's `notify_error` and raises it: a search miss as `LookupError`, a yt-dlp
  "Sign in to confirm your age" as `AgeRestrictedError` (both terminal `lookup_failed`), anything
  else as `NoOutputFileError` carrying the real reason. Terminal on every rung, proxy included
  → *v39.2*. *(2026-10-13: right but mostly unreachable in production. A dead proxy failed before
  any search, as a breaker-feeding `no_output`, so proxy-rung tracks never reached this
  classification, and the breaker's streak outlived every trip. See the v40.1 entries.)*
- A breaker streak that survives its own trip turns a queue of tracks that can never succeed
  into a permanent global pause. One failure per release re-trips it at the top step, and the
  success that would reset it never comes. Every trip and manual release now start a fresh
  streak; escalation still waits for a success → *v40.1*
- On a proxied attempt our only TCP peer is the proxy, so a connection-level failure (aborted,
  reset, refused, timed out) is the proxy's, not YouTube's or the track's. A proxy that accepts
  and then drops surfaces as requests' plain `ConnectionError`, not `ProxyError`. A dead proxy
  raises while ytmusicapi builds its client, before any search. Neither may feed the breaker or
  consume the track's rung (`retry.is_proxy_transport_error(..., via_proxy=True)`). The free retry
  is granted only once in a row: a reset or read timeout can also happen *after* YouTube was
  reached, mid-download, and while other tracks keep the proxies healthy a rung-free 15m retry
  could repeat forever → *v40.1*
- yt-dlp's `DownloadError` keeps the original error in `.exc_info`, not `__cause__`; walk both
  when classifying an exception chain → *v40.1*
- Hard-failure markers are matched case-insensitively and must never be a substring of rate-limit
  or bot-check text: "not a bot", "try again later", "This content isn't available", a bare
  "Video unavailable", 429 and 403 all stay on the ladder. So does geo-blocking: it depends on the
  egress IP, so another rung can change it. Each exclusion has a negative test → *v40.1*
- `alerts.py` runs in the watchdog process and must not import spotdl, even indirectly through
  `retry.py`. A constant both of them need lives in a light module (`attempts.py`) → *v40.1*
- A matched video that is still an upcoming premiere or live event ("Premieres in 102 days") is
  `NotYetReleasedError`, terminal `lookup_failed` by the owner's call; before, it looped the
  ladder as a breaker-feeding `no_output` → *v54.1*
- No YouTube stream is above ~130–160k without Premium, and spotdl re-encodes to whatever
  `--bitrate` it's given: a "320k" MP3 is ~2.5× the size with a false bitrate. Offered now: opus|
  m4a|mp3 at `best` (opus/m4a untouched) or a re-encode target ≤160k → *v54.2*
- A forced `player_client` list can silently lose every audio-only stream (SABR), and
  `bestaudio/best` then picks format 18, a 360p video with ~96k AAC. It shows only in the files: 44.1
  kHz and nothing above ~16 kHz, where Opus is 48 kHz → *v54.2*

**Celery, tasks & durability**
- A fire-and-forget Celery send loses an alert five ways (a >300s `meta` backlog expires it, a
  killed worker-meta drops one mid-send and strands its prefetched ones for 6h, a Matrix
  5xx/429 is dropped, a failed send burns the cooldown, a broker error at enqueue drops it):
  alerts are rows in `alert_outbox` now, delivered with backoff → *v59*
- The outbox orders a category's alerts by `created_at` from the database's
  `clock_timestamp()`, not the caller's `now`; a release is recorded under a share lock on
  `worker_state` so a newer trip can't be overtaken → *v59*
- A new job's tracks sit `pending` with a NULL `scheduled_at` once expand_job has sent them;
  anything measuring "due" must use `coalesce(scheduled_at, updated_at)` → *v59*
- `expand_job`'s tracks carry an outbox marker (`pending` + `scheduled_at`) under a lease, so a
  broker error mid-enqueue is beat's next tick, never a stranded track → *v56*
- `timedelta(days=10**9)` raises OverflowError: an unbounded `retention_days` stopped the archive
  sweep for every later user (v56 bounds new values and clamps old rows) → *v56*
- A server timestamp compared with `Date.now()` is a skewed countdown: use the worker status's
  `server_time` offset (`api.serverToLocal`) or a server-computed remaining time → *v56*
- `attempts.py` must not import `serializers`/`proxies` (spotdl) — alerts.py imports it → *v56*
- Deleting a proxy a download is using waits for it (`delete_requested_at`, never picked, removed
  by `finalize_proxy_deletions` once idle); `pick_proxy` locks only its chosen proxy → *v56*
- SQLAlchemy's `with_for_update(key_share=True)` renders `FOR NO KEY UPDATE`; `FOR KEY SHARE`
  needs `read=True` too. Check the SQL, not the flag → *v56*
- A track beat reclaimed mid-download (v55) may still be downloading through its proxy:
  `proxy_in_use` counts it until the reclaim row is rewritten → *v56*
- Two bulk UPDATEs of one job's tracks (cancel vs expand's claim) take the job row lock first, or
  they can deadlock; a partial index on `state = 'waiting'` can't serve `state IN (…)` → *v56*
- A persistent Redis (`appendonly`) keeps "last seen" timestamps across downtime; treat a
  pre-boot value as "since boot" or every restart looks like an outage → *v36*
- Celery's own "Task ... received/succeeded" log lines echo task *args*: anything secret-shaped
  passed to `.delay()`/`apply_async` must be redacted before enqueue, not only where it's used
  → *v36*
- A thread started in a prefork worker's main process (e.g. from `worker_ready`) lives through
  every later child fork (`worker_max_tasks_per_child`); run long-lived side loops as their own
  process (`python -m ...`), not a thread there and not multiprocessing `spawn` (its child
  resolved `app` from site-packages instead of the dev bind mount) → *v36*
- Every `track_attempts` row goes through `attempts.record_attempt`: it assigns `attempt_number`
  and maintains `tracks.attempts_made`/`failure_count`. `tracks.attempt_count` is still the
  ladder's failure count, not "attempts" → *v35*
- A redelivered `download_track` for a `completed`/`skipped_duplicate` track is a no-op → *v35*
- `expand_job`/`sort_library` run for minutes (a discography is ~90–130s of Spotify round trips);
  on `worker-meta`'s shared 2-slot `meta` queue two of them starved beat's 30s dispatch. They
  have their own `expand` queue and `worker-expand` service since v34.1 → *v34.1*
- Celery's Redis `visibility_timeout` must exceed the longest task: with `acks_late` a task still
  running when it expires is redelivered and runs *concurrently* a second time (6h since v34.1)
  → *v34.1*
- `record_failure` computes the ladder delay **before** incrementing `attempt_count`; reversing it
  skips the first rung → *v06*
- Only real `AudioProviderError`s feed the circuit breaker; the "other" bucket shares the ladder but
  never trips it → *v06*. *(2026-10-13: stale since v23. `no_output` feeds it too; terminal
  verdicts and proxy transport failures never do, see v40.1.)*
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
- A manual retry endpoint that revives a terminal track state must itself gate on the parent job's
  `archived_at` — nothing else can, since the archivable lifecycles by construction exclude a
  `waiting` track, making the retry endpoint the *only* path back into a state `dispatch_due_tracks`
  would act on → *v20*
- `download_track` only gates on `CANCELLED` — a redelivered message for an already-`COMPLETED`
  track can regress it to `SKIPPED_DUPLICATE` (found, documented, not fixed) → *v15*
- Verifying a new hourly (or longer) `beat_schedule` entry actually fires doesn't require waiting
  out the real interval — temporarily edit the schedule literal to a few seconds, `docker compose
  restart beat`, confirm `Scheduler: Sending due task ...` in real container logs, then revert the
  literal and restart again before committing → *v19*
- Celery workers do **not** hot-reload on code changes the way `uvicorn --reload` does — a
  long-running `worker-dl`/`worker-meta` process keeps executing whatever Python it imported at
  boot even though the dev bind-mount already has newer source on disk. Concretely bit this
  session: a worker process started *before* a new `TrackErrorType` enum member (`NO_OUTPUT`) was
  added crash-looped with `LookupError("'no_output' is not among the defined enum values...")`
  every time it tried to read back a row a *different*, already-restarted process had written with
  the new value — the row was correct, the stale process's loaded enum class wasn't. Any session
  that edits `app/models/*.py`, `app/services/*.py`, or `app/tasks/*.py` mid-session must
  `docker compose restart api worker-dl worker-meta beat` before trusting further real-stack
  verification, not just re-run the script → *v23*. **Fixed 2026-10-24 (v52)** for the three
  workers: `scripts/dev/reload.py` restarts them on a backend edit in dev; `beat` still needs a
  restart
- A Docker daemon restart (e.g. to change `/etc/docker/daemon.json`) can leave a Celery worker's
  broker connection stale even though the container itself reports `healthy` and `celery inspect
  active`/`reserved` show it idle rather than stuck — `dispatch_due_tracks` kept "succeeding" every
  30s without actually dispatching anything for several minutes until `worker-meta`/`beat` were
  explicitly restarted. Confirm real progress via the Redis queue length (`LLEN downloads`) and the
  worker's own log timestamps, not just container health/`inspect active` → *v23*
- A per-attempt history row's ordinal can't both literally mirror `tracks.attempt_count` *and* be
  unique per real invocation once a path exists that must log a row without consuming a real ladder
  rung (the breaker-requeue early return) — no value of `attempt_count` satisfies both, so a
  breaker-requeue row and the real attempt that follows it end up sharing a number. Left as-is
  (harmless: ordering uses `started_at`, not rendered as a label) → *v24*
- The stale-track reclaim sweep (`beat._reclaim_stale_tracks`) bypasses `download_track` entirely by
  design, so a real worker crash mid-download leaves no per-attempt history row at all — a real,
  reachable diagnostic gap, out of v24's scope (which named `download_track`'s own six exit paths,
  not `beat.py`) → *v24*. **Fixed, v31**: the sweep now snapshots each stale track's
  `attempt_count`/`updated_at` *before* its bulk `UPDATE` (reading them back via that same
  `RETURNING` would already show post-update values — see this file's own v31 section) and records
  a `FAILED` `track_attempts` row on the abandoned invocation's behalf.
- A `FAILED`/`COMPLETED`-only "already exists" check that's deliberately content-blind (folder +
  filename match, never a checksum) will just as happily adopt a *corrupt* file left at that exact
  path as it would a genuinely-complete one — a disk-full or other I/O failure mid-`copy_verify`
  leaves a bad partial file sitting at the real destination name, and the next sweep run treats it
  as "already there," quarantining or deleting the actually-good source over it. Fixed by having
  `copy_verify` rename (never delete) its own failed copy off the exact destination filename on a
  checksum mismatch, freeing that name for a real retry → *v31*. *(2026-10-26, v57: only a
  mismatch was covered. A copy that fails outright (ENOSPC) raised with the partial file still at
  the destination; `copy_verify` now renames that one off too.)*
- A per-row loop that mutates the filesystem (delete/quarantine a source file) and the DB row for it
  must commit the DB change *before* the filesystem mutation, not after — committing after leaves a
  crash-window where the file's real location and the DB's belief about it disagree, and nothing
  downstream (a reconciliation sweep, a retry) can tell "moved but not yet recorded" apart from
  "genuinely missing" → *v28*
- A singleton run/status row toggled by an HTTP endpoint (e.g. "start this background sweep, 409 if
  already running") needs a real `SELECT ... FOR UPDATE` on the read-then-write, or two concurrent
  requests both observe the pre-toggle state and both proceed → *v28*
- Any task loop with its own per-item try/except still needs a second, outer try/except around
  everything *outside* that loop (setup, a final cross-cutting step) — an uncaught exception there
  has nothing to reset a "this is running" flag back down, permanently wedging it → *v28*
- A context manager that monkeypatches process-global state (e.g. `socket.getaddrinfo`) is safe only
  because `worker-dl` runs `--concurrency=1` — restore from a value snapshotted locally at entry,
  never from a mutable module-level name, or a test/attempt that rebinds that name leaks its
  replacement into the restored global process-wide → *v29*
- `reconcile_disk()`'s "mount looks missing" guard protects against an unmounted/empty root, not
  against a root that's mounted and non-empty but is a *different environment's* files — confirmed
  live: local dev's `worker-meta` boot pruned a real ledger row because the shared dev/prod database
  pointed at a completed download that only exists on the deployed instance's own, separate
  downloads volume. The dev/prod DB split this file's "Development environments" section already
  names as a deferred TODO is the actual fix; until then, avoid restarting local `worker-meta`
  (or anything that re-triggers `RUN_DISK_RECONCILE`) more than necessary → *v31*
  *(Corrected 2026-10-01, v32: the split is done. Local dev now runs on its own `spotdlwebtest`
  database behind a fail-closed `SPOTDL_ENV=dev` guard, so restarting local `worker-meta` is safe
  again. It reconciles the dev ledger only.)*
- Every process that runs the dedup gate must mount every root the ledger can point into. A root
  it can't see reads as "file gone", which means a re-download; `worker-dl` lacked the library
  until v38. `is_already_downloaded` now raises `LedgerRootUnavailable` for a missing file under
  a root that looks unmounted, and `download_track` holds the track instead → *v38*
- A re-download over a moved track leaves `in_library = true` on a ledger row whose `file_path`
  is back under `/downloads` (`db.merge` never touches `in_library`): that pair is the SQL
  signature of the damage (`scripts/moved_file_redownloads.sql`) → *v38*
- A running container keeps the environment it was **created** with. Editing `.env` changes
  nothing until the container is recreated (`docker compose up -d`, not `restart`), so "the `.env`
  points at dev" isn't proof the running stack does. Check `docker compose exec <svc> printenv` →
  *v32*
- `uvicorn --reload`'s supervisor never imports the app, so when its child dies on a config error
  the container stays up instead of exiting. The dev `api` command pre-validates settings before
  `exec uvicorn` → *v32*
- Every writer of `breaker_tripped_until` goes through `retry.record_breaker_release`; a direct
  write loses `breaker_events` history rows → *v44*

- Two ledger rows (two Spotify ids) can share one downloaded file; a sweep must file the second
  row to wherever it filed the first, or it's stranded as "source file missing" and pruned into
  a re-download. Rows stranded before v48 (production had 47) are relinked once, by data
  migration `cab1bff456eb` → *v48*
- `db.merge` copies only the attributes you pass: the download ledger upsert left `in_library`
  as it was, so a re-downloaded lost library file was never swept again (set it explicitly) → *v48*
- A Postgres native-enum column won't compare with a bound string parameter (`operator does not
  exist`); a portable migration casts it (`sa.cast(col, sa.String)`), and SQLite tests never
  notice → *v48*
- `reconcile_disk()` skips `/downloads` rows only while `/downloads` is empty, which an emptying
  sweep makes it; the first boot after a new download prunes every row whose file is gone → *v48*
  *(2026-10-26, v57: replaced by the `.spotdl-volume` mount sentinel; see the v57 entries.)*
- A root is "mounted" only while its `.spotdl-volume` sentinel is there. The app creates it only
  where it can tell (no ledger row under the root, or at least one of their files present); a
  mounted root whose every ledger file is really gone needs it created by hand → *v57*
- The library sweep and worker-dl's ledger upsert serialize per file on a Postgres advisory lock
  (`dedup.file_lock` / `record_download`); the sweep's lock needs its own connection, since its
  session commits the repoint before it deletes the source → *v57*
- Known library roots only grow (`app_settings.library_known_roots`): dedup, reconcile and file
  serving cover every root the install has used, and nginx's `/internal-library/` still aliases
  only `/mnt/raid1/media/music` → *v57*
- The quarantine dir must be a folder inside the downloads dir (owner decision, 2026-10-27);
  anywhere else is a container's own layer, emptied by a recreate → *v57*
- CI runs pytest on the production host, where `/mnt/raid1/media/music` is the real library: a
  test reaching `reconcile_disk` must keep every managed root under `tmp_path` → *v57*
- `graphify update` drops `graphify-out/graph.html` past 5000 nodes; run it with
  `GRAPHIFY_VIZ_NODE_LIMIT=10000` → *v55*
- Priority and bump are admin-only on the server since v48 (403 before the job lookup, the same
  for any id), not only hidden in the UI → *v48* *(2026-10-26, v56: now 404, the A6 rule below.)*
- A library sweep archives only the sweeping admin's own settled jobs; every user's moved
  tracks are still repointed (owner decision, F34) → *v48*
- A real production breaker trip (2026-10-18 18:46 UTC) reached `breaker_events` but never the
  Matrix room; unexplained, and its logs were gone by the next deploy → *v48* *(2026-10-28,
  v59: every candidate loss path reproduced on the slot stack, and the alert outbox closes all of
  them; see v59.)*

- `download_track` owns a track only while it is still in the state it found on entry and no
  attempt row has been recorded since (its entry token); every write to the track before the
  download (claim, hold, dedup resolution) is conditional on that, and the outcome is written
  under the row lock → *v55*
- A reclaim of a still-running download is superseded by that download's real outcome (one row,
  one counted attempt); the reclaim's reset and its rows commit together → *v55*
- Postgres `now()` is the *transaction's* start: an ORM read after a commit opens a transaction
  that idles across whatever follows (the whole download, before v55), and an `onupdate=now()`
  column then records that start. Set the time explicitly where it must be the write's → *v55*
- spotdl's "file already exists" skip returns the path exactly like a download; only the
  tracker's `notify_download_skip` tells them apart → *v55*
- Consecutive identical `held` rows collapse into one (`hold_count`), but one breaker trip holds
  each track only once: it's repeated trips, a pause or an unmounted root that repeat a track's
  hold → *v55*
- The forced-IPv6 rung is skipped where `network_path.ipv6_routable()` (a cached UDP route
  probe) says IPv6 can't work; dev and production networks have IPv6, so it's still used there →
  *v55*

**Live progress & SSE**
- `view=others` drops the admin's own channel on the server, so the page never hears the admin's
  own downloads there: their amber needs a separate own-download check; a dropped run of own
  messages must still heartbeat on schedule (the tunnel's idle timeout) → *v54*
- SSE payloads name no owner (v17), so in `view=all` the page can't tell whose a new lane is: one
  throttled bulk lookup (the view's `downloading` listing, owners embedded) places lanes → *v54*
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
- A client action that both (a) gets its own effect from a direct REST response and (b) is also
  published as an SSE event to that same acting session's own channel will see both, in
  non-deterministic order, and a bulk action over many ids makes this worse, not just duplicated —
  individual per-id echoes can race ahead of and resolve *before* the bulk HTTP response that
  triggered them. **Don't try to deduplicate the two signals through one shared function** (five
  fixes across six review rounds, each patching one race and opening another, before this was
  learned the hard way) — they carry genuinely different trust levels (the direct response has the
  complete, authoritative id list; a lone echoed id never does) and belong in two separate handlers:
  one, called only from the direct-response path, that's never invoked twice and can safely make
  decisions requiring the full picture; another, called only from the SSE path, built to be
  idempotent *by construction* (act only if current state doesn't already match the event) rather
  than deduplicated against a shared claim/counter → *v20*
- A store function that decides "reload the whole list" based on a per-event heuristic needs the
  same debounce treatment as a high-frequency per-item event stream, even if each individual trigger
  seems rare — a bulk backend action that publishes one event per affected row turns "rare" into "up
  to N times in one click" → *v20*
- The Waterfall's "appear/disappear/reappear" glitch (queue.ts's `liveActive`) is its own
  add-on-`downloading`/remove-on-anything-else rule colliding with a fast failure-then-retry loop —
  raw `curl -N` capture of a real repeatedly-failing track showed `downloading` → `waiting` landing
  under a second apart, then the identical cycle repeating every ~30s (beat's own dispatch-tick
  interval). The fix debounces the *removal*, not the add: a track leaving `downloading` stays in
  `liveActive` (updated in place) for a grace window and only actually drops out if no further
  `downloading` event arrives before the timer fires. The window has to be tuned against beat's own
  30s tick latency, not just the ladder delay — a first cut at 4s (plausible-looking, matches
  `scheduleJobRefresh`'s 400ms debounce in spirit) was proven too short by a live browser
  measurement; 60s (covering beat's worst-case ~30s dispatch latency after a track becomes due, plus
  jitter) is what actually bridged every observed cycle. This is a trivial fraction of the real
  retry ladder's 15-minute floor either way, so it doesn't misrepresent a genuine multi-minute wait
  as "still active" → *v23* *(Corrected 2026-10-14, v40.2: the window applied to `lookup_failed`
  too, which nothing automatic ever re-dispatches, so a "Not found" lane sat frozen at its last
  percentage for up to a minute after its job already read settled. It now ends at once; only
  `waiting` keeps the window.)*
- A `StreamingResponse` route's `Depends(...)` dependency chain isn't torn down until the whole
  streamed body finishes, not when the route function returns — a `yield`-based dependency
  (`get_db`) used there holds its DB session (and whatever transaction its last query left open)
  for the entire life of the connection, hours for an SSE tab left open. Confirmed live via
  `pg_stat_activity` (a `SELECT ... FROM users` sitting `idle in transaction` for the whole time a
  test SSE connection stayed open, clearing the instant it disconnected). Fix: don't route a
  long-lived response's auth check through a `Depends(get_db)`-shaped dependency at all — resolve
  and close its own session immediately, driving `get_db` (or its test override) by hand instead of
  through `Depends` → *v31*
- `queue.ts`'s `liveActive`/`incoming` were SSE-only until v34, so a hard reload or stream
  reconnect emptied the Waterfall and the incoming list until the next event (forever, for a
  failed zero-track job). Both now re-hydrate from REST on every `reload()`; an SSE event stamped
  after a hydration started beats its snapshot → *v34*
- A page used to `reload()` on mount *and* on the stream's `onopen` (two requests per store, the
  first always superseded). Since v34.2 `onopen` is the only resync, with a one-shot REST
  fallback if the stream fails before it ever opens → *v34.2*
- Job listings read count, per-status counts and page from separate statements; under READ
  COMMITTED they disagreed ("9 items of 8") when a job committed mid-listing. They use one
  REPEATABLE READ snapshot since v34.2 (`db.begin_snapshot`) → *v34.2*
- The jobs scope's state chips are patched locally, not re-read, so every path that replaces or
  removes a job row must move its count too. A row refreshed after a track event used to swap the
  row only, so a settled job stayed counted as "active" until a hard reload → *v40.2*
  *(2026-10-28, v62: a job off the loaded page moves too, from the server's `job.status` event.)*
- A job's rollup status moves without any `job.state` event (a track settling); `job.status`
  (old → new) is published by `job_status.publish_change` after the commit, chained through Redis
  `SET … GET`, once per job for bulk changes → *v62*
- The SSE heartbeat is a named event since v62 (`event: heartbeat`), not only a comment: an event
  with no `data:` line is never dispatched, and patching `time.monotonic` in a stream test also
  drives asyncio's own clock → *v62*
- A downloading run is identified by its claim's `updated_at` (`clock_timestamp()`, not `now()`,
  which is fixed for a whole transaction and so for a whole rollback-isolated test) → *v62*
- Vite's dev `/api` proxy never closes the browser's SSE response when `api` dies, so in the
  normal `docker compose up` loop an `api` restart never triggers a reconnect at all (production
  nginx does close it). Test reconnect behavior through the real `web` image → *v34* (fixed
  2026-10-02 in v34.2: `vite.config.ts`'s proxy now destroys the client response when the
  upstream one closes incomplete)

**Proxies & secrets**
- `redact_text` lives in the stdlib-only `app/services/redaction.py` (re-exported as
  `proxies.redact_text`); importing `proxies` pulls in spotdl (~150 MB resident) → *v36*
- The Matrix alert token is a `SecretStr`, read only by `alerts.py` into the Authorization header;
  the settings API exposes only `configured` → *v36*
- Any proxy URL that is logged or persisted must go through `proxies.redact()`; spotdl's own error
  messages echo credentials → *v07*
- `JsonFormatter` adds an independent regex redaction pass as a safety net, not a replacement for
  the call-site fix → *v12*
- `sync_from_file()` deliberately does not hard-validate proxy format; the manual-add UI form does
  → *v07, v13*
- Deleting a proxy is source-conditional: `manual` rows hard-delete, `file` rows soft-disable →
  *v13*
- A provider class's client built once at construction time (`YouTubeMusic.__init__` ->
  `self.client = self._create_client()`) sits on the *cached* `Downloader`/provider instance for
  every subsequent attempt — patching only the construction classmethod misses whatever's already
  sitting on `.client`, since a search that succeeds on its first try never rebuilds it → *v30*
- Reading a `@staticmethod` off its *class* (to save and later restore it) unwraps the descriptor
  down to the plain underlying function — restoring it by assigning that plain function straight
  back leaves a bare function on the class, which is itself a descriptor: the next instance call
  implicitly binds `self` as an unwanted first argument. Re-wrap in `staticmethod(...)` before
  storing it. A real v30 regression (`force_proxy`'s own restore of `YouTubeMusic._create_client`)
  that broke every download in a `worker-dl` process after the first successful proxied attempt,
  found only by an actual real-stack album download, not any unit test (every existing test calls
  the method off the class, which stays callable either way) → *v31*
- The exact-substring credential-redaction guard (`if proxy_url in error_message: ...`, v07)
  only caught a leak that embedded that literal, already-known `proxy_url` string byte-for-byte —
  a re-wrapped or differently-formatted exception could embed the same credentials in a form that
  guard would miss. Replaced with `proxies.redact_text()`: a regex that redacts anything
  *shaped* like a credentialed URL anywhere in a message (requires an actual `user:pass@` to be
  present, so it never touches a message with nothing to redact), applied unconditionally rather
  than gated behind a match against one specific `proxy_url` → *v31*

- `pick_proxy` TCP-probes each candidate before use and cools down the ones that don't accept.
  Production's whole file-sourced pool was dead (`last_success_at` NULL on all 10), and every
  proxy-rung attempt was spent on one. With none reachable, the existing direct-IPv4 fallback
  applies → *v40.1*
- A terminal verdict reached through a proxy (no match, age gate) proves the proxy carried the
  request, so it's the proxy's success, not a failure to cool it down for → *v40.1*
- `proxies.redact()` of a credential-less proxy is its full URL; the stats labels are `host:port`
  → *v44*
- One connection target, one credential: a second row for a `host:port` is refused (409) by the
  API and skipped by `sync_from_file()`; a changed credential in `proxies.txt` rotates the row in
  place → *v44*

**File serving & HTTP headers**
- A FastAPI `@router.get` does **not** answer `HEAD` (405); the file endpoint lists both. nginx
  follows `X-Accel-Redirect` for `HEAD` too, so the probe catches a file deleted from disk → *v35*
- A response header built from DB-sourced/app-generated-but-not-actually-trusted text (here:
  `Content-Disposition`'s ASCII fallback filename, built from `Track.output_path`/the ledger's
  `file_path`) needs every non-printable byte stripped, not just non-ASCII ones —
  `str.encode("ascii", "ignore")` passes a literal CR/LF straight through, and a real ASGI server
  (confirmed against live uvicorn, not just the `TestClient`) rejects a header value containing
  one outright, crashing the response instead of the intended clean 404/200. The RFC 5987
  `filename*` form needs no equivalent guard — `urllib.parse.quote(..., safe="")` already
  percent-encodes those bytes → *v27*
- nginx's `X-Accel-Redirect` internal-redirect response keeps the *original* response's other
  headers (e.g. `Content-Disposition`) even though the served bytes/`Content-Type`/`Content-Length`
  come fresh from the internal location's own file lookup — confirmed live: the app never sets
  `Content-Type` at all, and nginx fills in `audio/mpeg` from its own `mime.types` purely off the
  file extension → *v27*
- A file-serving endpoint backed by more than one possible storage root (here: the original
  downloads volume, plus v28's new sorted-library location) needs the path-traversal/authorization
  check run against *each* root, picking whichever one the resolved path actually falls under —
  and every place that stands in for the real reverse proxy (nginx's own `internal` locations, plus
  the dev-only Vite fallback middleware that impersonates it locally) needs the second root added
  too, or a moved file silently 404s in exactly one of those environments while working in the
  others → *v28*
- Since v64 `api` mounts the downloads and library volumes **read-only** (base, dev override and
  prod overlay): the job zip is streamed by `api` itself, not nginx. Single-track downloads still
  go through `X-Accel-Redirect`, and their path check stays lexical (`follow_symlinks=False`):
  with the mounts, `.resolve()` would now follow a real symlink and refuse one nginx used to
  serve (review round 2). The zip is STORED with `Content-Length` known up front; nginx's
  `/api/` already had `proxy_buffering off`, so no location was added → *v64*
- An endpoint that streams for hours ends its transaction with `db.commit()` before returning the
  response (the connection goes back to the pool); `db.close()` on the request's session detaches
  every object the test's shared `db_session` holds → *v64*

**Frontend (SvelteKit)**
- SvelteKit's `replaceState` leaves `page.url` at the last navigation and records that stale URL
  in the history entry, so a later Back navigates to it: read a query-string state from `location`
  → *v54*
- A Back/Forward between two entries of the same route reuses the mounted page (no remount), and
  `navigating` is still set inside `afterNavigate`: adopt the popped entry's state there, never
  write the page's own over it → *v54*
- `svelte/no-navigation-without-resolve` rejects `replaceState(resolve('/') + '?view=…')`, any
  form: the query-string write carries a reasoned `eslint-disable-next-line` → *v54*
- Job create's `already_queued` hint returns the existing job with 200: don't add it to the store
  again; Spotify links are stored canonical → *v53*
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
- `flex-wrap: wrap` on a flex container that also switches to `flex-direction: column` at a mobile
  breakpoint defeats `align-items: stretch` for its children — a multi-line-capable container sizes
  each line's cross axis (width, once direction is column) to that line's own content instead of the
  full container width, so a child holding unbreakable content (e.g. a title-less job's raw
  `source_url` fallback, a long unbroken string) gets measured at its full natural width instead of
  the intended stretched width, overflowing the viewport even though the child itself already has
  `min-width: 0`/`overflow: hidden`/`text-overflow: ellipsis`. The mobile media query must explicitly
  set `flex-wrap: nowrap` to override the base (desktop) rule, not just `flex-direction: column` —
  caught by a real 390px screenshot overflowing horizontally, invisible to `svelte-check`/`eslint`
  since it's pure runtime layout → *v20*
- A store function that clears/removes an entry another async fetch might still resolve into (e.g.
  collapsing an expanded row, or a scope switch clearing the whole map) must bump that fetch's own
  sequence guard at the point of removal, not only at the point the next fetch *starts* — otherwise a
  slow response for an already-closed/cleared entry lands after the fact and silently recreates it,
  since its sequence number still matches whatever was current when it was issued → *v20*
- A module-level store survives a client-side `goto()` navigation — it must be explicitly reset on
  logout, or an unconditionally-rendered overlay (`IncomingJobs`/`Waterfall`, no `loading` gate)
  leaks the previous user's data into the next same-tab identity → *v22*
- The explicit "disconnect" button isn't the only door to `/login` — a session-check `load()` that
  redirects on 401 is a second, independent trigger for the same store-reset requirement above,
  reached by session expiry/revocation rather than a click → *v22*
- A `job.state` SSE event fires for the `expanding` state itself, not only for later transitions —
  a naive "insert this row into the page if it's missing" fix must not do so while `expanding`
  (still-`source_url`-titled) or `failed` (permanently zero-track), or the row gets sorted by a
  throwaway value it can never correct later, since an already-present row is only ever patched in
  place, never re-sorted → *v23.1*
- A `fetch()` response whose success is defined by a *header* (here: `X-Accel-Redirect`, meaningful
  only to a real nginx sitting in front of the app) rather than by its body reads as fully
  successful (`response.ok`, a parseable `Content-Disposition`) even when fronted by something
  that doesn't understand that header at all (Vite's dev proxy just forwards the empty body
  through) — the resulting 0-byte blob triggers a real, correctly-named browser "Save As" with no
  error anywhere. Caught by fresh-eyes review, not by testing against the one stack (real nginx)
  that's actually wired for it; fixed same session with a client-side `blob.size === 0` guard as a
  backstop, kept in place → *v27*. **Same day, caught again by the project owner's own live
  testing** (a documented, "accepted" gap can still surprise a real user in daily use, even with a
  clean error message): the actual fix that shipped is `vite.config.ts`'s
  `devFileDownloadFallback` plugin, a dev-only middleware that intercepts exactly this one route,
  makes its own request to `api`, and — if the response carries `X-Accel-Redirect` — serves the
  real file itself from disk instead of forwarding the empty body. Needed `docker-compose.override.yml`'s
  `web` volumes fixed too: it had been merging in the *base file's* `downloads:/downloads:ro`
  (a separate, always-empty, Docker-managed named volume) instead of `!override`-ing to the real
  `./downloads` host bind worker-dl/worker-meta actually write into, so the plugin would otherwise
  have 404'd against an empty mount even once it existed.
- A selector on a class added via `classList.toggle` is pruned by Svelte (`css_unused_selector`); bind
  the class with a `class:` directive on `$state` → *v40*
- `queue.activeTracks` is only current on `/`: leaving the dashboard closes the SSE stream but
  leaves `liveActive` at its last value, so anything reading it on another route must gate on
  `page.route.id === '/'` → *v40*

- An expanded row's lazily-fetched attempt history cached on the track id alone kept a row
  opened mid-download at "no attempts yet" after the worker wrote one; key the cache on the
  track's settled state, counts and `scheduled_at` → *v41*
- Svelte drops the whitespace at an `{#if}` boundary, so `label{#if …} <span>40%` renders (and
  names the button) "label40%"; eslint rejects `{' '}`, so put `&nbsp;` inside the span → *v41*
- `/`'s `<header>` sat inside `<main>`, so the page had no banner landmark; landmarks only count
  outside `main`. The worker-status poll lived in the pill, so gating the pill to the admin would
  have silently frozen the store TrackRow and the Waterfall read; the poll is now the page's → *v42*
- Raising `--text-dim` to WCAG's floor lands it next to `--text-muted`; don't move `--text-muted`
  to restore the gap, since `AmbientField.svelte`'s slate glow is calibrated against it → *v42*
- Following one field of a store with a writable `$derived` resets on *every* store emission; chain
  it through an intermediate derived of that field (`storeQ`), which only notifies on a new value
  → *v42*
- `data-sveltekit-preload-data="hover"` re-runs the root layout `load` on every hover, with `/`
  still mounted; anything that `load` does to the module store (a reset) happens under the live
  page. Reset only on a real 401 or an identity change, never on a network blip → *v42*
- The session cookie is shared across tabs: an identity switch in tab 2 reaches tab 1's next
  request and stream reconnect. Guard late async writes with `queue.getResetCount()`, and check
  `/api/auth/me` against the page's identity on every stream (re)connect → *v42*
- One confirmation for every destructive action: a native modal `<dialog>` driven by
  `confirmAction()`. Focus goes back to the trigger *before* the caller's action resumes, and a
  navigation answers "no", so a question never survives onto the next page → *v43*
- An `h1` placed between a page's `<header>` and its `<main>` is outside every landmark (axe
  `region`); a secondary page's `h1` opens its `main` → *v43*
- A long-running Vite dev server stopped opening the confirmation dialog (restart `web`); a new
  route leaves root-owned `.svelte-kit/types` (chown it in the container) → *v44*. **Corrected
  2026-10-24 (v52):** the dev `web` runs as uid 1000 with its own `.svelte-kit` volume, so no
  root-owned files; the dialog failure didn't reproduce (see v52)
- `/stats` windows are whole buckets ending with the current partial one: "Last 7 days" at 00:05
  is 6 days and 5 minutes, not 168 hours → *v44*
- Enter/Space on a button also fire `click` (`detail` 0): a "last clicked control" heuristic must
  ignore them, or a fast keyboard user's next dialog returns focus to the wrong control → *v45*
- An `{@attach}` on a list can run before its `{#each}` rows exist; anything it does to the rows
  (focus restore) must retry on the next mutation → *v45*
- The queue store patches a row that stops matching the filter in place, never drops it; only
  archive (archived hidden) removes a row from the list → *v45*
- Messages re-render on a language switch only where they're called at render time; one built at
  module scope, in a plain `const` or as a prop default freezes in its first language → *v46*
- Width breakpoints are `em`, so a larger browser text size moves the layout; `px` ones kept the
  desktop grid at 200% text and squeezed titles to 0px. Test with CDP `Page.setFontSizes` → *v47*
- An open `EventSource` can outlive the network silently; `/` watches `offline` and unreached polls
  (the SSE comment heartbeat is invisible to JS) → *v47* *(2026-10-28, v62: the heartbeat is an
  event now, so a stream silent past it restarts on a return to the tab or `online`.)*
- A page's `beforeNavigate` runs before the layout's `ConfirmDialog` one, which answers every open
  question "no" on a navigation, the cancelled one included: open a guard's question after the
  callbacks (a microtask). Back across two hard loads is a document unload (`beforeunload`), not
  a popstate → *v62*
- adapter-static's `fallback: '404.html'` plus nginx `error_page 404 /404.html` (in `location /`
  only, so a missing `/_app/` chunk keeps a plain 404) is what renders `+error.svelte` for an
  unknown path → *v62*
- `lastKnownTrackState` survives `queue.reset()`, so a store test reusing a track id and state
  sees no state change (no refresh): give each test its own ids → *v62*
- The session-ended handler navigates to `/login` before `queue.reset()`, or `/`'s outlived-check
  reloads the tab first → *v47*
- An empty live region in a flex column still takes a gap; take it out of the flow with
  `position: absolute`, never `display: none` → *v47*
- `content-visibility: auto` on rows clips focus rings and popups (paint containment) → *v47*
- A Playwright full-page screenshot drops touch emulation; measure 44px targets first → *v47*
- The inlang SDK "successfully" compiles zero messages when its plugin fails to load; the plugin
  comes from `node_modules` (never the CDN default) and `check-messages.mjs` counts the output → *v46*
- Hungarian: a count is a plural message, never `${n} noun`; an inflected noun means one message per
  noun; `Countdown` labels stand before the time → *v46*
- Formats = UI language + browser region (`en-HU`); plural messages take a pre-formatted `n`
  (Paraglide's `number` ignores the region) → *v46*

- A ≤640px column stack inherits flex-basis values meant for the row layout (the toggle's
  `16rem`, the bar's `100%`), which made every job row ~4× taller and hid its bar → *v39.1*
  (recorded in the v39 section; v39.1 has no section of its own)
- A host-side `svelte-kit sync` (`npm run check`/`build`) rewrites `.svelte-kit/generated` and Vite
  reloads every open page; the dev `web` has its own `.svelte-kit` volume since v52 → *v52*
- Removing a directory on the host detaches a container's volume mounted there (Paraglide's
  `cleanOutdir` did, on every host check): compile in place → *v52*
- Disabling a focused control drops its focus only on the browser's next frame, so a focus
  check right after an await can still see it focused: move focus before disabling (the
  library sweep's start) → *v52*

**Browser extension (`extension/`)**
- Spotify's DOM: rows `tracklist-row`, headers `action-bar-row` inside `album-page`/`artist-page`/
  `playlist-page`, cards `data-encore-id="card"` by their `cardTitle` link only (a music video's
  title is no link, and its subtitle names the artist), search's `top-result-card` by its first
  link; search rows lack `internal-track-link` → *v58*
- Spotify's cookie banner sits near the top `z-index`: the extension's menu and toast use the
  maximum, or the banner swallows clicks on them → *v58*
- The icon stops only the keys it acts on (Spotify's tracklist grid navigates with arrows
  through it); a click counts only when the last trusted press (pointerdown or mousedown)
  landed inside that icon or menu entry (a page's invisible `<label for>` forwards real clicks)
  → *v58*
- A fresh install's options page tests the default origin (production) on open; every
  extension request goes to the configured origin only (captured by principal) → *v58*
- `web-ext lint` refuses `update_url` (an error, "not allowed for Mozilla-hosted add-ons") unless
  run with `--self-hosted`, which an unlisted add-on is → *v61*
- AMO never takes the same version twice, even after a failure later in the job: a re-run must
  fetch the already-signed file (web-ext's exported `util/submit-addon` client), not sign again
  → *v61*
- AMO re-serializes `manifest.json` when it signs (tabs became 2-space indentation): compare it
  with the source as parsed JSON, never byte for byte, or every fetched file reads as other
  content → *v61.1*

**Testing & verification technique**
- A `docker exec … python /tmp/x.py` imports the image's site-packages `app`, not the mounted
  `/app/app`: set `PYTHONPATH=/app` → *v56*
- `download_track.delay` is one object for expand and beat: a monkeypatch of one patches both → *v56*
- `docker pause` on Redis fails no publish (the kernel buffers it); `docker stop` refuses → *v56*
- Playwright's `page.clock.install({ time })` skews the browser clock for countdown checks → *v56*
- A rebase that re-parents a migration under one a slot already passed: alembic sees the head as
  applied and skips the new parent; downgrade to it, stamp the old parent, upgrade → *v56*
- Driving `web-ext run`'s Firefox: BiDi and Marionette both refuse `moz-extension://` navigation
  (load it from the chrome context with `--remote-allow-system-access`), the temporary add-on's
  UUID can't be pinned by pref, content-script-made nodes are stale WebDriver references (click
  by coordinates), and `browser.i18n` follows the UI locale only with its langpack installed → *v58*
- A real download on a slot can finish in ~10 s, before six browser pages have logged in: hold
  the track `waiting` with `scheduled_at` a minute out, then start `realdl`. A Spotify id whose
  song is already on disk under the same name resolves instantly ("already exists" is the
  filename), check `in_ledger` and the title first → *v54*
- FastAPI's `app.routes` (0.141+) holds lazy `_IncludedRouter` wrappers: walk `original_router.routes`
  to find every `APIRoute` → *v53*
- Playwright's `request.newContext()` inside a test inherits the project's `storageState`; a slot's
  own real-stack evidence jobs skew later e2e picks (delete them first) → *v53*
- e2e names come from the compiled message files (`t()`); a saved language beats the browser
  locale, so setup/teardown clear both identities' language in the DB → *v46*
- The hidden admin 404s carry no error `code`, so they still read like an unknown route → *v46*
- GitGuardian flags a plausible-looking `scheme://user:pass@host` literal in a test and rescans
  every PR commit; assemble credentialed test URLs from parts → *v44*
- The committed browser suite is `frontend/e2e/` (`npm run test:e2e`, local stack only); write
  new browser checks there, by role/label, never in a scratchpad script → *v37*
- Playwright's accessible-name match is a case-insensitive **substring** by default: `'CONNECT'`
  matches "disconnect" and `'archive'` matches "unarchive". Use `exact: true` → *v37*
- A `page.goto()` inside a same-tab identity switch reloads the document and silently wipes the
  very store leak the test is looking for; stay client-side between logout and login → *v37*
- `npx playwright test 07` filters on the **absolute** path, and this checkout lives under
  `vb2007`, so it selects every file; pass `e2e/07-cross-user` instead → *v37*
- A "fresh" test track must be absent from `./downloads`, not just the ledger: spotdl's own
  `file already exists` skip returns a path, and the app records a `completed direct-ipv4` attempt
  that never touched the network → *v35*
- Forcing a real download failure: a compose overlay with `extra_hosts` mapping the YouTube hosts
  to `127.0.0.1`/`::1` on a recreated `worker-dl` (an in-place `/etc/hosts` edit needs both
  families) → *v35*
- The session cookie is `Secure`, so the browser suite needs a `localhost` origin (Chromium treats
  only that as secure over plain HTTP; `127.0.0.1` drops the cookie). Another dev server bound to
  `[::1]:5173` silently captures `localhost` from Node and the browser → *v38*. **Corrected
  2026-10-24 (v52):** Chromium does keep the `Secure` cookie on `http://127.0.0.1`; Playwright's
  own request contexts don't, so the suite targets `127.0.0.1` and its saved sessions drop the
  flag
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
- CI's backend-tests job deliberately has no ffmpeg (`ci.yml`'s own comment: "every test... mocks
  any real spotdl/network call"), so a unit test needing a real per-format audio container (mp3/
  flac/ogg/opus/m4a) can't generate one at test-run time. Pre-generate tiny (sub-10KB) silent
  fixtures once with `ffmpeg -f lavfi -i anullsrc=... -t 0.2` on a machine that has it, check them
  into `tests/fixtures/`, and have the test copy one into `tmp_path` per run — exercises the real
  mutagen read/write path with zero ffmpeg dependency at test time → *v26*
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
- A "no leak observed" result proves nothing about a sibling store with different render logic —
  one store's synchronous `loading:true` (set before any paint) happened to mask it there, but an
  unconditionally-rendered sibling store leaked in the exact same scenario. Check the actual
  persisted-store inventory, not one representative path → *v22*
- A local dev stack sharing production's real database means local test writes are real production
  writes — confirm the blast radius (a distinct test identity, not the real admin account) before
  running anything destructive-looking, even "just local" verification → *v22*
- Under `set -euo pipefail`, `var="$(failing-pipeline)"` aborts the script at that line even when
  `var` was `local`-declared on a *separate*, prior statement — not only the more commonly-known
  combined `local var=$(...)` form. A deliberate `if [ -z "$var" ]` diagnostic written right after
  such an assignment is dead code unless the assignment itself is guarded with `|| true` → *v22*
- An independent fresh-context review is worth its cost even on a version whose own author already
  ran real verification — it found two real gaps a same-session author was structurally unlikely
  to hit (a second, non-obvious trigger path to the same bug already fixed; a bash pitfall in the
  reviewer's own newly-written script) → *v22*. Reconfirmed on a much smaller patch slice: two
  independent reviewer agents, given only the diff and no implementation context, each
  *independently* found the same real duplicate-row edge case in a "deliberately small" frontend
  fix that had already passed real-browser verification across several scenarios — the author's
  own tests never happened to exercise the specific pagination-boundary/multi-tab conditions that
  triggered it → *v23.1*
- `uv pip compile pyproject.toml -o requirements.txt` treats an **already-existing** output file's
  pinned versions as a preference baseline (kept unless they no longer satisfy `pyproject.toml`'s
  constraints) — matching exactly what a human runs to regenerate the file. Recompiling into a
  *different* path (e.g. a scratch file, to "check without touching the real file") skips that
  baseline entirely and does a from-scratch resolve, which picks up every unrelated transitive
  package's routine upstream patch release since the file was last locked — a real, observed false
  positive on effectively every run, not a hypothetical. Always diff against an in-place recompile
  (`cp requirements.txt requirements.txt.orig && uv pip compile ... -o requirements.txt && diff`),
  never a separate output path, when checking for genuine drift → *v23*
- A `SessionLocal()` opened by an ad-hoc verification script and left uncommitted can sit
  `idle in transaction` in Postgres for hours without anything failing loudly — `pg_stat_activity`
  (state, `xact_start`) and `pg_locks` (joined back to `pg_stat_activity`) are how to find one and
  confirm what tables/rows it actually holds locks on, which is often unrelated to the query text
  currently displayed (that column shows the backend's *last* statement, not its whole history).
  One such leak was found and characterized this session (a `users` lookup pattern matching
  `require_session`'s per-request query, ~2.7 hours old) but not chased to a root cause or fixed —
  flagged here for whichever version next touches session/auth request handling, not silently
  dropped → *v23*
- This local dev machine's public IPv4 was, for the duration of this session, reputation-flagged by
  YouTube (`Sign in to confirm you're not a bot` on essentially every `music.youtube.com`
  extraction) while its IPv6 was completely clean — confirmed via `yt-dlp -4` vs `-6` on the same
  host, same track, repeatedly. Docker's bridge network has no IPv6 route by default
  (`docker network inspect`'s `EnableIPv6: false`), so every container was forced onto the flagged
  IPv4 regardless of anything at the spotdl/yt-dlp level. Enabling it locally for testing needs a
  daemon-level change (`/etc/docker/daemon.json`: `{"ip6tables": true}`, then
  `docker network create --ipv6 --subnet <ULA>/48 <name>` + `docker network connect`) — this is
  local-verification scaffolding only, never committed to any tracked compose file; production's
  own IPv4 was independently confirmed clean by the project owner during this session, so it did
  not need this. Don't assume a "some IPs are permanently blocked" finding generalizes across
  physically different hosts/ISP connections without checking each one → *v23*
- A real-browser verification's poll interval can itself hide the bug it's trying to catch: a 2s
  poll against a fast-transitioning row missed an intermediate wrong-position state entirely and
  read as a clean pass; re-running the identical scenario at 300-500ms surfaced it immediately.
  When a fix touches how a live-updating row is first inserted/positioned, poll fast enough to
  catch its very first paint, not just its eventual settled state → *v23.1*
- A test track directly inserted with a real, non-terminal `state` (`QUEUED`/`WAITING`) sits
  live in the shared dev/prod DB the moment it's committed — the real `beat` container (dev's
  `STALE_TRACK_AFTER_SECONDS`/`LADDER_SECONDS` are both shortened for exactly this kind of testing)
  can reclaim or dispatch it **while an ad-hoc script's own sleep is deliberately parking it there
  between two direct, in-process `download_track()` calls**, causing a second, genuinely unmocked
  execution against the same row from the real `worker-dl` process — observed directly (a stray
  `track_attempts` row whose error text was the real, unmocked `NoOutputFileError` message, not one
  of the script's own fake exceptions). Fixed by pushing the track's `scheduled_at` an hour into the
  future immediately after each of the script's own calls, before sleeping, so beat's own
  `scheduled_at <= now()` due-query never matches it during the window. A `db.commit()` right
  before that push (or any other point mid-script) expires every ORM object in the session
  (`expire_on_commit=True` default) — capture any value needed for a later calculation (e.g. the
  real ladder delay) into a plain variable *before* that commit, not after → *v24*
- This dev stack's `proxies` table is the **same, real, shared production table** (per this file's
  "Development environments" note) — inserting a fresh test `Proxy` row for verification makes it
  immediately eligible for **real production traffic**: `pick_proxy`'s LRU selection prefers a
  never-used proxy (`last_used_at IS NULL`) over any already-rotating real one, so a genuine
  in-flight real download can pick up a freshly-added throwaway test proxy before the test script
  itself does. Conversely, once a test track's own attempt count is high enough to want a proxy and
  its own test proxy has gone into cooldown (a real, expected consequence of a deliberately-failed
  attempt), `pick_proxy` will genuinely reach past it to a real, already-configured production proxy
  — observed directly: a verification run's final "successful" attempt used a real `source=file`
  proxy from actual `proxies.txt` config, not the test's own, and left a harmless reset
  (`consecutive_failures=0`, `last_success_at=now()`) on it. Don't assume a proxy-escalation test's
  proxy_id assertions can be pinned to "the one proxy I created" past the point it's cooled down →
  *v24*
- A standalone `docker run --network <project>_default ...` container resolves compose service
  names (e.g. `api`) through Docker's embedded DNS exactly like a real compose-managed container
  would, since that resolution is per-network, not per-project — useful for testing a service
  variant (here: a real nginx `web` build, to get around the dev-override-runs-Vite gap above)
  alongside an already-running dev stack without recreating anything the rest of it depends on →
  *v27*
- Playwright's `download.suggestedFilename()` reads the *browser's own* `Content-Disposition`
  parsing — the actual thing the "Done when" bullet asked to verify (a curl-based header check
  proves the header is well-formed, not that a real browser decodes it the same way) → *v27*
- httpx's `TestClient` and a real live uvicorn process don't always agree on what counts as an
  invalid response — a header value containing a raw CR/LF was accepted (if garbled) by the
  `TestClient` in this project's own test suite, but crashed a real running `api` container.
  Confirming a fix for anything touching raw header construction needs at least one curl against
  the actual running container, not just a green pytest run → *v27*
- No tcpdump in this sandbox session; a `socket.socket.connect` monkeypatch recording every real
  `(family, address)` a process actually dials is an equally rigorous, arguably more precise
  substitute for "prove which network path a real connection used" — precise enough that it caught
  a real, years-old bug (the proxy setting never reaching the network at all) that trusting a
  passed-in flag would have missed entirely → *v29*

- Forcing real failures on the dev stack: restart only `worker-dl` with a scratch compose overlay
  setting a dead `HTTP(S)_PROXY` plus a short `LADDER_SECONDS`. The real worker then produces
  real `no_output` failures, real proxy escalation and real breaker trips. The breaker re-trips
  after 5, so one track needs other tracks pushed out to reach 6 attempts → *v39*
- impeccable's `detect.mjs` CLI returns `[]` on this Svelte tree; only the in-browser overlay
  (`live-server.mjs` + injected `detect.js`) finds anything. Run `live-server.mjs` from a scratch
  directory (it writes state into cwd) and stop it with `--keep-inject` → *v39* *(Corrected
  2026-10-14, v41: not always. The CLI on named `.svelte` files did flag a `transition: width`
  in `TrackRow.svelte`'s style block. It reads CSS in Svelte files; what it misses is
  rendered-only rules like contrast.)*
- A `/library` sweep archives every settled job whose tracks it moved, for *every* user, so
  dashboard screenshots or e2e expectations taken after a sweep see fewer rows → *v39*
- Running `npm run test:e2e` cancels and archives every in-flight job of the e2e identities
  (`v37admin`/`v37user`) in global setup. Never build audit or screenshot data on those accounts
  and then run the suite before capturing → *v39*
- "Contrast no worse than before" under a moving glow means the old glow's brightest *visible*
  pixel, not its off-screen centre; measure "before" by rendering the old rule in the same browser
  → *v40*
- Playwright can't produce a hidden tab (`document.hidden` stays `false` through `bringToFront`,
  window minimize, a same-window CDP tab and focus emulation off, headed or not). Launch the cached
  Chromium binary directly and drive it over raw CDP, with a real second tab (`/json/new`) under
  `xvfb-run` → *v40*

- A dead proxy for forcing failures should be a refused port (`127.0.0.1:9`), not a blackhole
  address: each attempt through `10.255.255.1` hangs ~3 minutes on connect timeouts. Once the
  ladder reaches the pool-proxy rung, the dev pool's bot-checked proxies return spotdl's real "No
  results found", so real `lookup_failed` tracks come out of the same run → *v41*
- A DevTools grid overlay (`Overlay.setShowGridOverlays` over CDP) paints only in headed Chromium
  (`xvfb-run`), its colors must be `{r,g,b,a}` objects, and a clipped `page.screenshot` shifts
  it by the clip origin: take the full viewport, then crop → *v41*
- An e2e fixture written straight to the dev DB must date its attempts before the run started,
  or global teardown's zero-download check counts them as network attempts → *v41*
- `/`'s queue error state can't be produced by stopping `api` (`+layout.ts`'s session check
  redirects to `/login` first); answer `GET /api/jobs` with a 500 from Playwright, as v39 did. A real
  breaker trip needs no SQL: the dead-proxy overlay plus one album missing from the ledger trips it
  within about two minutes → *v42*
- impeccable's URL detector can't log in. Inject `detector/detect-antipatterns-browser.js` into an
  authenticated Playwright page and call `impeccableDetectAsync()`; its page-level rules then match
  the injected script's own source (`gradient-text`, `marquee`): false positives → *v42*
- Staging a library re-sweep: the destination keeps the source's *file name*, so a renamed copy
  is filed as a new file next to the original. Copy with the original name to exercise the
  "already there" (quarantine) branch → *v43*
- A ledger track submitted while the worker is paused is dispatched on expansion, and
  `download_track`'s pause gate holds it as `waiting` (a `held` attempt), so wait for `active` *or*
  `waiting`, not `pending`. No network either way → *v43*
- axe reads a dialog's colours mid entry-fade as a contrast failure; read it after the animation
  → *v43*

- Playwright's keyboard is US-only: emulate Hungarian keys over CDP (`huPress`); a real layout
  pass is Xvfb + `setxkbmap hu` + XTest via `uv run --with python-xlib` → *v45*
- Keyboard e2e races: wait for an open job's tracks before `→`, for a reload before `j`, and for
  the URL before reading `h1` after a navigation → *v45*

- `docker compose exec -T` reads the shell's stdin, so inside a `while read` loop it swallows the
  remaining lines; feed the list into one `exec ... sh -c 'while read ...'` instead → *v48*
- A Celery worker keeps the code it started with (no hot reload), so a worker started before an
  edit runs the old code: handy for a real before/after on the same stack, a trap otherwise → *v48*.
  **Corrected 2026-10-24 (v52):** the dev workers now reload on an edit, so that before/after
  needs a prod-like run (`-f docker-compose.yml`)
- v31's open questions closed on dev: a real album's every `COMPLETED` file exists at its
  `output_path`, and four real ladder delays matched `LADDER_SECONDS` exactly → *v48*
- Playwright's request contexts send a `Secure` cookie over plain HTTP only to `localhost`, even
  though Chromium keeps it on `127.0.0.1`: the suite runs on `127.0.0.1` with saved sessions
  stripped of the flag → *v52*
- A wait on the rows (or on "loading" being gone) right after typing a search can pass on the
  list from before the search: wait for the search's own `?q=` answer (spec 14's `typeSearch`)
  → *v52*

- pytest runs on real Postgres: a per-run database (`TEST_DATABASE_URL` names the server and a
  `test`-marked stem), Alembic-built, dropped at the end; `db_session` rolls back, `committed_db`
  truncates → *v51*
- A race test needs `committed_db` and `tests/concurrency.py` (a `Gate` at a named point, a
  `Thread`, `blocked_or_done` reading `pg_stat_activity`'s lock waits); never a sleep, and never
  beside `db_session`/`client` (it calls the endpoint function directly) → *v51*
- Inside `db_session`'s one transaction: `begin_snapshot`'s isolation switch is dropped, `now()`
  is the test's start time throughout, and SAVEPOINTs stand in for commits → *v51*
- The migrations seed `worker_state` id 1: a test inserting it must `merge`, not `add` → *v51*
- `now()` inside `db_session` made two "left `updated_at` alone" tests pass with their guard
  reverted; such a test pins an explicit past value → *v51*
- `db_session` fails a test that opens its own connection (an unpatched `SessionLocal` now
  reaches the real run database); the run refuses a server holding a production database,
  loopback included → *v51*
- Running Alembic from a test with an ini file runs `fileConfig()`, which disables every logger
  the app already made (and every `caplog` assertion with it) → *v51*
- A browser's download progress can't be seen on localhost (1.2 GB lands in seconds) and CDP's
  `Network.emulateNetworkConditions` doesn't throttle downloads: put a rate-limited TCP relay in
  front of the server instead. Playwright saves a download under a GUID, so `chrome://downloads`
  shows that name; the real one is `download.suggestedFilename()` → *v64*

**CI**
- The `pytest` job's Postgres is a service container the runner pulls with the shared
  `~/.docker/config.json`, before any step (a job-private `DOCKER_CONFIG` can't reach it);
  published on `127.0.0.1::5432`, trust auth → *v51*
- The `job` context (a service's mapped port) is unavailable in a job-level `env:`: the file fails
  to parse and GitHub shows a 0-second failed **`push`** run, not a PR check; `actionlint` (in
  Docker, `rhysd/actionlint`) catches it locally → *v51*
- An unquoted colon in a workflow step's `name:` fails the **whole file** at parse time — the run
  vanishes from PR checks rather than showing as failed → *v12*; the same for a `run:` one-liner
  holding `: ` (a 0-second "push" run, then `gh workflow run` answers 422 "does not have
  'workflow_dispatch' trigger") → *v60*
- `docker compose config` needs a real `.env` on disk, separate from `${VAR}` interpolation → *v12*
- `npm run check` runs `svelte-kit sync` first, so `PUBLIC_*` vars must be set job-wide, not per
  step → *v12*
- Extend the existing workflow file; don't add a second one (`docs/CI_SELF_HOSTED_RUNNER.md` said
  so, and v12 ignored it and had to undo it) → *v12*
- A release created with the default `GITHUB_TOKEN` doesn't trigger other workflows (GitHub's own
  loop prevention) — chain via `workflow_run` instead of a downstream `release:`/`push` trigger
  → *v21*. **Corrected 2026-10-23 (v49):** call the next stage as a job of the same run
  (`workflow_call`) instead; `workflow_run` leaves an empty run behind every completion → *v49*
- A `deploy` job polling another workflow's conclusion deadlocks against a single shared
  self-hosted runner — chain from the upstream workflow instead of polling → *v21*
- `workflow_run`'s own `github.sha`/`github.ref` are the default branch's current head, not the
  triggering commit — resolve the real commit explicitly (e.g. from the release tag) → *v21*
  (moot since v49: nothing uses `workflow_run`; the chain passes the commit as an input)
- `repos/.../actions/permissions/workflow`'s `default_workflow_permissions` caps what any
  workflow's own `permissions:` block can grant, independent of that block → *v21*
- `importlib.metadata.version("pkg")` reports the PyPI-normalized version string (`2026.7.4`);
  a package's own `__version__` attribute can use a different, non-normalized format
  (yt-dlp's is `2026.07.04`, zero-padded) — comparing a built image's installed version against
  PyPI's `.../pypi/<pkg>/json` `info.version` needs the former, or every comparison spuriously
  fails → *v23*
- `uv lock --check` asserts `uv.lock` is up to date with `pyproject.toml` without writing —
  the direct CI equivalent of the in-place-recompile-and-diff technique above, for the newer lock
  format → *v23*

- GitHub answering `429` to the runner's action download kills the job at "Set up job", and the
  `notify` job needs the same action, so the failure and its alert vanish together (4.40.2 never
  deployed, and nobody was told) → *v48*; every `notify` is now one `curl` step with no `uses:`
  → *v49*
- **Never chain workflows through `workflow_run`.** It fires on every completion of the named
  workflow (PRs, schedules, dispatches) and the run it starts has to skip itself, and a skipped
  run completes too, so the next link fires as well. Call the stages as jobs of one run
  (`uses:` + `workflow_call`) → *v49*
- A called workflow sees the **caller's** `github` context (`event_name`, `workflow`, `sha`):
  decide its mode from its inputs, never from `github.event_name` → *v49*
- A job-level `timeout-minutes` cut *cancels* the job: a `cancelled()` step starts but is killed
  about 5 minutes later, no step after it runs, and even the job's log is lost. Put
  `timeout-minutes` on the long steps (a timed-out step just fails); `cancel-timeout-minutes`
  isn't a GitHub key → *v60*
- "The job was not acquired by Runner of type self-hosted even after multiple attempts" is
  GitHub's broker losing a job's assignment to the one runner (online, idle host), the first job
  of a run whose jobs queue at once; the job is `cancelled` with no steps and no runner → *v60*
- No `concurrency` group anywhere: even `cancel-in-progress: false` cancels an older *pending*
  run. Deploys are serialized by the single runner, and a stale one is a no-op by version → *v49*
- The one runner takes jobs roughly FIFO across all runs, so each later stage of a merge's run queues
  behind every job started meanwhile; a burst interleaves stage by stage → *v49*
- A workflow listener matches the upstream by the default branch's workflow at that *path*: a
  renamed test copy of `ci.yml` still woke `main`'s Release. Test copies get their own file → *v49*
- `git ls-remote … | grep` under the default `bash -e` (no pipefail) hides a failed remote read;
  read it in an assignment first → *v49*
- A merge's release can find its version already tagged by another run: deploy only when the tag
  points at this run's commit (`owned`) → *v49*
- An unbumped merge deploys nothing now; `gh workflow run "Release & Deploy" -f redeploy=true`
  puts the current release back (after a `manual-*` dispatch, or for a workflow-side fix; the
  health script and compose files still come from the tag) → *v49*
- `workflow_dispatch` only runs a workflow file that exists on the default branch: a new
  workflow is proven before merge by a scratch branch whose own (push-triggered) test file calls
  it with `uses:` → *v61*
- GitHub's `releases/latest/download/…` is the app's newest `v*` release, so the extension's
  `update_url` reads a fixed `extension-updates` prerelease instead; extension releases are
  created `--latest=false` → *v61*
- `gh release view`/`download` exit 1 for both "release not found" and real errors: match the
  message (`release not found`, `no assets match the file pattern`, `no assets to download`) and
  fail on anything else → *v61*

**Performance**
- Never load "everything the queue needs" with a per-job (or per-row) request loop; one bulk
  request, always → *v12*
- Removing the `Session` parameter from a serializer, not just adding a bulk query, is what makes
  the N+1 impossible to silently reintroduce → *v15*
- Filter jobs *before* aggregating their tracks, not after — a search/archived/source_type filter
  that excludes a huge job should never pay to aggregate it → *v18*
- A rAF loop writing `transform` costs a 1-element style recalc + commit per frame, never zero.
  On an idle `/` every main frame also re-samples the Waterfall noise floor's 40 animated bars
  (~80 elements in the trace's style count), so profile a frame loop on `/account` → *v40*
- Retargeting a Web Animation on every pointer move costs more than a rAF loop (~1.5×); the
  glow runs the loop while moving and hands off to a back-dated WAAPI glide once moves stop → *v48*
- A new Web Animation's start time resolves a frame late (`currentTime` 0 meanwhile) and `pause()`
  needs a rendered frame: set `startTime`, and pin a hidden tab's position yourself → *v48*
- Outside a frame Chrome's `document.timeline.currentTime` is a 60Hz-grid estimate; read a
  glide's position at a frame's own timestamp, and probe without a logger rAF → *v48*

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
  specific spotdl exception types would miss cases like this. **Closed, not a bug**: v23's session
  independently hit an unexplained `Error: 'uri'` and flagged it as a loose end; v23.1 traced it
  back to this exact entry — the track ID in question was typed from memory and never verified to
  exist. Known, correct behavior; don't re-investigate it a third time → *v04, v23, v23.1*
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
- **Corrected 2026-09-27 (found in v29's session, fixed in v30):** the "real downloads succeed
  through a real proxy end-to-end" claim two bullets up was true about the download's outcome and
  wrong about *why* — the connection never actually went through the proxy at all. spotdl's
  `Downloader.__init__` only wires the `proxy` setting into `GlobalConfig`, which the
  `piped`/`bandcamp`/`sliderkz` audio providers and the lyrics providers read; `youtube-music` (the
  only audio provider this app has ever configured) reads neither `GlobalConfig` nor any per-call
  proxy argument, for either ytmusicapi's search or yt-dlp's own download. This session's real,
  credentialed-proxy test watched the wrong signal (that the download succeeded) instead of the one
  that mattered (which IP address the connection actually used) — confirmed empirically in v29 via
  `socket.socket.connect` observation, which showed a real search connecting straight to a real
  Google IP while a real proxy sat configured and unused. Left in place rather than deleted, per
  this file's own "know a past claim was wrong" convention — see `plan/master-v3/v30-proxy-routing-fix.md`
  for the fix.

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
  jobs, one shared `concurrency` group) and deleting the two predecessor files.
  (2026-08-12 correction: merging the files fixed the workflow-group split, but left
  `compose-config`/`frontend` as true siblings with no downstream summary node — v21.1
  renamed `publish-report` to `summary` and fanned it in from all four jobs, since the
  underlying "one PR, one pipeline" intent this entry describes was still only half true
  until then.) **Read
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

### v20 job-centric-ui gotchas (learned building the job/track hierarchy UI, search/sort, archive
controls, and the `/account` route)

- **`GET /api/worker/status`'s `busy` flag (added this version) is deliberately a bare boolean, not
  "which track"** — `worker-dl`'s global `--concurrency=1` invariant means at most one track across
  *every* user is ever `downloading`, so the query behind it (`EXISTS (... WHERE state =
  'downloading')`) is cheap and correct at any realistic scale, but it must never grow an id/title
  field: doing so would leak a foreign track's identity to every session, the exact failure class
  v17's per-user SSE channels exist to prevent. `Waterfall.svelte`'s "no signal here — worker busy
  elsewhere" text is sourced from this flag specifically so an idle-for-this-session waterfall during
  someone else's real download doesn't read as broken — confirmed live by setting another user's
  track to `downloading` directly in the DB and watching the text appear within one 5s poll tick,
  then reverting.
- **`track_listing.list_tracks`'s embedded `job` object gained a `title` field this version**,
  computed via the same `rollup.job_title_expr` the job listing already used — needed because the
  Tracks-scope UI ("matching jobs auto-expand showing only their matching tracks") has nothing else
  to show as a group header; the raw `job.source_url` embed alone would mean every group in that view
  displays a URL instead of an album/playlist name. See the `correlate_except(Track)` gotcha above
  (Database & migrations section) for the query bug this specific addition surfaced.
- **The Tracks-scope state filter (`QueueControls.svelte`) intentionally has no live counts**, unlike
  the Jobs-scope status filter (`counts_by_status`) — there is no equivalent global per-track-state
  count endpoint, and adding one for a filter chip's cosmetic count wasn't judged worth a new backend
  aggregate this version. Revisit if a future version's plan explicitly asks for it.
  **Superseded 2026-10-02, v35 (g):** the tracks listing now returns `counts_by_state` and the
  chips render it — see this file's v35 section.
- **A store function that clears or removes an entry another in-flight fetch might still resolve
  into must invalidate that fetch's own sequence guard at the point of removal** — `queue.ts`'s
  `toggleExpand` collapse path and `setAllUsers`'s full-map clear both call the new
  `invalidateExpandedFetch(jobId)` helper before dropping state, specifically because a
  fast expand-then-collapse (or a scope switch mid-fetch) could otherwise let a stale
  `loadExpandedTracks` response land afterward and silently re-open a row the user had already
  closed — its sequence number still matched what was current when the fetch was *issued*, since
  nothing had bumped it at the point of removal. Found by an independent fresh-context code review
  of this version before merge, not by the real-stack Playwright pass (which never happened to hit
  the exact race window) — a reminder that live-stack verification and independent code review catch
  different classes of bug and neither substitutes for the other.
- **Archiving/unarchiving a job while `include_archived=false` must also decrement
  `countsByStatus`/`totalEstimate` client-side, not just remove the row from `items`** —
  `job_listing.list_jobs`'s `counts_by_status` and `total_estimate` are themselves computed over the
  archived-filtered base query server-side, so a job leaving view under the current filter also
  leaves whichever status bucket it was counted under; `queue.ts`'s `applyArchiveResult` adjusts both
  in the same update rather than waiting for the next full reload to reconcile them. Same
  independent-review finding as above.
- **`JobRow`'s expand-toggle button cannot reuse `TrackRow`'s "the whole row is a `<button>`"
  pattern verbatim** — a job row needs several *other* real interactive controls (priority input,
  bump/cancel/archive buttons) alongside the expand toggle, and nesting a `<button>`/`<input>` inside
  another `<button>` is invalid HTML. Fixed structurally: the toggle is its own `<button>` wrapping
  only non-interactive content (chevron, badge, title, source-type, owner), and the action controls
  are separate sibling elements in the same flex row.
- **`GET /api/jobs`'s literal 3,000-track single-job "Done when" requirement was verified against a
  real Postgres row, not assumed from the v18 precedent** — seeded directly (`bulk_save_objects`
  -equivalent, staged at `/app/`, never `/tmp/`) with 2,700 `completed` / 250 `lookup_failed` / 50
  `waiting`, plus one track ~1,500 rows deep with a unique searchable name. Against the real running
  dev stack (`docker compose`, real Postgres): the job rendered as one collapsed row; expanding
  fetched a bounded ≤50-row page in comparable time to a small job, never all 3,000; a Tracks-scope
  search for the deep unique name returned exactly that one track without ever paginating through the
  job first, proving the search runs server-side over the full history rather than over whatever
  happened to already be loaded. All seeded rows deleted afterward; job/track/`downloaded_tracks`
  counts confirmed identical to their pre-test values.
- **The real upstream login requirement (CLAUDE.md, v15's testing entry) was satisfied via the
  *admin* identity, not the non-admin test account** — `.env`'s `DEV_TEST_PASSWORD` turned out (by
  trial, not by the comment text alone) to belong to `ADMIN_EMAIL`, not the `spotdlwebtest@example.com`
  account the adjacent comment describes registering; the non-admin identity was verified via the
  documented direct-session-mint fallback instead. Worth re-confirming which account a
  `.env` credential comment actually describes before assuming — the two are adjacent in the file but
  not for the account the placement might suggest.
- **`POST /api/tracks/{id}/retry` had no awareness of the job-level archive flag at all** — a real
  gap a *second* independent fresh-context code review caught (the first review round covered the
  new frontend store logic; this one covered the interaction between v20's new archive UI and the
  pre-existing `retry_track` endpoint from v10). `archive._ARCHIVABLE_LIFECYCLES` guarantees an
  archived job is always `settled`/`failed`/`cancelled`, which by construction excludes a `waiting`
  track — the *only* way a `waiting` track could exist under an archived job at all is `retry_track`
  itself reviving a `lookup_failed` one, and once revived, the real running `dispatch_due_tracks`
  (which filters purely on `Track.state`/`scheduled_at`, never on the parent job's `archived_at`)
  would genuinely dispatch it for a live download — real rate-limit exposure from a job the UI still
  labels "archived." Fixed at the one place the gate actually needs to live: `retry_track` now 409s
  with `archived_at is not None` before checking retryability, rather than adding a redundant second
  check to `dispatch_due_tracks` for a state it can no longer reach. `_get_track_or_404` now returns
  `archived_at` alongside the existing owner id so this costs no second query. Confirmed against the
  real running `api` container (a `lookup_failed` track under a freshly-archived job, real session,
  real `POST .../retry` → `409 {"detail": "Job is archived; unarchive it first"}`), not just the new
  `test_retry_track_rejects_when_job_is_archived` unit test; probe row and session deleted afterward.
- **`applyArchiveResult` (the store function reacting to an archive/unarchive) went through six
  independent review rounds and five distinct bug fixes before it stabilized — worth reading in
  full, because the shape of the mistake (not just the final fix) is the reusable lesson.** The
  starting bug was narrow: the single-job archive/unarchive path live-decremented
  `countsByStatus`/`totalEstimate` using only `p.items.filter(...)`, which silently undercounted
  whenever `archive.archive_jobs(job_ids=None, older_than=None)` (the "clear log" bulk action,
  `all_settled: true`) archived more jobs than fit on one loaded page (`DEFAULT_LIMIT = 50`) —
  confirmed by seeding 60 extra tiny settled jobs (68 total, 64 eligible) and watching the count
  hint land inflated after a real "clear log" click. The natural-looking fix — detect
  `removed.length < ids.length` (ids the API touched that this store has no local record of) and
  fall back to a full `reload()` in that case — is where the real trouble started, because that
  same signal turned out to fire for a completely different reason too: **the backend publishes a
  `job.state` SSE event (`archived: true/false`) for *every* job an archive/unarchive call touches,
  including an ordinary single-job action, not just the bulk one** — so the acting session's own
  already-open `EventSource` receives an echo of its own action, and whichever of {the direct HTTP
  response, that echo} arrived *second* always found its id already gone (removed by the first) and
  misread that as "the API archived more than this page holds," firing a spurious reload for what
  was really an ordinary single-job click. Two further rounds of trying to *deduplicate* the two
  signals through one shared function each fixed one race and opened another — a flat 5-second time
  window suppressed a genuinely new archive/unarchive of the *same* job issued within that window
  (indistinguishable from "the expected echo of the earlier action"); replacing it with a
  sighting-counter (claim on the first sighting, consume-and-delete on the second, so a third
  sighting reads as fresh again) fixed that, but a further round found the counter's own safety-net
  cleanup timer could still let a stale claim survive long enough to matter under enough manufactured
  concurrent activity. **The fix that actually held was structural, not a smarter heuristic**: split
  the one shared function into two genuinely different ones, because "my own direct response" and
  "an SSE echo of unknown origin" are not the same kind of signal and were never going to be
  reconciled by deduplicating them as if they were.
  - `applyOwnArchiveAction` (renamed from `applyArchiveResult`) is called *only* from
    `archiveJobs`/`unarchiveJobs`'s own awaited response, never from the SSE path — so it is
    structurally impossible for it to be invoked twice for one real action, and it needs no dedup
    logic at all. It alone decides "patch precisely" vs. "bulk reload," using the complete,
    trustworthy id list the API actually returned.
  - `patchArchivedFlagFromEvent` (new) handles the SSE echo, completely separately, and is
    deliberately *idempotent by construction* rather than deduplicated: it only ever acts when a
    currently-loaded row's `archived_at` doesn't already match the event, so calling it any number
    of times, in any order, converges to the same correct state with no shared timing-sensitive
    bookkeeping. It never triggers a reload and never needs to guess whether it's looking at a bulk
    action, because a single echoed id was never the right unit to make that call from in the first
    place — that ambiguity, not the dedup mechanism's precise shape, was the actual root cause across
    all five fixes.
  - One last wrinkle, closed by a `recentlyEchoRemovedArchiveIds` marker set: since the echo can
    (confirmed via real request-timing measurement, not assumed) arrive and remove a row *before*
    the direct HTTP response for the very same action resolves, `applyOwnArchiveAction` needs to
    know "this id is already correctly gone because the echo got here first" so it doesn't
    misidentify that as an unloaded bulk job and fire a needless reload. This is a one-directional,
    single-purpose signal (echo → direct-response, for the *same* action only) rather than a
    symmetric claim both sides write to, which is what kept it from reintroducing the earlier bugs.
  - Verified against the real running stack, each scenario the earlier rounds' bugs actually
    manifested in: a single-job archive now fires **0** extra `GET /api/jobs?...` requests; a
    64-job "clear log" still fires exactly **1** (debounced via `scheduleArchiveReload`, since the
    backend's per-job publish loop means dozens of individual echoes can each independently reach
    the client before the slow bulk response does); archive → unarchive → re-archive the same job
    three times within 3 seconds all genuinely take effect, confirmed via the archived-view toggle
    each time, not just an optimistic patch. (Network-request counting had its own early false
    positive worth remembering too: `GET /api/jobs/{id}` single-row refetches share the substring
    `/api/jobs` with the list endpoint and were briefly miscounted as reloads in the verification
    script itself, not the app.)

### v21 release-automation gotchas (learned building GitHub releases, GHCR image publishing, and
automated deploy-to-host)

- **A release/tag created with the default `GITHUB_TOKEN` does not trigger other workflows** —
  this is GitHub's own loop-prevention rule, not a bug or a permissions gap. It means
  `release: [published]` cannot drive `publish-deploy.yml` without adding a personal access token
  as a repo secret. Chaining via `workflow_run` (release.yml → publish-deploy.yml) sidesteps this
  entirely with no PAT anywhere in the pipeline — confirmed by reading GitHub's own events
  documentation before designing around it, not discovered the expensive way via a silently
  non-firing workflow. *(Corrected 2026-10-23, v49: the loop-prevention rule still holds, but
  `workflow_run` was the wrong way around it. It fires on every completion of the upstream
  workflow and leaves a skipped run behind each time. The stages are now jobs of one run, calling
  the workflows through `workflow_call`; see the v49 entry.)*
- **A `deploy` job that polls `ci.yml`'s conclusion would deadlock against a single self-hosted
  runner** — this repo has exactly one runner (`vbServer`) shared across every workflow. A job
  holding that runner's only slot while waiting on another workflow that needs the same runner to
  even start is a real deadlock, not a theoretical one. The fix is structural, not a timeout:
  chain `release.yml` off `ci.yml` via `workflow_run` (so "CI passed" is a precondition for the
  job even being scheduled, never something a running job waits on), and `publish-deploy.yml` off
  `release.yml` the same way. *(Corrected 2026-10-23, v49: `needs:` between jobs of one run
  gives the same guarantee without `workflow_run`.)*
- **`workflow_run`'s own `github.sha`/`github.ref` are the default branch's current head, not
  necessarily the commit that triggered the upstream run** — verified against GitHub's events
  reference before relying on it. `release.yml` explicitly checks out
  `github.event.workflow_run.head_sha`; `publish-deploy.yml` resolves everything from the
  release's own tag (`gh release view --json tagName`) and the exact commit SHA that tag points
  to, never the ambient event context.
- **`docker checkout --detach <branch-name>` cannot reliably resolve a bare branch name to
  `origin/<branch-name>` the way plain `git checkout <branch-name>` DWIMs it** — `--detach`
  disables that convenience lookup. `publish-deploy.yml`'s `resolve` job therefore always resolves
  to a concrete commit SHA (via a real `actions/checkout` at the human-readable ref, then
  `git rev-parse HEAD`) before the `deploy` job ever runs `git checkout --detach`, so the target is
  always unambiguous regardless of whether the input was a branch, a tag, or a SHA already.
- **`git clean -fd`, never `-fdx`, in the deploy job** — `.env` and `proxies.txt` are gitignored on
  purpose (they hold real secrets and the real proxy pool), which is exactly what `-x` also
  removes. `-fd` alone leaves ignored files untouched while still clearing any stray untracked
  build artifact.
- **`docker-compose.prod.yml`'s `image:`/`build: !reset null` pair has to be repeated on every
  service that needs it, not set once** — `build: ./backend` arrives at `migrate`/`api`/
  `worker-dl`/`worker-meta`/`beat` via the base file's `x-backend` YAML anchor (`<<: *backend`),
  so a bare `image:` on one of these services alongside the *inherited* `build:` still builds
  locally and ignores the pulled tag (Compose prefers `build` when both keys are present after
  merge). Each service needs its own `build: !reset null` to actually remove the anchor's value.
  Confirmed with `docker compose config` rendering every service's resolved `build` as `null` and
  `image` as the GHCR ref, not just eyeballing the YAML.
- **The OCI `org.opencontainers.image.source` label is what links a GHCR package to its GitHub
  repo** — without it, a pushed package shows up as an orphaned, unlinked entry under the
  publishing account's Packages tab rather than appearing on the repo's own sidebar. Set at build
  time (`docker build --label org.opencontainers.image.source=https://github.com/<repo> ...`),
  not something fixable after the fact except through GHCR's manual "Connect repository" UI.
- **`default_workflow_permissions: read` at the repo level silently caps what any workflow's own
  `permissions:` block can grant** — found via `gh api repos/.../actions/permissions/workflow`
  before the first real run, not after a mysterious 403. A workflow declaring
  `permissions: { contents: write, packages: write }` still needs the repo-level setting raised to
  "Read and write permissions" first (Settings → Actions → General); the per-workflow block is a
  ceiling *within* that repo setting, not independent of it.
- **The documented deploy host paths had drifted from reality** — `docs/DEPLOYMENT.md` and
  `docs/CI_SELF_HOSTED_RUNNER.md` described `/opt/spotdl-web` and a dedicated `github-runner` OS
  user; the real host has the deploy checkout at `/mnt/raid1/spotdl-web` and the runner at
  `/home/vb2007/gh-actionrunners/spotdl-web` running as `vb2007` (the same user that owns the
  deploy checkout, already in the `docker` group). Found only by actually SSHing in and checking —
  never assume a runbook still matches the host without verifying against it first, especially
  before wiring a workflow that will `git reset --hard`/`docker compose up -d` for real.
- **The host's `.env` was missing `ADMIN_EMAIL`** — mandatory since v17 (every backend container
  crash-loops at boot without it). Would have made the very first automated deploy fail on
  something unrelated to the pipeline itself; caught and fixed in this slice's host pre-flight
  before the pipeline ever ran for real, rather than discovered as a confusing first-deploy
  failure.
- **`docker manifest inspect` against a private GHCR image, unauthenticated, fails the same way as
  "image doesn't exist yet"** — used deliberately as the already-published check in the `publish`
  job: it doesn't need to distinguish "not published" from "published but I can't see it," since
  both cases correctly mean "build and push."

- **A persistent self-hosted runner's `docker login` credential outlives the job that created
  it and poisons later, unrelated pulls** — unlike a GitHub-hosted runner's disposable VM, this
  runner's `~/.docker/config.json` is shared across every job and every future run. The
  `publish` job's `docker login ghcr.io` (needed to push) left a credential behind that was
  still there — and by then invalid — when the `deploy` job tried a plain, unauthenticated
  `docker compose pull` of the same (now public) images moments later; Docker sent the stale
  credential instead of falling back to anonymous, and GHCR answered `denied: denied` for an
  otherwise-public image. Reproduced and fixed live on the real runner (confirmed via
  `~/.docker/config.json` and a manual `docker logout ghcr.io` unblocking the exact same pull)
  before adding an unconditional `docker logout ghcr.io` (`if: always()`) as the `publish`
  job's last step.
  *2026-10-19: the logout wasn't enough.* Every repository's runner on this host runs as the
  same Unix user, so the "shared" file is shared with other repos' jobs too, and a
  logout only cleans up after itself. v47's release `publish` logged in at 12:07:15, then
  vb2007.hu-api's concurrent release logged in (its own token) and out twice, the last
  logout at 12:08:06; the push at 12:08:07 failed `unauthorized: unauthenticated: User cannot
  be authenticated with the token provided`. `publish` and `deploy` now start with a "Use a
  job-private Docker config" step: `DOCKER_CONFIG=$RUNNER_TEMP/docker-config`, a copy of the
  shared `config.json` minus `auths`/`credsStore`/`credHelpers`, with `cli-plugins` and
  `contexts` linked in (plugins are only looked up under `DOCKER_CONFIG` and the system dirs).
  The login, the push and the deploy's anonymous pulls never touch the shared file. A rerun of
  a failed `publish` is safe: nothing moved on the host (`deploy` never started).
- **`pg_backup.sh` (a pre-existing v12 script) had never actually succeeded on this host** —
  it reads `DATABASE_URL` verbatim from `.env`, which is written for the *containers*
  (`host.docker.internal`, resolved via `extra_hosts: host-gateway`). That hostname is **not**
  resolvable from the host's own DNS on Linux (only Docker Desktop maps it on the host too) —
  confirmed by running the unmodified script for real and getting
  `could not translate host name "host.docker.internal"`. Fixed by substituting `localhost` for
  that one hostname after the existing `+psycopg` strip, since the script only ever runs
  directly on the host (Postgres is host-native, per the locked decision) — verified by
  re-running it for real afterward and inspecting the resulting dump with `pg_restore --list`.
- **`git checkout --detach --force`, not just `--detach`, is needed for an automated deploy
  checkout** — even after resolving to an unambiguous commit SHA (see the DWIM gotcha above),
  `git checkout` still refuses to switch when a *tracked* file has local, uncommitted drift
  (`error: Your local changes ... would be overwritten by checkout`). Hit for real when a script
  fix was hand-applied directly to the host checkout ahead of the pipeline deploying it itself —
  a completely ordinary occurrence (anyone SSHing in and patching a file by hand), not an edge
  case worth dismissing. `--force` makes the checkout always land exactly on the resolved commit
  regardless of that drift; `git clean -fd` afterward is unrelated (it only ever touched
  untracked files) and didn't need to change.
- **`worker-meta` was mid-crash-loop from a real, pre-existing OOM** (not merely "observed
  restarting" — confirmed via `docker inspect ...  --format 'OOMKilled={{.State.OOMKilled}}'` →
  `true`, exit 137) **the entire time this slice's health gate was being built**, and it
  permanently blocked the gate from ever reporting the stack healthy. Root cause: no
  `--concurrency` flag on its Celery command, so it defaulted to `os.cpu_count()` (8 on this
  host) prefork children, each importing the heavy spotdl/yt-dlp dependency tree — reliably
  exceeding its 768M prod limit. Fixed with `--concurrency=2` (meta tasks are lightweight; two
  workers is ample) rather than raising the memory limit, since the host's spare RAM is
  genuinely tight (shared with Matrix/Vaultwarden/TubeArchivist, swap already full at the time).
  A pre-existing bug outside this slice's stated scope became in-scope the moment it started
  blocking the very thing being built — worth remembering next time a "flag for later" item
  turns out to sit on the critical path.
- **A "reasonable-looking" hardcoded default path can be silently wrong for the real host, and
  nothing will tell you until it's already created something** — `scripts/pg_backup.sh`'s
  original default (`/srv/spotdl-web/backups`, inherited from this doc's own original,
  never-fully-reconciled greenfield example) had no relationship to this host's actual storage
  layout: the real deploy checkout and downloads both live under `/mnt/raid1` (a RAID array,
  also reachable from other machines via a Samba share literally named `srv-raid1` — a
  coincidence of naming, not the same path as the bare `/srv` on the host's own root
  filesystem). The first time the script actually ran for real on the host, it silently
  `mkdir -p`'d a brand-new `/srv/spotdl-web/backups` on the **OS root disk**, not the RAID
  array — a live production host running several other unrelated services, so a mistakenly
  ballooning root filesystem is a real risk, not a hypothetical one. Caught only because the
  user noticed `/srv` mentioned in a changelog and immediately knew it didn't belong (it hadn't
  existed before this session). Fixed by deriving the default from the script's own
  `REPO_ROOT` instead of a second hardcoded absolute path — a default that's *computed from
  where the code actually is* can't independently drift from where the code actually is, the
  way two independently-typed absolute paths always eventually can. **The general lesson**:
  every hardcoded absolute path in a script or doc that will run for real on a specific host is
  a claim about that host's layout — verify it against the real host (as this slice's other
  path corrections already did for the deploy checkout and `DOWNLOADS_DIR`) rather than trusting
  it because it "sounds like" a normal Linux convention. `/srv` is a real, common,
  intentionally-empty-by-default FHS directory — that's exactly what makes a stray, wrong
  `mkdir -p /srv/...` easy to miss, since finding an unexpected `/srv/<project-name>/` doesn't
  look obviously broken at a glance.
- **A backup directory placed *inside* a git-managed deploy checkout must be gitignored, or the
  next automated deploy silently deletes it** — once `pg_backup.sh`'s default moved to
  `<repo root>/backups` (fixing the gotcha above), that directory sits inside the exact tree
  `publish-deploy.yml`'s `deploy` job runs `git clean -fd` against on every single deploy.
  `-fd` deletes any untracked file not covered by `.gitignore` — without an explicit
  `/backups/` entry (added alongside the path fix, not as an afterthought), every real Postgres
  dump ever taken would have been wiped by the very next deploy. The general form of this bug:
  moving *any* generated, non-source data (logs, caches, backups, uploads) to live inside a
  git-managed directory that a deploy pipeline resets is only safe if it's gitignored — verify
  this every time such a path changes, not just when it's first introduced.
- **An idempotency-skipped deploy looks identical to a stuck one from `docker compose ps`
  alone** — after the real post-merge chain ran, every container still showed its original
  `CREATED`/`Up` time from hours earlier, which looked like the deploy had silently done
  nothing. It hadn't: `publish`'s already-published check and `deploy`'s already-deployed check
  (see the Idempotency section of `docs/RELEASE_PIPELINE.md`) both correctly found the exact
  same version already built and running, because the merge introduced zero `backend/`/
  `frontend/` source changes beyond what live pre-merge testing had already deployed under the
  same version string — confirmed with `git diff <pre-merge-test-commit> <merge-commit> --
  backend/ frontend/` coming back empty, not assumed. The general lesson: `docker compose ps`'s
  `CREATED`/`Up` columns answer "when was this container process last (re)started," not "did the
  most recent deploy do anything" — a content-identical image legitimately never recreates the
  container, and that's the idempotency feature working, not a stuck pipeline. Verify via the
  deploy job's own logs (which step ran vs. skipped) and a source diff before assuming a deploy
  failed silently.

### v22 multi-user-hardening gotchas (learned re-running the cross-user sweep at the seams v14–v20
left unchecked, verifying production, and reconciling docs)

- **A module-level frontend store is itself a data surface, and the REST-level sweep can't see
  it.** `backend/tests/test_ownership.py` (extended per-version through v14–v20) already covered
  every REST surface in the plan's sweep table before this version started — list isolation,
  direct-id 404s, admin gating, search/scope, archive/retention. The one real gap was in
  `frontend/src/lib/stores/queue.ts`: `queue` is a singleton created once at module load
  (`export const queue = createQueueStore()`), and `onLogout()` (`frontend/src/routes/+page.svelte`)
  navigated away with SvelteKit's `goto()` — a client-side transition that never reloads the page
  or resets any JS module. A same-tab logout(A) → login(B) left A's `incoming` (just-submitted,
  still-expanding jobs) and `liveActive` (currently-downloading track) entries sitting in memory,
  and both render **unconditionally** (`IncomingJobs.svelte`/`Waterfall.svelte` have no
  `page.loading`-style gate) — B's dashboard showed A's submitted Spotify URL. Fixed with
  `queue.reset()`, called from `onLogout()` before the navigation, clearing
  `page`/`expanded`/`incoming`/`liveActive`/`allUsers`/`filters` back to empty and invalidating any
  in-flight fetch (bumps `pageFetchSeq` so a late-resolving stale response can't repopulate
  anything). Confirmed both ways with a throwaway Playwright script against the real local stack:
  reverting the fix reproduced the leak deterministically (not a timing race — an "incoming" entry
  sits there indefinitely, no reload ever clears it on its own), and restoring the fix closed it.
  **A first attempt at reproducing this was a false negative** — timing the check around
  `page.items`/`$page.loading` (whose synchronous `loading:true` set in `reload()` happens to mask
  that specific store within the same task, before any paint) suggested nothing leaked at all; only
  targeting `incoming` specifically (which has no such gate) exposed the real, unconditional bug.
  Lesson: a "no leak observed" result from one render path proves nothing about a sibling store
  with different rendering logic — the sweep needed the actual persisted-store inventory (`page`,
  `expanded`, `incoming`, `liveActive`), not one representative check.
- **`onLogout`'s explicit `queue.reset()` wasn't the only door to `/login` — a fresh-context
  independent review of the PR caught a second one**: `frontend/src/routes/+layout.ts`'s `load()`
  runs on every client-side navigation and redirects to `/login` on a 401, entirely independent of
  the "disconnect" button. A session going invalid any other way (expiry, revocation, a wiped
  `sessions` row) and the user then making *any* in-app navigation reaches this exact redirect
  without ever running `onLogout`'s `reset()` — same unconditional `incoming`/`liveActive` leak,
  different trigger. Fixed by calling `queue.reset()` from this one chokepoint too (right before
  the redirect), so it's covered regardless of *why* the session is gone rather than only the one
  explicit path. Reproduced and closed with the same before/after Playwright technique as the
  first fix, this time via a raw `fetch('/api/auth/logout')` (bypassing the UI's own handler
  entirely) followed by an ordinary in-app link click rather than the disconnect button.
- **The reviewer also found a `set -e` dead-code path in `scripts/verify_separation_sse.sh`'s
  `login()`**: `token="$(grep ... | head -n1 | sed ... | tr -d ...)"` under `set -euo pipefail`
  aborts the whole script the instant the pipeline fails (e.g. a genuine 401 during login) —
  *before* the deliberate `if [ -z "$token" ]` diagnostic ever runs. Reproduced directly (a
  minimal repro with the same shape: declare-then-assign, not the more commonly-known
  combined-`local`-assignment version of this gotcha, so worth remembering separately). Fixed
  with `|| true` on the assignment, letting the emptiness check that follows be what actually
  decides pass/fail. Also added: the SSE script's own sweep-table coverage was missing the row
  for a *non-admin* B attempting `all_users=true` (only the reverse/admin direction was tested);
  added, plus a `SPOTDL_WEB_USER_B_TOKEN` override so this check works even when only one spare
  real non-admin identity is on hand (mint a session directly for a distinct third identity
  rather than reusing the admin's credentials for both B and ADMIN — which was tried first here,
  and produced a confusing FAIL that was actually a test-setup mistake, not a real leak; the
  script now checks B isn't accidentally admin and fails loudly with a clear message instead).
- **A second, independent review round caught two more instances of the exact same two bug
  classes just fixed** — not new categories, but the first fix's own audit didn't sweep the rest
  of the file. `JOB_ID="$(echo ... | grep ... | head ... | grep ...)"` (job creation) has the
  identical `set -e`/pipefail dead-code shape as `login()`'s token extraction; fixed the same way
  (`|| true`). And the new "is B accidentally admin" diagnostic introduced by the *previous* round
  referenced `$SPOTDL_WEB_USER_B_EMAIL` unconditionally, which is unset under `set -u` when B was
  supplied via the same round's own `SPOTDL_WEB_USER_B_TOKEN` alternative — an unbound-variable
  crash in exactly the mode meant to make this check usable at all. Fixed with
  `${SPOTDL_WEB_USER_B_EMAIL:-via SPOTDL_WEB_USER_B_TOKEN}`. Neither was a security-property false
  pass (both still failed loudly, just with a worse message), but the general lesson holds: once a
  bug class is found once in a file, audit the *whole* file for it, not just the one instance that
  was reported — a fix applied to only the reported line invites the reviewer to find the sibling
  instance in the next round instead of this one.
- **Re-verified with real captured SSE bytes this time, not only a narrative summary** — the
  plan's own "Done when" explicitly wants the SSE capture pasted, not summarized. A clean
  post-fix run's actual output:
  ```
  PASS: A's own stream saw its own job (...) -- events are flowing.
  PASS: B's stream contains zero mention of A's job id.
  PASS: B's all_users=true attempt was silently ignored -- zero mention of A's job id.
  PASS: admin's all_users=true pattern-subscribe saw A's job id (reverse direction confirmed).
  verify_separation_sse: all checks passed.
  ```
  and the raw captured admin-channel bytes for that same run (four real events, exactly as
  expected — `job.state` expanding→expanded→cancelled and one `track.state`):
  ```
  data: {"ts": "...", "type": "job.state", "job_id": "...", "state": "expanding"}
  data: {"ts": "...", "type": "job.state", "job_id": "...", "state": "expanded"}
  data: {"ts": "...", "type": "track.state", "track_id": "...", "job_id": "...", "state": "skipped_duplicate"}
  data: {"ts": "...", "type": "job.state", "job_id": "...", "state": "cancelled"}
  ```
- **v16's migration was already applied to production before this version started** — found via
  a direct table check (`users`/`user_settings` already existed, with 3 real users and 7 real
  jobs), not assumed from the plan's phrasing. v21's automated deploy pipeline (and pre-merge
  `workflow_dispatch` testing during v17–v20's own development) had already carried it out as a
  side effect of shipping those versions to the real host. This version's actual work was
  *verifying* that, not performing it: a fresh `pg_backup.sh` + restore-into-a-scratch-container
  drill (row counts matched exactly: 4 users/16 jobs/35 tracks/93 downloaded_tracks before and
  after), and confirming a track already in `downloaded_tracks` still resolves `skipped_duplicate`
  rather than re-downloading when submitted by a brand-new second user. General lesson: a version
  plan can be stale about what's *already true* on production by the time it's picked up,
  especially once automated deploy is in the loop — check real state before executing a "perform
  X" task literally.
- **The production host's on-disk git checkout can drift behind the release it's actually
  running, silently** — found while trying to bring the checkout in line with `IMAGE_TAG=2.21.0`
  before running `pg_backup.sh`: the host was detached at an old pre-merge test commit
  (`36c8293`, itself an ancestor of the real `v2.21.0` tag — left over from `workflow_dispatch`
  testing during development, e.g. of `dev-ci-summary-consistency`), and `scripts/pg_backup.sh` at
  that commit still had the pre-v21-fix hardcoded `/srv/spotdl-web/backups` default, which promptly
  failed with a permission error on the OS root disk — the exact failure mode the real fix
  (`d146697`) exists to prevent, resurfacing because the fixed version was never actually pulled
  down. Worse: `git fetch origin --tags` was flat-out *rejected* ("would clobber existing tag")
  because the host also had a **stale local `v2.21.0` tag** — created during v21's own pre-merge
  testing before the real release process cut the authoritative tag with the same name — silently
  shadowing the real one every git tag lookup would otherwise resolve. Fixed with
  `git tag -d v2.21.0 && git fetch origin --tags && git checkout --detach v2.21.0`. This never
  affected the *running containers* (those come from the already-pulled GHCR image, independent of
  the working tree), but it means any host-level script invoked directly (backup, restore,
  anything not baked into an image) can silently run stale code. Added to
  `docs/DEPLOYMENT.md`'s troubleshooting table so this doesn't get rediscovered the expensive way.
- **Local dev and production now genuinely share live data, not just a theoretical risk** — this
  version's own local verification (Playwright leak repro, the SSE separation script) wrote real
  rows into the same shared database production serves, confirmed by the second real test
  identity's jobs showing up in a production-side query moments later. Harmless here because
  ownership scoping kept it out of the admin's own view and everything created was cleaned up
  (cancelled test jobs), but it's the first time this actually happened rather than being a
  documented-but-unexercised risk. `docs/LOCAL_DEV.md` and `CLAUDE.md`'s dev-environment table
  updated to say so plainly rather than "revisit once there's data worth protecting" — that
  threshold has now been crossed.
- **Registering a fresh real-upstream test account whose original password isn't on hand is
  normal, not a blocker** — the pre-existing `spotdlwebtest@example.com` (from v17's own testing)
  no longer authenticated with this session's known `DEV_TEST_PASSWORD`; rather than chase down or
  reset its real password, a fresh account (`spotdlwebtestv22@example.com`, plain alphanumeric
  username — the known hyphenated-username upstream bug still applies) was registered against the
  live `https://api.vb2007.hu` with that same password, per the standing rule. Confirmed real login
  for both `balazs@vb2007.hu` (existing admin) and the fresh identity before treating the sweep as
  covering real auth, not only the direct-session-mint fallback.
- **The v22-mandated closing pass** (re-reading `plan/master-v2/` to confirm every "Done when"
  bullet across v14–v22 was actually checked with its own evidence, not just asserted) found the
  historical record in good shape but not perfect: of 60 "Done when" bullets audited across
  v14–v21, 50 had concrete evidence (a command, an exact count, a quoted log line) findable in
  `docs/GOTCHAS.md`/merged PR bodies; 6 were asserted only via a blanket claim with no bullet-
  specific detail (mostly v20's UI interactions — PR #22's "Playwright pass covering every Done
  when bullet" doesn't itemize which bullet exercised what); 4 were the routine, low-materiality
  "`graphify update .`" bullet with no evidence either way. One bullet (v16's "existing suite
  passes unchanged") isn't asserted-and-unbacked but disproven-and-fully-explained — an
  intentional, user-approved deviation, already documented in three places. None of the 6
  asserted-only bullets showed evidence of an actual regression, only thinner-than-ideal
  documentation of work the surrounding evidence makes very likely genuine.
  - Two of the six were worth a same-session spot-check rather than leaving as "probably fine":
    v20's non-admin-hides-`/settings`-and-403s / admin's-all-users-toggle-adds-owner-column
    bullet, and v19's "a previously-downloaded track survives archiving and still resolves
    `skipped_duplicate` on resubmission" bullet (the plan's own text calls this "the property
    that matters most" for that version, yet it had no test distinct from the row-count check).
    Both re-verified live against the real stack this session: the v20 UI bullet directly (a
    non-admin genuinely sees no settings link and gets a real 403; the admin's all-users toggle
    genuinely reveals the second user's job with an owner column, confirmed via
    `page.content().includes(...)` on the real rendered page) — and the v19 dedup property
    incidentally, as a byproduct of this version's own production verification task (the same
    `skipped_duplicate` resolution already recorded above, on a track that had been through
    multiple real submit/cancel cycles under archiving-adjacent conditions).
  - The other four (v20's scope-toggle-search-across-jobs, sort-reorders-whole-set, state-filter-
    counts-match-API, plus the routine graphify bullets) were left as documentation-thinness, not
    re-tested individually — their underlying server-side behavior is evidenced elsewhere
    (`test_job_listing.py`'s cursor-pagination-across-pages coverage; a live cross-job search
    confirmed as part of this same session's testing, returning matches spanning >15 distinct
    job ids for one query) and the frontend wiring is a direct, simple pass-through with no
    client-side reordering/filtering logic of its own to regress.
  - "All services healthy afterward" (v22's own migration-verification bullet) reconfirmed at the
    very end of this session: `docker compose -f docker-compose.yml -f docker-compose.prod.yml ps`
    on the real host shows every service `healthy` (api/web/redis) or running-with-no-healthcheck-
    by-design (beat/cloudflared), `worker-dl`/`worker-meta`/`beat` each `Up 26 hours` — i.e.
    untouched and stable across this entire session's local/production verification work, not
    freshly restarted into a state that hasn't been exercised. "A real download completes end to
    end" is satisfied by the pre-existing real usage already on this host (7 real jobs predating
    this session, all through the identical unmodified download pipeline) rather than a fresh
    download deliberately triggered just for this checklist — consistent with the project's own
    stance on not spending real rate-limit budget on a check redundant with existing evidence.

### v23 download-reliability gotchas (learned root-causing the download outage, fixing the
live-view metadata gap, and root-causing the Waterfall appear/disappear/reappear glitch)

- **The stale-yt-dlp-pin hypothesis was wrong, and only real-stack reproduction caught it.** The
  master plan's leading hypothesis was that `yt-dlp==2026.7.4` had gone stale. Reproducing against
  the real `worker-dl` container with `spotdl`/`yt-dlp` logging raised showed the actual failure:
  a real `AudioProviderError` ("Sign in to confirm you're not a bot") raised deep inside spotdl's
  `search_and_download`, caught and swallowed *by spotdl itself*, surfacing to `download_track` as
  a bare `output_path is None` with no exception at all. Pulling yt-dlp's actual nightly build (a
  month past the pinned stable — PyPI's own stable channel hadn't shipped anything newer) and
  re-running the identical failing track reproduced the *exact same* failure — proving the pin
  itself was not the cause before writing a single line of the fix. The real cause: the production
  Docker image never installed a JS runtime, so `spotdl.utils.deno.get_local_deno()` found nothing
  and YouTube's PO-token challenge could never be solved (see the spotdl-library entry above). This
  is the scenario the plan's own "prove the root cause, don't bump and hope" instruction and its
  4th review lens exist for — the visible symptom and the leading hypothesis coincided with the fix
  that was actually planned, but the evidence didn't support it once actually gathered.
- **The confirming end-to-end proof needed three layers, not one.** (1) A direct call to spotdl's
  `Downloader.search_and_download` with Deno present succeeded and produced a real, `ffprobe`-
  verified mp3 for a track that had failed in real production. (2) The exact same result reproduced
  through the actual `download_track` Celery task (not a reimplementation), confirming the fix
  works through the real code path, not just an isolated spotdl call. (3) A full real HTTP job
  submission (`POST /api/jobs`) through the real API, real expansion, real dispatch, and real
  worker, watched live in an actual browser, completed with a real downloaded file and correct
  Waterfall behavior throughout. Each layer would have missed a different class of regression the
  others couldn't have caught alone.
- **A residential IP being reputation-flagged by YouTube is real but per-host, not per-session.**
  This local dev machine's own public IPv4 was flagged for the session's duration (confirmed
  `-4`/`-6` A/B, see the Docker Compose entry above); the project owner's live test on the actual
  production host, from a different IP, succeeded immediately with the same Deno-based fix. Don't
  generalize a single environment's network reputation to "the fix doesn't work" or "the fix always
  works" without checking the specific host in question.
- **The circuit breaker tripped on its own testing traffic during this session, and that was
  correct behavior, not a bug to route around.** Repeatedly reproducing `AudioProviderError`/
  `NoOutputFileError` failures against real tracks fed the same breaker the app relies on to
  protect against a real outage — it tripped mid-investigation and correctly blocked all dispatch
  for its escalating backoff window. Clearing it directly in the DB (`consecutive_failures = 0`,
  `breaker_tripped_until = None`) was the right move to continue *testing*, but the trip itself is
  exactly the behavior v06's breaker was built for; don't mistake "verification hit a hard stop I
  understand" for "the breaker fired when it shouldn't have."

### v23.1 download-reliability-followup gotchas (learned recording v23's production
confirmation, closing the yt-dlp-ejs pin gap, and fixing a job vanishing from the Jobs list)

- **v23 confirmed working in production** by the project owner against the deployed instance
  (release pipeline run [31832103988](https://github.com/vb2007/spotdl-web/actions/runs/31832103988)):
  a real single-track submission downloaded successfully end to end, the Waterfall appear/
  disappear/reappear glitch was gone, and live download metadata (title/artist) rendered
  correctly from the first event. This closes v23's one previously-unverified item.
- **A `job.state` SSE event fires for the `expanding` state itself, not only for later
  transitions** — confirmed empirically via real-browser polling at 300ms granularity (a coarser
  2s poll in an earlier pass of the same verification missed this window entirely and gave a
  misleadingly clean-looking result). This matters because any code reacting to `job.state`
  events must not assume the first event it sees for a given job already has real, track-derived
  data (title, in particular) — the frontend's `derive`-style `Job.title` genuinely can be still
  the raw `source_url` fallback at this point, for a job with zero tracks so far.
- **`patchPageJob` (`frontend/src/lib/stores/queue.ts`) — the reported "new job vanishes from the
  Jobs list until a full refetch" bug — had a second, deeper layer once the obvious
  `idx === -1 return p` bail was fixed.** Simply inserting-if-missing on every `job.state` event
  reintroduced a subtler version of the same class of bug: the *first* insertion often happened
  while the job was still `expanding` (per the gotcha above), using its raw `source_url` as the
  sort key under a title/track_count sort. Once a row exists, every later event for that job only
  ever patches it in place (`idx !== -1` branch) and never re-sorts it — so the row's *text*
  updated correctly to the real derived title once the job reached `expanded`, but its *position*
  stayed wherever the URL had sorted it, permanently. Caught only by watching actual DOM order in
  a real browser under a non-default sort with two known tracks whose titles bracket each other
  alphabetically (`docs/GOTCHAS.md` testing-technique entries' own "mocked verification is not
  verification" lesson, again) — invisible to `svelte-check`/`eslint`, and invisible to a coarser
  poll interval that simply missed the intermediate wrong-position state. Fixed by never inserting
  (only patching, which is already a safe no-op when absent) while `job.state` is `expanding` or
  `failed` — the same two states `applyJobEvent` already keeps in the `incoming` overlay instead
  of removing from it, so the two now agree on exactly when a job is allowed to have a page row at
  all.
- **This is the second real bug found in this store by production use rather than by tests** —
  the same pattern as v09's sort-tiebreaker gotcha and v10's terminal-state guard (both listed
  above): a live, stateful frontend store accumulating patches over time has failure modes a
  request/response test never exercises, because nothing about a single request captures "what
  does the *next* event do to state a *previous* event already wrote." Worth specifically
  stress-testing any future change to this store against a sequence of live events, not just its
  handling of one event in isolation.
- **A third layer of the same `patchPageJob` fix, caught only by this version's mandatory
  fresh-eyes review (two independent reviewer agents found it independently)**: appending a
  newly-inserted job at the *tail* of the currently-loaded window is unsafe whenever
  `page.nextCursor` is non-null. The cursor is keyed off the old last-loaded row's own
  `(sort value, id)` tuple (`pagination.apply_cursor`, backend) and knows nothing about a
  row spliced in locally after the fact — a tie or a value at/after that row is exactly what
  the server's own "everything after the cursor" condition matches, so a later `loadMore()`
  (which concatenates with no id dedup) can legitimately re-fetch the same job from the server
  and render it twice. Confirmed directly against the real API: fetching
  `GET /api/jobs?sort=track_count&dir=asc&limit=1` twice in sequence (second call using the
  first's `next_cursor`) against three real jobs tied on `track_count=1` returned a different
  job each time, purely by id tie-break — proving the cursor's tie-break is real id-based
  state the frontend can't see or replicate locally. Fixed by treating "would append at the
  tail, and more pages still exist" the same as the `q`/`next_retry` cases above: fall back to
  `scheduleReload()` instead of guessing. Inserting strictly *before* an already-loaded row
  stays safe regardless of `nextCursor`, since that row's own sort value is provably before
  whatever the cursor holds.
- **A fourth, broader layer, also caught only by review**: `patchPageJob`'s insert branch was
  reachable from *any* `job.state` SSE event, not only ones for a job actually leaving the
  `incoming` overlay — that event fires for every state change on every job the owning user's
  channel carries (another tab/device acting on it, an admin, `beat`'s retention auto-archive
  sweep — `cancel_job` publishes to the job's *owner*, not the acting session, precisely so
  those other cases reach every open tab). A job sitting beyond the currently-loaded page
  window that merely changes state is *not new* — it was already counted in the original
  `total_estimate`/`counts_by_status` snapshot, and inserting it (double-counting it, and
  risking the same tail/cursor duplicate above) has nothing to do with the reported bug at all.
  Fixed by gating insertion behind an explicit `allowInsert` flag, true only where the caller
  knows for certain this is legitimately new: `applyJobEvent`, gated on whether the job's id
  was actually present in `incoming` a moment before this event (`wasIncoming`), and this
  session's own `cancelJob` (always a job the acting session could already see somewhere).
  Every other call site (`bumpJob`, `setJobPriority`, and `applyJobEvent` for a job that
  `wasIncoming` says no to) keeps the original, safe "patch in place only if already loaded,
  otherwise do nothing" behavior — the behavior this whole store had *before* the bug this
  version set out to fix, which was correct all along for anything that isn't a job newly
  leaving the overlay.
- **The `KeyError('uri')` loose end from v23 is closed** — see the v04 section's entry above,
  which already fully explained the mechanism; the ID in question was simply never verified to
  exist. Not investigated further.

### v24 attempt-history gotchas (learned building `track_attempts`)

- **A breaker-requeue row can share `attempt_number` with the real attempt that follows it.**
  `download_track` captures `attempt_number = track.attempt_count` once at the top of the
  function (`backend/app/tasks/download.py`), before any gate runs. The breaker-active early
  return writes its `track_attempts` row from that same captured value but deliberately does
  **not** increment `tracks.attempt_count` — bumping it there would make the next real attempt
  read `attempt_count >= 1` and incorrectly reach for a proxy, breaking the locked "attempt 1 is
  always direct" rule. So whenever a track is breaker-requeued and then, once the breaker clears,
  actually attempted for real, both rows are stamped with the identical `attempt_number`. This is
  a genuine tension between the schema's literal "mirrors `tracks.attempt_count`" definition and
  "one row per attempt" being unique per real invocation — there is no `attempt_count` value that
  satisfies both once a path exists that must log a row *without* consuming a real ladder rung.
  Deliberately left as-is (schema kept literal) rather than switched to an independent row-sequence
  counter: `started_at`/`finished_at` stay correctly ordered regardless via the endpoint's secondary
  sort key, and the frontend never renders `attempt_number` as a visible label (`TrackRow.svelte`
  shows outcome/direct-or-proxy/timestamp/error only), so the collision has no observed UI impact —
  only a direct SQL/API query against `track_attempts` would ever see two rows sharing a number.
  **Designed away 2026-10-02, v35 (a):** `attempt_number` is now a per-track 1-based sequence
  assigned by `attempts.record_attempt`, unique-constrained, and a breaker hold is outcome `held`.
  `attempt_count` still isn't bumped by a hold, so "attempt 1 is always direct" holds. See v35.
- **The stale-track reclaim sweep (`beat._reclaim_stale_tracks`) writes no `track_attempts` row at
  all.** It bulk-`UPDATE`s any `DOWNLOADING`/`QUEUED` track stuck past `STALE_TRACK_AFTER_SECONDS`
  straight back to `WAITING`, bypassing `download_track` (and therefore `attempts.record_attempt`)
  entirely — by design, since it exists precisely for a worker crash/OOM-kill/restart that never
  got to run any of `download_track`'s own exit paths. A real crash mid-download is exactly the
  scenario this project's Celery durability invariants (`task_acks_late` + this sweep) exist to
  recover from, so it's a real, reachable gap in the "why does this one keep failing?" story v24
  exists to close — just outside v24's own scope, which named `download_track`'s six exit paths
  specifically and never touched `beat.py`. Left for whichever version next does deeper worker-
  reliability work (candidate: v30's hardening close) rather than folded into v24 unasked.
  **Fixed, v31**: see this file's own v31 section.

### v25 username-ui gotchas (learned building `users.username` + moving worker controls)

- **httpx's own client-side cookie jar cannot be trusted to replay the `VB-AUTH` token on a
  follow-up request.** The obvious implementation — reuse one `httpx.AsyncClient` for both the
  login `POST` and the `GET /user` that follows, letting the client's cookie jar carry the
  session cookie across the two calls automatically — silently fails against the real local
  upstream instance: `vb2007.hu-api`'s `.env` sets `COOKIE_TARGET_DOMAIN=localhost`, so its
  `Set-Cookie: VB-AUTH=...; Domain=localhost` fails RFC 6265 domain-matching the moment the
  request host is anything else (`host.docker.internal` from inside a container, or
  `api.vb2007.hu` in production) — `http.cookiejar`'s domain-match rule requires the request
  host to equal or be a dot-suffixed subdomain of the `Domain` attribute, and neither host
  qualifies. The fix: extract the token directly from the raw `Set-Cookie` header text
  (`upstream_auth._fetch_username`'s `_VB_AUTH_RE`) and hand it to a **second**, independent
  `httpx.AsyncClient` via its `cookies=` constructor kwarg, bypassing domain-matching entirely.
  Confirmed the failure mode is real (not just theorized) by first reproducing it with the
  naive shared-client approach against the local upstream before writing the extraction fix —
  the naive version returned `username=None` on every real login, silently degrading exactly the
  way the "never fail login on a fetch failure" design intends, which would have made a
  domain-mismatch bug indistinguishable from "upstream is just flaky" without checking.
- **`users.username` reconciles asymmetrically to `is_admin`, on purpose.** `is_admin` is
  re-derived unconditionally on every login (v17's pattern); `username` is only overwritten when
  the current login's `GET /user` actually returned a fresh, non-`None` value —
  `get_or_create_user`'s `if username is not None: user.username = username` guard. Reconciling
  it the same way `is_admin` does would mean one flaky upstream call blanks out a previously
  known-good display name for every page the user's jobs appear on (including in another user's
  admin all-users view) until their next successful login. Verified against the real stack by
  temporarily disabling the local upstream's `GET /user` route entirely (commented out in
  `vb2007.hu-api`'s router, reverted after) and confirming a fresh test account still logged in
  successfully with `username: null`, then re-enabling the route and confirming the very next
  login populated it correctly.
- **The upstream username-change test needs a *second* fresh login to get a live `VB-AUTH`
  token** — `vb2007.hu-api`'s `/auth/login` regenerates `user.authentication.sessionToken` on
  every successful login and persists it, invalidating any token captured from an *earlier*
  login the moment a *later* one (even through spotdl-web's own proxy) succeeds for the same
  account. A token captured, then used again after an intervening login elsewhere, gets a bare
  `{"error": "You must be logged in to perform this action."}` — not a bug, just means
  upstream-side test scripts that log in once and reuse the token across multiple steps must
  re-login (or at least re-fetch the token) immediately before each authenticated call that
  happens after another login could plausibly have occurred in between.
- **`docker compose up -d <service>...` does recreate a container whose only changed input is
  `.env`** (no `docker-compose.yml` edit needed) — confirmed by container start time jumping to
  "5 seconds ago" immediately after an `ALLOWED_EMAILS` addition, needed here to allowlist a new
  test account without restarting the entire stack.

### v26 id3-integrity gotchas (learned building tag verify/repair)

- **`app.services.downloads.get_supported_output_options()` already existed** (added in v13,
  introspects spotdl's own `--format`/`--bitrate` argparse choices) — the plan's "support what
  `get_supported_output_options()` reports" referred to this existing function, not a spotdl
  built-in of the same name (no such spotdl function exists in 4.5.2, confirmed by grepping the
  installed package). `tagging.py`'s `SUPPORTED_FORMATS` is a narrower set than what that function
  reports, though: `{"mp3", "flac", "ogg", "opus", "m4a"}`, excluding `"wav"` — see the "spotdl
  library" entry above for why WAV can't be verified with `get_file_metadata`.
- **spotdl's `get_file_metadata`/`embed_metadata` are the real read/write path** — see the "spotdl
  library" topic entry for the two gaps found (flac/ogg/opus never get a distinct "year" tag; WAV
  read-back is broken). `tagging.repair_tags` calls `embed_metadata` for everything it already
  handles correctly, then patches "year" directly for flac/ogg/opus, then re-reads the file to
  check whether cover art actually landed (spotdl's own `embed_cover` swallows fetch failures
  silently and returns the file unchanged — there is no other way to detect "did the fetch actually
  work" than reading the result back).
- **The workers must be restarted (`docker compose restart worker-dl worker-meta api beat`) to pick
  up new backend code**, even though `docker-compose.override.yml` bind-mounts `./backend/app` live
  — that bind mount makes new files visible on disk, but Celery workers/uvicorn are long-running
  processes that import modules once at startup; there's no `--reload`/autoreload wired for them
  (unlike a typical `uvicorn --reload` dev setup). Editing files with a worker already running
  silently keeps executing the pre-edit code with zero error — this cost real time in-session
  before being caught (a "fixed" bug that reappeared identically because the fix hadn't loaded).
- **An ad-hoc script invoked by absolute path (`python /tmp/foo.py`) puts the script's own directory
  first on `sys.path`, not the process's cwd** — even with `docker compose exec -w /app`, the
  bind-mounted `/app/app` loses to the stale baked-in `site-packages` copy the exact same way v11's
  entry describes for a bare `python -c`. Piping the script via stdin (`python - < script.py`) with
  `-w /app` set keeps `''` (cwd) as `sys.path[0]` instead, and does pick up the live bind-mounted
  code — confirmed by re-running the identical script both ways against the same file.
- **Importing `app.tasks.download` directly, as the first project import in a one-off script,
  raises a circular-import `ImportError`** (`app.tasks.download` → `app.tasks.celery_app` →
  `app.tasks.expand` → `app.tasks.download`, still mid-init). Every real entry point avoids this by
  loading `-A app.tasks.celery_app` first (the Celery CLI's own convention); a script calling
  `download_track` directly needs `import app.tasks.celery_app` before the `from app.tasks.download
  import download_track` line for the same reason.
- **Real end-to-end verification of all six "Done when" bullets this session**, against the real
  local stack, real Postgres, and the real Spotify→YouTube Music pipeline (search via
  `spotdl.utils.search.get_simple_songs` for a real track — never a guessed/fabricated Spotify URL):
  a real downloaded mp3 (Daft Punk — "One More Time") read back with **all six fields present**,
  verified independently via `ffprobe`; the same file's tags deliberately stripped with a raw
  `mutagen.id3.ID3(...).delete()` call (independent of `tagging.py`), then repaired by the real
  `tagging.repair_tags` using a real `Song` object, re-verified via `ffprobe` afterward; a track
  whose `song_json.cover_url` was patched to an unreachable host (ABBA — "Dancing Queen") completed
  successfully with the audio intact, no video/cover stream in `ffprobe`'s output, and a
  `track_attempts` row reading `"tag warning: cover art missing: fetch from Spotify failed or no
  cover art available"`; a second format (Fleetwood Mac — "Dreams", flac) round-tripped correctly
  *and* exercised the flac year-tag-gap repair for real (`missing tags ['year'], repairing` in the
  worker log, confirmed present afterward via `ffprobe`); a wav download (The Cure — "Friday I'm In
  Love") logged `format .wav not supported for tag verification, skipping` and completed normally.
  This network's YouTube bot-check (the same one v23/v29 already document) made roughly half of
  real download attempts this session fail with the pre-existing `NO_OUTPUT` symptom — unrelated to
  this version, retried with a fresh track each time rather than chased.
- **One unexplained anomaly, not reproduced, not blocking**: during this session's testing, one
  track (a "Coldplay — Yellow" test job, submitted through the real API while manually pausing/
  patching/unpausing the worker via direct DB writes to force a specific timing window) ended up
  `completed` in the database with a plausible `output_path` and a real-looking ~9-second
  `track_attempts` row, but the file was never actually present on disk, and `docker compose logs
  worker-dl` never showed a "received"/"succeeded" pair for that specific task invocation even after
  the container had been up for over an hour with no restarts. Every other real attempt this session
  (including several using the identical pause/patch/retry technique afterward) showed fully
  consistent DB/filesystem/log state. Given it appeared exactly once, under a test methodology that
  itself does something no real user flow ever does (writing directly to `WorkerState`/
  `Track.song_json` mid-flight from a separate DB session while the real worker is running), this
  reads as a testing-harness artifact rather than a `download_track`/tagging defect — `tagging.py`
  never touches file existence or deletes anything, so it can't be the cause even in theory. Flagged
  here rather than silently dropped; if it recurs under normal (non-test-harness) operation, it's
  worth a dedicated investigation, but not chased further in this version given the `download_track`
  code path itself has ordinary, well-covered failure modes and this doesn't match any of them.
  *(2026-10-19, v48: closed, not reproduced under normal operation. A real 11-track album on the
  dev database with normal pacing left every `COMPLETED` track's file at its `output_path`
  (`stat` inside `worker-dl`, 11/11 present); see the v48 section.)*
- **Deferred, found by fresh-eyes review**: a tag warning reuses `TrackAttempt.error_message` on a
  `COMPLETED` outcome (per the plan's "reuse the attempt row" instruction), but the only consumer,
  `frontend/src/lib/components/TrackRow.svelte:174-176`, renders *any* non-null `error_message`
  through `.attempt-error` (`color: var(--fail)`, the same red used for genuine failures) regardless
  of `outcome` — so a track that downloaded fine but had a cover-art fetch fail displays a green
  "completed" badge next to failure-red text. The plan didn't ask for a frontend change here and
  v26 doesn't touch the frontend at all (`package.json`'s version bump is the only frontend diff),
  so left as-is rather than expanded out of scope — worth a small dedicated fix (outcome-aware
  styling, or a distinct "warning" tone) whenever a version next touches `TrackRow.svelte`.

### v27 file-downloads gotchas (learned building `GET /api/tracks/{id}/file`)

- **`_resolve_track_file_path` reads the `downloaded_tracks` ledger (keyed on `spotify_track_id`)
  before falling back to `Track.output_path`, deliberately** — both `COMPLETED` and
  `SKIPPED_DUPLICATE` set `Track.output_path` directly (`download_track`, `app/tasks/download.py`),
  but the ledger is the field the master-v3 invariants say v28's library move will repoint, not the
  per-track column. Reading the ledger first is what lets this endpoint "keep working unchanged"
  once v28 starts moving files, per the plan's own explicit requirement — verified now with a test
  where the ledger and the track's own `output_path` deliberately disagree
  (`test_download_track_file_prefers_ledger_path_over_track_output_path`), proving the ledger wins.
- **The path-traversal guard needs no filesystem access, and `api` gets no `/downloads` mount at
  all** — `Path(...).resolve(strict=False)` on an absolute, possibly-nonexistent path is purely
  lexical (no I/O), so confirming a candidate path is `is_relative_to` the configured downloads
  root doesn't require the file (or even its parent directories) to actually exist in this
  container's mount namespace. Only `web` (nginx) needs the real mount, since it's the one that
  actually serves bytes — see the compose diff.
- **Two real bugs surfaced by fresh-eyes review, both fixed and re-verified against the real
  running stack** (not just re-run through pytest):
  1. `_content_disposition`'s ASCII fallback stripped non-ASCII bytes but not non-printable ones,
     so a filename containing a literal CR/LF crashed a real running `api` container's response
     (confirmed via direct curl to the container's published port, both before and after the fix)
     instead of the clean 404/200 this endpoint is supposed to guarantee either way — see the "File
     serving & HTTP headers" topic entry for the general lesson.
  2. `downloadTrackFile` (`frontend/src/lib/api.ts`) treated any `response.ok` as success, so under
     the local dev override (Vite fronting `web`, not nginx — see the Compose topic entry) a
     download silently "succeeded" with a real, correctly-named, 0-byte file. Fixed with a
     `blob.size === 0` guard, kept in place as a backstop.
- **The `blob.size === 0` guard above was the wrong place to stop** — the project owner hit the
  resulting "Downloaded file was empty" error on their own very next live test, immediately after
  this PR's "merge-ready" review pass. A documented, "this is a known accepted gap" tradeoff still
  reads as a broken feature to the person actually using it day to day; asked directly, the owner
  chose to close the gap rather than leave it documented. Fixed with `vite.config.ts`'s
  `devFileDownloadFallback` — a dev-only Vite middleware (registered only under `command ===
  'serve'`, so it's genuinely absent from `vite build`'s output) that intercepts exactly
  `/api/tracks/{id}/file`, makes its own request to `api`, and — when the response carries
  `X-Accel-Redirect` — serves the real file itself from the same `/downloads` mount, instead of
  forwarding the meaningless-to-Vite empty body. This needed `docker-compose.override.yml`'s own
  `web` volumes fixed alongside it: it had been *merging* the base file's `downloads:/downloads:ro`
  (a separate, permanently-empty, Docker-managed named volume — never the real files) instead of
  `!override`-ing to the real `./downloads` host bind the way worker-dl/worker-meta already do, so
  the new plugin would otherwise have 404'd against an empty mount regardless. Re-verified against
  the real running dev-override stack afterward: owner download (exact sha256 match), unauthenticated
  401, stranger 404, corrupted-path 404, and missing-file-on-disk 404 all pass through the Vite
  fallback identically to how they pass through real nginx.
- **Real end-to-end verification this session, against the real local stack** (real Postgres, real
  files already on disk from earlier versions' own testing — no fresh download was run purely for
  this version, since v23/v26 already prove the download pipeline itself and v27 only adds a
  read/serve path over files that already exist): a standalone nginx container built from this
  version's own `frontend/Dockerfile`, attached to the running compose project's network and
  mounted read-only at the real `./downloads` host path, alongside two identities that went
  through the *real* upstream login (`https://api.vb2007.hu`, since the local instance wasn't up
  this session) — the existing admin (`balazs@vb2007.hu`) and a non-admin test account
  (`spotdlwebtestv22@example.com`) — plus one direct-session-mint stranger identity. Confirmed:
  owner downloads a real file with an **exact sha256 match** against the file on disk; a stranger
  gets 404 on that same track id; the admin gets 200 on it too; a corrupted `output_path` pointing
  at `/etc/passwd` and at a `../`-escaping relative path both 404; a track whose recorded path
  doesn't exist on disk 404s; a retention-archived job's track still downloads; curling the
  `internal` nginx location directly from outside returns 404; and — via a real Chromium driven by
  Playwright (the cached browser at `~/.cache/ms-playwright/`, per the v13 entry) — a non-ASCII
  track (`ADÉLA - Ain't In LA.mp3`) downloads through the real UI with `download.suggestedFilename()`
  correctly reading `ADÉLA - Ain't In LA.mp3` and an exact sha256 match on the saved bytes. All
  test DB rows (jobs/tracks/the one throwaway stranger user) deleted afterward; `.env`'s temporary
  `UPSTREAM_AUTH_BASE_URL` override reverted and the `api` container recreated once more to restore
  the pre-session state.

### v28 library-sort-move gotchas (learned building the admin-only sort & move sweep)

- **`reconcile_disk()`'s v12 mount-not-attached guard was originally left unextended for the new
  library root — caught only by fresh-eyes review, not the author's own real-stack testing.** The
  author's own live verification happened to run against a stack where both mounts were healthy the
  whole time, so the gap never surfaced. The fix is per-root, not a second blanket check: skip
  pruning only the ledger rows whose `file_path` actually lives under whichever specific root
  (`download_output_dir` or `library_target_dir`) looks missing/empty, rather than refusing to prune
  *anything* the moment either root looks bad. A blanket "refuse if either root is unhealthy" version
  was tried first and rejected — a freshly deployed/dev instance where v28's sweep has simply never
  run yet has a genuinely empty `library_target_dir` by construction, and a blanket check would
  permanently block the far more commonly needed downloads-root reconciliation until the first sweep
  ever succeeds. Regression tests: `test_reconcile_disk_skips_only_library_rooted_rows_when_library_dir_missing`,
  `test_reconcile_disk_prunes_downloads_root_normally_when_library_never_used`.
- **Per-row DB commit ordering matters for crash safety, and the first draft got it backwards.**
  The original per-row loop did `unlink()`/`quarantine()` the source *then* commit the ledger
  repoint in a shared `finally` a few lines later — a worker crash/OOM/redeploy in that window
  leaves the DB still pointing at a now-deleted source path with `in_library` still `False`, and
  the *next* sweep (or `reconcile_disk()`) finds nothing at that stale path and either records a
  permanent "source missing" error or silently drops the ledger row — exactly the re-download
  exposure this whole app exists to avoid, and the file is still sitting there, correctly moved,
  completely untracked. Fixed by committing the ledger repoint (`file_path` + `in_library`)
  **immediately after** the copy is verified (or the pre-existing target is confirmed) and
  **before** the source is ever deleted or quarantined — a crash in the new gap between that commit
  and the delete instead just leaks a redundant source file (recoverable manually, `find
  <downloads> -newer <ledger repoint time>` or similar), which is a far better failure mode.
- **"Already exists" (folder+filename, content-blind) has two genuinely different cases that look
  identical in code but must not be handled identically: a file already there from *before this
  sweep started*, vs. two different tracks whose destinations collide *within the same sweep*.**
  The plan's dedup rule (`v28-library-sort-move.md` rule 3) is explicitly about the first case —
  a pre-existing library file (manual import, an earlier sweep, a bitrate re-download) correctly
  absorbs the "duplicate" without content comparison. Naively applying the exact same `dest.exists()`
  check to the *second* case means the second of two same-sweep colliding tracks (e.g. two
  genuinely different songs that both predate v28's track-numbered filename template and happen to
  share a generic name under the same artist/album/year) gets treated as a duplicate of the first,
  silently repointing its ledger row onto the *first* track's file and quarantining/deleting its
  own, actually-different audio — permanent data loss with no error surfaced. Fixed by tracking
  every destination this sweep has already claimed (`spotify_track_id` -> `Path`) and treating a
  second, different-track claim on the same path as an **error**, never a merge. Verified against
  real audio (two ledger rows pointing at two copies of the same real downloaded file under
  different source paths but an identical basename): the first moves normally, the second is
  recorded in `run.errors` as `"destination collides with track <id> moved earlier in this sweep"`
  and its own source file is left completely untouched (`test_sort_library_flags_intra_sweep_destination_collision_as_an_error`).
- **A crash anywhere outside the per-row loop (settings load, the ledger query itself, or the
  post-loop `Track.output_path`/job-archival sync) left `library_sort_runs.state` wedged at
  `running` forever, permanently 409-ing every future sweep with no recovery short of a manual DB
  edit.** The per-row loop already had its own try/except; nothing wrapped the rest of the task
  body. Fixed with two layers: `_sync_tracks_and_archive_jobs`'s call is wrapped so a failure there
  (secondary bookkeeping — the ledger repoints that actually matter are already committed per-row by
  that point) records an error and still lets the run finish `idle`; and the whole sweep body is
  wrapped in an outer try/except that resets `state` to `idle` and records a top-level error on any
  other uncaught exception. Both paths verified with a monkeypatched crash
  (`test_sort_library_resets_to_idle_when_sync_and_archive_raises`,
  `test_sort_library_resets_to_idle_when_settings_load_raises`).
- **`POST /api/library/sort`'s "already running" check was a plain read-then-write with no lock** —
  two concurrent triggers (e.g. an admin double-clicking the "start sweep" button) could both
  observe `idle` before either commits `running`, dispatching two sweeps against an overlapping
  ledger snapshot. Fixed with a real `SELECT ... FOR UPDATE` (`db.get(..., with_for_update=True)`)
  on the singleton run row, so the second request blocks until the first's transaction commits and
  then correctly sees `running`. Not hardened against the one-time race before any run row exists at
  all (nothing to lock yet) — an astronomically narrower window than the routine double-click case,
  and not practically testable against SQLite's single in-process test session anyway (real
  concurrent-transaction locking needs the real Postgres stack, per this file's existing "Direct-DB
  tests of beat behavior race the real beat container" entry).
- **v27's file-serving endpoint needed a real code change, not just "the ledger already handles
  it"** — the master plan's own critical-interactions section predicted this, and it was still an
  easy miss: `download_track_file` (`app/routers/tracks.py`) had exactly one allowed root
  (`download_output_dir`); a track moved into `library_target_dir` fell entirely outside it and
  404'd. Fixed by accepting either root and picking the matching nginx `X-Accel-Redirect` prefix
  (`/internal-downloads/` vs. the new `/internal-library/`). This needed three coordinated changes,
  not one: the FastAPI endpoint's dual-root resolution, a second `internal` location block in
  `nginx.conf` aliasing `library_target_dir`'s default path, **and** `vite.config.ts`'s
  `devFileDownloadFallback` (the v27-era dev-only Vite middleware that stands in for real nginx
  under `docker compose up`'s override) — missing the third one specifically produced a silent
  404 in local dev even after the first two were correct, caught only by an actual curl against the
  real running dev stack, not by pytest (which never exercises Vite at all).
- **A stale image tag from an earlier non-override build silently shadowed the dev Vite image.**
  After adding a new bind mount to `docker-compose.override.yml`'s `web` service, `docker compose up
  -d` recreated the container but reused whatever image was last built under the plain
  `spotdl-web-web` tag — which, on this machine, was a previous **prod-style** build (the final
  nginx stage, no `npm`), not the override's own `target: build` stage. The container crash-looped
  with `exec: npm: not found`. `docker compose up -d` alone never rebuilds; `docker compose build
  web` (respecting the override's `target: build`) followed by `docker compose up -d web` fixed it.
  Same root cause as this file's existing "`image:`/`build: !reset null` must repeat on every
  service..." entry, just triggered by a stale cache instead of a config gap — worth remembering
  that *any* mid-session compose-file edit to a service's `build`/`volumes` can require an explicit
  rebuild, not just a recreate, if that image tag has ever been built a different way before.
- **Deferred, found while triaging fresh-eyes review (not fixed this version): a disk-full/I/O
  failure mid-`copy_verify` leaves a partial, corrupt file at `dest` that the *next* sweep attempt
  would silently adopt as though it were a legitimate pre-existing library file.** `copy_verify`
  correctly leaves a failed copy in place rather than deleting it (`library.py`'s own docstring:
  "nothing is ever deleted on the target filesystem, not once, not under any flag"), and the ledger
  row correctly stays un-repointed on that first attempt (satisfies the plan's own "Done when"
  bullet as literally tested: source intact, ledger unchanged). But retrying that same row later
  computes the identical `dest`, finds it already exists, and — because "already exists" is
  deliberately content-blind (rule 3) — treats the corrupt partial as a genuine duplicate: quarantines
  or deletes the actually-good source and repoints the ledger onto the corrupt file. Distinguishing
  "our own failed leftover" from "a real pre-existing library file" would need some content signal,
  which directly contradicts the plan's explicit content-blind design — a real tension in the plan
  itself, not a straightforward coding bug, and not observed in this session's real testing (would
  need an actual disk-full/IO fault mid-copy to trigger). Flagged here rather than silently dropped,
  for whichever version next touches this path (v30's hardening close is the natural owner).
  **Fixed, v31**: `copy_verify` now renames (never deletes) its own failed copy off the exact
  destination filename on a checksum mismatch — see this file's own v31 section.
- **Real end-to-end verification this session, against the real local stack** (real Postgres, a
  throwaway `./test-library` directory bind-mounted over `worker-meta`/`web` — never the live
  ~120k-track directory, per the plan's own testing rule): real downloaded files already on disk
  from earlier versions' testing were used as ledger rows (real tags read via `tagging.read_tags`,
  e.g. Muse — "Ruled by Secrecy" resolving to `Muse - Absolution - (2004)`); a real sweep moved
  three files, repointed their ledger rows and one real `Track.output_path`, and archived that
  track's job; a fourth, cross-user job (a second, non-admin test identity's job) was archived in
  the same sweep, confirmed via direct DB read and its own `job.state` SSE event; the moved track
  was re-downloaded through the real dev stack's `X-Accel-Redirect`/Vite-fallback path with an
  **exact sha256 match**; a real folder+filename conflict was exercised both with quarantine on
  (source moved to `./downloads/quarantine`, pre-existing target file byte-for-byte untouched) and
  off (source deleted directly, target still untouched) using deliberately different-content files
  standing in for a different-bitrate re-download; `reconcile_disk()` was run for real via a
  `worker-meta` restart both before and after the fixes above, confirming all moved rows survive
  (`checked N ledger rows, removed 0`); the real intra-sweep collision case was reproduced with two
  ledger rows pointing at two copies of the same real file under an identical basename; `docker
  compose config` validated for both dev and prod, confirming the library mount resolves to exactly
  one bind target per service with no merge conflicts; and the raw SSE stream was captured live
  (`curl -N /api/stream`) during a real sweep, showing `library.progress` events with `done: true`
  on completion. All ad-hoc test ledger rows/jobs/users were created under clearly-named
  `v28-*`/`*testv28*` identities, never the real `ADMIN_EMAIL` account.

### v29 network-path-escalation gotchas (learned building the IPv4/IPv6 escalation rung)

- **The plan's own claim that `track_attempts` "already carries the nullable network-path column
  reserved by v24" was stale/wrong** — checked against the real model, the real v24 migration
  (`5ae734a0485b_add_track_attempts_table.py`), and the real installed schema before writing a
  single line: no such column exists anywhere. v24 never reserved one. Added fresh in this version's
  own migration rather than assuming the plan's premise — exactly the "verify a referenced
  file/function still exists before acting on it" rule this file's own header states.
- **A brand-new native enum column added via a plain `op.add_column` (not as part of
  `op.create_table`) needs an explicit `.create(op.get_bind(), checkfirst=True)` first, or the
  `ALTER TABLE ... ADD COLUMN` fails against real Postgres with `type "..." does not exist"`.**
  Every prior enum in this project was created as a side effect of its own table's `create_table`
  (which auto-creates the type); this is the first one added to an *existing* table on its own.
  Confirmed by actually running the migration against the real dev Postgres, not assumed — the first
  draft failed exactly this way. Downgrade still needs the usual explicit `DROP TYPE` (CLAUDE.md's
  standing enum invariant), unaffected by this.
- **Two independent mechanisms are needed to force an IP family across yt-dlp's and ytmusicapi's
  stacks, because only one of them exposes a knob for it.** yt-dlp's own `-4`/`-6` (via spotdl's
  `yt_dlp_args` option, merged through `args_to_ytdlp_options`) is real and verified safe against the
  installed source: that function's merge logic only lets a bare-default flag's value through when
  the flag didn't already change it, so `-4`/`-6` can't clobber the deno `js_runtimes` options this
  app also depends on (v23). But ytmusicapi's client is built with a hardcoded `YTMusic(language="de")`
  (`spotdl/providers/audio/ytmusic.py`) — no family/session override exists on that call at all — so
  `network_path.force_family` instead monkeypatches `socket.getaddrinfo` process-wide for the
  duration of a single attempt, which covers *both* stacks since both ultimately resolve DNS through
  it. Safe only because `worker-dl` is `--concurrency=1`; guarded with a re-entrancy lock that raises
  loudly rather than silently leaking one attempt's forced family into another's.
- **`force_family`'s restore path must snapshot `socket.getaddrinfo` locally at entry, not read it
  back from the module-level `_real_getaddrinfo` name at exit.** The first draft restored from that
  module attribute directly; a test that monkeypatches `_real_getaddrinfo` (to avoid making real DNS
  calls) then leaves `socket.getaddrinfo` pointed at the test's own fake function *process-wide*
  once the context manager exits — a real test-isolation bug caught by the test's own assertions
  failing, not by inspection. Fixed by capturing `previous_getaddrinfo = socket.getaddrinfo` at
  entry and restoring exactly that in `finally`.
- **Real per-stack proof needed two different techniques, not tcpdump (unavailable in this sandbox
  session).** A `socket.socket.connect` monkeypatch recording every `(family, address)` the process
  actually dialed, wrapped around (a) a real `requests.get()` (standing in for ytmusicapi's own
  session mechanism) and (b) a real `yt_dlp.YoutubeDL(...).extract_info(...)` call built with the
  real `args_to_ytdlp_options(["-4"]/["-6"], ...)` merge `get_downloader` uses — both against real
  YouTube/Google traffic, nothing mocked. Forcing IPv4 connected successfully to a real Google IP for
  both stacks. Forcing IPv6 correctly restricted *every* connection attempt to IPv6-only addresses
  for both stacks (confirmed zero IPv4 addresses ever attempted), and then failed at the network
  level — this local dev sandbox has no real IPv6 route (`curl -6` to youtube.com times out here),
  separately confirmed via SSH that the actual production host *does* have real, working IPv6
  connectivity. This is the correct, honest result for this environment: the forcing mechanism is
  proven correct independently of whether this specific box's uplink can complete the connection.
- **Editing `docker-compose.override.yml` to enable IPv6 on the project's default network
  (`enable_ipv6: true` + an `ipam.config` subnet) recreates the Docker network, and any already-running
  container *not* otherwise recreated by that same `docker compose up` is left attached to nothing —
  its embedded-DNS-based service-name resolution (e.g. `redis`) breaks with `socket.gaierror: Name
  or service not known` even though the container itself keeps running and looks "healthy" in
  whatever state compose last observed.** Confirmed live: after this edit, `api`/`beat`/`worker-dl`/
  `worker-meta` were recreated onto the new network (compose detected their command/environment
  needed no change but *something* triggered recreation) while `redis`/`web` initially were not,
  and `api`'s health check started failing on real Redis DNS lookups. A full `docker compose down`
  followed by `docker compose up -d` (not just another `up -d`) put every container on the same,
  consistent network and resolved it. **Any future compose network-level change (not just this one)
  should be verified with a full down/up on the real stack, never just `up -d` again**, and checked
  against real service-to-service DNS (not just container health) before considering it safe.
  Confirmed harmless for docker-compose.prod.yml -- `docker compose -f docker-compose.yml -f
  docker-compose.prod.yml config` never sees this override-only change at all.
- **A significant, unrelated-to-this-version bug was found while proving each rung's mechanism
  empirically**: the existing proxy escalation rung has never actually routed real traffic through a
  configured proxy, for either HTTP stack, since v07. See the v07 section's own corrected entry above
  and `plan/master-v3/v30-proxy-routing-fix.md` — inserted as its own version per the owner's explicit
  direction rather than folded into this one, since it's a correctness fix to a rung that already
  existed, not part of adding the new ones.
- **Caught by this version's own mandatory fresh-eyes review, not the author's real-stack testing**:
  the first draft set `chosen_path = NetworkPath.PROXY` unconditionally *before* calling
  `proxies.pick_proxy(db)`, rather than deriving it from what that call actually returned.
  `pick_proxy` returns `None` whenever every proxy is disabled or in cooldown — routine for a
  personal tool's handful of proxies, not an edge case — and when that happens the real attempt is
  an unforced, un-proxied direct connection, while `track_attempts.network_path` still recorded
  `'proxy'`. Directly violated this version's own "Done when" bullet (network_path must record the
  path actually *used*). The one existing test built for exactly this branch
  (`test_download_track_retry_falls_back_to_direct_when_no_proxy_available`) captured `proxy` but
  never asserted on `network_path`, which is why it shipped once already. Fixed by deriving
  `chosen_path` from `pick_proxy`'s actual return value, falling back to a forced `DIRECT_IPV4` (not
  an unforced connection) so the fallback stays deterministic the same way attempt 1 already is.
  Re-verified against real Postgres with `pick_proxy` forced to return `None`.
- *(2026-10-26, v55: no longer accepted. Where IPv6 isn't routable the rung is skipped (a cached
  UDP route probe, `network_path.ipv6_routable`), and attempt 2 takes the proxy rung.)*
  **Accepted, not fixed: forcing the IPv6 rung unconditionally costs one extra ladder wait per
  retrying track in any environment where IPv6 isn't actually routable yet.** At the time this
  version shipped, that was every currently-deployed environment (production's daemon change was
  deliberately deferred). **Correction, v31:** production's own IPv6 rollout has since happened, as
  a separate follow-up (PR #39, `docker-compose.prod.yml`'s `enable_ipv6`/`ipam.config` block,
  `docs/DEPLOYMENT.md` updated to reflect it as applied) — the "every currently-deployed
  environment" framing above is now stale for production specifically; this whole paragraph's cost
  analysis still applies to any environment where IPv6 genuinely isn't routable (a fresh local dev
  setup, say). Attempt 2 reliably fails fast (`OSError`, classified
  `OTHER`, doesn't trip the breaker) rather than reaching the proxy rung immediately, pushing the
  first proxy attempt from attempt 2 to attempt 3 and adding one ladder step's delay
  (`retry.next_delay(1)`, currently 1h) before it. This is the plan's own explicit design (`v29-*.md`:
  "escalation-only is the conservative start and what this plan assumes"), not a bug, and resolves
  itself once IPv6 is actually enabled per this file's rollout section — flagged here because a
  fresh-eyes reviewer correctly asked whether the owner still wants it live exactly this way in the
  meantime, and the answer wasn't re-litigated as part of this version.

### v30 proxy-routing-fix gotchas (learned making the proxy rung actually route real traffic)

- **Patching `YouTubeMusic._create_client` alone is not enough — a real end-to-end run caught this,
  not a unit test.** `get_downloader`'s cache means a `Downloader` (and its already-constructed
  `YouTubeMusic` provider) can outlive many attempts; `YouTubeMusic.__init__` calls
  `self.client = self._create_client()` exactly once, at construction time, which happens in
  `download.py` *before* `force_proxy`'s context is ever entered. The first version of `force_proxy`
  patched only the classmethod (so a *future* client rebuild would pick up the proxy) and passed
  every one of its own unit tests, since those tests called `_create_client()` directly rather than
  going through an already-built provider. The very first real run against the live stack (a real
  credentialed proxy, `socket.socket.connect` observation, ytmusicapi's `get_results` called on a
  real cached-Downloader-shaped provider) showed one connection going straight to a real Google IP
  before two others correctly hit the proxy — the search succeeded on its first attempt, so
  `YouTubeMusic.get_results`'s own "rebuild the client and retry" path (the only place that would
  have called the patched classmethod) never ran. Fixed by having `force_proxy` also reach into
  `downloader.audio_providers`, swap `.client` on every `YouTubeMusic` instance directly for the
  duration of the attempt, and restore the original object on exit. **Any future context manager
  that patches a classmethod meant to affect an object that might already be constructed and cached
  must also patch the existing instance directly** — patching only the constructor is invisible to
  anything built before the patch went active.
- **Verified against the real running stack, real credentialed proxies from `proxies.txt`, nothing
  mocked**: a `socket.socket.connect` monkeypatch (same technique v29 used) recording every real
  connection during (a) a real `ytmusicapi` search, (b) a real `yt-dlp` `extract_info` metadata
  fetch, and (c) three full, real `Downloader.search_and_download()` attempts against three
  different real Spotify tracks/proxies — every single observed connection for the audio-provider
  path (search + download) went to the configured proxy's address, zero went to origin. The
  no-proxy control path (attempt 1/2 of the ladder, `force_proxy(None, ...)`) was separately
  confirmed to still connect directly, unaffected.
- **All 5 of this project's real configured proxies failed the actual media-stream download step**,
  each for its own distinct, already-documented, orthogonal reason: `HTTP Error 403: Forbidden` (x2),
  YouTube's bot-check challenge ("Sign in to confirm you're not a bot"), `407 Proxy Authentication
  Required` (a stale/duplicate `proxies.txt` entry), and a `LookupError` (search returned no usable
  result through that specific proxy). None of these is a routing bug — every failure happened *after*
  the connection log confirmed the attempt actually reached the proxy address, not origin. This is
  the exact IP-reputation/bot-check gap `CLAUDE.md`'s "Proxy escalation does not cover IP-reputation
  bot-checks" invariant already documents (proven in v23/v29): now that the proxy rung genuinely
  routes traffic, it inherits that gap for real, rather than never encountering it at all. **A real,
  fully successful end-to-end download through one of these specific 5 proxies was not achieved this
  session** — the fix's own correctness (does the connection reach the proxy) is proven independently
  of whether any specific cheap datacenter proxy is currently good enough to fool YouTube's own
  defenses, the same reasoning v29's IPv6-forcing entry above already applied to its own environment
  limitation.
- **Every proxy's `last_success_at`/`consecutive_failures`/`cooldown_until` value recorded before this
  version landed reflects direct-connection health, not proxy health**, and should be treated as
  meaningless once this ships — no migration needed (the columns were always correctly typed for
  their *intended* meaning), just a fact worth knowing before reading history off a live/deployed
  `proxies` table older than this version.
- **Deferred, not fixed this version**: `download_track`'s credential-redaction guard
  (`download.py`'s except-block, `if proxy_url in error_message: ...`, shipped in v07) is an exact
  substring match against the full `scheme://user:pass@host:port` string. Before this version, the
  proxy rung never actually reached a real connection, so this guard was essentially never exercised
  against a real proxy-related exception. It now is, for the first time — a fresh-eyes review
  correctly flagged that a `requests`/`urllib3` `ProxyError` or a yt-dlp network exception isn't
  guaranteed to embed the credentialed URL in exactly this form, which could in principle let a raw
  URL slip past the guard. **Checked against this session's own 5 real proxy failures** (403,
  YouTube's bot-check text, a 407 auth error, and a `LookupError`) — none of the real captured
  messages embedded the proxy URL in any form, so this hasn't manifested in practice. Left as-is:
  this guard is pre-existing v07 logic this version's plan explicitly didn't touch ("this fix changes
  whether the proxy is used, not the ... logic around it"), and hardening it into a
  pattern-based (not exact-string) redaction is a good candidate for v31's hardening pass, not a v30
  regression. **Fixed, v31**: see this file's own v31 section — `proxies.redact_text()`.

### v31 v3-hardening gotchas (learned closing out master v3: the cross-user sweep, three
named-candidate fixes from v24/v28/v30, a real production connection leak, a real v30 regression,
a core correctness gap in `download_track` itself, and doc reconciliation)

- **The single most important, and least-resolved, finding of this version — found only because
  task 4 insists on a real album downloading end to end rather than trusting the DB:
  `download_track` marked tracks `COMPLETED` — real ~10-20 second attempts, sometimes with a real
  proxy, real `TrackAttempt` rows — whose files never existed anywhere on disk. This was not a rare
  edge case: an audit of every `downloaded_tracks` ledger row created this session (26 rows, a mix
  of singles and every one of a real 20-track album) found **zero** whose recorded `file_path`
  actually existed, checked both from `worker-dl` (the container that actually writes files) and
  from the real host bind mount.**

  **What this is not**, ruled out directly: not the local/prod shared-database cross-environment
  hazard this file's own dev/prod-DB entry describes (Redis — and therefore the actual Celery task
  execution — is never shared between environments, confirmed by watching these exact tasks run to
  completion in this session's own `docker compose logs worker-dl`, with real per-track search/
  download/proxy log lines); not spotdl reporting `None` (already handled, a different code path);
  not a disk-space or permission problem (86G free, correct uid ownership throughout). **A
  hypothesized mechanism that turned out to be wrong, recorded so it isn't retried the same way**:
  spotdl's output-template renderer (`spotdl/utils/formatter.py`) does replace `{track-number}`
  with an empty string when a song's `track_number` is `0`/`None`, which looked like it explained one
  observed case (a file present on disk under a name missing its `"05 - "` prefix) — but a live,
  isolated re-fetch of that exact track's metadata immediately afterward returned a perfectly normal
  `track_number: 5`, contradicting the theory as the general explanation. Repeated attempts to
  force a second, cleanly-observed success (direct call to `download_one` in isolation, checking
  `Path.exists()` in the same process immediately on return) were blocked by this network's own
  real rate-limiting exhausting every configured proxy in turn during this session's investigation
  window — a real, currently-live condition, not a test artifact, and consistent with this file's
  own IP-reputation findings from v23/v29/v30. **Root cause not found this session.**

  The reason this went unnoticed for as long as it did: the v26 tag-verification step
  (`tagging.verify_tags`, which *does* touch the file) was wrapped in a broad `except Exception`
  specifically so a tagging bug could never fail an otherwise-good download — but that same guard
  silently swallowed the `FileNotFoundError` a missing file raises there too, turning "the download
  never actually happened" into an indistinguishable, harmless-looking "tag warning" on a track the
  rest of the code then marked `COMPLETED` anyway. **Fixed, as a correctness floor rather than a
  root-cause fix**: `download_track` now checks `output_path.exists()` immediately after the
  existing `output_path is None` check and *before* tag verification ever runs, raising the same
  `NoOutputFileError`/`NO_OUTPUT` classification (so it correctly feeds the breaker and re-enters
  the retry ladder) instead of ever reaching the tagging step on a file that was never written.
  Given this was found to be universal this session, this fix's honest consequence is that **no
  track may currently be able to reach genuine `COMPLETED` at all** until the real root cause is
  found — correctly retrying forever rather than lying is still strictly better than the status quo
  ante, but this is flagged as the clearest, most urgent priority this file has ever recorded for
  the very next session, ideally with its own dedicated time budget rather than as a side-thread of
  another version's own work (which is exactly how this session lost significant time to it).
  **Second update, same session, with `strace` (installed via `sudo pacman -S strace` — this
  sandbox didn't have it): the mystery is not "the file gets deleted."** `strace -f -e
  trace=unlink,unlinkat,rename,renameat,renameat2` attached to *both* the celery parent and its
  actual prefork worker PID (`docker top` to find the real child — the container's PID 1 alone
  isn't the task-executing process) captured **zero matching syscalls** across a real, freshly
  reproduced `COMPLETED` track during the trace window. Combined with `/downloads`'s entry count
  never once changing all session (99 at the very start, 99 at every check since, including
  immediately after this traced completion) — the file is never created under the reported name
  at all; nothing deletes it afterward, because there was never anything there to delete. The one
  early case that looked like a real, persistent file (`Pharrell Williams - Happy...mp3`, no
  `track-number` prefix) is now suspect for a much more mundane reason: that exact filename could
  already have existed from a prior, unrelated local test session — `/downloads`'s entry count
  never actually grew to confirm a new write happened, which this session should have checked
  immediately and didn't.

  Repeated, isolated, direct `downloads.download_one()` calls (bypassing `download_track`/Celery
  entirely, run back-to-back against several different known-good tracks, with and without a
  proxy) made **immediately after** this finding **all failed honestly** — real `AudioProviderError`s,
  a real `None` return, no phantom success to inspect. This network's own IP-reputation problem
  (documented since v23/v29/v30) reads as significantly worse right now than earlier in this same
  session, plausibly *because of* this session's own unusually high request volume (many rapid
  manual retries, direct out-of-band `download_one()` calls competing with the real
  `--concurrency=1` worker for the same IP/proxies). **This session could not, in the time
  remaining, force and directly observe a fresh, cleanly-isolated success to inspect the exact
  moment `search_and_download` claims one** — every attempt after installing `strace` failed at
  the network layer before ever reaching that code path. A bare `yt-dlp` CLI call (bypassing spotdl
  entirely) also hit a 403 with a "no JS runtime found" warning even though spotdl's own
  `is_deno_installed()` correctly reports the locally-installed deno as available — a real
  difference between the two invocation paths, but a red herring for this specific bug once
  confirmed spotdl's own wiring finds deno correctly; not itself the cause of a phantom success.

  Concrete next steps for a future session, revised: **do not hammer this network again for this
  specific investigation** — let real, normally-paced traffic (the actual ladder, not rapid manual
  retries) run for a while first so the IP-reputation state genuinely recovers, then attach `strace
  -f -e trace=%file` (broader than just unlink/rename — cover every file-path syscall so a write
  under a completely unanticipated name is caught too) to the real `worker-dl` prefork child
  *before* triggering a single real attempt, and watch one happen end to end without interrupting
  it. Also worth trying, per the project owner's own suggestion mid-session: running spotdl
  natively on the host (a plain venv, `pip install spotdl==4.5.2` matching `requirements.txt`,
  real `ffmpeg`) outside Docker entirely, to rule out anything overlay-filesystem- or
  bind-mount-specific — not completed this session (host Python is 3.14, newer than the pinned
  stack targets; dependency resolution wasn't attempted before time ran out).

  **Correction, v31.1, with much lower alarm than the above:** the exact ledger row this entry's own
  `strace` session found missing (`.../09 - The Weeknd - Blinding Lights.mp3`) was re-checked the
  next day, cold, with no manual retries in between — it existed, real content, correct size,
  matched by a fresh dedup lookup exactly as designed. Nothing in this codebase touches that file
  between one day and the next except the normal, patient, ladder-driven retry `beat` already runs
  every 30s regardless of anyone watching. A second, freshly-submitted, never-before-attempted
  track (the same Chopin piece this file's v31 entry used for its `strace` test) completed on its
  very first real attempt under this session's *own* patient, un-hammered testing — real file,
  correct size, all six tag fields, cover art. The most likely explanation, now that a working
  comparison point exists: **v31's own investigation was largely chasing an artifact of its own
  aggressive testing methodology** — rapid manual retries, direct out-of-process `download_one()`
  calls competing with the real `--concurrency=1` worker for the same IP, and several rapid
  `worker-dl` container restarts mid-investigation, all overlapping in ways ordinary usage never
  would. Left as "very likely, not proven" rather than fully closed — the `strace` session's own
  zero-syscalls-observed result during a live "completed" event is real evidence that doesn't
  simply vanish, and this correction doesn't re-explain it. But weighed against a clean, gentle,
  first-attempt real success the very next day, the balance tips toward "an artifact of the
  investigation, not a standing bug" rather than the reverse.
  Regression test added: `test_download_track_nonexistent_output_path_feeds_breaker`. Also required
  updating 12 existing "success"-path tests in `test_download_task.py` that mocked `download_one`
  to return a hardcoded, never-real `Path("/downloads/song-a.mp3")` — every one of them was, from
  this check's perspective, already testing a false-success scenario and just didn't know it; they
  now write a real (fake-content) file under `tmp_path` first. **The same gap existed a second way**:
  `dedup.is_already_downloaded()` also trusted a ledger row's `file_path` with no existence check,
  so a stale row (the exact shape this file's cross-environment-pruning entry above already
  describes) could mark a track `SKIPPED_DUPLICATE` against a file that doesn't exist — arguably
  worse than the `COMPLETED` case, since a duplicate-skip never even attempts a real download that
  might fix itself. Fixed the same way: returns `None` (never-downloaded) instead of a path that
  doesn't exist, without touching or deleting the stale row itself (`reconcile_disk()` stays the
  one place that mutates the ledger for a missing file, at boot).

  **Critical update, same session, after the fix above was live and restarted into `worker-dl`**:
  the exact same failure mode kept recurring on *fresh* tracks submitted after the fix — a track
  reaching real `COMPLETED` (real ~10-30s attempt duration, sometimes a real `proxy_id`) whose
  recorded file still did not exist moments later. Since `output_path.exists()` is checked
  immediately after `download_one` returns and *before* anything else runs, a track reaching
  `COMPLETED` at all is only possible if that check saw `True` — meaning either (a) the file
  genuinely exists at check time and is deleted afterward by something not yet identified, or
  (b) the fix is somehow not executing for these attempts despite being confirmed present in the
  running container's source (`docker compose exec worker-dl grep` confirmed the new line's text
  in `/app/app/tasks/download.py` throughout). Investigated and ruled out this session: a second,
  lingering "zombie" `worker-dl` node from an overlapping restart (`celery inspect ping`/
  `active_queues` showed exactly one `worker-dl@<hostname>` connected, matching the current
  container, every time this was checked); stale bytecode in `__pycache__` (found — every `.pyc`
  under `backend/app/**/__pycache__` is root-owned and dated to the original image build in
  July/August, far older than the bind-mounted `.py` sources — but a fresh `python -c` import in
  the same container always reflected current source correctly, and Python's default mtime-based
  invalidation should recompile regardless of a stale `.pyc`'s presence, so this is flagged as a
  real image-hygiene smell worth cleaning up but not confirmed as this bug's cause — **correction
  2026-10-02, v35 (f):** those root-owned `__pycache__` dirs were on the *host* dev tree, seen
  through the `./backend/app` bind mount, not in the image, whose own `/app` had none; see v35);
  spotdl's own
  `embed_metadata`/`repair_tags` doing an unsafe temp-file swap (read directly from the installed
  package source — every write is a plain in-place `mutagen`/`ID3` `.save()`, no delete or rename
  of the target path visible anywhere in that call chain). A tight, second-by-second filesystem
  watch (`ls /downloads` polled every 1s in `worker-dl` for up to ~280s, spanning submit-through-
  well-past-completion) across three separate fresh single-track attempts that each reached
  `COMPLETED` **never observed the file count change at all** — meaning by the time any external
  observer (even a 1-second-resolution poll) can look, the file is already gone, or was never
  visible to anything outside the exact process instant of the internal check. This session lacked
  `strace`/`inotifywait`/`auditd` to pin down the actual deleting party with certainty; it isn't
  installed in this sandbox and couldn't be added within this session's remaining time.
  **Status: still unresolved, more severe than first understood** — the existence-check fix is
  still correct and necessary (it stops a lie from reaching the database), but on its own it has
  **not** been shown to stop a track from reaching `COMPLETED` with no real file behind it in this
  environment. Whatever removes the file appears to act inside the same narrow window the check
  itself runs in, which is the single strongest lead for the next session: instrument
  `download_one`'s *caller* (not spotdl's own internals) with a stat/watch loop spanning from
  immediately after `search_and_download` returns through several seconds later, ideally with
  `strace -f -e trace=unlink,unlinkat,rename,renameat` attached to the live `worker-dl` process
  during a real attempt, to catch the exact syscall and its caller.
- **A genuine, currently-shipped v30 regression, found only by actually running a real album
  through the final merged code (task 4's own reason to exist): every download in a `worker-dl`
  process breaks with `YouTubeMusic._create_client() takes 0 positional arguments but 1 was given`
  the moment *any* attempt anywhere in that process's life first uses a real proxy successfully.**
  Root cause in `proxies.force_proxy`: `YouTubeMusic._create_client` is a `@staticmethod`; reading
  it off the *class* (`YouTubeMusic._create_client`) to save/restore it unwraps the staticmethod
  descriptor down to the plain underlying function — capturing exactly that plain function and
  restoring it later by assigning it straight back onto the class leaves a bare function sitting
  there, and a bare function is *itself* a descriptor: the next `self._create_client()` called on
  any instance implicitly binds `self` as an unwanted first positional argument to a function
  defined to take none. Confirmed with a two-line repro (`prev = Cls.static_method; Cls.static_method
  = prev; instance.static_method()` raises the identical `TypeError` shape) and live in this
  session: a real 20-track album's every track failed identically, one proxy-download success
  after another success, until this was fixed and `worker-dl` restarted. Fixed by wrapping the
  captured value back in `staticmethod(...)` before storing it (`previous_create_client =
  staticmethod(YouTubeMusic._create_client)`) — every existing unit test for `force_proxy` missed
  this because they all call `_create_client()` off the *class*, which stays callable either way;
  the bug only shows calling it off an *instance* with no arguments, exactly how spotdl's own
  retry-rebuild path (`YouTubeMusic.get_results`) actually calls it. New regression test added
  (`test_force_proxy_leaves_create_client_callable_as_an_instance_method_after_exit`), confirmed to
  fail without the fix and pass with it.
- **An intermittent, not-fully-root-caused anomaly, recorded honestly rather than silently dropped**:
  three separate times this session, a real failed download attempt's next `scheduled_at` matched
  `DEFAULT_LADDER_SECONDS` (900s/3600s/14400s — the *production* ladder) instead of this local
  dev's `.env`-overridden `LADDER_SECONDS=5,10,15,20,30`, on the same `worker-dl` container/process
  where every direct check (`docker compose exec worker-dl env`, and a fresh one-off `python -c
  "from app.config import get_settings; ..."` in the same container) consistently showed the
  correct override. Ruled out: container-level env staleness (`docker compose restart` doesn't
  re-resolve env, but a full `--force-recreate` was tried too and the anomaly still appeared once
  more after it); the `retry_track` endpoint itself (reads correctly, just sets `scheduled_at =
  now`); a stale-object/import mismatch (module `__file__` and settings `id()` were sane).
  A temporary debug log placed directly inside `next_delay()` then showed *correct* resolved
  settings for at least one real call in the same session, and a subsequent clean, isolated
  single-track test (a track untouched by the rest of the session's activity) got the correct 5s
  first-retry delay — so this does not reproduce on demand, and may be specific to this sandbox's
  handling of the multiple rapid worker-dl restarts/recreates performed in quick succession while
  chasing the proxy bug above, not a bug in the ladder code itself. Flagged here rather than
  investigated to exhaustion given the disproportionate effort already spent versus the bounded,
  non-corrupting consequence (a longer wait before a retry, never a wrong or lost one) — worth
  a look if a future session sees it recur with cleaner reproduction conditions.
  *(2026-10-19, v48: closed, not reproduced. One real track failing through a dead-proxy
  `worker-dl` got `scheduled_at` = failure + 5s, 10s, 15s, 20s on its four retries, exactly
  `LADDER_SECONDS=5,10,15,20,30`; see the v48 section.)*
- **The deferred idle-in-transaction connection leak (flagged in v23) is real, root-caused, and
  fixed.** `/api/stream` returns a `StreamingResponse`; Starlette doesn't tear down a
  `yield`-based dependency (`Depends(get_db)`) until the *entire* response completes, which for a
  streamed body means "whenever the SSE connection itself closes," not when the route function
  returns. `require_session`'s own `db.get(User, ...)` (issued *after* `current_session`'s commit)
  therefore sat in an open transaction for the full life of the connection — confirmed live by
  opening a real `curl -N /api/stream` connection and watching `pg_stat_activity`: a `SELECT ...
  FROM users` row sitting `idle in transaction`, clearing the instant the connection was killed.
  Fixed with a dedicated `require_session_for_streaming` dependency (`backend/app/routers/auth.py`)
  that drives `get_db` (or its test override, resolved via `request.app.dependency_overrides`) by
  hand instead of through `Depends`, closing its session immediately after the auth check rather
  than leaving it open for the stream's lifetime. Re-confirmed clean over a 23s+ open connection
  after the fix. Every other route is unaffected — a normal JSON response completes immediately
  after the handler returns, so `require_session`'s shared per-request `db` there was never the
  problem; only a route returning a genuinely long-lived response needs this treatment.
- **A real, live cross-environment data-integrity hazard, found while setting up this version's own
  local verification, not induced by it.** The shared dev/prod database's `downloaded_tracks`
  ledger was already empty (0 rows) at the start of this session, despite `tracks` holding real
  `COMPLETED` rows referencing files that don't exist in local dev's own downloads volume. The
  `worker-meta` boot log (from before this session started) showed `reconcile_disk: checked 1
  ledger rows, removed 1 with missing files` — local dev's disk reconciliation pruned a real ledger
  row because the file it pointed at only exists on the deployed instance's own, separate downloads
  volume. `reconcile_disk()`'s existing "mount looks missing" guard (v12) protects against an
  unmounted/empty root; it has no protection against a root that's mounted, non-empty, but simply
  *a different environment's files* — which is exactly local dev's shape. Not fixed this version
  (the real fix is the dev/prod DB split `CLAUDE.md`'s "Development environments" section already
  named as a deferred TODO, now overdue rather than theoretical) — `worker-meta` was not restarted
  again for the remainder of this session to avoid pruning further real rows.
  *(Corrected 2026-10-01, v32: fixed by the dev/prod database split. Local dev runs on
  `spotdlwebtest`, guarded fail-closed in `app/config.py`, so local `reconcile_disk()` only ever
  sees dev ledger rows. One correction to the record: the shared database was production's own
  `spotdlweb`. `spotdl_web`, the name in `.env.example`/`DEPLOYMENT.md`, does not exist on the
  server as of 2026-10-01. See the v32 section.)*
- **Three gaps prior versions explicitly flagged by name as "a v31 candidate," fixed:**
  1. `beat._reclaim_stale_tracks` now records a `FAILED` `track_attempts` row for the invocation it
     reclaims — snapshotting `attempt_count`/`updated_at` via a plain `SELECT` *before* the bulk
     `UPDATE`, not by reading them back from that update's own `RETURNING`. Learned the hard way:
     SQLAlchemy 2.0's ORM-enabled bulk `update(Track)` (built from the mapped class, not
     `Track.__table__`) still re-evaluates a column's Python-side `onupdate` for every row it
     touches even when that column is never named in `.values()` — the first version of this fix
     read `updated_at` straight off the `RETURNING` clause and got back "now" instead of the moment
     the track actually got stuck, silently defeating the whole point.
  2. `library.copy_verify` no longer lets a corrupt partial file (a disk-full/I/O failure mid-copy)
     sit at its real destination filename. Folder+filename "already exists" is deliberately
     content-blind (the plan's own dedup rule), so a bad copy left at the exact expected path would
     be silently adopted as "the real file" by the next sweep, which would then quarantine or
     delete a perfectly good source over it. Fixed by renaming (never deleting — the target
     filesystem invariant holds even for a copy the sweep itself just wrote) the failed copy off
     its real filename on a checksum mismatch.
  3. `download_track`'s credential-redaction guard is pattern-based now (`proxies.redact_text()`),
     not an exact match against one already-known `proxy_url` string — see this file's own v30
     section for the gap this closes. Requires an actual `user:pass@` to be present before touching
     anything, so a message with nothing to redact (the overwhelmingly common case) passes through
     completely unchanged.
- Browser-driven verification (Playwright/chromium) is not available in this sandbox — no
  `apt-get` for its system dependencies, and its browser-binary CDN download times out (a
  network-restricted sandbox, not an app problem). The v25 UI bullets that specifically need a real
  browser (status pill placement, mobile layout, keyboard focus ring) were not independently
  re-verified this session as a result — noted plainly rather than silently skipped; this project's
  own established technique for the one property that *does* need the real wire (SSE isolation) is
  curl-based anyway (`scripts/verify_separation_sse.sh`), not browser-based, and that was re-run
  clean against the real local stack with two freshly-registered real-login identities.
- Running a full `alembic upgrade head → downgrade -1 → upgrade head` round-trip check against this
  project's actual database is not safe to do from local dev anymore, for the same reason as the
  ledger-pruning finding above: local dev and the deployed instance share one physical database, and
  a live downgrade would momentarily change the schema out from under whatever the deployed instance
  is doing mid-request. Skipped this session rather than risk it — another data point for the DB
  split, not a substitute for actually doing it.

### v31.1 followup gotchas (learned closing out v31's one deferred item, plus a second,
independently-found production bug from the same conversation)

- **The real root cause of most "spotdl returned no output file for this track" failures on the
  deployed instance: yt-dlp's own default player-client choice, not an app bug and not an IP block.**
  Diagnosed live with the repo owner directly on the production host, not in this sandbox: raw
  `yt-dlp` (bypassing spotdl and this app entirely) 403'd identically to the app's own failures on
  the exact two albums that had just failed in production. The first hypothesis — this network's
  IP being reputation-flagged the same way v23/v29/v30 already documented — turned out to be wrong,
  disproven by looping the same URL through every real yt-dlp player client one at a time:
  `android_vr` (yt-dlp's own default pick here, and the *one* client that's specifically designed to
  never need a PO-token) 403'd every single time — direct, `-4`, `-6`, through a real configured
  proxy, with `deno` forced — while `android`, `web`, and `mweb` all succeeded cleanly, from the
  *same* IP, in the *same* test run. That rules out an IP-level block completely: the IP can
  clearly still talk to YouTube; only the one client the app was implicitly relying on happens to be
  broken right now. Confirmed via `spotdl --yt-dlp-args '--extractor-args
  "youtube:player_client=android,web,mweb"'` against both originally-failing albums — both
  downloaded cleanly, including the one via `music.youtube.com` (this app's actual configured
  provider). Fixed by always forwarding that same `--extractor-args` fragment through
  `get_downloader`'s `yt_dlp_args` (`backend/app/services/downloads.py`), independent of the
  family/proxy fragments already there — new `YOUTUBE_PLAYER_CLIENTS` setting (default
  `android,web,mweb`), not hardcoded, since this is exactly the kind of extractor-arms-race surface
  that will need retuning again without a redeploy. Real-stack verified: a track that needed 4+
  failed attempts the day before completed on its very first real attempt after this fix, direct
  connection, no proxy, full tags and cover art, real file confirmed on disk.
- **A reminder that a version bump needs `uv lock` run again, not just the `pyproject.toml` edit** —
  CI's `deps-sync` job caught this on v31's own PR (`uv.lock --check` failed: the lockfile still said
  the old version). `uv lock` after every version-string bump, before pushing, not after CI says so.

### v32 dev-database gotchas (learned moving local dev onto `spotdlwebtest` and adding the guard)

- **Production's real database is `spotdlweb`, not `spotdl_web`.** `.env.example`,
  `.env.dev.example` (before v32) and `docs/DEPLOYMENT.md` §2 all say `spotdl_web` for both role and
  database, and v32's own plan keyed the guard on that name. The server (`pg_database`, 2026-10-01) has
  `spotdlweb` and `spotdlwebtest`, both owned by role `spotdlweb`, and no `spotdl_web` at all. A
  guard on the documented name alone would have protected nothing. `PRODUCTION_DATABASE_NAMES` in
  `app/config.py` holds both: the real name, plus the documented one for a fresh install that
  followed `DEPLOYMENT.md` literally. The templates/DEPLOYMENT.md mismatch itself was left as is
  (out of scope: production docs).
- **The local stack had been running on production for days after `.env` was switched.** The owner
  had already pointed `.env` at `spotdlwebtest`, but the running containers were created three days
  earlier and `printenv DATABASE_URL` inside them still named `spotdlweb`. Compose bakes `env_file`
  into the container at creation, and `docker compose restart` doesn't re-read it; only a recreate
  (`up -d`, `--force-recreate`) does. Stopped at the start of v32. Lesson: verify the running
  container's env, not the file.
- **`uvicorn --reload` never exits on an import-time config error.** The reloader supervisor
  (PID 1) only watches files; the child that imports `app.main` dies on the `ValidationError` and
  the supervisor waits for a file change forever. The container stays "Up" and serves nothing.
  Every other service (celery workers, beat, `migrate`) exits non-zero on its own. Fixed by
  `sh -c "python -c '…get_settings()' && exec uvicorn …"` in the dev override only. Production runs
  without `--reload`, where uvicorn exits 1 on its own.
- **Where the guard lives, and why there.** `get_settings()` runs at import in `db.py`, `main.py`,
  `celery_app.py` and `alembic/env.py`, so a `Settings` `model_validator` stops every process before
  its first connection. `env.py` re-checks the exact URL it hands to Alembic as a second layer.
  `libpq` also accepts `?dbname=` in the query string, which overrides the path, so the guard checks
  both. An unrecognized `SPOTDL_ENV` value is refused too, so a typo can't silently disable it.
  Error messages name the database, never the URL, because the URL carries the password.
- **`alembic downgrade base && upgrade head` is clean on every revision through `e7c1f9a4d2b6`.**
  First time it was ever safe to run (no disposable database before v32). All 11 downgrades ran,
  then all 11 upgrades. A clean re-upgrade alone doesn't prove every `DROP TYPE` is there:
  `e7c1f9a4d2b6` creates its enum with `checkfirst=True`, so a leftover type would be silently
  reused. The direct check does: every migration that *creates* a native enum
  (`ebc1d43e2c21` ×5, `5ae734a0485b`, `d2f4a6b8c1e3`, `e7c1f9a4d2b6`) drops it in `downgrade()`.
  `5ae734a0485b`'s second enum reference reuses `track_error_type` with `create_type=False`, so
  it correctly drops nothing. `pg_trgm` stays installed after `base` by design
  (`b6dde562e77a`'s own comment).
- **A fresh dev database re-seeds through the app's normal paths.** `users` rows come back on first
  real login (admin from the dev `.env`'s `ADMIN_EMAIL`, a test account), file-sourced proxies on
  `worker-meta` boot (`sync_from_file: 5 in file, 5 added`). Nothing needs a manual insert.

### v33 deploy-safety gotchas (learned hardening publish-deploy.yml's preflight, rollback and alerts)

- **Compose prints interpolated values in some error messages.** Found while building the
  preflight's redactor, not assumed: a compose file with `ports: ["${REDIS_PASSWORD}"]` fails
  `docker compose config --quiet` with `invalid containerPort: <the password>` on stderr. So
  "`--quiet` has no stdout" isn't enough to keep a render's output out of a log. The preflight
  (`publish-deploy.yml`) passes that stderr through a redactor that masks every `.env` value (the
  raw text and the value with an inline ` #` comment dropped) before printing it. Verified with
  exactly that broken port: the log line came out as `invalid containerPort: ***`.
- **`compose ps <svc>`'s exit status is the only reliable "broken vs. not yet" signal, and its
  stderr must stay out of the value.** For a service with no container it exits 0 and prints
  nothing. On an interpolation error, a bad file or no daemon, it exits non-zero. The pre-v33
  `wait_for_stack_health.sh` swallowed both with `2>/dev/null || true`, so a missing `${VAR:?}`
  read as "not healthy yet" and waited out the full 420s. Round 1 of v33 then captured
  `2>&1` to show the error. That's wrong in the other direction: on a *successful* call, compose
  still writes WARNs to stderr (`The "REDIS_PASSWORD" variable is not set. Defaulting to a blank
  string.`, obsolete attributes), and `2>&1` puts them into `$status`, which then never equals
  `healthy`. That would roll back a perfectly healthy deploy. The fix keeps stderr in a temp file
  and prints it only on a non-zero exit. Reproduced both ways with a stub `docker` on `PATH`
  (healthy + a WARN): the `2>&1` version exits 1, the fix exits 0.
- **Scripts in the deploy job's workspace come from the ref being deployed, not from the
  workflow.** `actions/checkout` with `ref: needs.resolve.outputs.commit` is right for the
  deployed code's own scripts (`wait_for_stack_health.sh`, which must match its compose files).
  It's wrong for the *pipeline's* tools: a `workflow_dispatch` of a pre-v33 tag would have no
  `check_required_env.py` or `migration_guard.sh` at all, so it would fail its preflight (or report
  "database ahead" from a missing file's exit 127). Found by the round-1 blind review. The tools
  now come from a second, sparse checkout of `github.sha` (the workflow's own commit) at
  `.pipeline/`.
- **Python `urllib`'s default User-Agent is blocked by Cloudflare in front of
  `matrix.vb2007.hu`.** `Python-urllib/3.x` gets HTTP 403 with the plain-text body
  `error code: 1010` (Cloudflare's browser-signature ban). Synapse never sees the request, and
  the body isn't JSON, so a client that parses Matrix errors crashes instead of reporting.
  Confirmed side by side: the same POST with an explicit `User-Agent` reached Synapse and got its
  normal `M_FORBIDDEN` JSON. `matrix_notify.py` sets one. Any future Python client for this
  homeserver (v36's app alerts) needs the same, and so does anything else behind that zone.
- **`a < missing-file 2>/dev/null` doesn't silence the missing file.** Redirections apply left to
  right, so the `<` fails before `2>/dev/null` exists, and bash prints `No such file or directory`
  anyway. It showed up in the first real run's Summary when `.last-good` didn't exist yet. Put
  `2>/dev/null` first.
- **Two stdin redirections on one command: the last wins.** `python3 - < err.txt <<'PY'` runs the
  heredoc as the script and never reads `err.txt`. Caught in review before the first run, and
  replaced with passing the file as an argument. It's an easy shape to write when a heredoc
  script also needs data.
- **A `compose run` probe in the same project as a *differently configured* running stack tries
  to recreate the project network.** Running the migration guard locally with the prod compose
  files, while the dev stack (dev override) was up under the same project name, failed with
  `network spotdl-web_default has active endpoints`. On the host the probe uses the same files the
  stack was started from, so this doesn't happen there. Locally, give the probe its own project
  (`GUARD_COMPOSE_ARGS="-p v33-guard-test -f ..."`), and remove its network and `redis-data`
  volume afterwards.
- **A PR's CI run also queues a `Release` and a `Publish & Deploy` run, and both are no-ops.**
  `release.yml` fires on every CI completion, PRs and dispatches included. Its job is skipped
  for non-push events, and a run whose only job is skipped concludes **`skipped`**, not
  `success`. `publish-deploy.yml`'s `resolve` requires `success`, so it skips itself as well.
  Confirmed from the run list during v33's testing: `Release` 36848033567 → `skipped`, then
  `Publish & Deploy` 36848040363 → `skipped`. A pending run in either concurrency group shows up
  as `cancelled` when a newer one replaces it. These runs queue behind real work on the single
  runner, which is why a scratch dispatch can sit `queued` for a while, but they never touch the
  host or send a notification. `.last-good` therefore first appears on the first release-mode run
  after v33 merges (main's push → CI → `Release`, which succeeds with the tag already existing →
  `Publish & Deploy`, idempotency-skipped if the host is on that release's tag; if a
  `manual-*` dispatch is what's running, it redeploys the release instead, and records it once
  healthy). *(Corrected 2026-10-24, v49: a merge without a new version no longer deploys at
  all; `gh workflow run "Release & Deploy" -f redeploy=true` is what puts the release back and
  writes `.last-good`.)*
- **A pending `workflow_dispatch` in the `deploy-prod` concurrency group gets silently replaced.**
  GitHub keeps at most one running and one *pending* run per concurrency group
  (`cancel-in-progress: false` only protects the running one). During v33's final verification,
  a push to the PR branch started PR CI → `Release` (skipped) → a `Publish & Deploy` run that
  would itself have skipped. It entered `deploy-prod` as the newer pending run and cancelled the
  queued rollback-test dispatch (`36860980814`, `cancelled` with no jobs run). So while a
  verification dispatch is queued behind another run, don't push to any branch with an open PR,
  and check the dispatch actually started before waiting on it.

### v33.1 v33-followup gotchas

- **Under `bash -e`, `x="…$([ cond ] && echo y)…"` aborts the script when `cond` is false.** A line
  that is only an assignment takes its exit status from its last command substitution, and
  `[ false ] && echo` returns 1. GitHub Actions' default shell is `bash -eo pipefail`, so a
  `notify` step written that way died before sending the very "rollback FAILED" alert it existed
  for. Caught by blind review, not by my own test, because I had run the extracted script
  with plain `bash`. **Test extracted Actions scripts with `bash --noprofile --norc -eo pipefail`**,
  never plain `bash`, and use if/else (or `|| true` inside the substitution) for conditional text.

### v34 live-hydration gotchas (learned fixing "Active signal"/incoming jobs vanishing on refresh)

- **Root cause, reproduced on the real stack before the fix (every shape):** `liveActive`
  (Waterfall) and `incoming` (IncomingJobs) in `frontend/src/lib/stores/queue.ts` were fed only by
  SSE and the post-submit optimistic insert; `reload()` (mount, every stream `onopen`) loaded only
  `page`. After a hard reload both started empty:
  - (a) an `expanding` job (expansion held by stopping `worker-meta`) was gone from incoming; it
    stays visible as a "tuning in" row in the main list, so the overlay was the casualty. Its SSE
    capture carried only heartbeats, so nothing would ever bring it back until expansion ended.
  - (b) a failed zero-track job (`https://open.spotify.com/track/0000000000000000000001`,
    `KeyError('uri')`) vanished for good: nothing publishes for it again until it's dismissed.
    **Timing trap when reproducing:** reload while it's still `expanding` and the later `failed`
    event re-adds it over SSE, which looks like "survives". Reload only after it shows failed.
  - (c) a downloading track: progress ticks are sparse (0% → 25% within ~1.5s, then 25% → 40%
    ~2–6s, and a ~29s silent stretch on another run), so a reload in a gap showed "0 lanes" while
    the worker was mid-download. A reload a few seconds after the gap "survives" only because
    the next tick lands, which looks like no bug.
  - (d) a paced track: `download_track` sets `downloading` only *after* `pacing_delay()`'s sleep and
    publishes nothing during it; the track was `pending` (not even `queued`) in the DB for the
    whole 94.6s pacing log line. Nothing disappeared on reload, since nothing was ever shown.
    Recorded decision: no "next up — pacing" lane, because the backend can't tell pacing from
    queued, and the job row already shows it active.
- **Merge rule: SSE beats an older REST snapshot via per-id stamps, not timestamps.** Every SSE
  event (and the session's own submit/cancel) stamps its id from a counter; a hydration notes the
  counter at start and leaves stamped ids alone. Safe because every publisher commits before it
  publishes, so any change the REST read missed arrives as an event *after* the hydration started.
  A `job.state` event is stamped on arrival, before its own `getJob` resolves. A *complete*
  snapshot (no `next_cursor`) also prunes: a lane still marked `downloading` but absent from it
  missed its ending event while disconnected and drops; a lane in its v23 grace window is left to
  its timer. Before v34 such a lane (the track completed while `api` was restarting) stuck at its
  last progress until a manual reload; now the reconnect's snapshot clears it.
- **Progress isn't persisted server-side**, so a hard-reloaded lane renders 0% (`Waterfall`'s
  `progress ?? 0`) until the next tick, typically seconds. Title/artist come from REST and are
  correct immediately. *(2026-10-02, v34.2: the browser now keeps its last tick per track in
  localStorage (`progressCache.ts`) and a hydrated lane shows it; see the v34.2 entry.)*
- **Hydration limits:** failed jobs stay `failed` until dismissed (`cancel` → `cancelled`) or
  archived, so the default page size (50) silently hid older ones. Both hydrations ask for the
  backend cap (1000) and stop pruning when a snapshot comes back truncated. Found by blind review.
- **Vite's dev proxy keeps a dead SSE stream open.** With `api` restarted, `curl -N` through
  `:5173` hung until its 90s timeout, while the same curl straight to `:8000` exited at once
  (`rc=18`). The browser's EventSource therefore never errors, never reconnects and never
  re-hydrates in the normal dev loop. Production nginx closes the stream
  (`ERR_INCOMPLETE_CHUNKED_ENCODING` → 502s → `200 /api/stream` → hydration). The reconnect bullet
  was evidenced by running the real `web` image beside the dev stack:
  `docker build -t <tag> frontend && docker run --rm --network spotdl-web_default -p 127.0.0.1:8081:80 <tag>`.
- **Dev `.env`'s `STALE_TRACK_AFTER_SECONDS=20` is shorter than a real download** (~10–30s),
  so beat's stale sweep re-queued a track mid-download; the redelivered task then hit dedup.
  Raise it while testing anything download-shaped (v35's redelivery guard is the real fix).
  *(2026-10-02, v34.2: `.env.dev.example` now ships 300s.)*
- **A frontend unit-test runner exists from v34:** `npm run test:unit` (vitest) in `frontend/`.
  It mocks `$lib/api` with `vi.mock(..., importOriginal)` and drives the singleton `queue` store,
  calling `queue.reset()` between tests. Not wired into CI. *(2026-10-02, v34.2: it is now, as
  the `frontend` job's "Unit tests (vitest)" step.)*
- **Verification downloads are real rate-limit exposure.** About 20 single-track and album
  downloads across this session tripped dev's breaker (5 consecutive `AudioProviderError`s, proxy
  attempts included). Reproducing download-shaped bugs needs a few tracks each. Reuse a long
  track, or hold a `downloading` snapshot with Playwright's `route.fetch()`, rather than
  submitting fresh tracks per run; don't release the breaker to keep testing.

### v34.1 expansion-fixes gotchas

- **A spotdl `KeyError` during expansion usually means Spotify answered `NotFound`.** spotdl
  4.5.2 uses SpotipyFree (scraping Spotify's private `api-partner.spotify.com/pathfinder`
  GraphQL via `spotapi`), not the official Web API, unless `use_official_api=True`. It indexes
  straight into the response, so a nonexistent id raises `KeyError('discography')` (artist) or
  `KeyError('uri')` (track). v34 misread the artist case as "artist expansion is broken". The
  id it used, `06HL4z0CvFAxyc27GsvL7h`, is a 404 on open.spotify.com itself; Nirvana
  (`6olE6TJLqED3rqDCT0FyPh`) expanded to 535 songs. **Check a failing id against
  `https://open.spotify.com/oembed?url=…` before concluding the integration broke.**
  `expansion.expand()` now re-raises these as a readable `ValueError`.
- **Measured expansion cost:** Nirvana 535 songs in 88.9–90.7s, Pink Floyd 392 songs in
  126.6–129.0s. That's minutes of a Celery slot per discography. With both on `worker-meta`
  (`--concurrency=2`), three 30s `dispatch_due_tracks` ticks sat `received` until the first
  finished. On `worker-expand` the dispatch cadence stayed at exactly 30s throughout.
- **`worker-expand --autoscale=2,1` memory:** 237 MiB idle (one child), 653 MiB peak with two
  concurrent discographies, under the 768M prod limit. A third concurrent expansion queues
  behind the first two. A quick single-track job submitted during two artist archives waits
  for a free slot, which is the cost of not paying for a third child's memory all the time.
- **`worker-meta` keeps its library mount** even though the sort sweep moved off it:
  `reconcile_disk()` (boot) checks ledger rows that point into the library. Without the mount
  its per-root guard skips them as "root looks unmounted" (safe, not a mass prune; an earlier
  draft of this entry claimed otherwise), but a genuinely deleted library file would then never
  be pruned and never re-download. **And the two now run concurrently** (a
  deploy recreates both mid-sweep): `reconcile_disk()` could read a row's old `/downloads` path,
  the sweep commit the repoint and unlink the source, and the check then find the old path missing
  and delete the freshly moved row. Since the sweep always commits before it unlinks,
  `reconcile_disk()` now re-reads a row (`db.refresh`) and re-checks its current path before
  pruning it. Found by blind review.
- **`expand_job` used to overwrite a mid-expansion cancel with `failed`** on its failure path
  (the success path was already a conditional UPDATE). Both are conditional now. A job cancelled
  before its task even starts is skipped without any Spotify calls (live: `is cancelled, not
  expanding; skipping`, 0.003s).

- **Every recovery path for `pending` tracks risks a duplicate message, so `download_track`
  drops a message whose track is `waiting`/`lookup_failed`** (no attempt row, no event). Only
  `pending` (expand_job), `queued` (beat) and a crash-redelivered `downloading` are legitimate.
  expand_job re-enqueues a job's still-`pending` tracks on an `EXPANDED` redelivery, or when
  something raised after its EXPANDED commit, because nothing else ever picks `pending` up. A
  duplicate landing after the first attempt failed into the ladder would otherwise retry
  immediately on the next rung (live check: `is waiting, not due; dropping stray message`,
  attempt rows 1 → 1). A duplicate finding a `completed` track is v35's item (c). An overlapping
  run of the same job (a redelivery past the visibility timeout) now rolls back its own track
  inserts when the UPDATE finds the job already `expanded`.
- **`cancel_job` row-locks the job (`refresh(..., with_for_update=True)`) before reading its
  tracks.** Verified on the dev Postgres: expand_job's conditional UPDATE blocked while the lock
  was held (`still blocked after 2s: True`), then matched 0 rows, and the job ended `cancelled`.
  The test suite runs on SQLite, which ignores `FOR UPDATE`, so its test only pins that the lock
  is requested.
  *(2026-10-24, v51: the suite runs on Postgres, and the race is reproduced on two real
  connections, in both orders: `test_jobs.py`, `test_expand_task.py`.)*
- **Known, not fixed: a broker error *inside* expand_job's success-path enqueue loop strands
  the rest of that job's tracks in `pending`.** The task fails and is acked (`acks_late` acks
  failures), so nothing redelivers it. A generic "stale pending" sweep isn't a safe fix: a
  535-track discography's tracks legitimately sit `pending` in the broker for hours behind
  `worker-dl --concurrency=1`, and pending messages pass `download_track`'s gate, so the sweep
  would duplicate-dispatch them. This needs Redis to fail mid-loop. Recovery: re-send
  `expand_job` for that job; its `EXPANDED` branch enqueues exactly the still-pending tracks.
  *(2026-10-26, v56: fixed with an outbox marker on the track, see v56's section. Tracks a
  pre-v56 run stranded have no marker and stay stranded; the recovery above still applies.)*
- **Rolling back across v34.1 strands the `expand` queue.** A pre-v34.1 compose has no
  consumer for it, and `--remove-orphans` removes `worker-expand`. An expansion queued or
  in flight at rollback time stays `expanding`, and a library sweep stays `running`, which
  409s every new sweep. Recovery: roll forward, or re-send `expand_job` on the old stack (it
  then routes to `meta`).

### v34.2 live-view-followup gotchas

- **"N+1 of N" job counts were a snapshot race, not a frontend bug.** `list_jobs` runs three
  statements: the capped `total_estimate`, `counts_by_status`, and the page. Under Postgres
  READ COMMITTED each gets its own snapshot, so a job committed between them appears in the
  page but not the count. Reproduced while submitting 40 jobs against 4 polling listers: 8 of
  411 listings mismatched, e.g. `(9, 8)`. With `begin_snapshot()` (commit, then a REPEATABLE
  READ transaction, Postgres only) the same load gave 0 of 356. Any future endpoint that reports
  a count beside a page should read both from one snapshot.
- **Why `onopen` and not mount:** a REST snapshot taken before the stream subscribes can miss an
  event that lands in between; one taken from `onopen` practically can't. (Strictly, the
  response headers, and so `onopen`, can precede the Redis subscribe by one round trip, but
  the REST snapshot needs a full browser→api→DB round trip after `onopen`.) So the eager mount reload was never
  the authoritative one. Removing it means `setAllUsers` must itself bump
  `pageFetchSeq`/`liveHydrateSeq` and blank the page: it no longer fetches, so nothing else would
  stop a late old-scope response or old rows from showing until the reconnect lands. Live: a page
  load sends exactly 1 page + 1 + 1 hydration requests (was 2/2/2), a scope switch sends 1/1/1, a
  filter change sends the page only, and a forced 502 on `/api/stream` triggered one REST
  fallback so the page still rendered.
- **Progress across a hard reload, localStorage (`spotdl:live-progress:v1`):** trusted only for
  the same `attempt_count` and for 30 min, forgotten when a track leaves `downloading`, cleared
  by `queue.reset()`. It holds ids and numbers only. Live: the lane painted `25%` 154 ms after a
  hard reload and showed `40%` at the next real tick (~2 s); before v34.2 it read 0% in that
  window. Only the browser that saw the tick can show it; another device still starts at 0%.
- **Vite proxy fix, verified:** with `api` restarted, `curl -N` through `:5173` now exits at the
  same moment and with the same code as one straight to `:8000` (13.09 s, `rc=18`). In the
  browser the stream retried and then re-hydrated once, with incoming rows 4 → 4 and no
  duplicates.

- **`downloading` events didn't carry `attempt_count`**, so a lane created purely from SSE (no
  REST seed) recorded every tick under attempt 0 and a retried track's cache never matched its
  hydrated `attempt_count`. Retries are this app's normal state, so that gutted the feature.
  Found by blind review. Both downloading publishes now include it; live capture: every tick
  from `progress=0` to `100` carried `attempt_count=0` on a first attempt. **To test
  "survives a hard reload", re-import the store module (`vi.resetModules()`)**, never
  `queue.reset()`: that is logout, and it clears the cache by design.
- **The resync fallback is armed per resync (mount and every scope switch), not once per
  mount, and also fires on a 5s timer.** A network-level stream failure keeps the EventSource
  `CONNECTING`, which never reaches the `CLOSED` branch. Live: a scope switch under a 502ing
  stream showed the new scope via the fallback within 1.5s, and a `connectionreset` stream left
  "Loading…" at 2s, resolved by 7s.

### v35 correctness-sweep gotchas

- **(a) Counting decision: stored counters, one write site.** `tracks.attempts_made` (rows that
  reached the network: `completed`, `failed`, or `cancelled` with a `network_path`) and
  `tracks.failure_count` (`failed` rows) are maintained only by `attempts.record_attempt`, in the
  same transaction as the row it inserts, via an ORM `update(Track)...returning(...)` with
  `synchronize_session="fetch"` so `download_track`'s already-loaded `Track` sees the new values.
  That UPDATE runs first so it takes the track's row lock before `max(attempt_number) + 1` is read:
  beat's stale reclaim (worker-meta) and `download_track` (worker-dl) can write rows for the same
  track concurrently. Derived-in-SQL counts were rejected because every listing and every SSE
  event would then need its own aggregate. The counting rule is derived from the row alone
  (outcome + `network_path`), so the counters can always be recomputed from `track_attempts`.
  Beat's reclaim of a track stuck `downloading` stays `failed` (as v31 recorded it). One stuck
  `queued` hadn't reached the network, so it is now recorded as `held` with a warning note (found by v35's two
  blind review rounds; a first fix that kept it `failed` but uncounted left a red row beside
  "failures: 0"). The migration can't tell old reclaim rows apart and keeps them `failed`. A
  reclaim that races a still-running invocation gets the lower `attempt_number` despite its later
  `started_at`; the endpoint orders by number, so that one pair can show out of time order.
- **(a) Breaker hold = outcome `held`, still a row.** It keeps the history honest (you can see the
  pause) without counting as an attempt. The migration identified existing holds by
  `download.py`'s fixed message text (1,857 of 1,864 `failed` rows on dev), renumbered every
  track's rows 1..n by `started_at`, and backfilled the counters; checked against a CSV of the
  expected per-track values computed before the upgrade (1,899 tracks, identical), then
  downgrade → upgrade on the same data.
- **(a) The ladder input didn't move.** `tracks.attempt_count` is still only incremented by
  `retry.record_failure` and still drives both `next_delay` and the network-path rung;
  `test_ladder_step_ignores_held_and_cancelled_rows` pins delay *and* rung for 0–6 failures with
  held and cancelled rows interleaved. A success doesn't reset it (pre-existing): a track that
  completed after 2 failures reads `attempt_count=2, attempts_made=3, failure_count=2`.
- **(d) `warning_message` is its own column.** Set at the write site: the tag-repair note on a
  completed attempt and the breaker-hold reason. `error_message` now only ever means a failure.
  A real tag warning was produced on dev by mapping `i.scdn.co` (the Spotify cover CDN) to
  localhost inside `worker-dl`: the download succeeded and the cover repair failed.
- **(e) Streamed download = `HEAD` probe, then `<a download href>`.** The probe keeps the inline
  error notice (a plain navigation to a 404 would replace the page). On a 54 MB file the
  browser's RSS rose +5–6 MB vs +54–57 MB for v27's Blob flow, through both the Vite fallback and
  nginx. The Vite fallback answers `HEAD` from `stat()` without streaming the file.
- **(f) `PYTHONDONTWRITEBYTECODE=1` plus stripping every `__pycache__` the root build leaves.**
  The image's own `/app` never had root-owned caches; the root-owned ones were site-packages (52)
  and the base image's stdlib (46). Stripping them all costs ~0.2s per process start
  (`import app.tasks.celery_app`: 3.13s → 3.30s). In dev the stale root-owned caches were on the
  host tree (`backend/app/**/__pycache__`, `backend/alembic/__pycache__`, from Aug 2), visible
  through the bind mount; they were removed with a root container, since the host user can't.
- **(g) `counts_by_state` on the tracks scope** comes from one grouped query over the same filtered
  set before `state=`, read from the page's snapshot (`begin_snapshot`, as in v34.2). The chips
  re-read it with a debounced 1-row request on a track *state change* only: a count spans tracks
  that aren't on the loaded page, so it can't be patched locally.
- *(2026-10-26, v55: every race in this entry is fixed: E2 re-checks the state in the reclaim
  `UPDATE`, E3 lets the live download's outcome supersede the reclaim's row, E6 publishes the
  cancel after its row with counters, E4 exits after the pacing sleep. See the v55 section.)*
  **Reclaim races (pre-existing, documented by v35's third review, not fixed):** beat's reclaim
  `UPDATE` doesn't re-check `state` after its snapshot `SELECT`, so a track that commits
  `COMPLETED` in between is reset to `WAITING` (then dedup-skipped to `skipped_duplicate`) — the
  same "completed track rewritten" outcome (c) closes for redelivery, via another path. A reclaim
  of a still-alive `downloading` invocation also counts that one network attempt twice (the
  reclaim's `failed` row plus the real outcome's). A mid-download cancel's event goes out before
  its attempt row and carries no counters; the frontend never patches an already-`cancelled` row
  anyway, so its displayed counts update on the next reload. A track reclaimed while its message
  sits in `download_track`'s pacing sleep still downloads afterwards (the post-sleep check only
  looks for `cancelled`), and beat dispatches it again — pacing is off by default (`MAX_SEC=0`).
- *(2026-10-26, v55: all three fixed: E8 records the skip as `skipped_duplicate`, E9 clears
  `last_error` on success, E7 holds no transaction across the download.)*
  **Found while verifying, not fixed (pre-existing):** spotdl's `file already exists` skip is
  recorded as a `completed direct-ipv4` attempt and counts as one; a completed track keeps its
  last failure in `last_error`, so TrackRow still shows a red "last read" on it; and
  `download_track` reads `track.song_json` right after the `downloading` commit, which opens a
  transaction that stays idle for the whole download (the completed row's `updated_at`, which is
  Postgres `now()`, shows the download's *start* time).

### v36 alerting gotchas

- **Design: where each alert is noticed.** Breaker trip/escalation is queued at the trip point
  (`retry.maybe_trip_breaker`) on the session's `info` and enqueued from a global `after_commit`
  listener (dropped on `after_rollback`), so a trip that never committed is never announced. It
  goes to `send_alert` on the `meta` queue with `retry=False`. Release, failure spike and beat
  stale are checked by the **watchdog**, a separate process (`python -m
  app.services.alert_watchdog`) that worker-meta's `AlertWatchdogStep` bootstep starts and
  supervises when `RUN_ALERT_WATCHDOG=true`, every 60s. Library sweep results are enqueued from `sort_library`.
- **Beat-stale: the recorded choice.** The watchdog is not beat-scheduled, because beat is the thing
  it watches. Beat's heartbeat (`spotdl:beat:heartbeat`) is written at the start of every
  `dispatch_due_tracks` run, so strictly it proves "beat scheduled *and* worker-meta ran the tick".
  Both of worker-meta's slots stuck for longer than the threshold (default 180s) also reads as
  "beat looks dead". That's still a real dispatch outage, just mislabelled. Each `send_alert` is
  bounded at 10s per connect/read phase, so it can't do that on its own short of a burst.
- **Why a process, not a thread (review round 1).** The first version was a daemon thread in
  worker-meta's main process. That process forks a new prefork child every 50 tasks, and a fork
  taken while the thread held a lock (logging, psycopg, ssl) could leave that child deadlocked: one
  of beat's two dispatch slots. multiprocessing `spawn` was tried next and failed live in dev: its
  child unpickled `app.services.alerts` from the image's site-packages copy, not the
  `./backend/app` bind mount (`AttributeError: Can't get attribute '_watchdog_main'`). `python -m`
  with cwd `/app` resolves `/app/app` first, in dev and prod alike. The child exits once it's
  reparented (worker-meta gone). It imports config/models/app_settings only: **~89 MB resident**,
  measured, against ~220 MB for a worker-meta child. That's why `redact_text` moved out of
  `proxies.py`.
- **The watchdog is supervised (review round 3).** A bare `Popen` whose handle was dropped meant
  an OOM-killed watchdog silently ended every watchdog alert while worker-meta stayed healthy.
  `celery_app.AlertWatchdogStep` (a worker bootstep, `requires` the Timer) starts it and polls
  it every 60s from the worker's own timer, in the main thread, with no extra thread in the
  forking process. A dead watchdog is respawned and the exit code logged (verified with
  `kill -9`). `SEND_TIMEOUT_SECONDS` is per httpx phase and DNS isn't covered. Send errors scrub
  the token literally, since h11 can quote header values. Round 4: a failed spawn (`OSError`) is
  logged and retried on the next tick, never fatal to worker-meta. The release's marker delete
  is a compare-and-delete (Lua), so a newer escalation's marker survives. The watchdog reads
  everything and closes its DB session *before* sending, so a hung send never holds locks a
  `migrate` would queue behind.
- **A literal token scrub isn't enough (review round 5).** h11 refuses a header value with a control
  character and quotes it *repr-escaped* (`b'Bearer syt_...\ntail'`), so `str.replace(token, ...)`
  never matches. Reproduced against a real socket. Now a non-printable token is refused before
  any request is built, and only connect/timeout/network errors keep their text; every other
  exception is reported by class name alone. Accepted, not changed: the watchdog reads the DB
  first, so a Postgres outage also skips that minute's beat-stale check, and a Redis outage logs
  a traceback every 60s. *(2026-10-28, v59: one traceback per outage now, then a "still down"
  line every 10 min and a recovery line; the database checks keep running through it.)*
- **Alerts are early-acked and expire (review round 6).** The global `task_acks_late=True` plus the 6h
  visibility timeout would redeliver a crashed worker-meta's alert hours late, and possibly twice
  once its cooldown had lapsed. `send_alert` sets `acks_late=False` and `enqueue` passes
  `expires=300`. A crash drops an alert, which is what "dropped" means here. The watchdog also
  reads the open-trip marker *before* the breaker state, so a marker set by a newer escalation
  can't be paired with a stale "released".
  *(2026-10-28, v59: superseded. Alerts are rows in `alert_outbox`, delivered by beat's
  `deliver_alerts` and the watchdog with backoff; `send_alert` only records a leftover message.
  The expiry and the early ack are exactly what lost them, see v59.)*
- **Redaction twice.** `alerts.enqueue` redacts before the text reaches the broker, and
  `format_body` redacts again before the PUT. Found by v36's real-stack check: the room copy was
  already clean, but Celery's "Task received" line logged the raw credentialed URL from the task
  args. Unit tests that only inspected the sent body couldn't see it.
- **Cooldown = Redis `SET NX EX` per `(category, fingerprint)`, claimed before sending.** Two
  workers can't double-send, a worker-meta restart doesn't re-fire inside the window (verified
  live), and a failed send isn't retried inside the window ("logged once and dropped"). If Redis is
  down the alert is dropped rather than risk a duplicate. Fingerprints: `trip:<step>:<tripped_until>`,
  `release:<that trip>`, the spiking `error_type`, `stale`, and the library sweep's `finished_at`, which is unique per
  run, so sweep reports are never suppressed.
  *(2026-10-28, v59: the cooldown is decided in Postgres at insert, under an advisory lock, and
  counts only pending or sent rows: a failed send no longer burns the window, and a suppressed
  alert is a row.)*
- **Release only for a trip the room heard about.** `spotdl:alerts:breaker_open` is set only when a
  trip alert was actually *sent* (not suppressed, toggled off, or failed), and release also waits
  for a manual pause to end (review round 1).
  *(2026-10-28, v59: the Redis marker is gone; the watchdog reads the newest trip row in the
  outbox, and records a release only when that row is `sent` and has no release row yet.)*
- **One fingerprint per trip, not per step (review round 2).** `trip:30m` as a fingerprint let a
  *second* 30m trip within the cooldown (after a success reset the escalation) be suppressed,
  so the room's last word stayed "released" while downloads were paused again. The fingerprint is
  now `trip:<step>:<tripped_until>`, the open marker stores it, and the release is
  `release:<that trip>`.
- **Redis is persistent here (`--appendonly yes`), so heartbeats outlive downtime (review round
  2).** Without `max(heartbeat, watchdog start)`, every restart after more than the threshold of
  downtime announced a dead beat and burnt the cooldown a real one would need.
- **A spike is re-sent only with a newer attempt (review round 2).** The newest matching attempt's
  `finished_at` is remembered per error_type. With a window longer than the cooldown, the same
  frozen rows (the breaker stops attempts) would otherwise re-alert every cooldown.
  `track_attempts.finished_at` is indexed for this every-minute query.
- **Spike excludes `lookup`.** "Not found" is terminal and about the track. A playlist of
  unavailable tracks fails them back to back, which isn't YouTube changing (review round 1).
  Holds, skips and cancels never touched the network, so they neither break nor extend a run. A
  reclaimed-stuck `failed` row (no error_type) breaks one.
- **Real-stack trigger used for the spike/breaker:** `YOUTUBE_PLAYER_CLIENTS=android_vr` (v31.1's
  blocked client) still fails today as `no_output`, which feeds the breaker. It tripped at the
  default threshold of 5 with no code change. Dev's short `LADDER_SECONDS` makes the retries
  immediate, so watch the count. The local `.env` had no `YOUTUBE_PLAYER_CLIENTS` line at all: a
  `sed` that "changed" it silently did nothing. Check the value inside the container
  (`get_settings()`), never the file.
- **Category 5 (worker down) skipped, by the plan's own rule.** No existing signal says "worker-dl
  stopped consuming". QUEUED tracks' `updated_at` is reset every `STALE_TRACK_AFTER_SECONDS` by
  beat's reclaim. `track_attempts.finished_at` going quiet is indistinguishable from an idle
  queue. Telling the two apart needs new state (a "backlog since" marker), which is more than the
  plan allows for this optional item. Beat's reclaim already records `held` "reclaimed: still
  queued" rows, which is where a dead worker-dl shows today.
  *(2026-10-28, v59: built, see v59. The "backlog since" marker is the watchdog's own memory,
  with no new heartbeat.)*
- **Non-admin `/settings` already shows "Admin access required" per panel.** The new Alerts panel
  does the same as the existing Output/Library panels (the page itself isn't admin-gated). The
  settings redesign is v43.
- **Test-alert is 404 for a non-admin, per the plan.** Every other admin-only route answers 403
  (`require_admin`). The alert settings GET/PATCH keep 403 to match their siblings. *(2026-10-26, v56 (A6): an admin route whose path names an id (priority, bump, one proxy) now answers a non-admin 404, like stats and the test-alert send; `tests/test_admin_gating.py` holds the table.)*

### v37 e2e-harness gotchas

- **Accessible names that contain another element's text collide.** A job toggle's name is
  "Expand tracks for <title>", which also matches a track row searched by the same title, so the
  "track" click collapsed the job instead. Track rows are now looked up inside the job's own
  `Tracks` list (`trackToggle` in `e2e/support/ui.ts`).
- **A flash only exists where nothing gates rendering.** After logout, `beginResync()` hides
  stale *page* rows behind "Loading…", so a leaked store only shows through the incoming/Waterfall
  overlays. Spec 1 gives the first identity a failed incoming job on purpose, and a
  `MutationObserver` records any render of its text during the second identity's login. With
  `queue.reset()` removed from `onLogout`, it caught the URL on both projects.
- **Spec 7 matches foreign titles exactly, minus the user's own row text** (review rounds 5–6).
  A substring match over "every title the admin owns" also hit chrome ("done") and the user's own
  track's album/artist cells (an admin album job titled like the user's album). Titles render as
  their own elements, so `exact: true` still catches a leak; both owner filters were re-shown red.
- **"Own" text in a cross-user check must not come from the listing under test.** Taking the
  user's own titles from `GET /api/jobs` made a broken owner filter count the admin's titles as
  the user's own. The leak still failed, but at an unrelated guard. Own jobs are filtered by
  `owner_email` (review round 7).
- **graphify reads only the repo-root `.gitignore`.** Nested ignore files (`frontend/.gitignore`)
  aren't consulted, so Playwright's `playwright-report/`, `test-results/` and `e2e/.auth/` got
  indexed: ~1,262 nodes of minified bundles outranked real code in `graphify query`. The root
  `.gitignore` repeats them. Anything generated under a subdirectory needs a root entry before
  `graphify update .` (review round 7).
- **Cross-user checks need a positive control that tolerates duplicates.** Other dev users own
  tracks with the same titles as the e2e user's own, so a leak first surfaced as a strict-mode
  violation on the user's *own* row. The positive check uses `.first()`, so the foreign-title
  assertion is the one that names a leak.
- **Admin endpoints answer 403, not 404** (`require_admin`, pinned since v22). The v37 plan's
  "404" was a slip; the owner confirmed asserting 403 (recorded in the master plan's
  Amendments). Only the v36 test-alert POST is 404. *(2026-10-26, v56 (A6): one rule now. An
  admin route whose path names an id (priority, bump, one proxy) answers 404 like
  `/api/admin/stats` and the test-alert send; the id-free ones keep 403. `test_admin_gating.py`
  holds the table.)*
- **`skipped_duplicate` attempts carry no `network_path`**, and an expected label computed from
  the API agrees with the UI even when the API drops the field (both fall to "no network"). So
  spec 3 requires the key on every attempt, and also checks an admin-owned track a past
  `@network` pass left with a real path (picked in setup, unique title, archived), so a broken
  "direct · IPv4" label fails a default run. Both were shown red (review round 1). On a dev DB
  with no such track it **fails**, asking for one `npm run test:e2e:network` pass (review round
  3: a warning annotation let a broken label go green).
- **Attempt history is oldest first** (`order_by(attempt_number)`), so a retried download's
  completed row isn't `.first()`. Locate it by the API's index (review round 3). The opt-in `@network` spec itself requires
  the served file's mtime to postdate the test, per v35's "file already exists" trap.
  That check earned its place on its first two runs: two "fresh" ids (`4uLU6hMCjMI75M1A2tKUQC`,
  `7GhIk7Il098yCjg4BQjzvb`) turned out to be other Spotify releases of a song already downloaded.
  Each recorded a `completed direct-ipv4` attempt in about 20 ms that never touched the network,
  and only the mtime check failed. Pick a candidate by title too (`song_json->>'name'`), not just
  by ledger absence.
- **The default `@network` track can't be hardcoded.** A passing run puts it in the ledger, and
  the first candidate (One More Time) was already there via the sorted Discovery album. The spec
  requires `E2E_NETWORK_TRACK_URL` and refuses a ledger hit.
- **A ledger row is not a ledger hit.** `dedup.is_already_downloaded` returns None when the
  row's file is gone, which means a real download. Setup preflights every `LEDGER_TRACKS` id
  with that same function, **inside `worker-dl`** (it mounts only `/downloads`; `worker-meta`
  also sees the library and would approve a moved file worker-dl can't see), and refuses to start, and a seed or spec 2 job that doesn't settle as a
  duplicate is cancelled so it can't keep retrying on the ladder (review round 1).
  *(Corrected 2026-10-10, v38: worker-dl now mounts the library read-only, so the two agree. The
  preflight stays in worker-dl, the worker that decides, and also counts an unmounted root as a
  miss.)*
- **Teardown counts `network_path is not null` for normalized emails.** Emails are stored
  lowercased, so a mixed-case `.env.e2e` value matched no user and the check passed vacuously.
  Outcome-based counting also misread beat's stale reclaim (`failed`, no path) as a download.
- **Global teardown's zero-download check compares `timestamptz`.** `track_attempts.finished_at`
  is `timestamp with time zone`, so the ISO `now()` from setup compares correctly. It was checked
  against 91 historical network attempts, so the query isn't vacuous.
- **Found, not fixed (pre-existing, outside v37): `worker-dl` can't see library-sorted files, so
  its dedup gate misses them.** `worker-dl` mounts only `/downloads`, in dev and in
  `docker-compose.prod.yml` alike, but v28's sort & move repoints `downloaded_tracks.file_path`
  into the library root. `dedup.is_already_downloaded("3H3cOQ6LBLSvmcaV7QkZEu")` (a sorted
  Discovery track) returns the library path in `worker-meta` and `None` in `worker-dl`, so
  resubmitting any moved track would re-download it. That contradicts the master-v3 invariant
  that a move must never cause a re-download. Reported to the owner in the v37 PR. *(2026-10-10: scheduled
  as v38, `plan/master-v4/v38-moved-file-dedup.md`; later slices renumbered. Fixed in v38, see
  below.)*
- **The suite refuses a non-loopback `E2E_BASE_URL`** (review round 2). The preflight and the
  teardown read the local stack, so driving another origin would leave them guarding the wrong one.
- **An in-flight download is invisible to the DB.** An attempt row is written only when the
  attempt ends, and cancelling a job flips a `downloading` track to `cancelled` without stopping
  worker-dl. A first fix that counted `state = 'downloading'` missed exactly the cancel-on-timeout
  case it was meant for (review round 4). Teardown now asks the worker
  (`celery_app.control.inspect().active()`) and fails if any running `download_track` belongs to
  an e2e identity, or if worker-dl doesn't answer. Setup runs the same check before recording
  `startedAt` and refuses to start, so an aborted `@network` pass's still-running download isn't
  blamed on the next default run (review round 10).
- **Every resync re-renders the job list, so expand only after the first one lands.**
  `reloadPage()` swaps the list for "Loading…", which unmounts the rows. A job's expansion
  survives (it lives in the store, `queue.toggleExpand`), but a track row's is component-local
  and is lost. Waiting for "Loading…" to clear isn't enough: the 5 s fallback
  reload can clear it before a slow stream opens and re-lists. `openDashboard()` waits for the
  stream's response, then a `/api/jobs` response after it (review rounds 8–9).
- **Playwright runs global teardown even when global setup throws** (it registers the teardown
  first). Setup therefore deletes the previous run's `run.json`/`seed.json` up front and writes
  `run.json` (`startedAt`) before submitting anything, so teardown never checks an earlier run's
  window (review round 5).
- **Cleanup that guards against a live download uses its own request context**
  (`cancelUnlessSettled`). A test-level timeout can close `page.request` before a `finally` runs.

### v38 moved-file-dedup gotchas

- **The re-download was real, and it also corrupted the ledger.** Reproduced on dev before the fix:
  `2KH16WveTQWT6KOG9Rg6e2` (Survivor, Eye of the Tiger, sorted into the test library on
  2026-10-02), resubmitted by `v37admin`, recorded a `completed direct-ipv4` attempt after a 33 s
  YouTube download, and `db.merge` repointed the ledger row to
  `/downloads/04 - Survivor - Eye of the Tiger.mp3` while `in_library` stayed `true`. The library
  copy was still there, so the track had two files and the next sort would have met an existing
  target. That `in_library` + non-library path pair is what `scripts/moved_file_redownloads.sql`
  looks for.
- **An unmounted root holds the track rather than trusting the ledger.** Both were allowed by the
  plan. Holding (`waiting`, a `held` attempt, `retry.next_delay(0)`, no `attempt_count` step, no
  breaker feed) self-heals: verified live, four holds with worker-dl's library mount removed, then
  `skipped_duplicate` on the next dispatch once it was back. Trusting the ledger would mark a
  track a duplicate of a file nobody can confirm exists, and nothing would revisit it. The error
  is logged once per hold, so a missing mount on production (15 min ladder) logs every 15 min per
  affected track, which is the point.
- **The guard is per configured root, like `reconcile_disk`'s.** A path under neither
  `download_output_dir` nor the *current* `library_target_dir` isn't guarded: after an admin
  repoints `library_target_dir`, rows still under the old root fall outside both. They're fine
  while that old root stays mounted (it's the same `/mnt/raid1/media/music` mount today). The
  damage query has the same blind spot in reverse: after a repoint it reports old-root rows as
  `ledger_back_in_downloads`. *(2026-10-26, v57: every library root the install has used is
  guarded now, `app_settings.library_known_roots`.)*
- **The guard covers the downloads root too, and that can stall a track.** If `/downloads` is
  ever genuinely empty (a sort moved everything and no `quarantine/` dir exists) while a ledger
  row still points at a hand-deleted file there, the track is held every ladder step, forever,
  with an error each time, and `reconcile_disk` skips the same row for the same reason. Fix it
  by hand: delete that ledger row. Accepted as the safe direction (plan: "a silent re-download
  is not an option"). *(2026-10-26, v57: fixed. "Mounted" is the root's `.spotdl-volume`
  sentinel, not "non-empty", and a file missing under a mounted root drops its row and downloads
  again.)*
- **A miss re-reads the row before deciding** (blind review round 1). The sweep commits a
  repoint and then unlinks the source, so a check that read the old `/downloads` path just
  before saw neither file. Same fix as `reconcile_disk`'s v34.1 recheck: `db.refresh(row)`.
- **The damage query compares path prefixes with `left()`, not `LIKE`**: `_` in a path is a
  `LIKE` wildcard, and a trailing slash on `library_target_dir` flagged every library row.
- **Six dev library rows also have a same-named file in `./downloads`** (Mr. Brightside, Africa,
  Take on Me, Hotel California, Bohemian Rhapsody, Shape of You). They aren't the moved-file
  signature (their ledger rows still point into the library) and weren't investigated: out of
  scope, listed in the PR.
- **`localhost:5173` can be two servers.** Docker publishes the dev `web` on `127.0.0.1:5173`
  only, so another project's Vite dev server listening on `[::1]:5173` wins `localhost` for Node
  and the browser. An e2e run then failed with HTML where JSON was expected and a foreign page in
  the screenshot. `127.0.0.1` isn't a way around it: the session cookie is `Secure`, which
  Chromium honours over HTTP only for `localhost`. Stop the other server. **Corrected 2026-10-24
  (v52):** wrong about Chromium, which keeps a `Secure` cookie on `http://127.0.0.1` too. It's
  Playwright's request contexts that send one only to `localhost`/`*.localhost`. The suite now
  targets `127.0.0.1` (v52, D6).
- **Production's library went live after the merge (2026-10-11).** `LIBRARY_DIR` had pointed at
  the empty test folder `/mnt/raid1/media/test`; the owner changed it to `/mnt/raid1/media/music`,
  recreated the stack and sorted 12 already-downloaded tracks: 12 moved, 0 already present,
  0 quarantined, 0 errors, Plex picked them up, and the Matrix sweep alert arrived. Before the
  switch, `scripts/moved_file_redownloads.sql` on prod returned no rows (no earlier damage) and
  worker-dl showed the mount `ro`. Safety argument for the flip: the sweep skips any destination
  that exists (`app/tasks/library.py`), `copy_verify` renames rather than deletes a bad copy, and
  every `unlink` is on the `/downloads` source.
- **`docker compose -f docker-compose.yml up -d` on the host takes the app down.** CLAUDE.md's
  environment table gave that as the host command (stale since the prod overlay); the session
  passed it on. Without `docker-compose.prod.yml` compose stopped every app container, built a
  local `worker-expand` image, created empty `spotdl-web_library`/`spotdl-web_downloads`
  volumes, then failed: `network spotdl-web_default has active endpoints (cloudflared)`. Nothing
  started on the wrong config, so no data was touched. Recovery: the overlay's `--profile tunnel
  down`, then `up -d --no-build`, then removing the two empty volumes and the stray image. The
  table is fixed.

### v39 ui-audit gotchas

- **Getting every track state onto the dev stack for a UI audit.** The dev DB rarely holds a live
  `waiting`, 5+-attempt, `lookup_failed` or tag-warning track. Real failures came from restarting
  only `worker-dl` with a scratch overlay (`HTTP_PROXY`/`HTTPS_PROXY` = `http://127.0.0.1:9`,
  `LADDER_SECONDS=15,15,15,15,15,3600`): the worker produced real `no_output` failures, escalated
  to IPv6 and then to the real pool proxies, tripped the breaker, and left a real 1h countdown.
  Five consecutive failures trip the breaker, and breaker holds record "held — not attempted"
  rows instead of attempts. So taking one track to 6 real failures meant pushing the album's other
  tracks' `scheduled_at` out and resetting `worker_state` once, in the dev DB. `lookup_failed` and
  the tag-repair warning can't be forced; they were seeded by SQL with spotdl's and
  `tagging.repair_tags`' real message texts (owner-approved). Restore with a plain
  `docker compose up -d worker-dl`, and clear `worker_state`, or the e2e suite's dedup submissions
  sit behind the breaker.
- **impeccable tooling on this repo.** The `detect.mjs` CLI scan of `frontend/src` returns `[]`
  (exit 0). A planted test file proves the engine works; it simply matches source patterns this
  tree doesn't have. Every real detector finding (low contrast, the unpadded Alerts panel, line
  length, flat type hierarchy) came from the browser overlay. `live-server.mjs` writes its state
  files into the current directory and a plain `stop` edits an injected tag in source, so run it
  from a scratch directory and stop it with `--keep-inject`. `critique-storage.mjs write` puts
  snapshots at the repo-root `.impeccable/critique/`. `surface-brief.mjs` writes to
  `frontend/src/.impeccable/surfaces/`, which counts as a `frontend/` change for the version bump.
- **A library sweep changes other users' dashboards.** `_sync_tracks_and_archive_jobs`
  (`app/tasks/library.py`) archives every settled job whose tracks the sweep moved, across all
  users, and the sweep report doesn't say so. A sweep run mid-audit made a verifier report "the
  job is archived" against screenshots taken minutes earlier. Take dashboard captures before any
  sweep. (Recorded as v39 finding F34.)
- **The e2e suite wipes the e2e identities' in-flight jobs.** v37's global setup logs in as
  `v37admin`/`v37user`, `DELETE`s every unsettled job they own, archives them, then posts its seed
  jobs (seen in the api log: two logins, two `DELETE /api/jobs/{id}`, two `/archive`, two
  `POST /api/jobs` within 0.5s). The v39 audit's "Trick" album, with its real failure history, was
  built on `v37user`. The e2e run that proved the stack healthy cancelled and archived it, which
  looked at first like an assessment agent breaking its read-only rule. Capture every screenshot
  before running the suite, or build audit data on a separate identity.
- **F01: in a column flex stack, flex-basis sizes height (fixed in v39.1).** JobRow's ≤640px block
  switches the row to `flex-direction: column` but inherited the desktop children's bases:
  `.toggle { flex: 2 1 16rem }` became a 256px *height*, and `.bar { flex-basis: 100% }` resolved
  against an indefinite height, fell back to the bar's empty content and overrode its
  `height: 0.5rem`, leaving a 2px border. It had been broken since v20. v20's 390px check measured
  widths (overflow) only, so it never looked at heights. For any column-direction collapse, reset
  the children's flex-basis and measure heights as well as widths.

### v39.2 swallowed-error classification gotchas (learned from a production artist download)

- **19 of 459 tracks of a Scooter artist job sat in `waiting` with "spotdl returned no output file
  for this track" and tripped the global circuit breaker twice** (2026-10-12; `worker_state`
  showed `consecutive_failures=6`, paused 2h). The stalled tail was all permanent failures retrying
  forever, and since `NO_OUTPUT` feeds the breaker they paused the whole pipeline too. Re-running
  spotdl's own YouTube Music search locally on the same `song_json` split them into two
  deterministic groups. **12 had no match at all**: mostly "- Remastered"/remix variants from
  compilation albums, e.g. "B.O.B. - Remastered 2013" and the 49-second "C.I.F.L.". spotdl raises
  `LookupError("No results found for song")` for these. **7 matched an age-gated video**: all the
  explicit tracks. Raw `yt-dlp` with the app's own `player_client=android,web,mweb` failed on
  every one with "Sign in to confirm your age". Neither is a rate limit. Neither changes with time,
  address family or proxy.
- **Why it all looked the same: `Downloader.async_search_and_download` wraps its whole body in
  `except (Exception, UnicodeEncodeError)`.** That includes the `self.search(song)` call that raises
  the `LookupError`. It appends a *string* to `downloader.errors` and returns `(song, None)`. The
  only place the real exception object surfaces is `SongTracker.notify_error(message, traceback,
  finish)`. Its second argument is named `traceback` but is the exception, with yt-dlp's
  `DownloadError` on `__cause__`. `download_one` wraps `progress_handler.get_new_tracker` for the
  duration of the call (an instance override on the cached Downloader's handler, deleted in
  `finally`) to capture it. That means the app's "LookupError is terminal" rule had never applied
  on the download path: spotdl always turned the miss into a `None`.
- **The age-gate marker is `"confirm your age"`, matched anywhere on the exception chain.** It must
  not be loosened to "Sign in to confirm". yt-dlp's bot-check says "Sign in to confirm you're not a
  bot", which *is* network-dependent (v23/v30) and has to stay on the retry ladder. Age-gated
  tracks land `lookup_failed` and stay manually retryable (`_RETRYABLE_TRACK_STATES`), so a future
  cookie file can still pick them up. There is no automatic route back.
- **A search miss is terminal on every rung, the proxy one included. This is a deliberate
  tradeoff.** v30 saw a search come back empty only through one bad proxy, so a proxy miss can be a
  false "Not found". A guard that kept proxy misses on the ladder was written and then dropped. Any
  track at `attempt_count >= 2` uses the proxy rung for every later attempt, and production's 10
  enabled proxies had never recorded a success (`last_success_at` all NULL, 2026-10-12). Under that
  guard, a genuine miss on that rung would have stayed `waiting` and kept feeding the breaker
  forever, which is the exact failure this version fixes. 5 of the 12 real misses were already
  there. A false `lookup_failed` is visible ("Not found") and manually retryable. A forever-waiting
  track is neither.
- **A local verification script run from outside `backend/` imports the main checkout's `app`, not
  a worktree's.** The venv's editable install points there, and `sys.path[0]` is the script's own
  directory, not the cwd. The first real-network check of this fix "failed" for exactly that reason.
  Set `PYTHONPATH` to the worktree's `backend/` and confirm `app.__file__` before trusting the
  result.

### v40 ambient-field gotchas

- **`queue.activeTracks` goes stale off `/`.** `+page.svelte` owns the SSE stream and closes it on
  unmount, but `queue` is a module singleton, so `liveActive` keeps whatever it held when the user
  navigated away. A track that finishes while the user is on `/settings` stays "active" in the
  store until they return. The ambient field's amber tint is therefore gated on
  `page.route.id === '/'` in `routes/+layout.svelte`. Verified on a real download: a second tab
  client-navigated from a live `/` to `/settings` showed the rest tone while `/` showed amber.
- **Playwright never reports a hidden tab.** Each Playwright page is its own window, Playwright
  enables CDP focus emulation, and it passes the anti-backgrounding flags. `bringToFront()` on
  another page, a CDP window minimize, a same-window `Target.createTarget` and
  `Emulation.setFocusEmulationEnabled({enabled: false})` all left `document.hidden === false`,
  headless and headed alike. What works is launching
  `~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome --remote-debugging-port=…` under
  `xvfb-run`, driving it over raw CDP (Node's global `WebSocket`; cookies via `Network.setCookie`,
  instrumentation via `Page.addScriptToEvaluateOnNewDocument`), and opening a real second tab with
  `PUT /json/new`. Switching tabs that way also fires a `pointerout` with a null `relatedTarget`.
- **The cost floor of a script-driven transform.** Measured with a Chrome trace on `/account`, the
  field alone: each frame is one `FireAnimationFrame`, one `UpdateLayoutTree` touching **1
  element**, then PrePaint, Layerize and Commit, about 0.3ms per frame in total. There was no
  Layout, and Paint didn't recur per frame. That's the minimum for any rAF loop writing
  `style.transform`. "Composite only" is reachable only for CSS/WAAPI animations with fixed
  keyframes. On an idle `/` (the noise floor only renders with no active track) the same frames
  show `elementCount: 81`, because Chrome re-samples the
  Waterfall noise floor's 40 compositor-animated bars whenever *any* main frame runs. The
  reduced-motion control (no field frames at all) shows almost no `UpdateLayoutTree`. The
  occasional full-viewport Paint bursts were the cursor crossing hover targets: the same bursts
  appear with the field static.
- **A native drag looks like the pointer leaving the window.** Dragging a link or a text
  selection fires `dragstart`, then `pointercancel` and a `pointerout` with a null
  `relatedTarget`, while the cursor is still on the page (verified headless and headed). Window-
  leave detection must ignore that `pointerout` until the next `pointermove` after the drop.
- **A selector on a class added with `classList.toggle` is pruned by Svelte** (`css_unused_selector`
  from svelte-check). Use a `class:` directive bound to `$state`.
- **"No worse than before" means the old glow's brightest *visible* pixel, not its centre.** The
  old ellipse was centred at −10%, off-screen, so what anyone saw was its top edge, and that edge
  dims with viewport height (amber 5% × (1 − 0.1·h/300px): 3.5% at 900px, 2.6% at 1440px). v40's
  first cut capped the peak at the off-screen centre (`#161410`). A blind reviewer caught that this
  is slightly *brighter* than anything text ever sat on. The peak is now computed from the
  viewport height in the component. To measure "before", render the exact old rule in the same
  browser (inject the old `body` gradient and hide the field) rather than trusting arithmetic.
  This budget leaves only about 4–9 8-bit code values above `--bg-0` in the strongest channel, so
  faint banding stays, as it did before v40.

### v40.1 breaker wedge fix gotchas (learned from production still stuck after v39.2)

- **v39.2's classification worked, and production stayed stuck anyway** (read-only, 2026-10-13,
  `4.40.0`). The track the owner was watching had gone `lookup_failed` ("Age-restricted", IPv6
  rung) on its first post-deploy attempt. The same Scooter job still had 16 tracks `waiting`, and
  `worker_state` read `consecutive_failures=10`, `trip_count=6`, paused 6h. Every user's jobs were
  blocked. Look at the job's *other* tracks before concluding a fix didn't take: four more "Fuck
  The Millennium" tracks, on other albums, were the ones still waiting.
- **The wedge.** The streak reset only on a success, and a release (timed or manual) kept it.
  After each release, the first breaker-feeding failure took it from 10 to 11 and re-tripped it at
  6h. Everything else dispatched in that window was `held` to the next release. A queue of tracks
  that can't succeed produced about one real attempt per 6h, forever, and never the success that
  would end it.
- **The dead proxies.** 9 of the 16 tracks were at `attempt_count >= 2`, so every attempt took
  the proxy rung, and every proxy was dead. The 18:01 re-trip was `ProxyError … Unable to connect
  to proxy (ConnectTimeout)`, raised while ytmusicapi built its client (`url: /`), before any
  search. v39.2 wrapped it as `no_output`. Proxy cooldown caps at 4h and the track ladder at 24h,
  so each retry met a fresh dead proxy. Those tracks could never reach the terminal
  classification v39.2 added.
- **The unit tests didn't catch the drop-the-connection case; the real stack did.** A local
  listener that accepts and closes, used as the only proxy, raised `requests.exceptions.
  ConnectionError(('Connection aborted.', ConnectionResetError(104)))`, which is not `ProxyError`.
  It fed the breaker and tripped the dev breaker 4→5. Fixed by treating any connection-level
  failure on a proxied attempt as the proxy's. That needed `download_one` to `raise … from` the
  swallowed error so the task could still see it.
- **Real-stack fixtures that worked, for next time.**
  - Unreachable proxy: a `manual` row at `http://10.255.255.1:3128`.
  - Drop-the-connection proxy: `python:3.12-alpine` running a 5-line accept-and-close loop on the
    compose network.
  - Working proxy: `alpine` + `apk add tinyproxy` with the `Allow` lines commented out.
  - A real breaker-feeding `no_output` with search still working: a worker-dl overlay with
    `extra_hosts` pointing `www.youtube.com` and `youtubei.googleapis.com` at `127.0.0.1` **and**
    `::1`. With only the IPv4 entry, the IPv6 rung resolved through DNS and downloaded fine.

### v40.2 live-desync fix gotchas (learned from production's Scooter job settling)

- **What the owner saw** (2026-10-14, `4.40.1`): the last three Scooter tracks went
  `lookup_failed` 20s apart. The job row already read `done — partial`, but the Waterfall kept
  three amber lanes at 25–40% for up to a minute, and the state chips still said "active 1 ·
  done — partial 0". The backend was right throughout. Both faults were in `queue.ts`.
- **The lanes:** v23's 60s removal grace (see the corrected Live progress entry) skipped only
  `completed`/`skipped_duplicate`/`cancelled`. `lookup_failed` was left out because a hand retry
  can revive it, but that retry sends its own `downloading` event, which re-adds a lane anyway.
  `LANE_ENDING_STATES` adds it for lane removal only. `TRULY_TERMINAL_STATES` (which also
  discards later events for a track) is unchanged.
- **The chips:** `refreshJobRow` (run 400ms after any track's state change) replaced the row
  without touching `countsByStatus`. It now goes through `patchPageJob`, which moves one count
  from the old `statusKey` to the new one. The comparison is against the row as it is now, so the
  job event's second re-fetch of the same status moves nothing. The two 404 removal paths had the
  same gap and now share `dropPageJob`. Limitation: a job off the loaded page can't be moved (its
  old status is unknown locally); its chips catch up on the next reload. *(Corrected 2026-10-28,
  v62: the server now publishes each move, old → new (`job.status`), and the store applies it to
  a job on the page or off it.)*
- **Real-stack check that reproduced it:** a scratch Playwright script logging in through the real
  upstream, opening `/`, submitting the age-gated `2veKKJYeJjc3MnyhfZ2Gma` (it lands
  `lookup_failed` in about 6s) and sampling the lane count and chip text every 250ms. Against the
  old `queue.ts` (vite HMR swaps it live), the lane stayed and the chips read "active 1" until a
  hard reload. With the fix, both changed within one sample of the API reporting `lookup_failed`.

### v41 track-detail-redesign gotchas

- **Stale history in an open row.** v24's lazy attempt fetch cached per track id. With the
  timeline now the admin's main read of a track, a row opened while it was `downloading` fetched
  zero attempts and kept saying "no attempts yet" after it completed, beside a strip reading
  "attempts 1". The cache key is now what writing an attempt row changes: the counts (a failure or
  success), `scheduled_at` (a `held` row moves no count), and the state, with
  pending/queued/downloading sharing one value so a dispatch or a progress tick never refetches.
  A collapsed run is keyed by its *oldest* attempt, so it stays open when the next identical
  failure lands and the refetch re-renders the timeline.
- **Disclosure names vs the e2e helpers.** The job toggle's `aria-label` ("Expand tracks for X")
  hid its visible status and owner (WCAG 2.5.3, F16), and every spec found jobs through it. Rows
  are now `<li aria-labelledby>` the title, so `jobRow` is `getByRole('listitem', { name })` and
  `jobToggle` the row's first button carrying the title. Job actions are named "archive X",
  "bump X to the front" and so on, so an `exact: true` match on a bare verb no longer finds them.
- **A focusable `<time>` is a Svelte a11y warning** (`a11y_no_noninteractive_tabindex`). The
  plan wants the absolute time "on hover/focus", so each timeline time is a real button that
  also pins the absolute time on click.
- **Forcing the nine cases on the dev stack.** First-try success, live downloading and a
  cancelled track are ordinary real runs (the downloading capture waits on the open page for a row
  to read "downloading N%", since a track takes ~10s). An artist submitted with the worker paused
  and then cancelled gives a 193-track job for "load more". The failure overlay (refused env
  proxy, `LADDER_SECONDS=15,…`) produced the 5-attempt IPv4 → IPv6 → proxy track with two
  identical consecutive proxy errors and a real `lookup_failed` on its own. The 1h waiting case
  is the same overlay with `LADDER_SECONDS=15,3600`. Only the tag-repair warning was SQL-seeded.

### v42 dashboard-redesign gotchas

- **The pill was the only worker poller.** `WorkerStatusPill.svelte` started the 5s
  `worker.refresh()` loop in its own `onMount`. TrackRow's breaker-aware countdown (v41) and, from
  v42, the Waterfall's "holding" line read the same store. Making the pill admin-only (v39 outcome
  3) would have left a non-admin's store at `null` forever, with no error anywhere. The poll moved
  to `+page.svelte` before the pill was gated.
- **Contrast floor vs hierarchy.** At 4.5:1 on `--bg-2`, `--text-dim` (`#808b94`) sits next to
  `--text-muted` (`#8b969d`). The tempting fix is to brighten `--text-muted` to restore the step,
  but v40's ambient field mixes its slate tone from `--text-muted` under a measured contrast budget,
  so that would quietly brighten the page glow. Dim and muted now differ by role (size, case and
  tracking), not by luminance.
- **A live region must not contain a countdown** (F07). The breaker pill re-announced every second
  because `role="status"` wrapped a `Countdown`. The pattern now: one `sr-only` sentence per state
  with a fixed clock time inside the live region, and the ticking text `aria-hidden` beside it.
- **Error state on the dev stack.** Stopping `api` doesn't show the queue's error state: the
  layout's session check fails first and redirects to `/login`. v39 and v42 forced it by answering
  `GET /api/jobs` with a 500 from Playwright. Stopping `api` *after* the page loaded is the real way
  to drop the SSE link (the masthead tell appeared ~10s later and cleared ~6s after `api` returned).
- **A real breaker trip, no SQL.** The v39 dead-proxy overlay (`HTTP(S)_PROXY=127.0.0.1:9`,
  `LADDER_SECONDS=15,…`) plus one album absent from the dev ledger fails five tracks in a row and
  trips the breaker within about two minutes; leaving it running re-trips at 2h after the first
  clears. Restore with `docker compose up -d worker-dl` and clear `worker_state` afterwards.
- **Detector on an authenticated page.** `detect.mjs` accepts URLs but can't log in, and the CLI on
  `.svelte` files misses rendered-only rules. Injecting `detect-antipatterns-browser.js` into a
  logged-in Playwright page and calling `impeccableDetectAsync()` works, but its page-level checks
  then scan the injected script's own text, so `gradient-text` and `marquee` on `body` are false
  positives. Its `gpt-thin-border-wide-shadow` fires at a 16px blur with two thin borders.
- **Thirty-three review rounds, mostly about state that outlives its owner.** After the visual
  work settled, every round found the same family: something async or module-level outliving the
  session, page or row it belonged to. A pending search debounce or an in-flight submit landing
  after a logout. An SSE stream opened under one identity still applying events after the layout
  reset the store. A focused button removed by a live update (Chrome fires `focusout` on removal;
  Firefox and WebKit don't). Each fix was small; the lesson is to ask, for every new timer, await
  and focus target, "what if its owner is gone when this runs?"
- **Focus on a removed element.** A row whose buttons unmount while focused (dismiss, a fold, a
  live update moving it between keyed groups) drops focus to `<body>`. IncomingJobs keeps a
  `{act, job}` memory from `focusin` and restores by data attributes after `tick()`; it clears the
  memory when focus leaves the panel, and `keepFocus` clears it *before* calling `focus()`
  (whose own `focusin` then records the new target).

### v43 secondary-surfaces gotchas

- **Re-sweep staging filed 79 duplicates.** To capture a second mid-sweep, files were copied from
  the dev test library back into `/downloads` under a `v43-resweep-` prefix and their ledger rows
  pointed at the copies. `library.destination_path()` keeps the source's file name, so the sweep
  saw no existing destination and *moved* every prefixed copy into the album folder beside its
  original (79 moved, plus one "source file missing" where two ledger rows shared a file). It was
  undone by repointing the ledger and `tracks.output_path` at the originals and deleting only the
  prefixed copies. Copying under the original name (as done next) takes the conflict branch:
  60 quarantined, the library never written, the ledger repointed back by the sweep itself.
- **Pause holds, it doesn't freeze.** With the worker paused, a newly expanded track is still
  dispatched once; `download_track`'s gate records a `held` attempt and sets it `waiting` with a
  `scheduled_at`. A spec that waits for `lifecycle === 'active'` times out on a `waiting` job.
- **Focus return in the confirmation.** The dialog focuses the trigger *before* resolving the
  promise; an action that then removes or disables its own trigger (remove proxy, a job's cancel,
  pause/resume swapping its button, start sweep) puts focus somewhere sensible itself with
  `keepFocus()` once its state settles: the proxy list's heading, the row, the new button, the
  sweep panel.
- **Native `<dialog>` and Esc.** The `cancel` event is prevented and answered by the same path as
  the safe button, so Esc, the safe button, a backdrop click and a navigation can't diverge on
  the answer or the focus return. The `close` event an answer's own `close()` fires arrives a
  task later, so it is skipped by a `closingByAnswer` flag: otherwise it could answer "no" to a
  question asked in between.
- **Spec 12 / spec 6 change the shared dev stack, and record each change on disk first**
  (`frontend/e2e/.auth/*-stage.json`, `expand-stopped`, `sweep-report.json`), so their own
  `finally` and, after a killed run, the next global setup can undo it. The settings restore is
  conditional (only while the value is still the one the spec set), and so is the sweep report
  (only over the spec's own run, by its start time). The worker pause, the restored failure
  streak (only over a zero, which a deliberate release also leaves) and the worker-expand restart
  are not: after a *killed* run, setup can't tell the spec's leftover from a change the developer
  made since, and undoes it. Each test also skips rather than
  override a worker that is paused, holding, or about to run real tracks, a stopped worker-expand,
  configured Matrix, or anything waiting to be filed. Clear log's archive is the one change not
  staged on disk: global setup's `clearSlate` archives every settled admin job at the start of each
  run anyway, so a killed run's leftover is the state the next run starts from.

### v44 admin-stats gotchas

- **A custom SQLAlchemy `FunctionElement` with constructor attributes must not inherit the
  statement cache.** `stats.epoch_bucket(col, seconds, offset)` renders its bucket length and
  offset as inlined integers (bound parameters in both the SELECT and the GROUP BY make Postgres
  reject the GROUP BY, since the two placeholders differ). With `inherit_cache = True` those
  attributes weren't in the cache key, so a 24h query compiled first served its `/ 3600` to the
  next 7d query in the same process. `inherit_cache = False` fixes it; a test runs 24h then 7d and
  asserts the 7d series (it fails with the cache on). The SQLite rendering lives in `conftest.py`
  next to the JSONB shim.
- **Every writer of `worker_state.breaker_tripped_until` goes through
  `retry.record_breaker_release`** (beat's tick on an expired pause, the admin's release,
  `record_success`, and `maybe_trip_breaker` before overwriting an expired pause), which flushes,
  re-reads the row `FOR UPDATE` and clears the value: that clear is what makes each `released`
  `breaker_events` row once-only. Since v44 an expired pause is NULL within ~30s (beat), where
  it used to keep its old timestamp until a success or release; every reader already treated
  NULL and expired alike. A new writer that sets or clears it directly loses history rows.
- **`proxies.redact()` of a proxy without credentials is its full URL**
  (`http://172.18.0.9:3128`), so "redacted" is not "not a URL". The stats payload carries no
  proxy URLs, so its labels are `host:port`; found only by grepping the real response against
  every raw `proxies.url` on dev. Two proxies on one gateway share a label (rows are keyed by
  position on `/stats`). *(2026-10-17: the owner ruled that out — see the next entry.)*
- **One connection target, one credential** (the owner's rule, decided on v44's PR). Two proxy
  rows for one `host:port` are the same proxy twice, and `/stats` could only tell them apart by
  the credential it must never show. `proxies.connection_target(url)` is the key: hostname and
  port, scheme and credentials aside, a missing port read as the scheme's default (`http` 80,
  `https` 443) the way urllib3 dials it. `POST /api/proxies` answers 409 on any row with the same
  target, enabled or not (the detail names the target and says where to fix it, never a
  credential); `PATCH` refuses to *enable* a row while another enabled row holds its target.
  `sync_from_file()` keeps the first line per target in file order, skips later ones (and a line
  whose target a manual proxy holds) with a warning that logs only the target, and disables a
  skipped line's existing row like a removed line. A new credential for a target whose old line
  left the file is a **rotation**: the old row takes the new URL, its cooldown and failure streak
  reset (`last_used_at`/`last_success_at` kept), so a credential change never mints a second row.
  Rows that predate the rule are not rewritten: two enabled *manual* rows for one target both stay
  enabled until deleted; a disabled duplicate can't be enabled beside its live twin. Two
  consequences of "file rows are never deleted": a target that was ever in `proxies.txt` can't be
  added in the UI afterwards (the 409 says to use `proxies.txt`), and a disabled manual proxy still
  holds its target, so a `proxies.txt` line for it is skipped (only a `worker-meta` warning says
  so) until the manual one is deleted. A byte-identical repeated line was always collapsed and is
  not a clash (dev's `proxies.txt` has one).
- **"Last 7 days" is the last 7 calendar days *including today so far*,** not the last 168
  hours. `stats.window_bounds` covers whole buckets of the viewer's clock ending with the one
  `now` is in, so at 00:05 local the 7d window is 6 days and 5 minutes long, and the 24h window
  at 14:05 starts at 15:00 yesterday. That keeps every bucket a whole hour or day, which the
  chart and its table need. The owner accepted it as-is (2026-10-17); a change that compares
  windows, or alerts on a window's totals, must not read it as a fixed duration. The offset is
  the browser's *current* one, so a 30d window spanning a DST change draws the days before it an
  hour off their local midnight.
- **A long-running Vite dev server can stop opening the v43 confirmation dialog.** After ~39h and
  many HMR updates on dev, clicking "release now" on `/settings` set nothing in `pendingConfirm`
  (the `<dialog>` stayed empty, no console error), while the built nginx image and a restarted
  `web` container both worked. Restart `web` before blaming the code. **Corrected 2026-10-24
  (v52):** a fresh browser saw it too (so it was the server's state, not a page's), and the check
  after the restart opened *pause*, not *release now*. v52 couldn't reproduce it; see the v52
  section for what was tried and what changed.
- **GitGuardian's PR check flags fake credentials in test proxy URLs** ("Basic Auth String" for a
  literal URL with a six-letter user and a four-character password; single-letter or `user:pass`
  ones were not flagged), and a `(user, password)`-shaped tuple of string literals as an
  "Authentication Tuple". It rescans *every* commit in the PR, so a fix-forward commit leaves the
  check red until the incidents are resolved in the GitGuardian dashboard or the commit is
  rewritten, and quoting the flagged string in a doc is a new hit. Build credentialed test URLs
  from parts (`test_proxies_router._cred_url`) or generate the values (`uuid4().hex`).
- **Adding a route while the dev `web` container runs leaves root-owned
  `frontend/.svelte-kit/types/src/routes/<route>/`**, and `npm run check` fails with `EACCES`.
  `docker compose exec -T web chown -R 1000:1000 .svelte-kit` fixes it (the v28 entry's `rm`
  needs the parent writable). **Fixed 2026-10-24 (v52):** the dev `web` runs as uid 1000 and has
  its own `.svelte-kit` volume.

### v45 keyboard-navigation gotchas

- **A keyboard Enter or Space on a button also fires `click`,** with `event.detail === 0`. v43's
  `ConfirmDialog` guessed its opener from "the control clicked in the last second" (Safari doesn't
  focus a clicked button), so a fast keyboard user who confirmed one question and opened another
  within a second got focus handed back to the first dialog's button. Only a pointer click
  (`detail > 0`) counts now, and any `keydown` forgets it.
- **A Svelte `{@attach}` on a list can see no rows yet (or not all of them).** The roving list's
  "take focus back after a remount" ran once at attach time, found no rows, and gave up; a reload
  (which swaps the list for its skeleton) then dropped focus to `<body>`. The claim now waits for
  the rows (the `MutationObserver`'s next settle and a microtask).
- **The queue store never drops a row that stops matching the filter.** `patchPageJob` (and the
  tracks-scope patch) only update an in-page row in place; a cancelled job stays under a "waiting"
  chip until the next reload. So of the plan's "row removed by cancel, archive or an SSE update",
  only archive (with archived hidden) removes a row today; `lists.ts` handles any removal.
- **Playwright's keyboard always maps through a US layout.** Emulate Hungarian keys with trusted
  CDP `Input.dispatchKeyEvent` (`e2e/support/keyboard.ts`'s `huPress`); Ctrl+Alt there (Windows'
  AltGr) types no text on Linux, so emulation proves "fires nothing", not "types `@`". The real
  layout pass needs an X server with `setxkbmap hu` and physical keycodes through XTest; there's no
  `xdotool` on this machine, but `uv run --with python-xlib` does it (XKB key names → keycodes from
  `xkbcomp -xkb $DISPLAY -`).
- **A keyboard e2e step races the page in three places:** `→` on a job whose tracks are still
  "Loading tracks…" does nothing (wait for the nested rows); `j` while a filter or sort change is
  reloading the list finds no list; and `page.locator('h1')` resolves the *old* page's `h1` until a
  navigation lands (wait for the URL or the heading text first).
- **The dev stack's e2e admin has one unarchived job after global setup** (`clearSlate` archives
  the rest), so a spec needing a neighbour row or several filter chips must create a row (a ledger
  track) or show archived first.
- **Don't run `npm run check` or `npm run build` while the e2e suite runs.** `svelte-kit sync`
  rewrites `frontend/.svelte-kit/`, the dev stack's Vite server answers with a full page reload,
  and spec 1 (which watches for exactly that) fails with "the observer must survive: no hard
  navigation in between". Seen in v45's final run; the suite alone passed. **Fixed 2026-10-24
  (v52):** the dev `web` container has its own `.svelte-kit` volume, so a host-side sync no
  longer touches the files its Vite serves.

### v46 i18n gotchas

- **Paraglide's `getLocale()` is overwritten to read a Svelte `$state`**
  (`frontend/src/lib/i18n/locale.svelte.ts`). That's what makes a language switch re-render in
  place with no reload: every message called in a template, a `$derived` or a function called from
  them tracks it. The flip side: a message called once, at module scope, in a plain `const` or as a
  prop's **default value** freezes in the language it was first built in. Label tables are
  functions (`jobStatusLabel`, `trackStateLabel`, `pathLabel`), and `Countdown`'s `label` lost its
  default (an unset label falls back at render time).
- **The inlang SDK treats a plugin it can't load as a warning,** and the compile still reports
  "Successfully compiled" with zero messages. Its default plugin source is a jsDelivr URL fetched
  at build time; the project loads `@inlang/plugin-message-format` from `node_modules` instead, so
  the Docker build needs no extra network. A local module path is resolved from the folder
  *containing* `project.inlang` (`./node_modules/…`, not `../node_modules/…`).
  `scripts/check-messages.mjs` (in `lint`, `check` and `build`) compares the compiled message count
  with the files', alongside the `en`/`hu` key and input parity.
- **The dev `web` container compiles Paraglide's output as root.** On the `./frontend` bind mount
  those root-owned files make every host-side `npm run check`/`lint` fail to recompile them
  (`EACCES`), so `src/lib/paraglide` gets an anonymous volume in `docker-compose.override.yml`,
  like `node_modules`. Both anonymous volumes outlive an image rebuild: after a dependency change,
  `docker compose build web` then `docker compose up -d --renew-anon-volumes`, or the container keeps
  the old `node_modules`. **Vite's recursive watcher doesn't cross into that nested mount:** a
  recompile landed in the volume while the dev server kept serving the old module (an e2e spec
  read "Időtartam" from the files and found "Mikor" on the page). `vite.config.ts`'s dev-only
  `watchCompiledMessages` adds the directory to the watcher explicitly. **That alone wasn't
  enough** (corrected 2026-10-19): Paraglide's default `cleanOutdir` empties and recreates the
  output, and the recreated directory dropped out of the watch again (a new key was "not a
  function" on `/account` until a restart; an in-place append had made the first fix look
  complete). The plugin now compiles with `cleanOutdir: false`; verified with two real
  recompiles in a row reaching the served module.
- **`npx vitest run` rewrites `frontend/.svelte-kit/` too** (its SvelteKit plugin syncs), so the v45
  rule "don't run `npm run check`/`build` while the e2e suite runs" covers the unit tests as well:
  a review agent's `vitest` during a run made the dev server reload and a keyboard spec lose its
  focused row mid-step (the same step passed 3/3 alone).
- **Formats are the interface language *with the browser's region*** (owner's rule on PR #68):
  `format.ts` builds `en-HU` from English and a Hungarian browser, and Chrome's ICU has the data
  ("17 Oct 2026, 13:05", "12 345,5", lowercase "pm" when 12-hour is pinned). Paraglide's own
  `number` registry function formats with the bare language (`en`), so plural messages take a
  pre-formatted `n` beside the raw `count` (`counted()`), never `local n = count: number`.
  **Intl has no data for most `hu-<region>` pairs** (`hu-US` resolves to plain `hu`), so the region
  silently stopped counting for a Hungarian interface; `format.ts` checks the pair resolved as
  asked and otherwise takes numbers and the default clock from the region's likeliest locale,
  **maximized explicitly** (`new Intl.Locale('und', { region }).maximize()`): Intl never
  maximizes `und-DE` itself, it falls back to the runtime's default locale (en-US in Chromium and
  Node), which made the region stop counting a second time (review round 7).
- **The browser decides the language until sign-in** (owner's rule on PR #68): no `/login`
  switch, nothing stored in the browser, nothing adopted at sign-in. The plan's pre-login choice
  and its adoption were built, reviewed, then removed on the owner's answer; a "choice someone
  else left in this browser" was the bug class that made the owner's rule the simpler one.
- **A saved language beats the browser's, and the API can set one but not clear one.** The e2e
  projects pin their browser `locale` (`en-US`, `hu-HU` for `hu`) and expect the page to follow it,
  so global setup and teardown reset both identities' `user_settings.language` to NULL straight in
  the database (`stack.ts`'s `setLanguage`). The specs read names from the compiled message files
  (`e2e/support/i18n.ts`'s `t()`, which passes `{ locale }`); spec 14 points the Node-side runtime at
  the project's language, since the keyboard bindings' labels are message functions.
- **`keyboard/bindings.ts` imports its messages relatively** (`'../paraglide/messages.js'`): the e2e
  suite imports the table under Playwright's Node loader, which knows no `$lib`.
- **Hungarian keeps the noun singular after a numeral** ("5 szám"), so a count is a message with
  `count` (an `Intl` plural selector in `en`, a plain variant in `hu`), never `${n} tracks`. A
  sentence that inflects its noun ("ezt az albumot nem sikerült beolvasni") is one message per
  noun, never a noun spliced in. `Countdown` prints `{label} {time}`, so Hungarian labels are
  phrased to stand before a time (`feloldásig 4:32`), and the time is `nowrap` so a phone wraps
  before it, never between "2 nap" and its clock.
- **Spec 14's priority keys raced the page, not the API** (v45's spec, exposed by v46 running it a
  second time in the `hu` project). A row takes one priority step at a time and drops a key pressed
  while the last step is still settling in the page, which outlasts the moment the API returns the
  new value; the spec pressed the next key as soon as the API did. Each step now waits for its own
  PATCH response and a page tick.
- **The hidden admin 404s carry no error `code` on purpose** (`require_admin_hidden`, the test-alert
  route): a code would tell them apart from an unknown route's `{"detail": "Not Found"}`, which is
  the point of answering 404. Every other user-facing error is an `app/errors.py` `ApiError`.

### v47 ui-polish gotchas

- **`px` width breakpoints ignore the user's text size** (WCAG 1.4.4). With the browser's default
  font at 32px a 1024px window kept the desktop row grid while every `rem` column doubled, and job
  titles measured 0px wide. `em` media queries are relative to the *initial* font size (the
  browser's setting, not `html { font-size }`), so they move with it. Testing it: setting
  `html { font-size }` from a page script does **not** exercise em queries; Chromium's
  `Page.setFontSizes` over CDP (`{ fontSizes: { standard: 32 } }`) does.
- **An open `EventSource` can outlive the network under it** (laptop sleep, a Wi-Fi change,
  Playwright's `setOffline`): no `error`, no events, `readyState` OPEN, the tell still "linked".
  The server's heartbeat is an SSE comment (`: heartbeat`), which page JavaScript never sees, so
  it can't be a watchdog. `/` treats the window's `offline` event, and two worker polls in a row
  that failed at the network level (a `TypeError`, not an `ApiError`), as the link being down.
  That doesn't cover a stream the server dropped while the machine slept with the network back
  on wake (no poll fails, and a quiet stream looks like a dead one): restarting on every return
  to the tab would wipe the list for a resync each time, so it is left to the browser's own
  socket timeout (review round 14).
- **A session-ended handler must navigate before it resets the store.** `/`'s stream and poll
  read a `queue.reset()` while still mounted as an identity change and `window.location.reload()`
  the tab, which lands on `/login` without the "your session ended" state. The layout's
  `onUnauthorized` handler `goto`s `/login` (with `state: { sessionEnded: true }`) first, then
  resets. `/api/auth/me` is excluded from the global 401 hook: the layout's load owns it.
- **An empty live region in a flex column still takes a `gap`**, so every panel ended in 16-40px of
  dead space. Collapsing it with `display: none` stops some screen readers announcing text that
  arrives later; `position: absolute` plus a 1px clip (app.css's `:empty` rule for `.form-error`,
  `.save-state`, `.field-error`) takes it out of the flow and keeps it announceable.
- **`content-visibility: auto` was tried for the 1600-row log and rejected:** it brings paint
  containment, which clips a row's 3px focus ring and the attempt timeline's absolute-time popup at
  the row's edge. Paging (50 rows) keeps normal use fast; a fully loaded log is ~28k nodes.
- **A Playwright full-page screenshot (or an element shot taller than the viewport) drops
  Chromium's touch emulation**, so `(pointer: coarse)` turns false and none of the 44px rules
  show in the image. Measure touch targets before any screenshot, or grow the viewport instead.
- **Fontsource faces are imported by the layout, not linked from `app.html`:** each weight's CSS
  declares every subset with a `unicode-range`, so a page downloads only latin and (Hungarian's
  ő, ű) latin-ext. Adding the packages needs the dev `web` container's `--renew-anon-volumes`
  (v46 entry above).

### v48 v4-hardening gotchas (learned closing out master v4)

- **Two ledger rows can share one downloaded file, and the sweep stranded the second (F34).**
  spotdl names a file from its metadata, so a single and its album cut (two Spotify ids) can
  resolve to the same `/downloads/...mp3`, and both ledger rows point at it. The sweep moved the
  file for the first row; the second then hit `source file missing on disk`, kept its old path,
  and would be pruned by `reconcile_disk()` into a re-download. The sweep now groups the ledger
  by source file: each file is decided once, and every row sharing it (re-read just before the
  repoint, so a row worker-dl recorded mid-sweep is included) is repointed in the same commit
  before the source is deleted (so neither a crash between rows nor a failed copy can split
  them). One window stays open: a row worker-dl commits between that re-read and the delete is
  still stranded, since the sweep and worker-dl run concurrently. Every count in the report
  (`total`, `processed`, moved, deleted, quarantined, errors) is a count of files, apart from a
  whole-sweep `<post-move sync>`/`<sweep>` error row. Real before/after on the dev stack, same running worker for
  "before" (it predated the edit): `main` listed `/downloads/v48-ghost.mp3` twice and left
  `v48-sharedA-2` stranded; the branch listed the ghost once and filed both `v48-sharedB` rows to
  one library file.
- **Rows stranded before v48 stayed stranded (repaired 2026-10-20, below).** Production's last sweep (2026-10-18) reported 47
  "source file missing" errors, and every one of the 47 not-in-library ledger rows has a sibling
  with the same basename already in the library: earlier sweeps stranded them. The fix only
  prevents new ones; those rows keep erroring on each sweep until repaired or pruned (a prune
  means a re-download if that track is requested again). _(2026-10-20, owner answer: repaired,
  by one-shot data migration `cab1bff456eb`, which runs after the deploy's pre-deploy
  `pg_backup` and before the new workers start (the old ones are still up while it runs). It relinks a row only if the last sweep listed its
  path as "source file missing on disk", no track with its Spotify id completed a download since
  that sweep started (a re-download writes the file back but `db.merge` keeps the row's old
  `downloaded_at`, so the attempts log is the signal), and exactly one in-library ledger file
  has its basename (the sweep keeps a source's basename); its
  completed and skipped-duplicate tracks follow. Read-only dry run on production: 47 of 47 rows,
  47 tracks. On dev, a real stranded row's file answered 404, then 200 after `migrate`; a
  downgrade and re-upgrade relinked 0. A failed 4.48.0 deploy past `migrate` can't roll back
  automatically (the database is ahead of 4.47.x); DEPLOYMENT.md's third way out downgrades
  `alembic_version` only, losslessly.)_
- **What kept the 47 rows alive was an accident.** `reconcile_disk()` (every worker-meta boot,
  so every deploy) refuses to prune rows under a root that looks unmounted, and an empty
  `/downloads` looks unmounted. Each sweep empties `/downloads` (unless it quarantined something:
  the default quarantine dir is `/downloads/quarantine`, which keeps it non-empty for good), so
  the deploys after it skipped the stranded rows. The first boot with any new download waiting would have pruned all of them,
  and each track would have re-downloaded when next requested. That is why the repair is a
  migration: every backend service waits for `migrate`, so it lands before `reconcile_disk()`. *(2026-10-26, v57: the "empty means unmounted" guard is gone; a
  mount sentinel decides.)*
- **A completed download's ledger merge never set `in_library`.** `db.merge` copies only the
  attributes given, so a row whose library file went missing and was downloaded again kept
  `in_library=True` on its new `/downloads` path, and no sweep (it reads only `in_library=False`)
  would ever file it. The merge now sets `in_library=False`. Real on dev: a library row repointed
  at a missing file, the track resubmitted, a real direct download, and the row read
  `/downloads/01 - Portishead - Mysterons.mp3`, `in_library=f`; the next sweep filed it (1
  quarantined, onto the existing library copy).
- **A first repair relinked at runtime, and the review rejected it.** The sweep and
  `reconcile_disk()` relinked any missing row to the one in-library file with its basename,
  forever. A user who deletes `/downloads/01 - Artist - Intro.mp3` to force a re-download would
  have had it linked to another album's `01 - Artist - Intro.mp3` instead, and the sweep's copy
  had no unmounted-root guard. Every legacy row exists at the moment v48 deploys, so a
  migration scopes the repair exactly; the runtime code was reverted.
- **A first fix that deduplicated the error log row by row was wrong.** The blind review found
  that a per-row pass still split shared rows (a failed copy for the first row, then a successful
  one for the second, deleted the source the first still pointed at) and that a per-path error
  list disagreed with the per-row live count `/library` derives (`processed − moved − deleted −
  quarantined`). Grouping by file fixes the cause; the error list is one entry per file because
  each file is processed once.
- **A sweep archives only the sweeping admin's jobs (owner decision, F34(b)).** It used to archive
  every user's settled jobs whose tracks it moved, silently. Now every user's `Track.output_path`
  is still repointed, but only the admin's own jobs are archived (`archive.archive_jobs` is scoped
  to that one user id), and only the admin gets archive events. Proven on dev: the admin's job was
  archived, `v37user`'s job kept its repointed track and stayed unarchived. The `/library`
  confirmation copy (en + hu) says so.
- **Priority and bump are admin-only on the server too (owner answer, 2026-10-20).** v47 hid
  them from non-admins but `PATCH /api/jobs/{id}/priority` and `POST /api/jobs/{id}/bump` still
  accepted a job's owner. Both now depend on `require_admin`, which answers 403 before the job
  lookup, so a non-admin gets the same 403 for their own job, a foreign one, and an unknown id
  (live on dev: 403 `admin_required` ×3, priority unchanged; the admin still 200/404). They left
  `test_ownership.py`'s 404 sweep for a 403 test of their own. *(2026-10-26, v56 (A6): an admin route whose path names an id (priority, bump, one proxy) now answers a non-admin 404, like stats and the test-alert send; `tests/test_admin_gating.py` holds the table.)*
- **The ambient glow's glide runs on WAAPI once the pointer stops (owner answer to v40's open
  question), and stays a rAF loop while it moves.** The first version retargeted a Web Animation
  on every move. At a real mouse's one move per frame that cost 0.90ms/frame against the loop's
  0.59 (each new animation restyles the element about twice, and ~45 keyframes had to be built and
  parsed); two keyframes with one cached `linear()` easing brought it to 0.80, still worse. The
  hybrid: the loop runs while moves keep coming, and once ~50ms pass without one it starts a
  two-keyframe glide from the last frame's position, `startTime` back-dated by the frame's step,
  so the hand-off frame matches the loop. Handing off on the first quiet frame made slow input
  start and cancel a glide each time (+15–23%); counting frames instead of time would do the same
  on 144–240Hz displays. Measured on `/login` against the v40 component (swapped in via
  `page.route`): the same style-update count while moving, 2–14% more main-thread time per frame;
  after the last move 4 loop frames, ~9 style updates and ~5ms of tasks instead of ~60 frames and
  21–25ms; at rest nothing.
- **Resuming the loop from a glide: pin it on the next frame, one frame back.** A move during a
  glide must restart the loop where v40's would have stepped from, the glide's position one frame
  before the next one. Pinning inside the pointermove read the wrong instant: Chrome's
  `document.timeline.currentTime` outside a frame is an estimate on a fixed 60Hz grid
  (`kApproximateFrameTime`), and inside a frame with no rAF pending it already reads that frame's
  time. Two earlier versions got this wrong in turn (a fresh first-frame step on top of the glide
  skipped a frame; then dt 0 ignored the new target for a frame, 6–8px off v40 on a 100px
  retarget). The loop now pins at the start of its next tick, at `now − interval` on the glide's
  own clock (`interval` is the shortest of the last three real loop frames, so one dropped frame
  doesn't stretch it). And the glide runs on to its fixed 1.6s end after v40 would have snapped:
  a pin within 0.5px of the target must count as at rest, or a resize ~1.2–1.6s after a leave
  drifted the glow dW/2 px instead of moving it with home. Probes that run their own rAF logger
  keep a rAF pending and hide all of this; screencast the composited result with no other rAF on
  the page.
- **A new Web Animation's `currentTime` reads 0 until the frame after it's created**, because its
  start time resolves a frame late. A retarget every frame then reads keyframe 0 every time, and
  the first WAAPI version froze while the mouse kept moving (0 px/frame over 117 moves). Set
  `startTime` yourself. Likewise `pause()` only takes effect on a rendered frame, which a hidden
  tab doesn't produce: pin the position instead. Probe at real rates: a `page.mouse.move` loop
  with waits sends ~20 moves/s, far below a mouse; CDP `Input.dispatchMouseEvent` at a 16ms
  interval gives one per frame (headless input lands between frames, a real mouse's in-frame).
- **`uvicorn --reload` hangs on open SSE streams.** Editing `app/tasks/library.py` made `api` log
  "Waiting for connections to close" and stop answering (container `unhealthy`), because an
  `/api/stream` connection was still open. `docker compose restart api` clears it. **Fixed
  2026-10-24 (v52):** see the v52 section.
- **The pipeline record since v33 found two releases that never reached production.** 4.40.2's
  `deploy` job died at "Set up job" on a GitHub `429` downloading `actions/checkout`, and the
  `notify` job needs the same action, so it died the same way: no Matrix message, and nobody
  re-ran it (production stayed on 4.40.1 until 4.41.0, ~30 h later). 4.47.0's `publish` failed on
  the runner's Docker credential, shared with another repository's concurrent release (its
  fix, a job-private `DOCKER_CONFIG`, is a separate change); that one did alert.
- **A real breaker trip never reached the room.** Production tripped on 2026-10-18 at 18:46:47 UTC
  (5 consecutive `no_output`, then ~460 `held` rows; *2026-10-26, v55: one trip holds each track
  once, so these were most likely ~460 distinct tracks' queued messages, which v55's
  same-track collapse doesn't shrink*) and released at 19:16:47; `breaker_events`
  has both rows, but the Matrix room has no trip or release message (its earlier trips, 10-12 to
  10-14, all alerted). The code path enqueues after the trip's commit and the send expires after
  300 s on `meta`; why it was lost can't be told: the next deploy (23:18) recreated every
  container and took the logs with it. Still open. *(2026-10-28, v59: still unknowable which one
  it was, but every candidate path reproduced and is closed; see v59.)*
- **v31's open questions, closed on dev.** A real 11-track album (Portishead, *Dummy*) completed
  with normal pacing, and `stat` found all 11 files at their `output_path` inside `worker-dl`.
  One track sent through a dead-proxy `worker-dl` overlay retried at exactly +5 s, +10 s, +15 s
  and +20 s (`LADDER_SECONDS=5,10,15,20,30`) before the pool-proxy rung's real "No results found"
  made it `lookup_failed`. The plan's "v21 empty-`DOWNLOADS_DIR` observation" has no matching entry
  in this file or the plans; the album run's files in `DOWNLOADS_DIR` are the evidence against it.
- **Stdin and `docker compose exec -T`.** `while read p; do docker compose exec -T svc stat "$p";
  done < list` stats only the first path: `exec -T` passes the loop's stdin to the container and
  consumes the rest. Run the loop inside one `exec ... sh -c 'while read ...' < list`.

### v49 ci-chain gotchas (learned replacing the `workflow_run` chain with one in-run chain)

- **`workflow_run` makes an empty run for every completion it hears.** The trigger fires whenever
  the named workflow completes, whatever its event or branch, so every PR's CI run, every
  scheduled run and every dispatch started a Release run whose only job skipped itself. A
  skipped run still *completes*, so it fired Publish & Deploy, which skipped too: 161 of 214
  Release runs and 159 of 230 Publish & Deploy runs in the whole history at v49 (160/212 and
  158/228 in the planning count) were these. The listener
  matches the upstream by workflow *name*, and GitHub names a run by the default branch's
  workflow at that file path: a scratch copy of `ci.yml` renamed on a test branch still ran as
  "CI" and woke `main`'s Release. Give a test copy its own file path.
- **The fix is jobs of one run calling workflows (`uses:` + `workflow_call`).** `needs:` orders
  the stages, the caller grants the permissions (`contents: write`, plus `packages: write` for
  the deploy) and passes
  `secrets: inherit`, and the stages a merge doesn't need show as skipped *jobs* in that one run,
  not as runs. A called workflow sees the caller's `github` context (`event_name`, `sha`,
  `workflow`, `ref`), so it takes its mode from its inputs, and only `main` may release:
  `plan` fails a dispatch from any other branch, which would otherwise tag and persist-deploy an
  unmerged commit.
- **A concurrency group cancels, even with `cancel-in-progress: false`.** GitHub keeps one
  running and one pending run or job per group and cancels the older pending one. So there is
  no group anywhere; the one self-hosted runner already serializes every job, and the deploy's
  version guard turns an older release arriving last into a successful no-op. A second runner
  would need another, non-cancelling lock.
- **The one runner takes queued jobs roughly first-in, first-out across all runs** (observed,
  not guaranteed). A merge's `plan`,
  `release` and `deploy` each become ready only after the previous stage finishes, so each of
  them queues behind every job of every run started meanwhile (other merges' and PRs' checks).
  A burst of merges therefore interleaves stage by stage, and a release can wait behind a whole
  wave of PR checks. That's why agents push in batches.
- **Burst test outcome (scratch, 2026-10-23).** Three version-bump pushes 14 s apart made three
  "Release & Deploy" runs, all `success`, none cancelled or skipped. With no concurrency group,
  nothing was cancelled by GitHub either (the question task 3 asked), so `deploy-prod` was dropped
  for good. The FIFO queue ran them stage by stage (the three `plan`s, then the three `release`s,
  …), 36 minutes from the first push to the last notice, and the stub deploys landed in push
  order (9.0.4, 9.0.5, 9.0.6). Only 9.0.6 pushed `latest`; the two older publishes, which ran
  after 9.0.6's tag existed, logged "Not pushing latest". An older version pushed afterwards
  (9.0.2 over the 9.0.6 baseline) is the guard's own test, recorded in the PR.
- **Nothing cancels, so ordering is the guard's job, not the queue's.** `latest` and the
  "Latest" badge are decided against the remote's `v*` tags right before they're set, never
  earlier in the run, and a deploy below `.last-good` is a no-op that writes nothing.
- **Read the remote in an assignment, not a pipeline.** GitHub's default `run` shell is
  `bash -e` without pipefail, so `git ls-remote … | grep -q .` reads a failed `ls-remote` as "no
  such tag" (and would have cut a release). `TAGS="$(git ls-remote …)"` fails the step instead.
- **A notice must not need a download.** A job with any `uses:` downloads its actions during "Set
  up job", before step one, so a GitHub `429` there kills every step (v48). Each `notify` is one
  `run:` step with `curl`: the URL and the token reach curl on stdin (`--config -`), never its
  command line; secrets are whitespace-trimmed first, since a pasted trailing newline breaks
  curl's config file and reads as "no response".
- **Two runs can carry the same untagged version** (a bump, then an unbumped merge whose `plan`
  runs before the first release). The second run's release finds the tag and succeeds, so a
  deploy gated only on "release succeeded" would ship the second commit under the first
  commit's tag. `release.yml` outputs `owned` (the tag points at this run's commit), and the
  deploy runs only when it's true.
- **A merge without a new version no longer deploys anything.** Before v49 every merge re-deployed
  the latest release, which also replaced a `manual-*` dispatch and shipped pipeline-only
  fixes. The owner's lever for both is a `redeploy` input on the "Release & Deploy" dispatch: the
  tag's commit, deployed in release mode with `main`'s workflow files and `.pipeline` scripts.
  What the deploy checks out (compose files, `wait_for_stack_health.sh`) is still the tag's, so a
  fix there needs a version bump, as before v49. And re-run a failed run's
  *failed* jobs only: "Re-run all jobs" re-runs `plan`, finds the tag, and ends green with
  nothing deployed.
- **A failed deploy is no longer retried by the next merge.** Before v49 every Release
  completion (an unbumped merge's included) fired Publish & Deploy, which retried a failed
  deploy. Now the deploy runs only after a release in the same run, so a failed one waits for
  `gh run rerun <id> --failed`; the notice says so by arriving at all. A re-run uses the run's own
  commit's workflow files (and expires after 30 days), so a workflow-side fix reaches the
  current release with a `redeploy` dispatch instead.

### v50 parallel-stacks gotchas (learned building the agent slot stacks)

- **Ports were the obvious collision, not the only one.** A second dev stack on the same machine
  also fails on:
  - the network: `docker-compose.override.yml` pins the dev network's IPv6 subnet
    (`fd00:dead:beef::/64`), and Docker won't create a second network with the same subnet.
    `docker-compose.agent.yml` gives each slot `fd00:dead:beef:<slot>::/64` (an `!override` on
    `ipam.config`, a list);
  - the bind-mount sources: in a fresh worktree `./downloads`, `./test-library`, `./proxies.txt`
    and the `web` container's anonymous-volume mountpoints (`frontend/node_modules`,
    `frontend/src/lib/paraglide`) don't exist, so Docker creates them root-owned (`proxies.txt`
    as a directory). The uid-1000 workers then can't write `./downloads`, and a host `npm ci`
    fails with `EACCES`. `agent_stack.sh up` creates them first, and copies
    `frontend/.env.example` to `frontend/.env`, without which `npm run check` (and Vite) can't
    resolve `PUBLIC_API_BASE_URL` from `$env/static/public`.
- **Postgres 18's image moved its data directory.** `PGDATA` is
  `/var/lib/postgresql/18/docker`, and the image refuses a volume mounted at the old
  `/var/lib/postgresql/data`. The slot volume goes on `/var/lib/postgresql`. 18.6 is production's
  version (`SELECT version()` on `spotdlwebtest`, the same server, 2026-10-23).
- **`env_file: .env` would leak the owner's identities into a slot.** Interpolation follows
  `--env-file`, but every backend container still loads the anchor's `env_file: .env`, so a slot
  would carry the owner's `ALLOWED_EMAILS` (the real admin included) and Matrix token. The overlay
  replaces it with `.env.agent` (`env_file: !override`), and builds `DATABASE_URL` itself from the
  slot's `AGENT_PG_*` values.
- **The e2e suite can't run without `worker-dl`.** Seeded jobs settle as `skipped_duplicate`
  inside `download_track`, and setup and teardown ask `worker-dl` (`celery inspect`, the dedup
  check) what it would download and what it's running. So `agent_stack.sh <slot> e2e` takes the
  realdl lock like a real download does, although a default run makes no network attempt
  (teardown proves it).
- **The e2e suite leans on the owner's dev history, not only `LEDGER_TRACKS`.** On a fresh slot
  database the first run failed 21 tests: specs 12 and 14 submit nine more ledger tracks
  (`CANCEL_TRACKS`, `SUBMISSION_TRACKS`, `HELD_TRACKS`, `NEIGHBOUR_TRACK`), spec 14 wants "an admin job with twelve or
  more tracks" and three pages of 50 jobs, and spec 3 an admin track whose attempt recorded a
  network path ("run `npm run test:e2e:network` once"). `scripts/agent_seed.py` recreates all of
  it (stand-in files are one-second silent MP3s: dedup is folder + filename only, so they count
  as present). One ordering trap: spec 9 takes the first two in-library ledger files *under the
  library root*, ordered by Spotify id, and spec 14's `098tt…` sorts before every other id. So
  the submitted-track rows are filed (`in_library`, which a library sweep skips, so spec 12's
  sweep has nothing to move) but kept under `/downloads`, and only spec 9's two sit in the
  library.
- **`ERR_NETWORK_CHANGED` from another stack.** Specs 10 and 11 once failed on a blank page: the
  trace showed every module request aborted with `net::ERR_NETWORK_CHANGED`. Chromium cancels all
  in-flight requests, loopback ones included, when it sees the host's interfaces change. It
  happened while slot 2's six backend containers were crash-looping (the v32 guard test), each
  restart adding and removing a veth (the journal also shows this host's VPN agent reacting to
  every one). That's the likely trigger, not a proven one: single restarts and 25 back-to-back
  `docker run`s didn't reproduce it. Another agent's crash loop can fail your run; re-run (v52
  owns retries).
- **Bash reads a script while running it.** An edit to `agent_stack.sh` while a long `realdl` or
  `e2e` from it was running would have run whatever text landed at bash's saved offset once the
  child command returned (a rebase that touches the file does the same). The commands now run
  from a `main` function, called on the script's last line, so the whole file is parsed first.
- **`docker compose ps -a` lists a stopped profile service.** After `realdl` stopped `worker-dl`,
  the exited container stayed in `ps -a` although its profile wasn't active, and `up`'s health
  wait read it as crashed. `realdl` now removes it (`rm --stop --force`) on release.
- **Healthchecks pass in seconds, not after `interval`.** Docker 25+ probes every 5 s during
  `start_period` (the default `start_interval`), so the workers' 120 s `interval` doesn't delay a
  fresh stack's health: a slot is healthy about 15 s after its containers start.
- **Tracks dispatched while `worker-dl` is off wait in the slot's Redis.** Beat keeps dispatching
  due tracks to the `downloads` queue, and its stale-track reclaim (`beat._reclaim_stale_tracks`)
  re-dispatches them every `STALE_TRACK_AFTER_SECONDS`, so duplicate messages pile up. They run on
  the next `realdl` (or `e2e`), for real if the track isn't in the ledger. `e2e` therefore refuses
  while such tracks exist, and `realdl` counts them as it starts.
- **The v32 guard's message names the owner's database.** A slot pointed at a production name
  refuses on all six backend services, but the advice reads "point DATABASE_URL at
  spotdlwebtest", which a slot never uses. Its fix is `agent_stack.sh <slot> env`.
- **The Alpine Postgres image collates differently from production.** The first slot overlay used
  `postgres:18.6-alpine`; `ORDER BY` over `('b','B','a','_z','Z')` gave `B Z _z a b` there (musl:
  codepoint order). `spotdlwebtest` and `spotdlweb` are `en_US.UTF-8` with the libc provider on
  Debian (glibc), which sorts case- and punctuation-insensitively first. Server-side sorts and
  cursor pagination over text would then pass on a slot in an order production never produces.
  Slots run `postgres:18.6-bookworm`; switching an existing slot's image needs `down --volumes`
  (an index built under one collation is wrong under another).
- **Cookies are not port-scoped.** `SPOTDL_SESSION` is a host-only cookie on `localhost`, and a
  browser sends it to every port there: logging in to a slot on `localhost:5174` replaces the
  owner's `localhost:5173` session, and each stack rejects the other's token. Playwright's
  contexts are separate jars, so the suite is unaffected; a person needs one browser profile per
  stack.
- **Changing a named volume's config makes Compose ask to recreate it, on a terminal only.** v50's
  first round labelled the base file's `redis-data` volume in the overlay. An existing slot then
  printed `Volume "spotdlweb-s1_redis-data" exists but doesn't match configuration in compose
  file. Recreate (data will be lost)? [y/N]` on every `up` run from a terminal, and an interactive
  `realdl` hung on it; without a TTY Compose went ahead silently, so scripted runs never showed
  it. Only `pgdata` carries the worktree label, as it has since that volume was first created.
- **Ignoring SIGINT in bash doesn't protect a `docker compose` child.** `trap '' INT` is inherited
  as "ignored", but the Go docker CLI re-enables SIGINT, so a second Ctrl-C during the realdl
  cleanup aborted `docker compose rm` and left `worker-dl` running with the lock free. The removal
  now runs under `setsid --wait`, out of the terminal's process group.
- **Bash defers a trapped SIGTERM until its foreground child exits.** `kill <agent_stack pid>`
  during `realdl <hour-long command>` did nothing until the command ended. The command now runs in
  the background with `wait`, so the trap fires at once and passes SIGTERM on (a background child
  of a non-interactive shell starts with SIGINT ignored, so SIGINT isn't forwarded as is).
- **`pg_isready` without `-h` checks the unix socket.** On a fresh volume the image's init runs a
  temporary server on the socket only; a socket probe passes while TCP clients (`migrate`) still
  get "connection refused". The slot healthcheck probes `-h 127.0.0.1`.
- **Celery as PID 1 ignores an early SIGTERM.** A process running as PID 1 gets no default signal
  actions, so until celery has installed its own handlers a SIGTERM does nothing, and `docker stop`
  waits out `stop_grace_period` (300 s for `worker-dl`) before SIGKILL. A `realdl` interrupted
  during `worker-dl`'s first seconds sat in its cleanup for the full five minutes. The slot overlay
  gives `worker-dl` `init: true` (tini as PID 1 passes the signal on, and celery, not yet handling
  it, simply exits); production's `worker-dl` is unchanged.
- **A `wait`-based signal forward reaches only the direct child.** The first `run_locked` sent
  SIGTERM to the command it started; `realdl sh -c 'sleep 299'` left the `sleep` running (a
  background child of a non-interactive shell starts with SIGINT ignored, so the terminal's Ctrl-C
  didn't reach it either). It now signals the command's whole process tree, on SIGHUP too.
- **A dead stderr kills the cleanup, twice over.** With `realdl … 2>&1 | tee log` and Ctrl-C, `tee`
  dies too. Bash then took SIGPIPE writing to it, and its EXIT trap (which bash 5.3 does run after
  a fatal signal) took another on its own first message, before removing anything, so `worker-dl`
  stayed up with the lock free. (Corrected 2026-10-24 in review: an earlier version of this entry
  said a signal death skips the EXIT trap.) With SIGPIPE ignored in bash,
  the docker CLI inherited a broken stderr and died of SIGPIPE itself (Go raises it on a failed
  write to fd 2) before removing the container. The script now ignores SIGPIPE while it holds the
  lock (the command gets the default back), turns errexit off in the cleanup, and sends the
  removal's output to `.agent-stack/realdl-cleanup.log` before copying it to stderr.
- **The script's production-`.env` check is SQLAlchemy's URL grammar, not a string cut.** Its first
  parse cut at the first `?` and took the last `/` segment, so a `?` in a password, a trailing `/`
  or space, `%77` or a socket URL (`postgresql:///spotdlweb?host=…`) named "production" past it,
  and `env`/`up` would then have commented out that checkout's `DATABASE_URL`. It now matches
  `sqlalchemy.engine.url._parse_url`'s pattern (what app/config.py's guard uses), checks both the
  path and `?dbname=`, percent-decoded and case-folded, and refuses a URL it can't parse. The
  main-checkout refusal fails closed too (a `git rev-parse` error refuses). (Corrected 2026-10-24:
  it checked only the first `dbname=`, and Compose interpolates `.env`, so `?dbname=x&dbname=spotdlweb`
  and `/${PGDB}` got past it. It now checks every `dbname=` and refuses a URL with a `$`.)
- **`docker compose --profile '*'` enables every profiled service.** The `run` guard looked for
  `worker-dl` next to a starting verb, `realdl` and `COMPOSE_PROFILES`, so
  `run docker compose --profile '*' up -d` started `worker-dl` (and `cloudflared`) outside the lock.
  It now refuses any `--profile`. The same `run docker compose up` had also skipped the mount
  preparation, so Docker created `proxies.txt` as a root-owned directory, which a later `up`
  accepted because it tested `-e`: `run` prepares the mounts now, and both refuse a non-file.

### v51 pytest-postgres gotchas (learned moving the suite from SQLite to real Postgres)

- **The move exposed no new race, and almost no test cared.** 601 of 602 tests passed on the
  first Postgres run. (The known E2 reclaim race, v55's, now has a real-connection reproduction:
  a strict xfail in `test_beat_task.py`, added after round 2 of the blind review pointed out
  that D8 names "reclaim".) The one failure was `test_stats.py`'s `test_current_breaker_state`, which
  inserted `WorkerState(id=1)`: the initial migration seeds that row, and `create_all` never did.
  It merges the row now. `committed_db`'s truncate puts the seed back, so every test starts from
  what a fresh `upgrade head` leaves.
- **Rollback isolation vs `begin_snapshot`.** `db_session` is one outer transaction with
  `join_transaction_mode="create_savepoint"`, so the code's commits become `RELEASE SAVEPOINT`s.
  Postgres sets an isolation level only at a transaction's start, and SQLAlchemy raises
  (`isolation_level may not be altered unless rollback() or commit() is called first`) when
  `begin_snapshot` asks for REPEATABLE READ inside it. The test connection drops that one option:
  with no concurrent writer, the rows read are the same. The snapshot itself is proven with
  `committed_db` (`test_job_listing_snapshot_hides_a_job_committed_mid_listing`).
- **`count_queries` would count the SAVEPOINTs.** They're the isolation's statements, not the
  code's, so the listener skips them. Without that, every N+1 guard broke.
- **`now()` doesn't move inside `db_session`.** Postgres's `now()` is the transaction's start, and
  the whole test is one transaction. The two v35 "`updated_at` left alone" tests turned hollow
  that way: with the guard reverted, the column's `onupdate=func.now()` wrote the value the row
  already held, and both still passed (blind review, round 1). They pin an explicit past
  `updated_at` first now. A test whose point is that a server timestamp moved, or didn't, needs
  an explicit past value or `committed_db`.
- **A failed race test must not leave its threads parked.** One that fails while another thread
  waits at a gate leaves that thread's transaction open, and its locks block the teardown's
  `TRUNCATE`. `committed_db` opens every gate and joins every thread first
  (`concurrency.release_all`).
- **The test marker alone doesn't keep a run off production's server.** `spotdlwebtest` passes
  it, and lives on the same server as `spotdlweb`. `TEST_DATABASE_URL` must also name a slot's
  `postgres` or a loopback host, and even that isn't enough on the production host (the CI
  runner), where loopback reaches production's Postgres: the run refuses any server that holds
  `spotdlweb`, `spotdl_web` or `spotdlwebtest`, checked over the connection before `CREATE
  DATABASE`.
- **A forgotten `SessionLocal` patch used to fail loudly, and now wouldn't.** Before v51 an
  unpatched one connected to a placeholder URL and errored; now `app.db.engine` is the run's
  real database, so it would read past the test's uncommitted rows and commit outside the
  rollback. `db_session` fails any test that checks out a connection of its own.
- **SIGTERM skipped `pytest_sessionfinish`** (live review), leaving the run's database behind;
  the session start installs `signal.default_int_handler` for SIGTERM, so it unwinds like
  Ctrl-C. A `%` in the rendered URL (any %-escaped password) crashed `alembic/env.py`'s
  `set_main_option` (configparser interpolation), printing the URL with its password; the
  conftest refuses such a URL first.
- **Round 3 of the blind review:** a harness timeout raised `AssertionError`, so the E2 strict
  xfail (`raises=AssertionError`) would have stayed XFAIL even if a rewrite stopped reaching the
  gate; the harness raises `concurrency.InterleavingBroke` now. A loopback URL with no port means
  5432, which on the runner is production's Postgres: refused before connecting. And
  `test_track_listing_embeds_derived_job_title` passed with its "first track" order reversed,
  since both tracks shared one `created_at` inside the test's transaction (pinned now; a full
  suite run with the order flipped fails it and nothing else).
- **Round 3 of the live review:** a failed `committed_db` test whose own Session stayed open (its
  traceback keeps it alive) held its row lock, and the next `db_session` test blocked forever.
  `committed_db` now terminates every other backend on the run's database before truncating. A
  stray commit from an unpatched `SessionLocal` was reported but stayed for the rest of the run:
  `db_session` truncates after one. A thread nobody joined lost its exception silently:
  `release_all` reports it. And `env -i NAME=value` put the password in `env`'s argv for an
  instant (an execve trace caught it): `agent_stack.sh` builds the clean environment with
  `os.execve` instead.
- **Round 4 of the blind review:** `?port=` in the query overrides the URL's port in the psycopg
  dialect, so `127.0.0.1:55432/x_test?port=5432` got past the "loopback, but not 5432" rule (the
  production-server check still held); `port` joined the refused query keys. And the suite read
  timestamps in the server's own TimeZone: against a server in `Europe/Budapest`, 15 tests failed
  (their `.replace(tzinfo=timezone.utc)` shifted the instant). The run's database is created with
  `ALTER DATABASE ... SET timezone TO 'UTC'`.
- **Round 4 of the live review:** a `db_session` test that left a lock held on an engine of its
  own hung the next test forever; the run's database has `lock_timeout = '30s'` now (it failed
  with `LockNotAvailable` after 30 s in the probe). The E2 xfail ran the "download" commit on the
  main thread, so a fix that row-locks the sweep's snapshot would have deadlocked it into an
  `InterleavingBroke` instead of an XPASS; that commit runs in a `Thread` now, and both fix
  shapes (a state re-check, a `FOR UPDATE` snapshot) give `XPASS(strict)`.
- **Round 5:** `committed_db` beside `db_session` (or `client`, `make_user`, anything built on
  it) errored at teardown with a stray-connection message that told the test to do what it was
  doing; it now fails at setup saying the two can't be combined, which wave 2's race tests need to
  know (call the endpoint function with committed sessions instead). A role-level `timezone`
  outranks the database's: 16 tests failed under `ALTER ROLE ... SET timezone =
  'America/New_York'`; conftest sets `PGTZ=UTC`, a startup option that outranks both. libpq's
  `PGHOSTADDR`/`PGSERVICE`/`PGSERVICEFILE` could pick another server than the URL's host: refused
  when set.
- **Fixture teardown order matters for race tests.** `committed_db` depends on `monkeypatch`, so
  it tears down (releasing parked threads) while the test's stubs are still in place.
- **Alembic from Python, without the ini.** `command.upgrade(Config("alembic.ini"), ...)` runs
  `alembic/env.py`'s `fileConfig()`, whose `disable_existing_loggers` silences every app logger
  already created, and every `caplog` test with it. conftest builds a bare `Config()` with only
  `script_location`, and catches `alembic.runtime.migration`'s INFO lines itself to print them.
- **pytest skips `pytest_sessionfinish` when `pytest_sessionstart` raises.** A failed migration
  would leave its database behind, so the start hook drops it itself before re-raising.
- **Proving a lock held, without a sleep.** `blocked_or_done` polls `pg_stat_activity` for a
  session in the run's database with `wait_event_type = 'Lock'`. The run's database is its own,
  so any waiter is the test's. Paired with a `Gate` on the holder (`before_commit` session event,
  `once=True`), each race test is deterministic, and each fails with its guard reverted (the PR
  lists the outputs).
- **The service container's pull happens outside the job.** The runner pulls and starts
  `services:` containers before the first step, with the runner user's shared
  `~/.docker/config.json`. publish-deploy's job-private `DOCKER_CONFIG` (#71) is set by a step and
  can't apply. The image is public, so it pulls anonymously, but a dead `docker.io` credential or
  `credsStore` helper in the shared file would fail the job before it starts
  (`docs/CI_SELF_HOSTED_RUNNER.md`, section 5).
- **A credentialed URL literal in a workflow is a GitGuardian finding** (v44), so the CI Postgres
  runs with `POSTGRES_HOST_AUTH_METHOD=trust`, published on loopback only.
- **`${{ job.services.<id>.ports[...] }}` only works from the steps on.** The first push had it in
  the `pytest` job's `env:`, where only `github`, `inputs`, `matrix`, `needs`, `secrets`,
  `strategy` and `vars` exist. GitHub rejected the whole file: the PR got a 0-second failed run
  listed under the **`push`** event (ci.yml has no `push` trigger at all), "likely failed because
  of a workflow file issue", and no check on the PR. `docker run --rm -v "$PWD:/repo:ro" --workdir
  /repo rhysd/actionlint:1.7.7 -shellcheck=` reports it before a push (`context "job" is not
  allowed here`). It moved to the "Run pytest" step's `env:`.

### v53 extension-api gotchas (learned building the extension's backend contract)

- **The cookie spike: a Firefox MV3 extension's background `fetch(…, {credentials: 'include'})`
  carries `SPOTDL_SESSION`.** Real Firefox 158.0.1 (headless, through geckodriver), the throwaway
  spike extension (scratchpad only) installed with `host_permissions` for the app's origins, the
  test user signed in through the app's own login form in the same profile (production: the
  owner let `v5s3user@example.com` into `ALLOWED_EMAILS` for the run, 2026-10-24, then removed it;
  its sign-in left a `users` row there with no jobs):

  | Origin | Total Cookie Protection | `GET /api/auth/me` | same, with `X-Spotdl-Client` | `POST /api/jobs` (header, search text) |
  |---|---|---|---|---|
  | `http://127.0.0.1:5176` | on (`cookieBehavior=5`) | 200, the user | 200 | 422 `url_not_spotify` (authenticated) |
  | `http://127.0.0.1:5176` | off (`cookieBehavior=4`) | 200 | 200 | 422 |
  | `http://localhost:5176` | on | 200 | 200 | 422 |
  | `http://localhost:5176` | off | 200 | 200 | 422 |
  | any of the above, signed out | either | 401 | 401 | 401 |
  | `https://spotdl.vb2007.hu` (production, 5.50.0) | on | 200, the user | 200 | not sent (no allowlist there yet) |
  | `https://spotdl.vb2007.hu` | off | 200 | 200 | not sent |
  | `https://spotdl.vb2007.hu`, signed out | either | 401 | 401 | |

  So the cookie is `Secure` yet set and sent over plain-HTTP loopback (Firefox treats loopback as
  a secure context), and `SameSite=Lax` doesn't stop a background request from an extension that
  holds a host permission for the origin, GET or POST. TCP partitions cookies by top-level site;
  an extension's background page isn't a third-party frame, so it reads the first-party jar either
  way. v58's cookie path stands; the key stays the fallback.
- **A Firefox match pattern has no port.** `permissions.contains({origins: ['http://127.0.0.1:5176/*']})`
  answers `false` even with `http://127.0.0.1/*` granted (the pattern is invalid, not denied), and
  the fetch works all the same. Check `scheme://host/*`. v58: declare host permissions without
  ports.
- **A key is no credential anywhere but job create, `GET /api/jobs/{id}` and `me`, so an admin's
  key gets 401 on an admin route, not 403.** The plan asks for "non-admin answers"; a non-admin's
  cookie gets 403 (404 on `/api/admin/stats` and the test-alert send), but a key never reaches
  `require_admin` at all: every other route keeps `require_session` (cookie only), which answers
  401 `not_authenticated` (owner's decision, 2026-10-24: keep 401). `test_api_keys.py`
  parametrizes this over every route in the app, not only the admin ones. The job read was added
  on the owner's decision the same day (the master plan's "read their own submission status"):
  through a key it's the key's user's own jobs only, an admin's too (404 otherwise). *(2026-10-26, v56 (A6): an admin route whose path names an id (priority, bump, one proxy) now answers a non-admin 404, like stats and the test-alert send; `tests/test_admin_gating.py` holds the table.)*
- **FastAPI keeps an included router as a lazy `_IncludedRouter` in `app.routes`** (0.162 in the slot's
  image, 0.141.1 in `uv.lock`/`requirements.txt`: both do). A test
  walking `app.routes` for `APIRoute`s finds only the four built-in docs routes; descend through
  each wrapper's `original_router.routes` (every router here carries its own prefix, and
  `include_router` adds none).
- **`hint: "already_queued"` answers 200 with the existing job, and creates nothing.** Owner-scoped,
  canonical URL, an unarchived job still `expanding` or with a `pending`/`queued`/`downloading`/
  `waiting` track. A settled, failed or cancelled job doesn't count, so re-submitting a finished
  link still re-runs it (dedup then settles it at once). Two simultaneous identical submits
  both created at first (the live review's 6 parallel posts made three jobs); the create now locks
  the user's row before the check, so they serialize: one 201, five 200. It's `FOR NO KEY UPDATE`
  (`with_for_update(key_share=True)`), not `FOR UPDATE`, on purpose: a concurrent login's session
  insert takes a `KEY SHARE` lock on the same row, which `FOR UPDATE` would block. An
  `expanding` job counts only for its first hour (a lost expansion would otherwise answer every
  re-submit forever, and a key can't cancel it). A `spotify:` URI the web UI submits is stored as
  typed (cookie requests keep today's behavior), so it never matches an `https` link's job. The web UI (the dashboard form and the incoming
  overlay's "try again") shows a notice for it instead of adding the returned job a second time,
  since that job is already on the page.
- **Every Spotify link a job stores is canonical now, the web UI's too.** `https://open.spotify.com/<type>/<id>`
  (no `intl-xx`, no `?si=`), so the hint matches a link however it was copied. Text that isn't
  such a link keeps today's path (the web UI's search, an `/episode/` link) and is stored as typed.
- **A cascade is resolved in the request, not in expansion.** One spotdl metadata call (`track`
  or `album`) through `_ensure_spotify_client()`, bounded at 10 s on a small thread pool: an
  ambiguous artist must reach the caller as a 409 with the candidates, and expansion has no one
  to ask. spotdl's scraping client answers an unknown id with a bare `KeyError` (422
  `cascade_not_found`); anything else is 503 `cascade_unavailable`.
- **The rate limiter fails open.** A Redis error lets the login or create through (logged), since a
  Redis outage shouldn't lock everyone out. In pytest there's no Redis at all, so every test not
  using the `fake_redis` fixture (`tests/extension_support.py`) runs unlimited.
- **Testing low limits on a slot: edit `.env.agent`, then recreate `api` through `run`.**
  `agent_stack.sh <slot> up` rewrites `.env.agent` from `.env` (only `COPIED_KEYS`), so appending
  `JOB_CREATE_RATE_LIMIT=4` and running `up` loses it; `run docker compose up -d --no-deps
  --force-recreate api` keeps it. Put the original back the same way afterwards.
- **Inside a Playwright test, `request.newContext()` gets the project's `storageState`.** Spec
  18's "cookie-less" key check went out with the signed-in user's cookie, the API tried the
  cookie first, and a revoked key "still worked" (200). Pass `storageState: {cookies: [],
  origins: []}` for a request that must carry only a key, and check the answer came from the key
  (a key's `me` has only `email`, `username`, `is_admin`).
- **The dashboard form never sends bare words.** `submitLink.ts` refuses text without a link,
  so the web UI's non-allowlisted submissions are a `spotify:` URI, a `<youtube>|<spotify>` pair or
  another site's link (all kept for a cookie request without `X-Spotdl-Client`); search text only
  arrives through the API.
- **Real-stack evidence jobs on a slot leak into later e2e runs.** Spec 14 picks the admin's
  largest job, archived ones included, so a cancelled 296-track artist job from a cascade check
  replaced the seeded 14-track album and four keyboard tests failed. Cancelling and archiving
  isn't enough: delete such jobs from the slot database (it's the slot's own) before `e2e`.
- **Text Postgres or UTF-8 can't take reaches the API as JSON escapes.** A NUL (`\u0000`) and a
  lone surrogate (`\ud800`) in a key label, a link or a login email each gave a 500 (a psycopg
  `DataError`, or `UnicodeEncodeError` in the login bucket's hash) until refused up front:
  `spotify_urls.storable` for links and logins, `api_keys.normalize_label` (also C1 controls and
  bidi overrides, which reordered the key prefix in the revoke dialog). In a test, httpx can't
  encode a lone surrogate (`json=` raises): send `content=json.dumps(...)`. And `str.strip()`
  removes `\x85` (NEL) as whitespace.
- **redis-py retries a dead connection with backoff by default** (6.x: three tries, exponential
  with jitter), so 1 s socket timeouts still left a "fail-open" limiter stalling each request for
  several seconds. `Retry(NoBackoff(), 0)` makes it fail at once.
- **FastAPI's default 422 echoes the submitted body back (`input`), so a lone surrogate in it made
  the 422 a 500, and that 500's traceback logged the whole body: a login's password, in plain
  text.** Pre-existing on every endpoint; `app/errors.py`'s `validation_error_handler` now answers
  `request_invalid` with each error's type, location and message only (still a list in
  `detail`, which `api.ts` already maps). The same encode failure hid in `cascade_invalid`'s own
  `params` (it echoed the value), and a NUL in a quoted cookie (`"\000…"`, which Starlette
  unquotes) made `get_valid_session` a 500 on every route until it answered "no session".
- **A broker error after the job row commits left a job `expanding` forever** (pre-existing), and
  v53's hint then handed it back to every re-submit for an hour. Job create now marks it `failed`
  and archived (it would otherwise sit in the incoming panel reading as an unreadable link) and
  answers 503 `queue_unavailable`, so the next submit starts over. It's archived, not deleted
  (soft archive is a locked decision), so a client hammering create through a Redis outage
  leaves one hidden row per try: the rate limiter fails open in that same outage.
- **`.delay()` on a task whose result is stored waits on the result backend first.** With Redis
  stopped, `expand_job.delay` took about 19 s to raise (the Redis result backend's
  `on_task_call` retries its connection 20 times), so the 503 above came after 19 s and the job
  sat `expanding` meanwhile. Nothing reads `expand_job`'s result: `ignore_result=True` (as
  `send_alert` already had) makes it fail in well under a second.
- **A key label's character rule took eight review rounds; the principle that held is "no text
  may be invisible".** Patching characters one by one kept losing: tag runs behind 🏴, joiner and
  variation-selector runs (the known smuggling encodings: two selectors per byte, one joiner per
  bit) and single ignorables after an ASCII word all made a label render exactly like another key's,
  or carry hidden data. The rule now (`services/api_keys.py`): Unicode's Default_Ignorable_Code_Point
  set is refused except in the one context a script or emoji needs it (ZWJ/ZWNJ around a virama,
  ZWNJ between letters of a joining script such as Arabic, ZWJ between emoji, past a presentation
  selector or skin tone as in ❤️‍🔥; VS15/VS16 after a non-ASCII symbol or punctuation, ℹ, or a
  keycap digit; ideographic variation selectors after a CJK ideograph; Mongolian selectors within
  Mongolian), and never more than 8 per label (`MAX_IGNORABLES`: enough for several emoji
  sequences, and a bound on what they could encode). The residue is accepted on purpose: one
  needless ignorable in a valid context (★️ vs ★, a ZWNJ after a non-joining Arabic letter) still
  renders like the plain text, but a label is shown only to its owner and every key row and the
  revoke dialog show the key's unique prefix beside it. Tag characters only as the three recommended
  subdivision flags (England, Scotland, Wales); controls, surrogates, line/paragraph separators,
  blank-drawing characters (U+2800, U+1D159, U+16FE4) and non-visible format characters refused
  (the prepended number signs, which draw, stay); one visible character required. Space
  separators trim at the ends and collapse inside (two spaces or an NBSP would look like one),
  in the form too, which also counts code points like the backend (its `maxlength` counts UTF-16
  units and once cut emoji labels mid-sequence, so it's only a 4x backstop). Python 3.12's tables
  are Unicode 15.0, so newer emoji (🫩) read as unassigned (`Cn`): those, and private use (macOS's
  Apple logo), count as visible.
- **Job create caps the link or search at 2048 characters** (`submit_too_long`): the web UI's
  cookie path had no bound, and a 20 MB "search" was stored, searched by worker-expand and echoed
  into every listing of that user's jobs (a 60 MB `GET /api/jobs`).
- **The login buckets key an IPv6 client by its /64** (one host holds a whole /64 and could rotate
  through it); an IPv4-mapped address counts as its IPv4, a zone id is dropped.
- **On a dev or slot stack every login shares one client address** (the Vite proxy's, or the
  container peer: no Cloudflare in front), so the per-address login bucket counts every login of
  every identity, successes included, against 5x LOGIN_RATE_LIMIT_FAILURES. Low test limits trip
  it within a few logins, and buckets from an earlier, longer window survive an `api` recreate:
  delete `spotdl:ratelimit:*` in the slot's Redis before a limits check.

### v52 dev-loop gotchas (learned fixing the dev loop and the e2e flakes)

- **`uvicorn --reload` hung because a reload is a graceful shutdown.** The old server waits for
  every in-flight response before it exits, and an `/api/stream` response only ends when its
  client hangs up. Reproduced on slot 2: with `curl -N /api/stream` open, an edit at 19:07:30 logged
  "Waiting for connections to close", `/api/health` stopped answering, and the old server finished
  only at 19:08:28, when the 60 s `curl` gave up. `--timeout-graceful-shutdown 3` in the dev
  command: the same edit at 19:09:12 logged "Cancel 1 running task(s), timeout graceful shutdown
  exceeded" at 19:09:15 and the new server was up at 19:09:19. The cancelled generator's `finally`
  unsubscribes, and the browser's EventSource reconnects. Production has no `--reload`, but a
  deploy's `docker stop` of `api` waits on open streams the same way, up to Docker's 10 s kill
  (not changed here).
- **The backend image has no `watchfiles`.** `backend/pyproject.toml` asks for
  `uvicorn[standard]`, but its uv `override-dependencies` (there for spotdl's own pins) replace it
  with plain `uvicorn`, extras gone, so the dev `api` reloads with `StatReload`, and there was no watcher to wrap the
  Celery workers with. `scripts/dev/reload.py` is a stdlib poller (one `os.walk` a second over
  `/app/app`), mounted read-only at `/opt/dev` and set as the three workers' dev `entrypoint`, so
  each worker's `command` is still `docker-compose.yml`'s (worker-dl's `--concurrency=1
  --prefetch-multiplier=1` can't drift). Only a `celery … worker` command is supervised: any other
  (a `docker compose run` one-off, a shell) is `exec`ed as is, so it's never re-run on an edit (an
  earlier version restarted one-offs too, and hung after them). A change
  sends SIGTERM (Celery's warm shutdown) and SIGKILL after the service's stop grace (300 s for
  `worker-dl`/`worker-expand`, Docker's default 10 s for `worker-meta`): a SIGKILLed main process isn't covered by
  `task_reject_on_worker_lost`, so its task would wait for the broker's 6 h visibility timeout or
  beat's stale sweep. A worker exiting on its own, for any reason, ends the wrapper with its status
  (128+N for signal N), so the v32 config guard still stops the container and Docker's restart
  policy covers every crash, a syntax error an edit brought in included (it crash-loops until
  fixed, and comes back after the fix on Docker's restart backoff: ~25 s after a 45 s error).
  A `docker compose stop` that lands while a just-reloaded Celery is still booting exits 143
  (Celery dies of the SIGTERM before its handlers exist, as it would unwrapped). An earlier version waited for the next edit instead after a crash soon after a reload,
  and a worker SIGKILLed in that window stayed dead behind a "healthy" container. `init: true`
  keeps the wrapper off PID 1 (which drops a signal that arrives before its handler exists) and
  reaps orphans.
- **A dev dependency change no longer needs `--renew-anon-volumes`.** `node_modules` is a named
  volume with a stamp of the `package-lock.json` it was installed from; the dev command runs
  `npm ci` into the volume when the bind-mounted lockfile differs (`npm ci` works on a mounted
  `node_modules`: no `EBUSY`). The stamp leaves out the app's own `version` (every slice bumps it,
  and a bare `sha256sum` of the lockfile would have reinstalled at every slice's first boot), and
  the dev healthcheck's `start_period` is 300 s, room for that `npm ci`. The one remaining step is a
  restart: `docker compose up -d` leaves a
  running container alone when its image didn't change (seen: removing a dependency again rebuilt
  to an identical cached image, and `up` printed `Running`), so `docker compose restart web`.
- **Root-owned frontend files came from the dev `web` running Vite as root.** It now runs as
  `node` (uid 1000) from a deps-only `dev` stage, whose `node_modules`, `src/lib/paraglide` and
  `.svelte-kit` are owned by `node`, so fresh volumes start that way. The volumes are *named*: a
  recreated container keeps its old anonymous volumes, which a pre-v52 container had filled as
  root. A pre-v52 checkout still has root-owned files in the bind mount; the dev command refuses
  to start over them and prints the `chown` that hands them back, and `agent_stack.sh up` runs it
  itself. The uid is fixed, not the host's: on a host whose user isn't uid 1000, Vite (uid 1000)
  can't write the bind-mounted files that user owns (`project.inlang`'s cache, say) and fails with
  `EACCES`. This host's user is uid 1000; another host would need a `user:` and a matching image.
- **A new named volume is filled from whichever image mounts it first.** Compose doesn't rebuild an
  image it already has when the override's `target` changes, so the first plain `up` after v52 ran
  the old root `build`-stage image, which filled the three new `web` volumes as root (tried on slot
  2 with the pre-v52 image re-tagged). The dev command now refuses a root image (with the one-step
  recovery: remove `web` and its volumes, `up --build`) and any of the three directories it can't
  write. `agent_stack.sh up` builds `web` before its first `run`. A missing `frontend/.svelte-kit`
  is created root-owned on the host as the volume's mountpoint, so `up` pre-creates it.
- **Host-side `npm run check`/`lint`/`build` reloaded every open dev page, two ways.**
  - `svelte-kit sync` regenerates `.svelte-kit/generated` (`root.js`, `root.svelte`,
    `server/internal.js` with a new `version_hash`), and on the shared bind mount the dev Vite
    logged `page reload .svelte-kit/generated/root.js` for each. The dev `web` now has its own
    `.svelte-kit` volume.
  - `scripts/check-messages.mjs` compiled Paraglide with the default `cleanOutdir`, which
    `rmdir`s `frontend/src/lib/paraglide` and recreates it (seen with `strace`). That directory is
    the mountpoint of the container's own compiled-messages volume, and **Linux detaches a mount
    whose mountpoint is removed from another mount namespace**: the container's mount table lost
    `/app/src/lib/paraglide` (1 entry, then 0), so from then on it shared the host's directory and
    every host compile logged `page reload src/lib/paraglide/messages.js`. That is also what
    v46's "the recreated directory dropped out of the watch" was. The script now compiles with
    `cleanOutdir: false`, as `vite.config.ts` already did: five compiles plus a full
    `check`/`lint`/`build` kept the mount and logged nothing. Host `npm ci` and `svelte-kit
    sync` remove no mountpoint, but a hand-run `rm -rf frontend/.svelte-kit` (or `node_modules`,
    or `src/lib/paraglide`) still does, and the container then shares the host's copy (a
    `.svelte-kit` loss also 500s every open page until the host regenerates it). `docker compose
    restart web` remounts all three, and the e2e global setup refuses to start while one is
    missing (`detachedWebVolumes`), so it can't come back as a mid-run reload.
  - A host `npm run build` still logs `page reload build/*.html`, and the e2e HTML reporter
    `page reload playwright-report/*.html` at the end of a run; Vite's client ignores both (it
    reloads only for its own page's HTML).
- **Chromium keeps a `Secure` cookie on `http://127.0.0.1`; Playwright's request contexts
  don't.** Logging in through the page on `127.0.0.1` gave a working session (`/api/auth/me` 200
  from the page), while a `request.newContext` made from that page's storage state got 401:
  Playwright's cookie matcher accepts plain HTTP only for `localhost` and `*.localhost`. The suite
  now targets `http://127.0.0.1:<port>` (v38's `[::1]:5173` capture can't happen), and global
  setup saves both sessions with the flag dropped, so every context made from them sends it.
- **Spec 12's "start sweep asks first" flake was the page's own race.** After a confirmed start,
  focus goes back to the start button, the page disables it (`starting`), sends the POST, and
  called `keepFocus(heading)` once the answer landed. A browser drops a disabled control's focus
  only on its next frame, so when the answer came back within the frame, the check still saw the
  button focused and did nothing; the stream's `running` then disabled it for good and focus fell
  to `<body>` ("focus after confirming"). Outside the suite, 4 of 30 confirmed starts ended on
  `<body>`; with focus moved to the panel heading *before* the button is disabled, 0 of 60.
- **Spec 14's load-more flake was the test's.** The job search re-lists after a debounce (~330 ms
  here), and the test's waits after typing (the job's row listed, "loading" gone) could pass on the
  list from before the search; the search's answer then re-rendered the rows under the next key
  press. Timed on slot 2, the skip-link test's "one row listed" wait passed 5–19 ms after typing
  while the search answered at 325–366 ms, in 10 of 10 runs. `typeSearch` waits for the request
  whose `q` is the typed text (the store applies only its newest request's answer).
- **Spec 3 makes its own network-path fixture** when the admin has no track with a recorded
  network path (a fresh database), so it no longer needs a prior `@network` pass.
- **v44's "a long-running Vite stops opening the confirmation dialog" didn't reproduce.** v44's own
  transcript says more than its entry: the failing control was *release now*, one minute after a
  real breaker escalation; a *fresh* browser also got the `<dialog>` element rendered but empty
  and never opened (so the server's state, not one page's); no console error; and the check after
  restarting `web` opened *pause*, not *release now*. A rendered dialog that never reacts while
  `confirmAction` (which `handleRelease` calls before anything else) did run means the page held
  two instances of `stores/confirm.ts`, or of the Svelte runtime. What v52 ran against the dev
  server, checking a fresh page each time (and, in the soak, a page kept open throughout):
  - 162 HMR cycles on the dialog's own files and their importers (`confirm.ts`, `ConfirmDialog`,
    `WorkerStatus`, `/settings`, the layout, `queue.ts`), with navigation between pages, HMR with
    the dialog open, and compile errors then fixes;
  - 40 bursts of simultaneous writes to eight of those files while a page loaded;
  - a host-side `svelte-kit sync`, a new npm dependency discovered at runtime (Vite optimized it
    without a new browser hash), and 10 in-process Vite restarts;
  - a soak against a second, pre-v52-style dev server (root, shared `.svelte-kit`) on a copy of
    the tree, mixing HMR edits, host-side `svelte-kit sync` (partly failing with `EACCES` on
    root-owned types, as v44's did), `chown` of `.svelte-kit`, routes added and removed, bursts,
    and `vite.config.ts` restarts: 1,759 cycles over 3 h 32 min (959 HMR edits, 189 bursts, 215
    host syncs, 84 `chown`s, 62 routes added, 41 restarts), with 334 checks of a fresh page and
    331 of a page kept open throughout. The dialog opened every time it was asked. The one stop
    was a fresh page that never rendered while the server stalled for 40 s under a parallel e2e
    run's load; from then on the probe counted those apart (4 more), and never one where the
    page rendered and the dialog didn't open.
  Every fresh page loaded `confirm.ts`, and each optimized dependency, under one URL, and the
  dialog opened every time. No fix went into `ConfirmDialog.svelte`. What v52 did change is the one
  mechanism found that rewrites what Vite serves from outside it: a host-side `npm run check`
  (which v44's session ran repeatedly while `web` ran as root, chowning `.svelte-kit` by hand)
  rewrote `.svelte-kit/generated` and detached the container's compiled-messages volume. Both
  now stay in the container's own volumes. If it recurs: list the module URLs a fresh page loads
  (`performance.getEntriesByType('resource')`) and look for `confirm.ts` or a
  `.vite/deps/svelte_internal_client` chunk under two queries before restarting `web`.
- **A reload restarts `worker-meta`'s boot work too.** Its boot runs `reconcile_disk()` (prunes
  ledger rows whose file is missing) and `proxies.sync_from_file()`, so since v52 every backend save
  runs them on the dev stack, as a manual `docker compose restart worker-meta` always did. That is
  safe during a library sweep: the sweep commits a row's repoint before unlinking the source, and
  reconcile re-reads a row whose file is missing before pruning it (v34.1).
- **Vite's error overlay can outlive a fixed compile error.** After a syntax error in a `.svelte`
  file and a byte-for-byte revert, an open page kept `vite-error-overlay` (vite-plugin-svelte skips
  the unchanged output, so no update clears it), and it intercepts every click: in a kept-open tab
  that looks exactly like "the dialog doesn't open". Esc or a reload clears it. Not v52's doing.

### v54 scope-others gotchas (learned building the admin's mine/all/others view)

- **`others` hides the admin's own downloads from the page, so U1's "the viewer's own download
  warms the page in every view" needs a second signal.** The stream drops every message on
  `channel_for(me)` (the plan's design: payloads stay owner-less, filtering is by channel only), so
  under `others` no event of the admin's own ever reaches the store. `queue.ownReceivingElsewhere`
  asks `GET /api/tracks?state=downloading&include_archived=true` (no `view`: mine is the default)
  on each resync and on the page's existing 5 s
  worker poll, in `others` only, and the layout's ambient field reads `queue.viewerReceiving`. So
  the field can take up to 5 s to warm or cool for an own download seen from `others`.
  _(Corrected 2026-10-26, v54 review rounds 4–8: the store-internal count is asked for one row
  (`limit=1`), on the poll only while that poll's own answer says the worker is busy (`busy` is
  "any track `downloading`", so idle means 0); each check takes its place in line when it
  starts, and the newest one that lands wins, so a failed poll discards nothing.)_
- **A filtered stream can go silent for longer than the heartbeat interval.** The heartbeat was
  "no message within 15 s"; with the admin's own progress ticks arriving every second and all of
  them dropped under `others`, nothing would have been written at all. `_event_stream` now also
  writes a heartbeat when 15 s pass since the last write, dropped messages or not.
- **Whose lane is it, in `all`?** The SSE payloads carry no owner, so a lane that arrives by event
  is unplaced until `resolveLaneOwners` (throttled to one per 250 ms, one bulk request: the view's own
  `downloading` listing, which embeds `owner_*`; the page tells the store the viewer's email, so the
  same listing says whose lane is the viewer's). Until then it reads as elsewhere (neutral), so the
  admin's own lane in `all` turns amber a moment after it appears. _(Corrected 2026-10-25, v54
  review round 2: the first version also asked `view=mine` and compared ids, two snapshots that
  could disagree.)_
  `lanesLookedUp` keeps a lane the lookup couldn't list (it left `downloading`) from asking again
  on every progress tick. _(Corrected 2026-10-26, v54 review round 4: the lookup is throttled, not
  debounced: ticks closer than 250 ms kept pushing a debounced one back. An unlisted lane stays
  unplaced rather than "not the viewer's", and any return to `downloading` asks again.)_
- **"Live" on a row was "receiving", not "receiving for you".** v47 made a job's badge and bar
  amber while one of its tracks downloads; in `all` that lit other users' rows too, which the
  first real-download probe showed. `JobRow`'s `own`, `TrackRow`'s `elsewhere` (threaded through
  `JobTrackList`) and `IncomingJobs`' pulse now follow the viewer, like the field and the Waterfall.
- **Verifying U1 needs a real download, timed.** The probe (six real browser pages, three views,
  two identities, en/hu, desktop/mobile) missed the first download: it finished while the pages
  were still logging in. Holding the track `waiting` a minute out let the pages settle first. A
  second id turned out to be a song already on disk under the same filename and settled in 0.2 s.
- **`replaceState` and `page.url` disagree, and history remembers the wrong one.** SvelteKit's
  `replaceState(url, state)` rewrites the address bar but leaves `page.url` at the last real
  navigation, and stores that stale `page.url` in the history entry (`PAGE_URL_KEY`). A Back to
  the entry then navigates to the stale URL: a hard load at `?view=others`, a switch to mine (the
  bar reads `/`), a trip to `/account` and Back came back as others. Both the "is the URL already
  right" check and the mount-time read take `window.location` (the page is `ssr = false`).
  `replaceState` in `onMount` of a hard load also throws in dev ("before router is initialized":
  `started` is set after mount and after the first `afterNavigate`), so the mount-time sync waits
  a `setTimeout`.
- **"Mine" leaves no query string, so the history entry has to say it another way.** A `/` entry
  left in mine looked exactly like a fresh `g d` to `/` (which keeps the store's view, v42), so a
  Back to it opened whatever view the admin used last. The view now also goes into the entry's
  page state (`replaceState(url, { view })`, `App.PageState.view`); SvelteKit restores it on a
  popstate before the page renders (`client.js`, `page.state = popped.state`), and a link or
  `goto` arrives with `{}`. Naming `?view=mine` instead would have changed every admin dashboard
  URL that specs 14 and 17 assert.
- **Three quick Backs raced the page's own URL sync.** The live reviewer's rapid Back sequence
  (dashboard → account → dashboard → account, then Back ×3) landed on the first `/` entry while
  the second dashboard was still mounted: a same-route popstate reuses the component, and its
  `afterNavigate` wrote its own `others` over the entry. It reproduced 5 of 6 times in Playwright
  and never in a slower script. `afterNavigate` now adopts the popped entry's view on a popstate,
  and the mount-time sync skips while another navigation is in flight.

### v54.1 premiere-terminal gotchas (learned from a production track stuck on an unaired premiere)

- **An upcoming premiere looked like a rate limit.** Production's "End Of An Era" (Dua Lipa)
  matched `h097ly4MFVg`, a YouTube premiere 102 days out. yt-dlp raises YouTube's playability
  reason verbatim (`raise_no_formats(reason)` in `extractor/youtube/_video.py`): `ExtractorError:
  [youtube] h097ly4MFVg: Premieres in 102 days`. Nothing in `_swallowed_error_to_raise` knew it,
  so every attempt (direct, IPv6, proxy) became `no_output`: back on the 24h ladder, feeding the
  breaker, spending proxy rungs. The markers are `premieres in`, `premiere will begin` and `this
  live event will begin`, checked after the dead-proxy check like the age-gate and
  unavailable-video ones.
- **Terminal even when it airs soon.** The owner asked for "not found" treatment, not a wait until
  the release date: a premiere can be months out and YouTube's reason is the same whatever the
  horizon. "Premiere will begin shortly" is terminal too; "retry now" brings any of them back once
  the video has aired. The reason stays in the attempt history ("Not released yet on YouTube: …").

### v54.2 best-quality gotchas (learned checking whether "320k" downloads were really 320k)

- **There is no 320k source.** Without Premium, YouTube and YouTube Music serve Opus 251 (~130–160k
  VBR, 48 kHz) and AAC 140 (~130k, 44.1 kHz) at most. spotdl downloads that, then runs ffmpeg at the
  configured `--bitrate` (`spotdl/download/downloader.py` ~741–772, `utils/ffmpeg.py` ~297), so
  `mp3`/`320k` made every file ~2.5× the size, added a lossy generation, and told Plex a false
  bitrate. Production: 2,303 files, 24.7 GB.
- **"best" means no re-encode, and that's only possible for opus and m4a.** spotdl's own `disable`
  moves an `.m4a` source into place as is and remuxes an Opus `.webm` with `-c:a copy` (only when no
  `ffmpeg_args` are set). Verified bit-exact: the app's `.opus` and a raw `yt-dlp -f 251` download of
  the same video have the same audio-packet MD5 (`ffmpeg -i X -map 0:a -c copy -f md5 -`). mp3 is
  always a re-encode, so its "best" is spotdl's `auto` (the source's `abr`, else 128k). The UI says
  which (`services/output_options.py`, the settings Quality select).
- **The source itself had regressed to ~96k, and nothing errored.** From late September, v31.1's
  forced `android,web,mweb` clients got no audio-only formats at all ("Some … formats have been
  skipped as they are missing a URL. YouTube may have enabled the SABR-only streaming experiment"),
  with or without Deno. `bestaudio/best` then quietly picked **format 18, a 360p video**, whose ~96k
  AAC got re-encoded to "320k". yt-dlp's own `default` set (`tv_samsung, visionos, web` in 2026.10)
  still got 251/140 from the same IP. **How to tell from files:** the sample rate (48 kHz is the
  Opus stream; 44.1 kHz is AAC 140 or format 18) and the spectrum (a 4× `highpass=f=16500` plus
  `volumedetect` read -55 to -91 dB on 92 sampled production files, -91 dB on a format-18 one, and -45 to -59 dB on the new Opus files). Production's
  library was 2,293 of 2,303 at 44.1 kHz. The dev `downloads/` dates show the switch: 48 kHz until
  2026-08-16, 44.1 kHz from 2026-09-28.
- **A bare `yt-dlp` on the host isn't the app's yt-dlp.** The worker images float yt-dlp to latest
  and wire spotdl's Deno (`--js-runtimes deno:/home/spotdl/.config/spotdl/deno` reproduces it). A
  host CLI without a JS runtime hung, and the dev worker's older yt-dlp listed different formats
  than a freshly built slot image. Probe formats inside a current worker container.
- **A stale `DEFAULT_FORMAT`/`DEFAULT_BITRATE` in `.env` isn't a boot error.** They only seed a
  fresh `app_settings` row, so a value the app no longer offers seeds `opus`/`best` instead
  (`services/app_settings.py`), and the migration `a7c4e1b9d2f5` rewrites an existing row on such a
  pair. Production's `.env` still sets both, which is harmless.
- **Known limitation:** opus at "best" when YouTube serves no Opus stream (format 18 only, as under
  the old clients) is a libopus re-encode with no bitrate given. The attempt doesn't record which
  source format was used (a `tasks/download.py` change, left out of this patch).

### v55 engine-races gotchas (learned closing the download engine's races, E2–E12)

- **The ownership token.** `download_track` reads, on entry, the state it found (`pending` from
  expand_job, `queued` from beat, `downloading` on a crash redelivery) and the track's newest
  `attempt_number`. It owns the track while both still hold: a cancel changes the state, and
  beat's reclaim always records a row. The `downloading` write is `UPDATE … WHERE state =
  <entry state> AND NOT EXISTS (a newer row)`; the pacing check, the hold and the dedup
  resolution check the same under the row lock. The plan's literal `state = 'queued'` would never
  have matched a new job's first message (`pending`), so the guard is "the entry state", which is
  `queued` for every beat dispatch. Only `download_track`'s own holds collapse into an existing
  row, and worker-dl runs one invocation at a time, so a collapse can't hide a reclaim. One gap
  is left, harmless: when the claim `UPDATE` waits on the row lock, Postgres re-checks the
  row's own columns against the new version but runs the `NOT EXISTS` subquery on the
  statement's original snapshot, so a reclaim *and* its re-dispatch both committing during that
  wait read as still owned. The invocation then downloads, and beat's message later finds the
  track `completed` or `waiting` and does nothing. The gate writes (`_lock_if_still_owned`) lock
  first and read the rows afterwards, so they have no such gap.
- **E3, the recorded choice: the late outcome supersedes.** The reclaim keeps writing a counted
  `failed` row (`attempts.RECLAIM_PREFIX`): when the invocation really died, that row is the only
  record of its network attempt. A still-running invocation's outcome rewrites that row in place
  (`record_attempt(supersede_reclaim_after=…)`) and moves the counters by the difference. The
  reclaim's reset and its rows now commit in one transaction: v35 committed the reset first,
  which let an outcome land in between, find no row, and count twice. The reclaim's `UPDATE`
  already takes every row lock the loop needs, so no new lock-order cycle (no new deadlock), but
  those locks are now held across the whole loop: a cancel or an outcome for a reclaimed track
  waits until the reclaim commits (milliseconds per track).
- **Reproducing a reclaim of a live download needs a long one.** A 23-minute track (Echoes)
  downloaded in 21 s on dev, finishing before any 30 s beat tick saw it stale. A 63-minute one
  (Sleep, *Dopesmoker*, `1K6A3m061BEzVMZwBy4cjy`) with `STALE_TRACK_AFTER_SECONDS=5` was
  reclaimed mid-download, re-dispatched, reclaimed again as `queued`, and completed: one
  `completed` row (the superseded reclaim row), one `held` row, `attempts_made=1,
  failure_count=0`. Beat's `waiting` events still go out during the download (counters 1/1);
  the completion's event corrects them.
- **E7: `now()` is the transaction's start.** The completed row's `updated_at` (an `onupdate`
  of `func.now()`) recorded the download's *start*, because the post-commit `track.song_json`
  read opened the transaction the completion later committed. Everything the download needs is
  now read before the `downloading` commit (the output-settings row too: an expired ORM row is
  the same trap), and the completion sets `updated_at = finished_at` explicitly, after
  `record_attempt` (its counter `UPDATE` with `synchronize_session="fetch"` expires the
  attribute, dropping a value set before it). On dev, `pg_stat_activity` showed worker-dl's
  sessions only ever `idle` during a real download.
- **E8: spotdl's skip signal.** `search_and_download` with `overwrite="skip"` (its default)
  returns the existing file's path exactly as a download does, after only a Spotify reinit.
  `tracker.notify_download_skip()` is called on that path alone (spotdl 4.5.2,
  `download/downloader.py`), so `download_one` captures it into `DownloadResult.skipped_existing`.
  It's recorded like a dedup hit (`skipped_duplicate`, no path, no counter, no breaker or proxy
  verdict), the ledger gets its row back, and the file is still tag-verified. Reproduced on dev by
  deleting a downloaded track's ledger row and submitting it again. spotdl's `respect_skip_file`
  branch (off by default) returns without the signal.
- **E10, the recorded choice: null `scheduled_at` on the verdict.** "Never touch scheduled_at"
  meant "never schedule a terminal track"; clearing a leftover keeps that, where teaching every
  reader to ignore it would leave the API reporting a retry time. Migration `d9b3e5f7a1c2`
  clears existing ones (a data rewrite of that one column on terminal rows, under the deploy's
  pg_backup). Reproduced with a real "retry now" (which sets `scheduled_at`) followed by the
  age-gate verdict.
- **E11's premise.** While the breaker is tripped, beat dispatches nothing and `_hold` parks a
  track until the trip ends, so one trip holds each already-queued message once: production's
  ~460 rows were most likely ~460 tracks. The collapse (consecutive identical holds of one track,
  `hold_count`) shrinks repeated trips (and pause/resume cycles: beat dispatches nothing while
  paused either) and the unmounted-root hold (every 15 min).
  The attempts API returns `hold_count`; the timeline still renders a collapsed row as one
  `held` (no "×N") until the frontend reads it, which the owner scheduled for v62 (ledger F11,
  2026-10-27).
- **E12: where IPv6 is routable.** The dev override and `docker-compose.prod.yml` both give the
  default network IPv6 (`enable_ipv6`, a ULA subnet), so the probe answers True there and the
  rung is used as before. The skip applies to a network without IPv6 (or a container with it
  disabled: a compose `sysctls: net.ipv6.conf.all.disable_ipv6: 1` overlay on worker-dl, under the
  realdl lock, reproduces it). Observed on dev with `socket.socket.connect` patched in an
  in-process `download_track` run (`docker compose exec -w /app -e PYTHONPATH=/app worker-dl
  python …`: from another directory Python imports the image's site-packages `app`, not the
  bind mount, and `app.tasks.celery_app` must be imported before `app.tasks.download`): with
  IPv6 disabled, the probe's UDP connect was the only `AF_INET6` socket and every TCP connect
  was `AF_INET`; on the slot's network every TCP connect was `AF_INET6`, and that attempt then
  timed out reaching `music.youtube.com` over IPv6 (`no_output`): this dev host's IPv6 egress
  from the Docker ULA network is unreliable, and a route isn't a working path. The skipped rung's row records the path really used (proxy, or
  forced IPv4 with no proxy up) with a note, not a new `network_path` value. `conftest.py` pins
  the probe to routable so the suite's rungs don't depend on the machine.
- **The cancel endpoints are still unconditional (v56's A1).** With the outcome now written
  under the row lock, a cancel arriving during the post-download window waits for the outcome's
  commit and then overwrites `completed` with `cancelled`, until v56 makes cancel re-check the
  state. The live UI then disagrees with the DB until a reload: the API's late `cancelled`
  event reaches a row already `completed`, which the store doesn't move to another state.
  *(2026-10-27, v56: fixed. Both cancels are conditional `UPDATE … WHERE state IN (…)` now; a
  track that completed first is left alone and the cancel answers 409.)*
- **graphify's HTML view stops at 5000 nodes.** This slice took the graph past it, and
  `graphify update .` deletes the tracked `graph.html` instead of updating it. Run it as
  `GRAPHIFY_VIZ_NODE_LIMIT=10000 graphify update .`.

### v56 api-gaps gotchas (learned closing A1–A8 and E1)

- **Loaded rows written back lose races; a conditional UPDATE doesn't.** `cancel_job` used to
  load the cancellable tracks, set `state = cancelled` on the objects and commit. A track whose
  completion committed in between was overwritten to `cancelled`, and the finished job relabelled
  (A1). The ORM flush is an `UPDATE … WHERE id = …`; it waits for the row lock and then writes
  regardless. `UPDATE tracks SET state = 'cancelled' WHERE job_id = … AND state IN (…)` waits for
  the same lock, but Postgres re-evaluates the `WHERE` on the newly committed row (READ COMMITTED),
  so the completed track is skipped and the cancel answers 409. The race test makes the
  completion hold the row lock uncommitted (as `record_attempt`'s UPDATE does) and fails on the
  old code. `DELETE /api/tracks/{id}` got the same shape.
- **The outbox marker, and why a lease.** Tracks are created `pending` with `scheduled_at` set
  (a microsecond apart, so beat keeps album order); beat's dispatch query takes `pending` as well
  as `waiting`, still only where `scheduled_at <= now`. `expand_job` claims its tracks by moving
  the marker `DISPATCH_LEASE` (10 min) ahead in one committed UPDATE, sends, then clears the sent
  ones' marker. A broker error puts the unsent ones' marker back to now (beat's next tick);
  anything worse (a killed worker, the DB gone too) lets the lease run out. Clearing the marker
  *before* sending would have stranded tracks on a crash between the claim and the sends.
  Verified on the slot stack with the broker refusing send #4: before v56, 12 of 15 tracks had
  no message and no marker; after, every track had exactly one message within one beat tick, with
  a mocked refusal and with Redis really stopped.
- **`docker pause` doesn't make a broker fail.** A paused container's socket still accepts the
  connection and the writes (the kernel buffers them), so a publish "succeeds" and is delivered
  on unpause. `docker stop` gives a real refusal (`Error -2 connecting to redis:6379`). The
  slot's Redis is `appendonly`, so the messages sent before the stop survive the restart.
- **A one-off script in a container imports the image's code.** `docker exec … python
  /tmp/script.py` puts `/tmp` first on `sys.path`, and `app` resolves to the installed copy in
  site-packages, built at `up`, not the worktree mounted at `/app/app`. The first E1 run silently
  ran the pre-v56 `expand.py` (which happened to make a good "before"). Pass `-e PYTHONPATH=/app`.
- **`download_track.delay` is shared.** `expand.py` and `beat.py` import the same task object, so
  monkeypatching `beat.download_track.delay` replaces expand's too. One stub that records who sent
  each track (`_Broker` in `test_expand_task.py`) keeps the two apart.
- **`timedelta(days=10**9)` raises `OverflowError`** (and anything past about 739,000 days
  overflows `now - delta`). `retention_days` had no upper bound, so one such value stopped the
  hourly archive sweep for every user after it (A5). 1–36500 now, else 422. A production row
  stored before v56 with a larger value would still break the sweep: check with
  `SELECT count(*) FROM user_settings WHERE retention_days > 36500 OR retention_days < 1`.
  *(2026-10-26, v56 round 3, owner's decision: the v56 migration clamps such rows, above 36500 to
  36500 and below 1 to NULL; proven on the slot DB, where a 10**9 row made the sweep raise.)*
- **The attempt's proxy label is captured, not joined.** v35 joined `proxies.url` at read time,
  so deleting a proxy would have erased "which proxy" (and the FK made deleting a used one a 500).
  `record_attempt` stores the redacted label; the migration backfills existing rows with a frozen
  copy of `proxies.redact()`'s rule. `attempts.py` can't call `proxies.redact()` itself: alerts.py
  imports attempts.py and must not import spotdl, which `proxies` (and `serializers`) do.
- **Breaker time comes from the server now (A7).** `/api/worker/status` answers `breaker_active`
  and `breaker_remaining_seconds`; `api.ts` adds `breaker_clears_at` (arrival time plus the
  remaining seconds, on the browser's clock). `breaker_tripped_until` stays the trip's identity
  (the release flow compares it for equality), never a clock reading. With the browser 2h ahead,
  main's pill showed "worker ready" during a real hold; now it counts down the server's time.
  `TrackRow`'s next-try countdown and the dashboard's own hold line still compare
  `breaker_tripped_until` with `Date.now()` (outside v56's scope, in its PR's "Found, not fixed").
  *(2026-10-26, v56 round 3, owner's decision: fixed in v56 too. The status also answers
  `server_time`; `api.serverToLocal()` places a track's `scheduled_at` on the browser's clock. A proxy's
  `cooldown_until` (`/settings`' countdown, `/stats`) still meets the browser's clock as is.)*
- **Retry-now is once per ladder step for a non-admin (A8).** `tracks.retry_now_step` holds the
  `attempt_count` at which it was used; equal means used. The check runs under the track's row
  lock (two presses at once: one 200, one 429). The 429's `retry_after` is the later of the
  track's slot and the breaker's clear, 0 when it's due anyway. `lookup_failed` retries and an
  admin's are unrestricted.
- **A `failed` job's cancel is a dismiss.** The first cut of A1 answered 409 for every job not
  `expanding`/`active`/`waiting`, `failed` included. But `IncomingJobs.svelte` dismisses a failed
  row (and finishes "try again") with `DELETE /api/jobs/{id}`, and specs 01/05 dismiss one: the
  row could never be cleared. Caught by review and by the e2e run; the owner kept `failed`
  cancellable (master plan Amendments).
- **SET NULL opens a new window: a proxy deleted mid-download.** The FK used to block that delete
  (a 500); now it succeeds, and the attempt row written when the download returns named a proxy
  that no longer exists, a ForeignKeyViolation that rolled back the whole commit, a completed
  download's ledger row with it. `record_attempt` now records no proxy when the row is gone
  (reproduced on two real connections, the worker session holding the expired proxy).
  *(2026-10-26, v56 round 3: `record_attempt` and `proxies.record_proxy_result` now read the
  proxy locked, so a delete landing while the attempt's transaction is open waits for its
  commit; only a delete committed before the read still leaves the row unlabelled. 2026-10-27:
  that lock is `FOR NO KEY UPDATE`, not the `FOR KEY SHARE` first written here; see the entry
  on `with_for_update(key_share=True)` below.)*
- **Bulk UPDATEs of the same rows need one lock order.** `cancel_job`'s `UPDATE … WHERE job_id`
  and expand_job's claim `UPDATE … WHERE id IN (…)` can lock one job's tracks in different
  orders. Both take the job's row lock first now (cancel_job always did), so they serialize.
- **A partial index only serves a query whose predicate implies it.** `ix_tracks_scheduled_at_waiting`
  (`WHERE state = 'waiting'`) can't serve `state IN ('waiting', 'pending')`; the planner fell back
  to a scan. `ix_tracks_scheduled_at_due` covers both states (`EXPLAIN` shows it used).
- **A clear that matches the lease alone.** A track worker-dl settles before expand_job clears its
  marker isn't `pending` any more; matching on `pending` too left a completed track with a future
  `scheduled_at`. Clearing matches the lease value only, which nothing else ever writes.
- **The outbox's per-track CASE has a size ceiling.** `_due_case` binds two parameters per track and
  the `IN` list one more, so one marker UPDATE carries about 3N binds (Postgres caps a statement at
  65,535): past about 21,800 pending tracks in one job, the redelivery path's UPDATE fails and
  those tracks stay unmarked. The largest real jobs are about a thousand tracks (a discography),
  so it's accepted; chunk the UPDATE if jobs ever get that big. The success path is safe
  regardless: `_mark_due` marks each track on its own ORM row before the claim.
- **A used proxy's delete waits for its download (owner's decision).** ON DELETE SET NULL made a
  used proxy deletable, and every review round then found another millisecond window where the
  delete met a download through that proxy (an FK violation, a StaleDataError, a lock-order
  deadlock with v55's track locking). Locks alone kept chasing corners, so the delete no longer
  races the download at all. `DELETE /api/proxies/{id}` deletes an idle proxy at once (204). One in
  use (`proxy_in_use`: a track `downloading` through it, or picked in the last 60s, which covers
  pick → the `downloading` commit) gets `delete_requested_at` instead (202, `deleting: true`).
  `pick_proxy` skips it, and after a candidate's probe locks only that one `FOR UPDATE SKIP
  LOCKED` (a delete deciding meanwhile holds the row, so the pick passes over it; no lock is held
  across the probes). `used_proxy_id` names the current attempt's proxy only (a direct attempt
  clears it), or `proxy_in_use` would see a direct download as going through the old proxy. A
  track cancelled mid-download within the stale-track window also counts as using its proxy: a
  cancel lets the download run to its end, and the delete must wait for it too. `finalize_proxy_deletions` (beat, every
  30s) deletes it once idle, and `/settings` shows it as "deleting" until then. On the slot it was
  gone 17s after its download ended.
- **Rebased onto v55: the proxy before the track, in every outcome path.** v55 locks the track's
  row in `download_track`'s success and failure paths (and in `record_attempt`) before anything
  reads the proxy. A proxy delete locks the proxy and then (ON DELETE SET NULL) the track, so
  those paths now take the proxy's lock first (`proxies.lock_for_outcome`); a statement-order test
  pins it. v55's supersede rewrite of a reclaim row stores the proxy label too, as a new row does.
- **`with_for_update(key_share=True)` is `FOR NO KEY UPDATE` in SQLAlchemy;** `FOR KEY SHARE`
  needs `read=True` as well. v56's proxy reads had the former while its comments said the latter.
  It's kept, now named (`attempts.PROXY_OUTCOME_LOCK`): it still makes a delete wait, and the
  outcome's transaction then updates the same proxy row (`record_proxy_result`), which needs it
  anyway: one lock up front rather than a `KEY SHARE` upgraded halfway through. Check the
  rendered SQL, never the flag name.
- **A reclaimed download is still a proxy's user.** v55's stale reclaim moves a live
  `downloading` track to `waiting` and lets the download finish and rewrite the reclaim's row.
  `proxy_in_use` counted only `downloading` (and recently cancelled) tracks, so a proxy behind a
  download beat had reclaimed could be deleted under it. It now also counts a track whose reclaim
  row is unrewritten and recent (`attempts.reclaim_unreported`). Every hold is bounded, so a
  delete is never stuck: a reclaimed download holds its proxy for one stale-track window after
  the reclaim (about twice the window after it started), a cancelled one for one window after the
  cancel; a download outliving that loses only its attempt's label, never its commit. And a cancel clears
  `used_proxy_id` unless the track's download may still run (`downloading`, or reclaimed and
  unreported): an ended attempt's proxy on a cancelled `waiting` track held its delete for the
  whole stale-track window, while clearing it on a reclaimed one let the delete through. One gap
  is left, the v55 claim's kind: a cancel that waits on beat's uncommitted reclaim re-checks the
  row's own columns afterwards but runs the `track_attempts` subquery on its original snapshot,
  so it misses the reclaim row and drops `used_proxy_id`; that download's proxy is then
  unprotected (the outcome still commits, unlabelled). Accepted: it needs a cancel within
  milliseconds of a 30-minute reclaim, and closing it would mean a proxy lock in beat's reclaim,
  against the delete's lock order.
- **A re-parented migration on a database that already ran it.** After the rebase put v55's
  `d9b3e5f7a1c2` under v56's `a9d3c5e7f1b2`, the slot's database still read `a9d3c5e7f1b2`, the
  head, so `alembic upgrade head` did nothing and `hold_count` was never added. Repair: `alembic
  downgrade d9b3e5f7a1c2` (runs only v56's downgrade), `alembic stamp a7c4e1b9d2f5`, `alembic
  upgrade head`. Production never sees this: it only ever runs the merged chain.

### v57 library-hardening gotchas (learned closing the sweep and dedup edge cases)

- **"Mounted" is a sentinel file now, never "non-empty".** Every managed root (the downloads dir
  and every known library root) carries `.spotdl-volume`. `reconcile_disk()` creates it where
  that's safe to decide: the root exists and either no ledger row points into it, or at least
  one of those files is really there. A root whose every ledger file is missing looks exactly
  like an unattached mountpoint, so it gets none, its rows are skipped, and the log says to
  create the file by hand once the mount is checked. Proven on slot 3: first boot logged
  "sentinel created" for `/downloads` and `/mnt/raid1/media/music`, later boots "sentinel
  present"; `/downloads` emptied (only the sentinel left) pruned a stale row; an empty
  mountpoint and a missing root were each skipped with a line. A sweep never touches the
  sentinel (it walks ledger rows, not the tree), so `/downloads` stays "mounted" after a sweep
  empties it, which is what keeps the v48 47-row accident from recurring. The sweep also creates
  its own target's sentinel under the same rule, so a newly switched library root counts as
  mounted before worker-meta's next boot.
- **A sweep refuses a target it can't confirm is mounted (review round 2).** If the sweep's
  `ensure_sentinel` can't establish the target's sentinel (the folder is missing, or ledger rows
  point into it and none of their files is there: an unattached RAID), it records "refused to
  start" and moves nothing. Filing into an unattached mountpoint would have put the new files on
  the wrong filesystem, and the next reconcile would have read them as proof the volume is there,
  created the sentinel, and pruned every real library row. A new library folder has to exist
  before its first sweep.
- **The sentinel rule's one gap, accepted:** a root with *no* ledger rows gets its sentinel even
  if it's an unattached mountpoint (an empty fresh volume looks the same). If the real volume
  later mounts over it and a later mount fails again, the hidden sentinel shows through. Needs
  two mount failures on a root the ledger didn't use at the first; requiring content instead
  would leave every fresh root without one.
- **`copy_verify` stages its copy (review round 2).** It copies to `.spotdl-copying-<hex>` (round 4: a
  fixed short name; `<name>.copying-<hex>` could pass the 255-byte limit on a long filename), verifies,
  then places it at the destination with a hard link (round 3), never over an existing file: a worker killed mid-copy
  leaves only the staging name, which no "already exists" check reads.
- **The library dir must be `/mnt/raid1/media/music` or a folder inside it (owner decision,
  2026-10-26).** That's where every compose file mounts the library and the only directory nginx
  serves; anywhere else is the saving container's own writable layer. A 422 on save
  (`library_dir_outside_mount`), and a "refused to start" from the sweep for a value saved before.
  The overlap checks run first, so each of L2's cases keeps its own message.
- **The quarantine dir must be a folder inside the downloads dir (owner decision, 2026-10-27).**
  It may not overlap the library, so the downloads volume is the only mount it can use; anywhere
  else (`/srv` was accepted before) is the sweeping container's own writable layer, and a
  recreate discards everything quarantined there. A 422 on save
  (`library_quarantine_outside_mount`, checked with quarantine off too) and a "refused to start"
  from the sweep for a value saved before, after the overlap and library-mount checks.
- **Interrupted copies leave hidden files on the library, by design (owner-accepted
  2026-10-27).** A killed worker, a full disk or a failed verification leaves its copy at a
  hidden `.spotdl-copying-*` / `.spotdl-copy-failed-*` / `.spotdl-verify-failed-*` name; nothing
  deletes it (the never-delete invariant). At most one track's bytes each, never read by dedup,
  reconcile or the sweep. To reclaim space, delete them by hand while no sweep is running.
- **An enclosing mounted root covers a folder root inside it (review round 4).** Under the mount
  rule every library root but the mount point is a folder inside it, so `dedup.covered()` takes
  any enclosing root's sentinel: a folder root removed by hand is "gone from a mounted volume"
  (dropped, pruned), not held forever, and the sweep creates a new target folder itself when an
  enclosing known root has its sentinel. The sentinel rule counts every ledger file under a root,
  nested roots' included (round 5): judged only on the rows whose most specific root it is, an
  unattached mount point looked empty, got a sentinel, and vouched for every folder inside it.
- **worker-dl's ledger upsert creates the downloads root's sentinel when it's missing (review
  round 4):** a file it just wrote proves the mount. Without it, a `/downloads` whose rows were all
  stale at 5.57.0's first boot would have stayed unconfirmed (and its stale tracks held) until
  someone created the file by hand; before v57 production's `quarantine/` folder kept `/downloads`
  "non-empty", so this would have been a regression. It proves the directory is writable, not
  that it's the right disk: if `DOWNLOADS_DIR` were a separately mounted disk that failed to
  attach, the first download into the bare directory would create the sentinel there (round 6;
  the old "non-empty" guard failed the same way after one download).
- **The quarantine dir is checked on every save and every sweep start, on or off** (L2 as
  written; a review round briefly relaxed it, round 5 put it back).
- **`copy_verify` places its copy with a hard link**, which fails on an existing name where a
  rename would silently replace a library file; the staging name is dropped only after the link
  (a filesystem without hard links falls back to a check and a rename).
- **Library and quarantine dirs must be absolute** (422 `library_path_not_absolute`): a relative
  path resolves against each container's own working directory, so the overlap check can't
  judge it.
- **A not-yet-filed row already inside the library is filed where it is.** At its own computed
  destination, or anywhere in a known library root: the sweep reports it once and sets
  `in_library`, with nothing on disk touched. Skipping without marking re-reported it (and sent a
  "finished with errors" alert) on every later sweep.
- **A known root around the downloads dir is ignored.** `known_library_roots()` leaves out any root
  equal to, inside or around `download_output_dir`: a value saved before L2's check stays in the
  list (nothing removes entries), and as a library root it would make every download read as
  "already in the library".
- **Cancel can't unwedge a run.** It only sets the flag the sweep reads between files; a run left
  `running` by a worker-expand that died mid-sweep still needs the row reset by hand (live review:
  a `docker compose kill worker-expand` 0.8 s into a sweep). Its message stays unacked and comes
  back after the 6 h visibility timeout: the task now drops a delivery that finds the row idle
  (the hand reset), and one that finds it still `running` with the cancel flag set stops before
  its first file. A killed copy leaves a hidden `.spotdl-copying-<hex>` in the library, never
  cleaned up (nothing there is deleted).
- **One sweep at a time, whatever the deliveries (review round 7, reproduced live).** A sweep
  message redelivered after its worker died, or after the 6 h visibility timeout, found the row
  `running` (a new start had set it) and swept beside the new one: 87 "appeared during the copy"
  errors and 87 orphaned `.spotdl-copying-*` copies (4.6 GB) in the test library. The 409 gate
  only guards the row, not the queue. `sort_library` now takes a session-level advisory lock on a
  connection of its own (autocommit, so never idle in a transaction) for the whole run; a
  delivery that can't take it is dropped. Real re-run: one delivery swept 30/30, the other logged
  "another sweep holds the lock", no new staging file. Round 8: a loser polls for the lock for 30 s
  before dropping, then re-checks the row; dropped at once, a start landing in the milliseconds
  between the previous sweep's idle commit and its unlock wedged its own row `running` (live: a
  start with the lock held 8 s from psql now waits and sweeps). A resumed sweep restarts its
  counts, so its "N of M" never reads past 100%. File serving covers the whole mount, as dedup
  and the sweep do.
- **The library mount is a managed root too (round 7)**, known root or not: dedup and reconcile
  guard a row anywhere in it. `test_dedup.py`'s fixture points `library_mount` at `tmp_path` as
  well, for the same CI-host reason as the other roots.
- **A sweep never moves anything inside the library mount**, known root or not (round 6): with
  the library dir a folder inside the mount, a not-yet-filed row elsewhere in the mount is marked
  filed, not moved (a move deletes its source). The sweep's target check also counts the mount's
  rows and accepts the mount point's sentinel.
- **A NUL in a library or quarantine path is a 422 `library_path_invalid`**, not the 500 every
  filesystem call on it raised (live review).
- **A file missing under a mounted root drops its row before the download (L5).**
  `is_already_downloaded` deletes the row (only while it still points at the missing path) and
  returns a miss, instead of holding the track on every rung. A missing file under a root
  without a sentinel still holds (v38).
- **The sweep vs worker-dl race needed a lock that outlives a commit (L3).** The sweep commits
  its repoint and only then deletes the source (v28's crash-safety order), so a transaction-level
  lock in the sweep's own session would end at that commit. `dedup.file_lock` holds
  `pg_advisory_xact_lock` on a connection of its own for repoint, commit and delete; worker-dl's
  `record_download` takes the same key in its own transaction and re-checks that the file still
  exists. If the sweep won, the attempt fails as an ordinary error (`LedgerFileMoved`: the ladder
  retries it, the breaker isn't fed) rather than recording a row on a dead path. The cost, accepted:
  the audio is in the library by then but this Spotify id has no ledger row, so its next attempt
  is a real download (worker-dl can't tell where the sweep put the file without the basename
  relinking v48 rejected). It needs spotdl's skip-existing to hand back exactly the file being
  swept, inside the sweep's lock window; before v57 the same race stranded the row instead.
  `tests/test_library_race.py` fails without the lock (a strict xfail) and passes with it. A
  `db_session` test can't open that second connection (conftest flags it), so the sweep's unit
  tests stub `file_lock`.
- **v31's `copy_verify` fix missed the disk-full case (L7).** On a 2 MiB tmpfs, `shutil.copy2`
  raised ENOSPC with 2 MiB of an 8.6 MB file already at the destination's exact name; the
  checksum rename never ran, and the next sweep would have read the partial file as "already
  exists" and quarantined (or deleted) the good source. A failed copy is now renamed off to
  `.spotdl-copy-failed-<hex>` (a rename needs no free space) and the error re-raised.
- **Known library roots only grow (L6).** Changing `library_target_dir` keeps the old value in
  `app_settings.library_known_roots`; dedup, reconcile, the sweep's "never move a library file"
  check and file serving all cover every known root. File serving still goes through nginx's
  single `/internal-library/` alias (`/mnt/raid1/media/music`), so the backend now computes the
  path relative to that alias: a root elsewhere answers 404, not a different file at the same
  relative path.
- **Quarantine inside `/downloads` stays valid (owner decision, 2026-10-26).** See the master
  plan's Amendments: L2's literal "not inside the downloads dir" would have refused every
  production sweep.
- **L8: the six dev "duplicates" are orphans of a filename change, not a second download.** The
  `./downloads` copies (Mr. Brightside, Africa, Take on Me, Hotel California, two Bohemian
  Rhapsodys, Shape of You) are named `Artist - Title.mp3`, dated 2026-08-01 to 08-15: spotdl's
  default template before v28. Their library copies are `NN - Artist - Title.mp3` (v28's
  template), dated 2026-10-01/02, and the ledger points at those. The August files belonged to
  the shared dev/prod database's ledger; v32 (2026-10-01) gave dev its own empty
  `spotdlwebtest`, so the tracks downloaded again under the new name and were swept, and the old
  files were left with no row (read-only check of `spotdlwebtest`: no row names an August file,
  and its oldest ledger row is 2026-10-01 10:43, the day v32 created it). Benign: nothing points at them, and deleting them is the owner's
  call. Reproduced on a fresh slot database to rule out a live cause: a 2-track album downloaded
  for real by one user (2 files), the same album by a second user (2 `skipped_duplicate`, still
  2 files), then one file deleted by hand and the track resubmitted (L5's case, one `completed
  direct-ipv4` attempt): still 2 files, one per track.
- **The L5 run, real:** `/downloads` holding only its sentinel, the ledger row on a hand-deleted
  file, and the resubmitted track recorded one attempt, `completed direct-ipv4`, no `held`.
- **CI's pytest runs on the production host.** `/mnt/raid1/media/music` there is the real library,
  and `reconcile_disk` writes sentinels: `test_dedup.py` keeps every managed root under `tmp_path`
  (an autouse fixture asserts it). `update_library_settings` keeps the old root as a known one, so
  a test that moves the library sets the row directly.

### v58 firefox-extension gotchas (learned building the extension and running it on real open.spotify.com)

- **The selectors that held (Firefox 158, Spotify signed out, 2026-10-26), all in
  `extension/content/selectors.js`:**
  - tracklist rows: `[data-testid="tracklist-row"]`. The track is the row's
    `a[data-testid="internal-track-link"]` on album/playlist/artist pages; search's song rows have
    a plain `a[href^="/track/"]` instead. The icon goes before the row's own
    `[data-testid="more-button"]`;
  - page headers: `[data-testid="action-bar-row"]`, its item the page's own address, and only when
    the bar sits inside that type's `[data-testid="album-page"|"artist-page"|"playlist-page"]` (on a
    navigation, the address changes before the old view goes, and a header icon would briefly name
    the new page over the old one). The title is `[data-testid="entityTitle"]`;
  - cards: `[data-encore-id="card"]`, identified **only** by the link around its
    `[data-encore-id="cardTitle"]`. The first real run caught a music video card (artist page,
    "Music videos") queuing *The Favors*, a whole artist: its title isn't a link, so "the first item
    link in the card" was the subtitle's artist link. Show, episode, profile and genre cards carry
    no item link of the four types and get no icon. Search's `[data-testid="top-result-card"]` has
    no marked title: there its first link is its own.
  - Class names are hashed (`e-101040-…`) and change; nothing reads them.
- **Rows are virtualized and recycled.** A 50-track playlist renders about 47 rows (`aria-rowindex`
  5–51 after a scroll), and React reuses row elements for other tracks. `scan()` retargets an icon
  whose row now shows another track rather than adding one. A real scroll pass checked every row:
  one icon each, naming that row's own track.
- **The cookie path, re-checked in v58's real run:** the background's `fetch(…, {credentials:
  'include'})` to `http://127.0.0.1:5177` carried the slot's session (fresh `web-ext` profile,
  default Total Cookie Protection), as v53's spike found. The key retry sends `credentials:
  'omit'`, so a stale cookie never decides the answer. `last_used_at` moved on the key's `me` and
  again on a click 65 s later (it updates at most once a minute).
- **Every create counts against the rate limit, an `already_queued` answer too** (v53's limiter
  runs before the duplicate check). With `JOB_CREATE_RATE_LIMIT=6`, the sixth click of a minute
  was the last one through, whatever the earlier five answered.
- **Spotify's OneTrust cookie banner covered the cascade menu.** Its bottom entry ("Whole
  artist") took the banner's click instead. The menu and toast now use `z-index: 2147483647`, and
  the menu follows its icon on scroll (Spotify scrolls its own views mid-render) instead of
  closing, closing only when the icon leaves the viewport.
- **`permissions.request` must run inside the click handler, before any `await`,** or Firefox
  refuses it as not user-initiated. The options page computes the origin pattern synchronously
  first. A pattern has no port (v53), so `http://127.0.0.1:5177` asks for `http://127.0.0.1/*`.
- **The now-playing bar shows a track only when logged in to Spotify.** Signed out, it's a "Sign
  up" banner. The owner uses Spotify logged out (in LibreWolf, which blocks DRM, so Spotify blocks
  playback after login), so v58 doesn't target it (owner's decision, 2026-10-26; master-plan
  Amendment).
- **Spotify's tracklist is a keyboard grid that includes the icon.** Once the grid has been
  used with the keyboard, Spotify gives row buttons a roving `tabindex=-1`, and the arrows are
  the only way to reach a row's icon. The icon's keydown first stopped every key, so
  ArrowLeft/Right/Up/Down and Home died on it (live review). It now stops only the keys it acts
  on: Enter, Space, the menu keys, and Esc while its menu is open. Arrows and Tab still go to
  Spotify.
- **`event.isTrusted` isn't enough against the host page.** A page script's synthetic
  `.click()`/`dispatchEvent` is untrusted and ignored. But an invisible full-page
  `<label for="<icon id>">` turned the user's real click anywhere into a *trusted* click on the
  icon (live review: it queued a job). A click now counts only when the page's last trusted
  press (`pointerdown`, or `mousedown`: a screen reader's "press" sends mouse events with no
  pointer event) landed inside that same icon or menu entry, or from the keyboard (`detail` 0
  on the focused button). Every real click starts with its own press, so nothing goes stale
  and a slow press-and-hold still counts. Two earlier versions failed review: a 1.5 s
  press-to-click window dropped slow presses, and a per-button "dismissing" flag outlived a
  press dragged off the icon. The same press also records which menu was open as it began, so
  a click on an open menu's opener dismisses it, even after the press's focus move. The menu's
  keyboard path calls a chooser kept in a `WeakMap`, never `.click()`.
- **A 401 proves a spotdl app only when it's the app's own** (JSON with `code`
  `not_authenticated` or `api_key_invalid`). An intranet's HTML basic-auth 401 was saved as the
  app address. An HTML 5xx (nginx's 502 with `api` down, Cloudflare's 530) reads as
  "unreachable", not "not a spotdl app".
- **A page can move focus too.** The final live review had a page script `focus()` an icon
  from its own field's Enter keydown. Firefox then sent the user's Enter activation to the
  icon: a trusted click, `detail` 0, on the focused button, and it queued. A keyboard click now
  also needs the trusted Enter/Space keydown to have landed on that same icon. The candidate
  menu never takes focus unless focus is still on its icon (not even from `<body>`). A request
  in flight belongs to the item, not the button, so a re-rendered row neither sends twice nor
  loses the answer.
- **What the page can read.** The toast and the icons' `data-*` live in Spotify's DOM, so
  in-page messages never name the app's address, and menu actions aren't stored on elements.
  Which items got a tick (`data-state`) stays visible to Spotify's scripts. That's inherent to
  showing the tick, and accepted.
- **Automating the extension in real Firefox (scratchpad harness, not committed):**
  - `web-ext run --arg=--marionette --arg=--remote-allow-system-access`, then a small Marionette
    client over TCP (no geckodriver needed).
  - WebDriver BiDi's and Marionette's Navigate both refuse `moz-extension://` URLs ("not allowed
    in this context"). From the chrome context, `gBrowser.selectedBrowser.loadURI(uri,
    {triggeringPrincipal: systemPrincipal})` opens them.
  - `extensions.webextensions.uuids` doesn't pin a temporary add-on's UUID. Read it with
    `WebExtensionPolicy.getByID(id).mozExtensionHostname`.
  - A WebDriver element reference to a node a content script created (the menu items) is stale
    at once. Click by viewport coordinates.
  - `extensions.webextOptionalPermissionPrompts=false` grants `permissions.request` without the
    doorhanger.
  - `browser.i18n` follows Firefox's UI locale, which needs its langpack (`firefox-i18n-hu` on
    Arch): `intl.locale.requested=hu` alone leaves an en-US build in English.
  - LibreWolf's `librewolf.cfg` turns off `devtools.debugger.remote-enabled`, so `web-ext run`
    can't attach to it (ECONNREFUSED on the RDP port).
  - The network capture: an `http-on-modify-request` observer in the chrome context, recording
    each channel's `loadInfo.triggeringPrincipal`. An extension request carries the add-on's
    principal (`addonId`), so the extension's traffic is told apart from the page's.

### v59 alert-delivery gotchas (learned making Matrix alerts durable)

- **O1, every candidate loss path, tried on slot 1 with v36's code** (`origin/main` at `1047f34`,
  Matrix through a local nginx proxy on the slot network, so the homeserver could be passed
  through, black-holed, refused, or answer 503/429, to the v49 scratch room):
  - **`meta` backlog past `expires=300`: reproduced.** worker-meta paused 310 s with one alert
    queued; on unpause Celery logged "Discarding revoked task: app.tasks.alerts.send_alert" and the
    room got nothing. (Beat's own heartbeat also stopped, so the watchdog rightly raised "Beat
    looks dead" after it.)
  - **worker-meta killed: reproduced, both ways.** Four alerts against a black-holed homeserver
    (each send hangs 10 s), then `docker kill -s KILL` 4 s in: the two executing were already
    acked (`acks_late=False`) and vanished; the two prefetched sat in Redis's `unacked` hash, due
    back only after the 6 h visibility timeout, long past their 300 s expiry. None reached the room.
  - **Matrix 503 and 429: reproduced.** "library alert not sent: HTTP 503 …", then nothing; the
    same for 429 (`retry_after_ms` ignored).
  - **The cooldown: reproduced for a repeat, not for a first alert.** A failed first send had
    claimed the Redis key, so the same alert raised again was "suppressed (cooldown)" and the
    room heard neither. A *first* trip alert can't be suppressed: its fingerprint carries its own
    `tripped_until`.
  - **Also tried: Redis down when the alert is raised.** "could not enqueue library alert
    (OperationalError)" after ~10 s, dropped. And with the busybox `nc` "black hole", which
    refused connections: four alerts dropped as ConnectError/RemoteProtocolError.
  - Which of these hit production on 2026-10-18 stays unknowable (the logs went with the 23:18
    deploy). Both the trip and its release were missing, which any failed trip send explains: the
    release was only ever sent for a trip the room heard about.
  - `tests/test_alert_loss_paths.py` covers each reproduced path through `alerts.enqueue` / a
    real trip commit and the `deliver`/`meta_killed`/`redis_down` fixtures only, so the same file
    ran against v36 with a support module that emulates its broker (expiry, early ack, the 6 h
    `unacked` wait, a publish error): 8 of 8 failed there, 8 of 8 pass on v59.
- **The outbox.** `alerts.record(db, …)` inserts the row in the caller's transaction, inside a
  savepoint (an insert error is one warning, never the caller's failure). The breaker trip is
  recorded in the trip's own transaction, so a rolled-back trip leaves no row. The cooldown is
  decided there: an identical `(category, fingerprint)` row still `pending` (any age), or `sent`
  inside the window (measured from `sent_at`: a late delivery starts the window late), makes the
  new one `suppressed`; a switched-off category is `suppressed` too. A spike's "newest seen"
  stamp moves only for an alert that goes out, as v36's moved only on a sent one, or a suppressed
  repeat would cost the reminder after the cooldown (review round 2).
  The reason is a code in `last_error` (`cooldown`, `category_off`), translated by the history
  panel. A lasting condition (beat dead, worker-dl down) is re-raised every watchdog minute, so a
  suppressed repeat is recorded at most once per window; and an alert that waits out a Matrix
  outage reaches the room once, not once per hour of it (review round 1). A transaction-scoped
  advisory lock on the pair makes "first" unique.
- **Delivery.** `deliver_due` claims one row at a time (attempts + 1, `next_attempt_at` a 120 s
  lease ahead) in a short transaction, sends with no transaction open, then records the outcome.
  Only the oldest pending row of each category is eligible, so a release never overtakes a
  backing-off trip. Backoff is 30 s, 2 min, 10 min, then every 20 min (the plan's example ended
  in hourly; every wait stays under Synapse's txn memory, review round 3); a row still unsent
  24 h after it was raised is `failed`. The category toggle is checked again at send time: one
  switched off during an outage isn't sent when the homeserver is back (v36 checked it there). A pass stops at its first failed send, and stops claiming after 20 s.
  Beat runs it every 30 s (`deliver_alerts`, `expires=25`), and **the watchdog runs one after
  every check**: a dead beat must still get its own alert out. Only one pass runs at a time
  (`pg_try_advisory_xact_lock`, held by a session of its own that touches no table, so no migrate
  waits on it): a slow homeserver can't take both of worker-meta's slots from beat's dispatch
  (review round 1). The lease still covers a pass that dies mid-send. A 413, or a 400 with
  Matrix's `M_NOT_JSON`/`M_BAD_JSON`/`M_TOO_LARGE`, is about one message: that row is given up at
  once and the pass goes on (review round 2). A bare 400 isn't: a proxy's or a malformed room
  id's 400 is every row's problem and backs off like a 5xx (review round 3).
- **Two clocks, accepted.** `created_at` (and a new row's first `next_attempt_at`) come from
  Postgres' `clock_timestamp()`; the due, lease and give-up checks use the app's clock. Production
  runs both on one host. Against the LAN dev database a skew of Δ delays a new row's first send by
  Δ, nothing worse (review round 2).
- **The Matrix transaction id is the row id.** Synapse answers a repeated PUT under the same txn
  with the first event's id and posts nothing (verified: a hand re-PUT of a delivered row's id
  returned the same `event_id`, and the room kept one copy). Synapse keeps txn ids for about 30
  min; every backoff wait is shorter, so a retry right after a send whose answer was lost dedupes
  (the live review proved it through a mirroring proxy: the PUT reached Synapse, the client timed
  out, two retries under the same txn, one message). **Accepted limit:** a lost answer followed by
  more than ~30 min of failed retries can still post twice, since nothing can ask Synapse whether
  a txn landed; so can one followed by a 429 whose `retry_after` is over ~30 min (a 429 must be
  honoured, review round 4).
- **Rows are stamped with the database's `clock_timestamp()`**, not the caller's `now`: delivery
  order is `created_at`, and it must follow the order rows were really written. The release is
  recorded under `SELECT … FOR SHARE` on `worker_state`: a trip updates that row (the savepoint's
  flush takes the lock) in the same transaction as its alert row, so either the trip committed
  first (the re-read sees it tripped, no release) or it waits and its row is stamped after.
- **A late delivery says so**: a row sent more than 2 min after it was raised gets "(raised
  YYYY-MM-DD HH:MM UTC, delivered late)", so "paused for 30m" read hours later isn't read as now.
- **The test alert** is recorded too (inserted already claimed, sent at once, then `sent` or
  `failed`; a failed one isn't retried, only a request that died mid-send is finished by a pass
  after the lease), so the history shows it. Its body and id are read before the commit: reading
  an expired row after it opens a transaction that stays idle through the send.
- **O4, worker down: the signal.** The newest worker-written attempt's end (beat's reclaim rows
  excluded: they're recorded on a stuck invocation's behalf; its end, not its `started_at`, since
  v55 merges a track's repeated holds into one row that keeps its first start, and a long
  download that just ended isn't idle time, review round 3 and the live review) or a `downloading`
  track's `updated_at`, against the oldest due track. Idle is measured from the latest of the
  oldest due time, the breaker's release and that last start, so a worker-dl that took a few
  tracks and then died midway through a backlog is caught too (review round 1; the first cut
  only compared the start with the due time). A track in `downloading` younger than
  `STALE_TRACK_AFTER_SECONDS` counts as busy now: a download's progress isn't written to the
  database, so a long one would otherwise read as a dead worker-dl (review round 2). The due time
  alone misleads twice: a track
  due during a trip only became dispatchable at the release, and beat's stale sweep rewrites a
  stuck track's `scheduled_at` to its own tick every `STALE_TRACK_AFTER_SECONDS` (1800 s in
  production), so it never ages past a longer threshold. The watchdog therefore remembers the
  first moment of an unconsumed backlog, and when dispatch last reopened. That memory is the
  "backlog since" marker v36 lacked; no heartbeat was added. A restart of the watchdog gives one
  threshold of grace, as beat-stale's does. It stays silent while beat is stale (its own alert)
  and while the breaker or a pause holds dispatch. The pacing sleep runs while the track is still
  `queued`, with no attempt row, so the effective threshold is never under `PACING_MAX_SEC` + 1
  min (review round 5). Its text says "isn't taking due tracks … worker-dl is down or stuck, or
  these tracks' queue messages were lost" (a `pending` track whose broker message was lost looks
  the same from the database), and names no "oldest due since": the stale sweep rewrites that,
  so it could read later than the idle time beside it (live review round 2). While beat is
  stale or Redis is out, dispatch counts as closed too: their return restarts the clock with a
  full threshold, as a breaker release does, or a standing backlog read as "down" the moment
  they were back (review round 6). **Accepted
  trade-off:** a worker-dl killed mid-download leaves its track `downloading`, which reads as
  busy until beat's stale sweep reclaims it, so that case is announced after
  `STALE_TRACK_AFTER_SECONDS` + the threshold (~45 min in production), not the threshold.
- **Found live: a new job's tracks are `pending` with a NULL `scheduled_at`.** expand_job's send
  clears v56's outbox marker, so `scheduled_at <= now` missed all 11 tracks of a fresh album and
  the first live run never fired. Due time is `coalesce(scheduled_at, updated_at)`.
- **O5.** `RedisOutageLog`: the first failed check logs one traceback, then one "still
  down (N checks)" line every 10 min, and a recovery line. The API's `/api/health` uses it too:
  Docker probes it every ~30 s, and the live review counted ~50 tracebacks from it in the
  25-min outage before it did. Celery's own "consumer: Cannot connect to redis" retry lines
  (54 in that outage) are Celery's and stay. The watchdog keeps its database checks
  (release, worker-down) and the delivery pass running through the outage; only beat-stale,
  worker-down (beat's state is unknown) and spike (its "newest seen" key) skip. A recovery is
  the check's verdict, never one read's, so a flapping Redis can't log "reachable again" and a
  fresh traceback inside one check. And beat gets one threshold of grace from Redis' return, as
  from the watchdog's start: it can't tick without its broker, so its heartbeat is as old as the
  outage, and v36 sent "Beat looks dead" just as beat resumed (live review round 2). The
  watchdog's delivery pass runs in a `finally`: with beat dead it's the only one, and a check
  that raises mustn't skip it (review round 5).
- **A `pending` track with a NULL `scheduled_at` that was never really sent** (a pre-v56
  stranded one) reads as worker-dl down once the watchdog has run a threshold. Before deploying,
  count them: `select count(*) from tracks where state = 'pending' and scheduled_at is null and
  updated_at < now() - interval '1 hour'`.
- **Deploy:** a v36 `send_alert` message still in the broker at deploy time is recorded into the
  outbox by the kept task. A trip open at deploy time has no outbox row, so its release isn't
  announced (the Redis marker is ignored).
- **The dev Matrix room is "spotdl-web CI scratch (v49)"** (owner's choice for v59), never
  production's "SpotDL Web Bot" room, which the local `.env`'s commented `MATRIX_ROOM_ID` names.
  `agent_stack.sh` rewrites `.env.agent` on every `up` and copies no `MATRIX_*`, so a slot that
  needs alerts appends them after `up` and recreates the backend services.

### v60 pipeline-resilience gotchas (learned closing P2–P8, O3 and the docs drift)

- **"Not acquired" is GitHub's, not the host's (P2).** Six scheduled runs (2026-09-12 to 10-15)
  had one job end `cancelled` with *"The job was not acquired by Runner of type self-hosted even
  after multiple attempts"*, no steps, `runner_name` empty. Every time, the runner (`vbServer`)
  was online and ran the run's *other* jobs; the host's load was low and no timer fires near
  those times. The listener's `_diag/Runner_*.log` shows the mechanism: on 10-04 and 10-15 the
  broker's first message, a second after the run was created, was a *sibling* job, which the
  runner took, while the job GitHub had assigned first never arrived; on 10-10 nothing came for
  61 s, and the late retry was refused (`POST …/acknowledge … NotFound`, then `POST …/acquirejob
  … Conflict`). It only hit scheduled runs, whose six jobs queued together after hours of idle,
  never a PR run. Since v49, Nightly is one job, so it needs another run queued at the same
  moment. Nightly's `notify` now tells it apart (API: the job `cancelled`, no steps, no runner,
  and that annotation on its check run) and re-dispatches once with `retry=true`. A job
  cancelled by hand while queued looks identical except for the annotation.
- **"Not acquired" can't be forced by stopping the runner (P2).** With the listener frozen
  (`kill -STOP`, idle, 2026-10-27 23:47:53Z) a Nightly dispatch's job stayed plain `queued`, no
  runner, for 19 minutes; GitHub just waited. The broker had handed the job over, though: on
  `kill -CONT` the listener read the stale message and logged exactly 10-10's signature,
  `acknowledge … Job not found`, then `acquirejob … Conflict` (the run had been cancelled by
  then). So a delivered, unacknowledged assignment is the mechanism, but GitHub's "not
  acquired" verdict needs its own retries to run out against a runner that keeps polling, which
  can't be staged on demand. The detection is verified on the real past run instead.
- **A job-level timeout is the wrong safety net (P4).** Scratch run 40595581518 (stand-in steps,
  the real rollback `if:`): with `timeout-minutes: 2` on the job, the health step was cancelled
  at 2 min, the `cancelled()` rollback started at once and was killed 4 min 49 s later, the
  `always()` step after it never ran, and `gh run view --log` answers "log not found" for that
  job: GitHub keeps only the annotation "The job has exceeded the maximum execution time". With
  `timeout-minutes: 1` on the health *step* instead, the step failed ("has timed out after 1
  minutes"), the rollback ran its full 9 minutes to success and the `always()` step ran. actionlint
  rejects `cancel-timeout-minutes`, so the 5-minute grace after a cancel can't be raised, which
  also means a hand-cancelled deploy's rollback has only that long.
- **The guard, not `up`, is what a changed `networks:` breaks (P3).** Reproduced with a toy
  project (Compose 5.6.0; the host has 5.6.1): `up` with a changed IPv6 subnet stops the
  containers, recreates the network and starts them again, fine in both directions. But `compose
  run --rm --no-deps migrate` with the *old* files, while the new stack holds the network, tries
  the same recreation and fails: "error while removing network: network … has active endpoints".
  That's migration_guard.sh's exit 1, a guard error, so no rollback. A third compose file with
  `networks: default: !override {name: <live network>, external: true}` makes the probe join the
  network as it is (`!override` replaces whatever keys the old definition had); when no such
  network exists the override is left out, since `external` would then fail with "declared as
  external, but could not be found". The network name comes from `config --format json`, whose
  full output holds `.env` values, so only that one field is printed.
- **Compose prints part of a value (P6).** `API_PORT=postgres://user:pass@db.example:5432/x`
  makes compose say `invalid IP address: 127.0.0.1:postgres://user:pass@db.example`: it split
  the port spec at the colons, so the full `.env` value never appears and `redact_env.py`'s
  whole-value masking let the password through. Any `scheme://userinfo@` is now masked as well,
  and so is every piece of a value cut at its colons. A value holding a tab, a control character
  or a non-printing one (NBSP, zero-width space) comes back Go-quoted (`\t`, `\u00a0`), so that
  form is masked too (live review).
- **`.last-good` versus old workflow copies (P7).** Every tag from v2.21.0 to v4.32.0 runs a
  plain `git clean -fd` after checking out its own commit, whose `.gitignore` has no
  `/.last-good`, so a dispatch *from* that workflow copy deletes the baseline (reproduced in a
  local clone with v4.32.0's own commands). None of them used `-x`, so `.git/info/exclude`,
  which no checkout changes, protects it from all of them.
- **journald, verified on a local stack before the overlay (O3).** `docker compose logs` after a
  recreation shows only the new container; `journalctl COM_DOCKER_COMPOSE_PROJECT=<project>`
  shows both. `CONTAINER_NAME` (and the `{{.Name}}` tag) is stable across recreations; stderr
  lines are priority 3, stdout 6. On the host the journal is persistent (`/var/log/journal`, 2.0
  GiB, back to 2026-07-11, default caps), every other project there uses json-file, and this
  stack writes about 0.7 MB a day.
- **A network change breaks the containers `up` doesn't recreate (P3, live review).** Compose
  5.6.0 / Engine 29.9.1: when `up` recreates a network whose config changed, a container whose
  own config didn't change (`redis:7.4-alpine`, `cloudflared`) is reconnected *without its
  service alias*: `getent`/`gethostbyname("redis")` fails from every recreated container, in the
  failed release's `up` and in the rollback's alike, and another plain `up` doesn't fix it.
  `--force-recreate` does. v29's gotcha, again; scratch run 40601071125 escaped it only because
  its logging change recreated every container anyway.
- **Compose decodes a value before echoing it (P6, live review).** `$$` becomes `$`, and in a
  double-quoted value `\\`, `\t`, `\r`, `\$` become themselves; a `$NAME` left in a value gets a
  "The \"NAME\" variable is not set" warning. The redactor masks the decoded form, its colon
  pieces and such names too.
- **A pipe hid a failed backup.** The backup step ran `pg_backup.sh | tee …` under Actions' default
  `bash -e` (no pipefail), so a failed dump passed the step and the deploy migrated without one
  (found by the round-2 review; the step now sets `pipefail`). Any `run:` that pipes a command
  whose failure matters needs it.
- **The X3 backup filenames are right as they are.** `pg_backup.sh` names its dumps
  `spotdl_web_<timestamp>.dump` and its retention globs that prefix: the `spotdl_web` in
  DEPLOYMENT.md's backup paths is a file prefix, not the database name (which is `spotdlweb`, read
  from the host `.env` by name only).
  *(2026-10-28, v60.1: the owner had the prefix renamed. New dumps are `spotdlweb_<timestamp>.dump`;
  retention and the retained count match both prefixes, so the old `spotdl_web_*` dumps still age
  out after 14 days. A dump's name no longer reads like a second production database.)*
- **The runner is a service now.** CI_SELF_HOSTED_RUNNER.md said it ran as a long-lived
  `./run.sh`; the host shows `runsvc.sh` (from PID 1) → `RunnerService.js` → `Runner.Listener
  --startuptype service`, runner 2.338.0, beside eight other repos' runners.

### v61 extension-release gotchas (learned building the extension's signing and release pipeline)

- **`update_url` and the linter.** `web-ext lint` treats an `update_url` as an error
  (`MANIFEST_UPDATE_URL`, "not allowed for Mozilla-hosted add-ons"). An unlisted add-on is
  self-hosted, so `npm run lint` passes `--self-hosted`, which only drops the AMO-hosting rules.
- **AMO never takes a version twice.** Not after a deletion, not after a failure in a later step.
  So a job that signed a version and then failed (the GitHub release, say) can't simply re-run
  `web-ext sign`. `extension-release.yml` first asks AMO for the version
  (`GET /api/v5/addons/addon/<guid>/versions/v<version>/`, the `v` forcing a version-number
  lookup) through web-ext's own exported client (`web-ext/util/submit-addon`: `Client`,
  `JwtApiAuth`), and downloads the signed file when it's there (a `disabled` file fails at once).
  A 404 means "sign it", and so does any other 4xx but 429 (an add-on AMO doesn't know yet may
  answer one; bad credentials then fail at `web-ext sign`); a 429 or 5xx fails the step.
  Anonymously, a public add-on's `versions/v<version>/` answers 200 and an unknown one 404
  (checked this session). With a made-up issuer AMO answers `401 {"detail": "Unknown JWT iss
  (issuer)."}`, checked this session.
- **The credentials stay off the command line.** The plan's `web-ext sign --api-key … --api-secret
  …` runs as `npm run sign` with `WEB_EXT_API_KEY`/`WEB_EXT_API_SECRET` (web-ext reads every flag
  from a `WEB_EXT_*` variable). The runner is the production host, where any process can read a
  command line (`ps`), not another process's environment.
- **"Latest" is the app's.** `releases/latest/download/updates.json` would serve whatever the
  newest app release carries, which is never the extension's file. The update manifest lives on a
  fixed `extension-updates` release (a prerelease, `--latest=false`, its tag outside release.yml's
  `v*`), and each `extension-v*` release is created `--latest=false`, so the app's badge never
  moves. An installed copy only ever reads the `update_url` it was installed with, so that release
  and its asset must never be deleted.
- **A new workflow can't be dispatched before it's merged.** `workflow_dispatch` (the UI and
  `gh workflow run`) runs only files on the default branch. A scratch branch with its own
  push-triggered test file (`.github/workflows/scratch-v61-release-deploy.yml`, never merged)
  calls the branch's real `extension-release.yml` with `uses:`, which works from any ref.
- **`gh release` errors are text.** `gh release view <missing>` and `gh release download
  <missing>` print `release not found`; a pattern matching nothing prints `no assets match the
  file pattern`, and a release with no assets at all `no assets to download` (gh's source; the
  first two were seen this session). All exit 1, like an auth or network failure, so the
  workflow matches the message and fails on anything else.
- **AMO rewrites `manifest.json` (found after merge, fixed in v61.1, 2026-10-29).** The first real
  signing (run 40767801329, extension 1.0.1) warned "The XPI AMO just signed differs from the
  source in: manifest.json". Parsed, the two are equal: AMO re-serialized the file (the source's
  tabs became 2-space indentation); the 18 other files were byte-identical. A warning on a fresh
  signing, but the re-run path (a version AMO already holds, fetched back) treated any difference
  as "signed from other content" and failed, so the documented recovery could never succeed
  (reproduced with the real signed XPI and the step's own `run:` block). `manifest.json` is now
  compared as JSON, every other file still byte for byte.
- **Two PRs bumping to the same version, both merged before the first one's release.** CI passed
  both (no tag yet). Whichever way the runs interleave, the second run's extension job runs: its
  plan either sees no tag yet, or sees the tag with other `extension/` content and hands over
  (`extension=true`) rather than only warning. The job's `released` step then compares the
  released tag's `extension/` tree with its commit's: equal, or a tag commit that already
  contains this one (GitHub's compare, `ahead`/`identical`, since the checkout is depth 1), is a
  no-op; otherwise it fails into `notify`, and keeps failing on every later run (each later
  commit's `extension/` differs from the tag's too) until a merge raises the version. The
  extension's version of release.yml's `owned`. The `updates.json` entry is read from the XPI's
  own manifest, never the checkout's, for the same reason. And a draft (what a killed `gh release create`
  leaves) is never "released": the job finishes and publishes it.
- **Same version, other content.** Release & Deploy's plan reads "the `extension-v<version>` tag
  exists" as "released". A version released from a branch (a dispatch) and later reused by a PR
  carrying different code would never ship, and neither would a version below a released one
  (plan skips it). CI's `check_version.py` refuses both: below the newest `extension-v*` tag, or
  equal to one whose `extension/` tree differs from the PR's. In the release job itself a
  version below the newest is a successful no-op, not a failure: two extension merges' runs can
  finish out of order on the one runner. And a signed file fetched back from
  AMO must equal the commit's `extension/` file for file (a web-ext build of it, minus
  `META-INF/`).

### v62 frontend-store-fixes gotchas (learned closing F1–F11)

- **The plan's F1 premise didn't hold.** `job.state` carries only the job's own state
  (`expanding`/`expanded`/`failed`/`cancelled`, plus `archived`), and a rollup move (a track
  settling turns `active` into `settled:complete`) publishes no job event at all. The owner chose
  to publish it: `job_status.publish_change(db, job_id)` (the owner is read from the job's row) runs
  after every announced change
  (the caller's commit first; once per job after a bulk loop: beat's dispatch and reclaim),
  computes the job's `status_key`, and swaps it into `spotdl:job-status:<id>` with `SET … GET`,
  under the job's row lock (`FOR NO KEY UPDATE`) together with its PUBLISH, so the chain is also
  the delivery order (review rounds 1–3).
  Two writers finishing together (the worker and an API cancel) can't both report the same old
  status, so the events form one chain. A missing key (a job from before v62, a 90-day-quiet job,
  a flushed Redis) sends no `prev_status`, and the browser re-reads its counts (one 1-row page);
  `prev_status: null` means a new job (`create_job`). It reads with the caller's session (a
  test's `db_session` fails a stray `SessionLocal`), ends that read's transaction (the download
  waits after some calls), never raises (the completion's call sits inside the download's
  `try`), and skips a session holding unflushed changes.
- **The browser counts a move once whichever way it arrives.** `countedJobStatus` is the status a
  job is counted under; a row refresh moves a count only while no `job.status` event has spoken
  for the job (a `getJob` answer can be older than an event already applied). F2: a page response
  whose request started before a later move doesn't overwrite it: "load more" never takes its
  page's counts (the same set as the local ones, kept current by every move; review round 5), a
  reload corrects the moved jobs it lists and re-reads the counts for one it doesn't.
  Residual: a reload snapshot taken after a commit whose event reaches the browser only after
  the response (the stream slower than a whole HTTP round trip) counts that move twice until the
  next reload.
- **The heartbeat had to become visible (F4).** As an SSE comment it never reached the page (v47),
  so "silent longer than the heartbeat" couldn't be told from "quiet". It's also a named event
  now (`event: heartbeat` with `data: {}`: an event with no data isn't dispatched), and each wait
  is the time left until the next one is due: in `others`, dropped messages used to stretch the
  silence to nearly two intervals. The page treats 15 s + 3 s of silence as dead, on
  `visibilitychange` → visible, `online`, and its 5 s worker poll: a laptop resumed with the tab
  visible can fire neither event (live review), and the poll's overdue timer runs at once on wake. Simulating sleep in Playwright: `setOffline`
  fires `offline` (the v47 path), so the new path is tested with `page.clock` fast-forwarding past
  the threshold and a dispatched `visibilitychange`.
- **No attempt id exists during a run (F10).** The attempt row is written when the invocation
  ends. The claim's `updated_at` (`clock_timestamp()`) is the run's identity: on every
  `downloading` event as `download_started_at`, and on the track's REST row while it downloads
  (nothing else writes a downloading track's row; a proxy delete's `SET NULL` is a DB-side FK
  action with no ORM `onupdate`). The cache key moved to `spotdl:live-progress:v2`.
- **F8's "current view" vs what clear log does.** The action archives every finished job of the
  viewer's, whatever the view shows, so the view's counts can only say "nothing to clear" where
  they cover all of the viewer's jobs: `mine`/`all`, no search, page loaded. Elsewhere it stays
  on. It's `aria-disabled` (still focusable, so its `aria-describedby` reason is read), not
  `disabled`.
- **F6 and the session.** Navigations that leave because the session ended or changed (a 401,
  another tab's sign-out or sign-in) set `leavingSession()`, which the unsaved-edits guard lets
  through without asking.

### v64 job-export gotchas (learned building the streamed zip and the M3U)

- **`api` couldn't read a single file.** Until v64 only nginx served audio (`X-Accel-Redirect`,
  v27), so `api` had no volume mounts; a zip built by `api` (needed for a known `Content-Length`,
  `MISSING.txt` from a real existence check and the zip's own layout) can't exist without them.
  The owner approved read-only mounts in all three compose files (2026-10-30). `DOWNLOADS_DIR` and
  `LIBRARY_DIR` were already required in production, so no new variable.
- **The plan's nginx change was already there.** `location /api/` has had `proxy_buffering off`
  since v12 (for SSE), and the export also sends `X-Accel-Buffering: no`. Verified against the
  nginx build (`docker build frontend`, run on the slot's network): a 1.2 GB zip streamed with
  `Content-Length: 1258291999`, `api` at 235 → 241 MiB throughout, and `pg_stat_activity` showing
  only `idle` pool connections (no `idle in transaction`) during the stream.
- **One expansion's tracks share a `created_at`.** `expand_job` inserts them in one transaction,
  and `now()` is the transaction's start, so a playlist in `created_at` order is random among ties.
  The export orders by `created_at`, then the song's `list_position`, `disc_number` and
  `track_number`. *(2026-10-30, review round 2: spotdl sets `list_position` only for playlists,
  so an artist job's albums interleaved; the key is now `created_at`, `list_position`, the album's
  `date` and `album_id`, then disc and track number: album by album, oldest first.)*
- **Membership is completed/skipped_duplicate *and* a file at its recorded path.** A track in any
  other state goes to `MISSING.txt` with its state, so the UI's "N of M files" (from
  `track_counts`, no request per row) and the zip agree unless a file vanished from disk, which
  `MISSING.txt` then names ("file not found at its recorded path").
  *(2026-10-30, live review round 2: the plan shows the strip "only when ≥1 track has a file",
  and a deleted file still counted. The strip's count is now the zip's own: `X-Export-Files` /
  `X-Export-Tracks` on the export's HEAD, read once when a job is opened and again when its
  settled count moves. One request per opening, never one per row.)*
- **Zip entry names are hostile input.** A basename can carry `\` (a separator to Windows
  extractors, so `..\..\x` would escape the folder), `:` and the rest of Windows' refused set:
  they become `_`. Duplicates are compared case-insensitively (an archive extracted on Windows or
  macOS folds case), and the playlist's and `MISSING.txt`'s names are reserved before any track.
- **A name is cut in UTF-8 bytes, from the stem** (review round 1). Cutting at 150 characters took
  the extension with it (`…(Remastered 2015).op`), and filesystems limit a name to 255 *bytes*:
  a Hungarian name's accented letters are two each, so a cut name plus ` (2)` could overflow on
  extraction. The cut is 200 bytes, taken from the stem; an "extension" is a short dot-suffix
  without spaces, so "No. 3" in a title isn't one.
- **An M3U line starting with `#` is a comment.** A track file named `#1 Crush.opus` would drop
  out of the playlist while staying in the zip, so such an entry is written `./#1 Crush.opus`.
- **`?paths=library` paths are the container's.** The library is mounted at the same path in
  every container (`/mnt/raid1/media/music`), so those are real for a media server only where
  `LIBRARY_DIR` is that path on the host too (production). A file still on the downloads volume
  (`/downloads/...`, meaningless on the host) is a `# not in the library yet:` comment line.
- **A library sweep during a long export: found again through the ledger** (owner's decision,
  2026-10-30). The plan stats each file once (the `Content-Length` is fixed), but a file is opened
  only when the stream reaches it, and a sweep may have moved it by then. The sweep commits the
  ledger's new path *before* it unlinks the source (`tasks/library.py`), so a miss re-reads that
  row once (its own short session, ended at once) and streams the file from the library if it's
  the size the plan counted; otherwise the stream ends (`ExportFileChanged`). Opening every file
  up front was the alternative, but the `api` container's soft open-file limit is 1024, below the
  2000-file default. One case still ends the stream: a target that already existed (the sweep's
  "already exists" is folder and filename only, any bitrate) with another size than the plan
  counted; a retry then exports it from its new place. Proven live: a sweep moved 13 files mid-stream, 7 were read from their new
  path, and every entry matched byte for byte. The server runs ahead of a slow client by the
  socket and nginx buffers, so the files already read never needed it.
- **Entries are added as sized iterables, not paths,** so the miss can be handled; the entry's
  timestamp in the archive is then the export's, not the file's.
- **`zipstream-ng`'s `add()` entries carry no file-type bits** (`zipinfo` lists the `.m3u8` as
  `?rw-------`); every extractor tried (Info-ZIP, Python) writes a normal file. Harmless.
  *(2026-10-30, review round 2: not harmless. Info-ZIP restores the mode, `0600`, so a media
  server reading the extracted folder as another user can't open the files; and since round 1
  every entry is an `add()`. `_ExportZip` sets `0644` on every file entry in the central
  directory, which is written last, just before it goes out.)*
- **An aborted download must close its iterator** (live review round 2). Starlette iterates a
  sync iterator in its threadpool and, on a disconnect, just drops it: the generator, and the file
  it was reading, stayed open until the cyclic garbage collector ran (30 aborts, 30 open files
  after 50 s). The response now wraps it in an async generator whose `finally` closes it, and
  `iter_chunks` closes the archive's own generator. Proven: 0 files open 3 s after 10 aborts.
  *(Review round 3: under ASGI spec ≥ 2.4 a disconnect surfaces as an `OSError` from `send()`
  (Starlette re-raises it as `ClientDisconnect`) and Starlette never calls `aclose()` on the
  body, so that `finally` still waited for the async generator's finalizer. The response
  (`_ClosingStreamingResponse`) now closes its body itself; a plain `StreamingResponse` in the
  same disconnect leaves the file open, which the test now checks.)*
- **zipstream-ng 1.9.3 counts a 65,535-entry archive's length without the zip64 end records**
  it then writes (`__len__` tests `>` the limit, the footer `>=`), so its Content-Length would be
  76 bytes short. The files limit is capped at 65,000 (env and settings). Above 4 GiB the count
  holds: a sparse 4.5 GiB test streams exactly the declared length.
- **A file can move between the plan's read and its stat too.** The rows are read, the
  transaction ends, then each file is stat'ed: a sweep in between left a moved file in
  `MISSING.txt`. The misses get one batched ledger re-read after the stats (one query, its own
  short session), as the stream does for a file that moves later.
  What's left is the allocator: the worker's VmRSS rises with many *concurrent* aborted streams
  (242 → 466 MB over 110, about 0.5 MB each and slowing), while tracemalloc shows 0 KiB net
  Python allocation over 100 aborted streams of our own code, and a single stream stays flat.
- **nginx's `send_timeout` (60 s) cut off a paused download.** `location /api/` only raised
  `proxy_read_timeout`/`proxy_send_timeout`, which time the upstream side. It's 3600 s now; a
  reader paused 75 s gets the whole 1.2 GB. There's no `Range` support, so a download can't
  be resumed.
- **Measure a stream's memory as the worker's VmRSS, not `docker stats`.** `docker stats`
  counts the page cache the stream reads through (516 → 965 MiB while VmRSS stayed at 255 MB).
- **An ending stream logs a traceback.** A file that can't be streamed as planned raises
  `ExportFileChanged` mid-response, and uvicorn logs the "Exception in ASGI application" with its
  traceback. Expected; there's no quieter way to end a response with a declared length.

