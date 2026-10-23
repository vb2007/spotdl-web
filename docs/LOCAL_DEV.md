# Local development environment

This is the primary environment for day-to-day work: your own PC, Docker already installed,
fast iteration with hot reload. **The Debian production host (`docs/DEPLOYMENT.md`) is a
separate, final deployment target** — not where you debug a broken feature. Bouncing every
fix through a `git pull` + rebuild + SSH-log-check cycle on that box doesn't scale as a
develop loop; do that locally instead, and only touch the Debian host to verify a version is
genuinely ready to merge.

Postgres itself is never dockerized, never duplicated (locked decision): both environments
reach the same physical Postgres server on the Debian host over the network. **They never share
a database.** Local dev uses its own dedicated dev database, **`spotdlwebtest`**, and production
keeps its own (`spotdlweb`). Redis and every other container run entirely locally and are never
shared with the deployed instance either. See [Dedicated dev database](#dedicated-dev-database)
below for how it's created, built and reset, and why this is enforced rather than just advised.
The one exception is an implementation agent's **slot stack** (master v5, v50): it runs its own
throwaway Postgres container, never the LAN server. See
[Parallel agent stacks](#parallel-agent-stacks-v50).

---

## 1. Configure `.env`

```bash
cp .env.dev.example .env
```

Fill in the real Postgres password for the dev database's role (the URL's database name must
stay `spotdlwebtest`, see [Dedicated dev database](#dedicated-dev-database)) and `ADMIN_EMAIL`, a
**test account**, never the owner's real admin address (v17+ — must also appear in
`ALLOWED_EMAILS`, or `migrate` fails at boot and the services waiting on it never start). Everything else in `.env.dev.example` is already dev-appropriate out of the box —
notably `LADDER_SECONDS` is pre-shortened to seconds instead of hours, since testing the real
retry ladder shouldn't take literal days.

`worker-meta` bind-mounts `./proxies.txt` (see `docker-compose.override.yml`), so a file needs
to exist at the project root before `docker compose up` or Docker creates an empty directory
there instead (silently breaking `sync_from_file()` — see the v07 gotchas in `docs/GOTCHAS.md`):

```bash
cp proxies.txt.example proxies.txt
```

An empty (or comment-only) `proxies.txt` is fine — proxy rotation just has nothing to draw
from, and every attempt falls back to direct.

## 2. Bring up the stack

Unlike the production host, you *want* `docker-compose.override.yml` here — it's what gives
you `uvicorn --reload` and `vite dev` with bind-mounted source, so edits show up without a
rebuild:

```bash
docker compose up
```

(No `-f docker-compose.yml` exclusion — that flag is specifically to *avoid* the override on
the production host. Here, the override is the point.)

**One gap this trades away:** the override runs `vite dev` for `web`, not nginx — anything whose
correctness depends specifically on nginx behavior (a new `internal` location, a new `location`
block) can't be exercised through this stack at all; verifying that kind of change needs
`docker compose -f docker-compose.yml up` (bypassing the override) or the deployed host instead.
File downloads (`GET /api/tracks/{id}/file`) are the one exception: `frontend/vite.config.ts`'s
`devFileDownloadFallback` plugin recognizes that route specifically and serves the file itself
in dev, so it works through the normal override stack too (see `docs/GOTCHAS.md`'s v27 entry for
why that needed doing, and why it wasn't the original design).

## 3. Verify

```bash
curl -s http://localhost:8000/api/health
```

Ports bound to `127.0.0.1` is fine and expected here too — this is your own machine, nothing
about the Cloudflare-Tunnel-only ingress rule changes; it just happens to not matter locally
since nothing here is reachable from anywhere else regardless.

## 4. Seeding a second user for multi-user testing (v17+)

Add a second address to `ALLOWED_EMAILS` (comma-separated, `ADMIN_EMAIL` stays whichever test
account should be the dev operator) and recreate `api`:

```bash
docker compose up -d api
```

The second identity's `users` row is created automatically on its first successful login — real
login needs a real password against whichever upstream `UPSTREAM_AUTH_BASE_URL` points at
(`host.docker.internal:3000` if the local `vb2007.hu-api` instance is running, otherwise the live
`https://api.vb2007.hu`; see `docs/GOTCHAS.md`'s v17 standing rule). Registering a fresh test
account against either is expected and fine — `POST /auth/register {username, email, password}`
(plain alphanumeric username; a hyphenated one 500s on the upstream, a known upstream bug, not
this app's). For a quick non-real-login identity instead (no password needed, but skips exercising
the actual auth path), mint a session directly:

```bash
docker compose exec api python -c "
from app.db import SessionLocal
from app.services.users import get_or_create_user
from app.services.sessions import create_session
db = SessionLocal()
user = get_or_create_user(db, 'second@example.com')
session = create_session(db, user.id)
db.commit()
print(session.token)
"
# then: curl -H 'Cookie: SPOTDL_SESSION=<token>' http://localhost:8000/api/jobs
```

## 5. Exercising sort & move locally (v28)

Never point `library_target_dir` at the real ~120k-track directory for a first run (the plan's
own words) — `docker-compose.override.yml` already wires a throwaway local stand-in for exactly
this, gitignored the same way `./downloads` is:

```yaml
worker-expand:      # v34.1: the sort sweep itself runs here
  volumes: !override
    - ./test-library:/mnt/raid1/media/music
worker-meta:        # boot-time reconcile_disk() checks ledger rows that point into the library
  volumes: !override
    - ./test-library:/mnt/raid1/media/music
worker-dl:          # v38: the dedup gate must see moved files
  volumes: !override
    - ./test-library:/mnt/raid1/media/music:ro
web:
  volumes: !override
    - ./test-library:/mnt/raid1/media/music:ro
```

`./test-library` starts out empty (create it if `docker compose up` didn't already). As admin,
point the app's own `library_target_dir` setting at the *container path* the mount above uses —
not some other path, or the sweep writes into the container's ephemeral overlay filesystem
instead of the bind mount, "succeeds," and nothing shows up on disk or through nginx:

```bash
curl -b <admin cookie jar> -X PATCH http://localhost:8000/api/settings/library \
  -H "Content-Type: application/json" \
  -d '{"library_target_dir":"/mnt/raid1/media/music"}'
```

Download a track, `POST /api/library/sort` as admin, and confirm the file landed under
`./test-library/<Artist> - <Album> - (<Year>)/` on the host, every `downloaded_tracks` row
pointing at that file had its `file_path` repointed (v48: two ledger rows, say a single and its
album cut, can share one file), and `GET /api/tracks/{id}/file` still serves it afterward (v31
proved this exact sequence — see `docs/GOTCHAS.md`'s v31 section). The sweep archives only the
sweeping admin's own settled jobs among those it moved (v48); another user's job keeps its
repointed track and stays unarchived.

## 6. When a version is ready

Push the branch and open/update the PR as usual. Before merging, do one final check on the
real target per `docs/DEPLOYMENT.md` — that's the only remaining reason to touch the Debian
host mid-development, and it should be a confirmation, not a debugging session.

## Dedicated dev database

**Rule (v32):** local dev runs against `spotdlwebtest`, never against production's database. This
used to be one shared database, and it went wrong exactly as predicted: v22's local test jobs
showed up in production's tables, and in v31 local `worker-meta`'s boot-time `reconcile_disk()`
pruned a real production `downloaded_tracks` row, because the file it pointed at only exists on
the deployed instance's own downloads volume (`docs/GOTCHAS.md`'s v31 and v32 sections).

**Enforced, not advised.** `docker-compose.override.yml` (dev only) sets `SPOTDL_ENV=dev` on every
backend service: `api`, `migrate`, `worker-dl`, `worker-meta`, `worker-expand` and `beat`. `app/config.py` then
refuses to start any of them when `DATABASE_URL` names a production database
(`PRODUCTION_DATABASE_NAMES`: `spotdlweb`, plus `spotdl_web`, the name `.env.example` documents),
and also when the database name can't be determined at all: an unparseable URL, or no database in
it. That's fail closed: "can't tell" never reads as "safe". Alembic's `env.py` re-checks the exact
URL it migrates. A refused service exits non-zero with the message below. On a plain
`docker compose up` you'll see it only in `migrate`'s log, because every other backend service
waits on `migrate` completing successfully and so never starts. To see each one refuse on its own,
use `docker compose run --rm --no-deps <service>`:

```
SPOTDL_ENV=dev but DATABASE_URL points at the production database 'spotdlweb'; refusing to start
-- point DATABASE_URL at spotdlwebtest, see docs/LOCAL_DEV.md
```

Production never sets the marker (the override file never applies there), so the guard is a no-op
in production. The flip side: the guard only protects processes that carry the marker, i.e.
containers started through the override. A host-side `alembic`/`python` run, or a local
`docker compose -f docker-compose.yml …` (which skips the override), has no marker and no guard.
Keep the local `.env` pointed at `spotdlwebtest` regardless. `SPOTDL_ENV` is reserved: **never set it in production**, not even to `prod`. Any value
other than `dev` is refused everywhere, so a typo can never silently disable the guard. The guard keys on "is it production", never on the dev name, so renaming the dev
database later doesn't break it.

**What the owner creates, once.** The database and its role live on the shared Postgres server,
created by the owner with Postgres superuser rights, never by an agent. `spotdlwebtest` exists
since 2026-10-01, owned by the same role as production's database. A fresh one follows the
`CREATE DATABASE … OWNER …` pattern of `docs/DEPLOYMENT.md` §2. The schema needs `pg_trgm`
(v18's trigram indexes), which the migration creates itself when the owning role is allowed to.

**How the schema gets built.** By the app itself: the one-shot `migrate` service runs
`alembic upgrade head` on every `docker compose up`, so an empty database becomes a current one
on first boot. Don't hand-write tables, and never restore a production dump into it: the dev
database starts empty on purpose, and nothing from production is copied in.

**How to reset it.** Drop and recreate it (owner, superuser), then `docker compose up` and let
`migrate` rebuild it. If only the schema is in a bad state, a disposable round-trip works too,
with the app services stopped so nothing writes mid-migration:

```bash
docker compose stop api worker-meta worker-expand worker-dl beat
docker compose run --rm --no-deps migrate sh -c "alembic downgrade base && alembic upgrade head"
docker compose up -d
```

**A fresh dev database means fresh `users` rows.** Every identity gets its row again on its first
successful login, and `is_admin` comes from the local `.env`'s `ADMIN_EMAIL` (a test account).
File-sourced proxies come back on `worker-meta`'s next boot through `sync_from_file()`. Manual
(UI-added) proxies, jobs and settings start empty.

## Browser end-to-end suite (v37)

A committed Playwright suite (`frontend/e2e/`, config in `frontend/playwright.config.ts`) drives a
real Chromium against the **running local stack**: the dev `web` origin, the real backend, the dev
database, real SSE. Nothing is mocked and nothing is started for you. It's the regression net for
the v39–v47 UI rework, so run it before calling any frontend change done.

**One-time setup**

1. Two **test** identities that log in through the real upstream: one is the dev `.env`'s
   `ADMIN_EMAIL`, the other isn't, and both are in `ALLOWED_EMAILS`. Register fresh ones freely
   (§4). Never the owner's real account. Keep both **dedicated to the suite**: every run cancels
   whatever they have in flight and archives the rest of their jobs, so manual admin testing
   belongs on another account (the dev `ADMIN_EMAIL` can be switched back for it).
2. `cp frontend/e2e/.env.e2e.example frontend/e2e/.env.e2e` and fill in both. The copy is
   gitignored (`git check-ignore frontend/e2e/.env.e2e` confirms it).
3. `cd frontend && npx playwright install chromium`.

**Run it** with the stack up (`docker compose up`):

```bash
cd frontend
npm run test:e2e            # the baseline specs, desktop (1280×800) and mobile (390×844), plus the hu project
npm run test:e2e:network    # opt-in: the one @network spec, a real YouTube download
E2E_STRICT=1 npm run test:e2e   # v43: fail, never skip, spec 12's tests that step aside on a busy stack
```

`E2E_BASE_URL` overrides the origin (default `http://localhost:${WEB_PORT:-5173}`, v50), for example
to aim at the production-style `web` image. It must stay a loopback origin, and the config refuses anything
else: setup and teardown check the local stack's database, so the browser must drive that stack.
Use `localhost`, not `127.0.0.1`: the session cookie is `Secure`, which Chromium only honours over
plain HTTP on `localhost`. If another dev server listens on `[::1]:5173`, it captures `localhost`
(compose publishes `web` on `127.0.0.1` only), so stop it before a run. Failures keep a trace and a screenshot under `frontend/test-results/`
(`npx playwright show-trace <trace.zip>`), and `frontend/playwright-report/` holds the HTML report.

**How it stays cheap on the real stack**

- Global setup logs both identities in once through the real `/api/auth/login`, cancels anything
  they left in flight, archives the rest ("clear log"), and seeds one job each. The specs reuse
  those sessions. Only spec 1 drives the login form itself.
- Every job a default run creates is a track **already in the dev ledger** (`skipped_duplicate`,
  resolved in milliseconds by `worker-dl`'s dedup gate) or a Spotify id that doesn't exist (a
  `failed` expansion). The tracks are listed in `e2e/support/stack.ts`'s `LEDGER_TRACKS`, and they
  must stay in the ledger with their files under `./downloads`. Global teardown **fails the run**
  if either identity made a network download attempt while it ran.
- Spec 9 (v38) also needs two ledger rows the library sort has moved into `./test-library`
  (`in_library`, file present) that the admin identity never submitted. It picks them itself and
  fails, asking for a sort, if there aren't two.
- The specs run one at a time (`workers: 1`): they share one queue, one beat and one `worker-dl`.
  A full run takes a few minutes, mostly beat's 30 s dispatch pass.
- The `@network` spec needs `E2E_NETWORK_TRACK_URL`, a track that is **not** in the dev ledger
  yet. A passing run adds it, so each pass names a fresh one, for example
  `E2E_NETWORK_TRACK_URL=https://open.spotify.com/track/<id> npm run test:e2e:network`. It refuses
  a track that's already there rather than passing on a duplicate.

**Writing specs:** select by role, label and accessible name (`getByRole`, `getByLabel`), never
by CSS class. The v40–v43 restyles must not rewrite the suite. If an element has no accessible
name, give it one in the component: that's an accessibility fix, not a test hack. Every project
pins its locale, because accessible names are text: `desktop` and `mobile` run at `en-US`, and
v46's `hu` project (desktop viewport, `hu-HU`) runs only the keyboard spec (14) and the Hungarian
smoke (15), reading names from the same message files the app renders. Spec 16 (i18n) drives its
own per-locale contexts and runs on `desktop` only. Specs are named `*.e2e.ts` so vitest's default `*.spec.ts`/`*.test.ts`
include never picks them up.

**Why local-only, with no CI browser job:** the self-hosted CI runner *is* the production host,
which also runs real services (Matrix/Synapse, Vaultwarden). Browsers and test traffic don't
belong there. The suite also needs the dev stack's database, ledger files and two upstream test
accounts, none of which exist on the runner. CI still lints and typechecks `e2e/` (`npm run lint`,
`npm run check`). Since v46 both also run `scripts/check-messages.mjs` (`en.json`/`hu.json` hold
the same keys with the same inputs), and `lint` adds `scripts/scan-literals.mjs` (no hard-coded
user-visible string outside the message files). Running it is part of each UI version's local checks.

## Parallel agent stacks (v50)

Master v5 runs up to four implementation agents at once, each in its own git worktree. Each one
brings up its own **slot stack** beside the owner's default one, through one script:

```bash
scripts/agent_stack.sh <slot> env      # write .env.agent from the worktree's .env
scripts/agent_stack.sh <slot> up       # (re)write .env.agent, build, start, wait until healthy
scripts/agent_stack.sh <slot> ps|logs|psql
scripts/agent_stack.sh <slot> run <cmd...>     # <cmd> aimed at the slot (its compose project, files, ports)
scripts/agent_stack.sh <slot> pytest [args]    # the backend suite, inside the slot's api container
scripts/agent_stack.sh <slot> e2e [args]       # the full Playwright suite against the slot
scripts/agent_stack.sh <slot> realdl <cmd...>  # worker-dl on, under the host-wide lock, for <cmd>
scripts/agent_stack.sh <slot> down [--volumes]
```

| Slot | Compose project | API | Web | Database |
|---|---|---|---|---|
| 1 | `spotdlweb-s1` | `localhost:8001` | `localhost:5174` | `spotdlweb_s1` in the project's own `postgres` container |
| 2 | `spotdlweb-s2` | `localhost:8002` | `localhost:5175` | `spotdlweb_s2` |
| 3 | `spotdlweb-s3` | `localhost:8003` | `localhost:5176` | `spotdlweb_s3` |
| 4 | `spotdlweb-s4` | `localhost:8004` | `localhost:5177` | `spotdlweb_s4` |
| owner | the checkout's directory name | `localhost:8000` | `localhost:5173` | LAN `spotdlwebtest` |

**Setting one up.** In a fresh worktree (`git worktree add -b <branch> ../spotdl-web-wt/<branch>
origin/main`), copy the owner's dev `.env` in (`cp ../../spotdl-web/.env .`), then `up` (it also
creates `frontend/.env` from its template, which `$env/static/public` needs). `env` and `up` also
comment out the copied `.env`'s `DATABASE_URL`: the worktree's own plain `docker compose up` would
otherwise run the branch's migrations on the owner's `spotdlwebtest`, and without it every backend
service refuses to start. The script refuses:

- a slot other than 1–4;
- the shared main checkout (a slot runs only from a linked worktree);
- a slot whose containers or database volume belong to another worktree (`env`, `up` and `down`
  hold a per-slot lock, `/tmp/spotdl-web-slot<slot>.lock`, so two worktrees can't claim one free
  slot at once);
- a worktree whose `.env` names a production database (`spotdlweb`, `spotdl_web`);
- `up worker-dl`, or `run` with a command that would start it (`run docker compose up worker-dl`).

**What `.env.agent` holds.** `env` derives it from the worktree's `.env`, gitignored, mode 600:

- the slot's `COMPOSE_PROJECT_NAME`, `API_PORT`, `WEB_PORT`, `FRONTEND_ORIGINS` and `SPOTDL_ENV=dev`;
- its database (`AGENT_PG_DB`, `AGENT_PG_USER`, `AGENT_PG_PASSWORD`; the overlay builds every
  backend service's `DATABASE_URL` from them, so `.env.agent` carries none);
- fresh random `REDIS_PASSWORD`, `SESSION_SECRET` and Postgres password (kept by later `env` runs,
  since the database volume was initialised with that password);
- the slot's test identities only: `ALLOWED_EMAILS=v5s<slot>admin@example.com,v5s<slot>user@example.com`,
  `ADMIN_EMAIL=v5s<slot>admin@example.com` (`AGENT_EXTRA_EMAILS=a@example.com,…` before `env` adds more);
- copied from `.env`, only engine and download tuning plus the upstream login: `UPSTREAM_AUTH_BASE_URL`
  (the real `vb2007.hu-api`), `SPOTIFY_CLIENT_*`, `LADDER_SECONDS`, `STALE_TRACK_AFTER_SECONDS`, pacing,
  format, bitrate and `DOWNLOAD_OUTPUT_DIR`, `PROXY_FILE`, `COOKIE_FILE`, `YOUTUBE_PLAYER_CLIENTS`. Never `.env`'s
  identities, Matrix token, tunnel token or database.

**The overlay.** `up` runs `docker compose --env-file .env.agent -f docker-compose.yml -f
docker-compose.override.yml -f docker-compose.agent.yml` (exported as `COMPOSE_PROJECT_NAME`,
`COMPOSE_FILE` and `COMPOSE_ENV_FILES`, so the e2e suite's own `docker compose` calls hit the slot
too). `docker-compose.agent.yml` is never part of a production invocation. It:

- adds a `postgres` service matching production (18.6 on Debian, so glibc's `en_US.UTF-8`
  collation, read from `spotdlwebtest` on the same server; Alpine's musl sorts text differently),
  with a named volume and a healthcheck, and no host port unless `.env.agent`
  has `PG_PORT` (`PG_PORT=55431 scripts/agent_stack.sh 1 up`; `PG_PORT= … up` removes it);
- points every backend service's `DATABASE_URL` at it and makes them wait for its healthcheck;
  `migrate` builds the schema on first `up`, as on the owner's stack;
- reads `.env.agent` instead of `.env` in every backend container;
- puts `worker-dl` in the `realdl` profile, so a slot never downloads by default;
- gives the project network its own IPv6 `/64` (`fd00:dead:beef:<slot>::/64`): the dev override
  pins one subnet, and two networks can't share it.

Everything else is already per slot: the project name prefixes every container, network and
named volume (Redis's data included), and `./downloads`, `./test-library` and `./proxies.txt` are
relative to the worktree (`up` creates them, so Docker doesn't create them root-owned).

**Logins.** Each slot logs in through the real upstream its `.env.agent` names
(`UPSTREAM_AUTH_BASE_URL`, copied from `.env`). Register its two identities there once, with a
plain alphanumeric username (§4). From the host, a `host.docker.internal:3000` upstream is
`localhost:3000`:

```bash
SLOT=1
UPSTREAM="$(sed -n 's/^UPSTREAM_AUTH_BASE_URL=//p' .env.agent | sed 's/host\.docker\.internal/localhost/')"
for role in admin user; do
  curl -sS -X POST "$UPSTREAM/auth/register" -H 'Content-Type: application/json' \
    -d "{\"username\":\"v5s${SLOT}$role\",\"email\":\"v5s${SLOT}$role@example.com\",\"password\":\"<a fresh password>\"}"
done
```

Then put them in `frontend/e2e/.env.e2e.s<slot>` (same keys as `.env.e2e.example`, gitignored).
`e2e` exports that file's keys, so they win over a `frontend/e2e/.env.e2e` in the worktree, but
the suite still reads that file for any key the slot file lacks: keep the slot file complete, or
the worktree free of `.env.e2e`.

In a browser, use one profile (or private window) per stack: cookies aren't scoped by port, so
the session cookie of `localhost:5174` and the owner's `localhost:5173` overwrite each other, and
each stack then answers the other's token with 401.

**Other commands against the slot.** Anything that should hit the slot rather than the owner's
stack runs under `run`, which exports the same `COMPOSE_*` variables and `API_PORT`/`WEB_PORT`:
`scripts/agent_stack.sh 1 run scripts/verify_separation_sse.sh` (its default base URL follows
`API_PORT`), `scripts/agent_stack.sh 1 run docker compose exec api sh`.

**Real YouTube traffic: the realdl lock.** At most one *agent* stack on this machine talks to
YouTube at a time (the owner's default stack keeps its own `worker-dl`, outside the lock: the
agents together add one dev stack's exposure). `realdl <cmd…>` takes
`flock -n /tmp/spotdl-web-realdl.lock`, refuses while any other slot's `worker-dl` still runs,
writes its holder (slot, worktree, pid, start time, command) into the file, rebuilds and starts
`worker-dl`, waits until it answers a ping, runs the command, then removes `worker-dl` and
releases the lock, however the command ends:

- Ctrl-C, SIGTERM or SIGHUP to the script ends the command and everything it started (as SIGTERM)
  and then cleans up; a second Ctrl-C during the cleanup doesn't cut it short (the removal runs in
  its own session), and `worker-dl` runs under an init (`init: true`), so it stops at once even
  when interrupted in its first seconds;
- the command doesn't inherit the lock, so if the script itself is killed outright, the lock frees
  while that slot's `worker-dl` may still run, and every other slot's `realdl` refuses (both before
  starting its own `worker-dl` and again once it answers) until
  it's gone (`scripts/agent_stack.sh <slot> down` there).

A second `realdl` from any slot fails at once, naming the holder: wait and retry, never start
`worker-dl` by hand. A track whose job is unfinished and whose Spotify id isn't in the ledger
really downloads once `worker-dl` runs: beat keeps re-dispatching it into the slot's Redis while
`worker-dl` is off (its stale-track reclaim). `realdl` says how many there are before it starts `worker-dl`.

**e2e on a slot.** The suite needs `worker-dl` (every seeded job settles there as a duplicate, and
setup and teardown ask the worker itself what it's running), so `e2e` runs under the realdl
lock too, although a default run makes no network attempt; it refuses to start while the slot
has unfinished tracks outside the ledger (above), which would. The suite was written against the owner's
long-lived dev database, so before it runs, `seed` (`scripts/agent_seed.py`, idempotent) recreates
what a fresh slot lacks:

- a ledger row and a one-second silent stand-in file for every track a default run submits
  (`LEDGER_TRACKS` in `frontend/e2e/support/stack.ts`, spec 12's `CANCEL_TRACKS` and
  `SUBMISSION_TRACKS`, spec 14's
  `HELD_TRACKS` and `NEIGHBOUR_TRACK`), under `./downloads/agent fixture/`, plus spec 9's two
  tracks the library sort moved, under `./test-library/agent fixture/`;
- the e2e admin's history: 120 archived jobs (spec 14 pages through three pages of 50), a 14-track
  album (spec 14's twelve-or-more-track job) and a track whose attempt recorded a network path
  (spec 3; on the owner's stack an earlier `@network` pass leaves one).

A new spec that leans on more of the owner's data needs that data added to the seed too. Then `npm run test:e2e`
runs from the worktree's
`frontend/` (run `npm ci`, `npm run check`, which compiles the messages the specs import, and
`npx playwright install chromium` there once) with
`E2E_BASE_URL=http://localhost:<web port>`.

**`pytest`** runs the backend suite inside the slot's `api` container, from the worktree's
`backend/` (the overlay mounts it read-only at `/src`), with pytest pinned to `uv.lock`'s
versions and a clean environment, as on the host.

**Teardown and reset.** `down` stops and removes the slot (`worker-dl` included); the database
and Redis volumes stay, so `up` comes back with the same data. `down --volumes` drops them, and
the next `up` builds a fresh database. A slot's database volume is labelled with its worktree, so
the next slice to use the slot can't silently inherit it: drop it with `down --volumes` from the
old worktree, or `docker volume rm spotdlweb-s<slot>_pgdata spotdlweb-s<slot>_redis-data` once that
worktree is gone (only the database volume carries the label; the Redis one holds the old queue). If a
worktree lost its `.env.agent`, `down [--volumes]` still works there: it removes the slot by its
compose labels instead.

**Known rough edge.** The dev `web` container runs Vite as root and writes `.svelte-kit/` and
`project.inlang`'s cache into the worktree root-owned. `up` hands those back to you once, but a
route added later can leave new ones (`docs/GOTCHAS.md`, v44; v52 owns the lasting fix).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Every container fails at startup with `failed to add the host <=> sandbox pair interfaces: operation not supported` (or any other veth/bridge networking error) | A kernel update landed via the package manager but the machine hasn't rebooted into it yet — the running kernel's module directory (including `veth`) has already been deleted from disk in favor of the new one | Compare `uname -r` against the installed kernel package version (`pacman -Q linux` on Arch) and check `/lib/modules/$(uname -r)/` exists; if it doesn't, reboot |
| `web` fails with `Bind for 127.0.0.1:5173 failed: port is already allocated`, even though nothing else is using that port | `docker-compose.override.yml`'s `ports:` list *merges* with `docker-compose.yml`'s instead of replacing it (list-type keys merge by default across compose files — `command`/`build` don't, so this is easy to miss), so `web` ends up with two host bindings to the same address | Confirmed fixed for `web` via the `!override` merge tag on its `ports:` key — if you add a *new* port mapping to any service in the override, check `docker compose config` for duplicates rather than assuming a plain list will replace the base file's |
| Stack was working, comes back broken after `docker compose down && up` with no config changes | Check `docker compose config` for the resolved service definitions before assuming it's a code regression — compose-file merge behavior is a common source of surprises that look like app bugs | |
| `migrate` exits at boot (and api/workers/beat never start, since they wait on it) with `SPOTDL_ENV=dev but DATABASE_URL points at the production database …` or `… can't be parsed` / `… names no database` (v32) | The local `.env`'s `DATABASE_URL` points at production's database, or is malformed. The dev guard refuses rather than risk production rows | Point `DATABASE_URL` at `spotdlwebtest` (see [Dedicated dev database](#dedicated-dev-database)). Never remove `SPOTDL_ENV` from the override to get past it |
| `migrate` fails at boot (api/workers/beat never start) with a `pydantic.ValidationError` naming `ADMIN_EMAIL` (v17+) | Either `ADMIN_EMAIL` is unset in `.env`, or it's set but not also present in `ALLOWED_EMAILS` — both are required at startup, by design | Add `ADMIN_EMAIL=you@example.com` to `.env` and make sure that same address is also in `ALLOWED_EMAILS` |
| After editing a backend file, `api` stops answering and goes `unhealthy`, logging `Waiting for connections to close` (v48) | `uvicorn --reload` waits for every open connection before restarting, and an `/api/stream` SSE connection (a browser tab, a `curl -N`, a Playwright run) never closes on its own | `docker compose restart api` |
| A backend change works through `api` but a task still runs the old code | Celery workers and `beat` don't hot-reload: they keep the Python they imported at boot, even with the source bind-mounted | `docker compose restart worker-dl worker-meta worker-expand beat` (whichever run the changed code) |
| A frontend dependency change doesn't show up in `web`, even after `docker compose build web` (v46) | `web`'s `node_modules` and compiled `src/lib/paraglide` are anonymous volumes (`docker-compose.override.yml`), and they outlive an image rebuild | `docker compose build web && docker compose up -d --renew-anon-volumes web` |
