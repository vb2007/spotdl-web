# v49 — Parallel Agent Stacks

Branch: `dev-parallel-stacks` → PR into `main`
Version: `5.49.0`
Wave / slot: **0 / 1. Serial: nothing else in master v5 starts until this is merged.**
Depends on: —

## Scope

Master v5 runs up to four implementation agents at once, each in its own worktree. Today that's
impossible:

- `docker-compose.yml` binds fixed host ports (`127.0.0.1:8000`, `127.0.0.1:5173`; the override
  rebinds `5173`).
- Every dev stack points at the one LAN database (`spotdlwebtest`), whose Alembic head every
  branch would move.
- Four `worker-dl`s would quadruple YouTube exposure from one IP.
- `check_version.py` accepts a version that goes *backwards*, which parallel merges make likely.

This slice builds the isolation. Per the owner's decision, each agent stack gets **its own
Postgres container on the local machine**, created and owned by the agent, with no dependency on
the LAN server.

Because v49 runs before the slot tooling exists, its own agent uses the default dev stack. Its
verification runs the new slot stacks it creates.

## Tasks

1. **Env-driven host ports and project name.**
   - `docker-compose.yml`: `"127.0.0.1:${API_PORT:-8000}:8000"`, `"127.0.0.1:${WEB_PORT:-5173}:80"`.
   - The override: `"127.0.0.1:${WEB_PORT:-5173}:5173"`.
   - The defaults keep today's behavior byte-for-byte for the owner and for production. Verify with
     `docker compose config` before and after (diff) for the dev and prod invocations.
   - Check every place that hardcodes `5173`/`8000` as a *host* port: the Vite config, the
     `FRONTEND_ORIGINS` default, `playwright.config.ts`'s `E2E_BASE_URL` default,
     `scripts/verify_separation_sse.sh`, and the docs. Each must follow the slot's env, while
     container-internal ports stay as they are.
2. **`docker-compose.agent.yml`, an opt-in overlay** applied *on top of* the dev override, never
   in production:
   - A `postgres` service on the **same major version as production**. Read it once via
     `SELECT version()` on the owner's `spotdlwebtest` with the existing dev credentials (read-only),
     and pin it. It gets a named volume, a healthcheck, and no host port by default (optional
     `PG_PORT` for `psql` from the host).
   - Every backend service's `DATABASE_URL` points at `postgres:5432/spotdlweb_s<slot>`, and
     `depends_on` the postgres healthcheck. `migrate` builds the schema on first up, as today.
   - `worker-dl` goes into a `realdl` profile, so it's **off unless explicitly requested**.
   - Redis, the downloads dir and the test library are already per-project or per-worktree
     (`./downloads` is relative to the worktree). Confirm this and document it.
   - Use `!override` wherever a list must replace (CLAUDE.md invariant), and verify with
     `docker compose config`.
3. **`scripts/agent_stack.sh <slot> <cmd>`**, the single entry point, with slots 1–4:
   - `env`: writes `.env.agent` in the worktree, derived from the worktree's `.env`:
     `COMPOSE_PROJECT_NAME=spotdlweb-s<slot>`, `API_PORT=800<slot>`, `WEB_PORT=517<3+slot>`,
     the slot DB URL, `SPOTDL_ENV=dev`, and `FRONTEND_ORIGINS` for the slot's web port. It never
     copies a production value. It refuses to run in a checkout whose `.env` names a production
     database.
   - `up`: `docker compose --env-file .env.agent -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.agent.yml up -d`, then waits for health.
   - `down [--volumes]`, `ps`, `logs`, `psql`, `e2e` (runs `npm run test:e2e` with
     `E2E_BASE_URL` set to the slot's web port), `pytest [args]` (runs the backend suite inside the
     slot's `api` container; v50 later points it at a throwaway test DB on the slot's Postgres).
   - `realdl <cmd…>`: takes `flock -n /tmp/spotdl-web-realdl.lock`, starts `worker-dl`, runs the
     given command, then stops `worker-dl` and releases the lock. If another slot holds it, fail
     with that slot's name (write the holder into the lock file).
   - It refuses an unknown slot, or a slot whose project is already running from a *different*
     worktree (compare the `com.docker.compose.project.working_dir` label).
4. **Real upstream login from a slot stack.**
   - Each slot's `.env.agent` keeps `UPSTREAM` pointing at the real `vb2007.hu-api`.
   - `ALLOWED_EMAILS`/`ADMIN_EMAIL` come from test identities only. Document a recipe that
     registers fresh per-slot test accounts (`v5s<slot>admin@…`, `v5s<slot>user@…`).
   - The e2e credentials file supports a per-slot override (`frontend/e2e/.env.e2e.s<slot>`,
     gitignored).
5. **A strictly-greater version check (ledger P9).** `check_version.py <base>` additionally fails when the
   branch version isn't semver-greater than the base's (stdlib tuple compare, keeping the script
   dependency-free). Add unit tests for the script (equal, lower, higher, patch bump).
6. **Docs.**
   - `docs/LOCAL_DEV.md`: a "Parallel agent stacks" section covering slots, ports, the local DB,
     the realdl lock, teardown, and resetting a slot DB (`down --volumes`).
   - `CLAUDE.md`'s dev-environment table gains an "Agent slot" column (editing lines, staying
     ≤250).
   - A GOTCHAS v49 entry.

## Files owned

`docker-compose.yml` (ports only), `docker-compose.override.yml` (ports only), new
`docker-compose.agent.yml`, new `scripts/agent_stack.sh`, `.env.dev.example`, `.gitignore`,
`frontend/playwright.config.ts`, `frontend/vite.config.ts` (only if a host port is hardcoded),
`backend/app/config.py` (`FRONTEND_ORIGINS` default only), `scripts/verify_separation_sse.sh`,
`.github/scripts/check_version.py` (plus its tests), `docs/LOCAL_DEV.md`, `CLAUDE.md`.

## Out of scope

- Any change to production compose behavior. `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` must be identical before and after.
- Running the owner's default stack against a local Postgres. The LAN `spotdlwebtest` stays theirs.
- CI changes beyond `check_version.py` (v50 handles pytest).

## Deploy notes

None. Production config output is unchanged (this is proven, not assumed).

## Done when

- [ ] `docker compose config` for the owner's default dev invocation and for the prod invocation
      are **byte-identical** before and after this branch (both diffs attached).
- [ ] **Two slot stacks run at once**, from two different worktrees (slots 1 and 2): both healthy
      (`agent_stack.sh <n> ps`), each reachable on its own web port in a real browser, each with
      a real upstream login.
- [ ] **Database isolation:** each slot's `migrate` built its own local DB. A throwaway migration
      applied on slot 1 doesn't exist on slot 2 (`alembic current` on both). A job created on slot
      1 is absent from slot 2.
- [ ] The v32 guard still refuses: pointing a slot's URL at a production name fails every backend
      service (log).
- [ ] `worker-dl` is absent from a slot stack by default (`ps`). `realdl` starts it, and a second
      concurrent `realdl` from the other slot fails with the holder's name (both terminals'
      output).
- [ ] `agent_stack.sh` refuses an unknown slot, a slot already running from another worktree, and
      a `.env` naming a production database (three runs).
- [ ] `agent_stack.sh <n> e2e` runs the full Playwright suite green against slot 1 **while slot 2
      is up**.
- [ ] `check_version.py` fails for an equal and a lower version, and passes for a higher one
      (script tests plus one real run against `origin/main`).
- [ ] Docs updated (diff). `CLAUDE.md` ≤ 250 lines. A GOTCHAS v49 entry and an index line.
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `5.49.0`. `uv lock` is in sync. `graphify update .` has been run.
