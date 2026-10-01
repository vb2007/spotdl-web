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
there instead (silently breaking `sync_from_file()` — see v07 gotchas in `CLAUDE.md`):

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
worker-meta:
  volumes: !override
    - ./test-library:/mnt/raid1/media/music
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
`./test-library/<Artist> - <Album> - (<Year>)/` on the host, the `downloaded_tracks` row's
`file_path` was repointed, and `GET /api/tracks/{id}/file` still serves it afterward (v31 proved
this exact sequence — see `docs/GOTCHAS.md`'s v31 section).

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
backend service: `api`, `migrate`, `worker-dl`, `worker-meta` and `beat`. `app/config.py` then
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
docker compose stop api worker-meta worker-dl beat
docker compose run --rm --no-deps migrate sh -c "alembic downgrade base && alembic upgrade head"
docker compose up -d
```

**A fresh dev database means fresh `users` rows.** Every identity gets its row again on its first
successful login, and `is_admin` comes from the local `.env`'s `ADMIN_EMAIL` (a test account).
File-sourced proxies come back on `worker-meta`'s next boot through `sync_from_file()`. Manual
(UI-added) proxies, jobs and settings start empty.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Every container fails at startup with `failed to add the host <=> sandbox pair interfaces: operation not supported` (or any other veth/bridge networking error) | A kernel update landed via the package manager but the machine hasn't rebooted into it yet — the running kernel's module directory (including `veth`) has already been deleted from disk in favor of the new one | Compare `uname -r` against the installed kernel package version (`pacman -Q linux` on Arch) and check `/lib/modules/$(uname -r)/` exists; if it doesn't, reboot |
| `web` fails with `Bind for 127.0.0.1:5173 failed: port is already allocated`, even though nothing else is using that port | `docker-compose.override.yml`'s `ports:` list *merges* with `docker-compose.yml`'s instead of replacing it (list-type keys merge by default across compose files — `command`/`build` don't, so this is easy to miss), so `web` ends up with two host bindings to the same address | Confirmed fixed for `web` via the `!override` merge tag on its `ports:` key — if you add a *new* port mapping to any service in the override, check `docker compose config` for duplicates rather than assuming a plain list will replace the base file's |
| Stack was working, comes back broken after `docker compose down && up` with no config changes | Check `docker compose config` for the resolved service definitions before assuming it's a code regression — compose-file merge behavior is a common source of surprises that look like app bugs | |
| `migrate` exits at boot (and api/workers/beat never start, since they wait on it) with `SPOTDL_ENV=dev but DATABASE_URL points at the production database …` or `… can't be parsed` / `… names no database` (v32) | The local `.env`'s `DATABASE_URL` points at production's database, or is malformed. The dev guard refuses rather than risk production rows | Point `DATABASE_URL` at `spotdlwebtest` (see [Dedicated dev database](#dedicated-dev-database)). Never remove `SPOTDL_ENV` from the override to get past it |
| `migrate` fails at boot (api/workers/beat never start) with a `pydantic.ValidationError` naming `ADMIN_EMAIL` (v17+) | Either `ADMIN_EMAIL` is unset in `.env`, or it's set but not also present in `ALLOWED_EMAILS` — both are required at startup, by design | Add `ADMIN_EMAIL=you@example.com` to `.env` and make sure that same address is also in `ALLOWED_EMAILS` |
