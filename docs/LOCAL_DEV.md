# Local development environment

This is the primary environment for day-to-day work: your own PC, Docker already installed,
fast iteration with hot reload. **The Debian production host (`docs/DEPLOYMENT.md`) is a
separate, final deployment target** — not where you debug a broken feature. Bouncing every
fix through a `git pull` + rebuild + SSH-log-check cycle on that box doesn't scale as a
develop loop; do that locally instead, and only touch the Debian host to verify a version is
genuinely ready to merge.

Postgres itself is never dockerized, never duplicated (locked decision) — both environments
reach the same physical instance on the Debian host over the network. **For now, both also
point at the same database.** Redis and every other container still run entirely locally and
are never shared with the deployed instance, regardless.

**This is no longer a hypothetical to "revisit later" — as of v22, real people are using the
deployed instance for real** (three real allowlisted users, real jobs, real downloaded files).
Anything you do locally — submitting a job, cancelling one, registering a test account — writes
to that same shared database. v22's own adversarial verification did exactly this (see
`docs/GOTCHAS.md`'s v22 section): local test-job creation showed up in the real deployed admin's
job list under a distinct test-account owner, harmless because ownership scoping keeps it out of
the admin's own view, but real rows in the real table nonetheless. Prefer a dedicated test
identity (never the real `ADMIN_EMAIL` account) for anything exploratory, and switch to a
dedicated disposable `spotdl_web_dev` database (§ "Once there's real data worth protecting"
below) the next time this gets in the way rather than continuing to defer it.

---

## 1. Configure `.env`

```bash
cp .env.dev.example .env
```

Fill in the real Postgres password (same role/database the Debian host uses — see
`docs/DEPLOYMENT.md` for how that was created) and `ADMIN_EMAIL` (v17+ — must also appear in
`ALLOWED_EMAILS`, or the `api`/`worker-dl`/`worker-meta`/`beat` containers all crash-loop at
boot). Everything else in `.env.dev.example` is already dev-appropriate out of the box —
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
correctness depends specifically on nginx behavior (an `internal` location, `X-Accel-Redirect`,
a new `location` block) can't be exercised through this stack at all; it silently no-ops instead
of erroring (see `docs/GOTCHAS.md`'s v27 entry for the concrete symptom this caused). Verifying
that kind of change needs `docker compose -f docker-compose.yml up` (bypassing the override) or
the deployed host instead.

## 3. Verify

```bash
curl -s http://localhost:8000/api/health
```

Ports bound to `127.0.0.1` is fine and expected here too — this is your own machine, nothing
about the Cloudflare-Tunnel-only ingress rule changes; it just happens to not matter locally
since nothing here is reachable from anywhere else regardless.

## 4. Seeding a second user for multi-user testing (v17+)

Add a second address to `ALLOWED_EMAILS` (comma-separated, `ADMIN_EMAIL` stays whichever one
should be the operator) and recreate `api`:

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

## 5. When a version is ready

Push the branch and open/update the PR as usual. Before merging, do one final check on the
real target per `docs/DEPLOYMENT.md` — that's the only remaining reason to touch the Debian
host mid-development, and it should be a confirmation, not a debugging session.

## Once there's real data worth protecting

Switch `DATABASE_URL` in the local `.env` to a dedicated `spotdl_web_dev` database (create it
with the same `CREATE ROLE`/`CREATE DATABASE` pattern as `docs/DEPLOYMENT.md` §2, on the Debian
host) so local runs stop touching the deployed instance's data. Everything else about this
workflow stays the same.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Every container fails at startup with `failed to add the host <=> sandbox pair interfaces: operation not supported` (or any other veth/bridge networking error) | A kernel update landed via the package manager but the machine hasn't rebooted into it yet — the running kernel's module directory (including `veth`) has already been deleted from disk in favor of the new one | Compare `uname -r` against the installed kernel package version (`pacman -Q linux` on Arch) and check `/lib/modules/$(uname -r)/` exists; if it doesn't, reboot |
| `web` fails with `Bind for 127.0.0.1:5173 failed: port is already allocated`, even though nothing else is using that port | `docker-compose.override.yml`'s `ports:` list *merges* with `docker-compose.yml`'s instead of replacing it (list-type keys merge by default across compose files — `command`/`build` don't, so this is easy to miss), so `web` ends up with two host bindings to the same address | Confirmed fixed for `web` via the `!override` merge tag on its `ports:` key — if you add a *new* port mapping to any service in the override, check `docker compose config` for duplicates rather than assuming a plain list will replace the base file's |
| Stack was working, comes back broken after `docker compose down && up` with no config changes | Check `docker compose config` for the resolved service definitions before assuming it's a code regression — compose-file merge behavior is a common source of surprises that look like app bugs | |
| `api`/`worker-dl`/`worker-meta`/`beat` all crash-loop at boot with a `pydantic.ValidationError` naming `ADMIN_EMAIL` (v17+) | Either `ADMIN_EMAIL` is unset in `.env`, or it's set but not also present in `ALLOWED_EMAILS` — both are required at startup, by design | Add `ADMIN_EMAIL=you@example.com` to `.env` and make sure that same address is also in `ALLOWED_EMAILS` |
