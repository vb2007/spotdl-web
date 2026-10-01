# v32 — Dedicated Dev Database

Branch: `dev-dev-database` → PR into `main`
Version: `4.32.0`

## Scope

Local dev and the deployed instance currently share one database (`spotdl_web`). v22 predicted
this would hurt once real data existed. v31 proved it: local `worker-meta`'s boot-time
`reconcile_disk()` pruned a **real production** `downloaded_tracks` row, because the file it
pointed at only exists on the deployed instance's downloads volume (`docs/GOTCHAS.md` v31 section).
CLAUDE.md marks the split as overdue: "do it at the start of the next version that touches the
backend, before anything else".

This version does that, and makes it a rule. **From v32 on, every implementation agent must run
the local stack against the dev database.**

## Division of work

- **The owner (before the agent starts):** creates an empty `spotdl_web_dev` database on the
  existing Postgres server, owned by or granted to a role the local stack can use, and puts the
  real `DATABASE_URL` into the local `.env`. The agent never creates databases or roles, and never
  needs Postgres superuser credentials.
- **The agent:** everything else, below.

If `.env` still points at `spotdl_web` when the agent starts, **stop and ask**. Don't edit the
owner's `.env` to guess a URL.

## Tasks

1. **Build the schema through the app's own path.** Bring up the stack. The one-shot `migrate`
   service runs `alembic upgrade head` against the new empty database. Don't hand-write
   `CREATE TABLE`s, and don't run a dump of production into dev: the dev database starts empty on
   purpose, and nothing from production is copied into it.
2. **Fail-closed guard.** Local dev must refuse to boot `api`, `worker-meta`, `worker-dl`, `beat`
   and `migrate` against the production database:
   - `docker-compose.override.yml` (dev only, never prod) sets an explicit marker, e.g.
     `SPOTDL_ENV=dev`, on every backend service.
   - `backend/app/config.py` validates at startup: when the marker says dev, the database name
     parsed from `DATABASE_URL` must not be the production name. The production name is a single
     constant or setting, never inferred.
   - The guard must also cover the `migrate` service and Alembic's own `env.py` path. A migration
     run against production from a laptop is the worst version of this mistake.
   - **Fail closed:** if the URL can't be parsed, the service refuses to start. The error message
     names the fix ("point `DATABASE_URL` at `spotdl_web_dev`, see `docs/LOCAL_DEV.md`").
   - Production is unaffected: the marker is absent there, and prod's own `.env` is untouched.
3. **Templates and docs.**
   - `.env.dev.example`: `DATABASE_URL` points at `spotdl_web_dev`, with a comment saying why.
   - `docs/LOCAL_DEV.md`: rewrite the "shared database" section as "dedicated dev database". Cover
     what the owner creates, how the schema gets built, how to reset it (drop and recreate, then
     let `migrate` rebuild it), and that a fresh dev DB means fresh users rows on first login.
   - CLAUDE.md's "Development environments": replace the shared-DB paragraph and table row with
     the split, stated as a rule, not a warning.
   - `docs/GOTCHAS.md`: a v32 entry, and correct the v31 entry in place with a dated note.
4. **Re-seed what local testing needs**, using the app's own flows only:
   - Log in a fresh test identity through the **real upstream** `vb2007.hu-api`, and a second one
     for cross-user checks.
   - The admin identity on dev comes from the local `.env`'s `ADMIN_EMAIL`. Use a test account,
     **never** the owner's real admin email.
   - Re-add any local proxies through the existing sync path.
5. **Downgrade round-trip.** Now that a disposable database exists, run
   `alembic downgrade base && alembic upgrade head` once on it. This was never safe to do before.
   Record any migration whose `downgrade()` is broken as a GOTCHAS finding (fix it here only if it's
   a one-line enum `DROP TYPE` omission. Anything larger is a follow-up).

## Out of scope

- Any change to production's database, `.env` or compose files.
- Copying or anonymizing production data into dev.
- A CI database. CI's pytest already uses its own Postgres service.

## Done when

- [ ] Local `docker compose up` succeeds against the empty `spotdl_web_dev`, and `migrate` exits 0
      (log line), with `alembic current` at head.
- [ ] **Isolation proven by observation:** create a job locally, then show with a read-only query
      against production's `spotdl_web` that its id doesn't exist there. Show the reverse for a
      production job id.
- [ ] A local `worker-meta` restart's reconciliation log shows it checked **dev** ledger rows
      (count matching dev, not production). The production `downloaded_tracks` count is unchanged
      before and after (read-only count).
- [ ] The guard refuses to start: temporarily point local `DATABASE_URL` at `spotdl_web`, and every
      backend service and `migrate` exit non-zero with the explanatory message. Show the log, then
      restore. Show an unparseable URL also refusing.
- [ ] The production compose invocation (`docker compose -f docker-compose.yml -f
      docker-compose.prod.yml config`) carries no dev marker (`config` output grep).
- [ ] At least one test identity logged in through the real upstream `vb2007.hu-api`. A second
      identity exists for later cross-user work.
- [ ] `alembic downgrade base` followed by `upgrade head` completes on dev, or each broken
      downgrade is recorded in GOTCHAS.
- [ ] Unit tests cover the guard: the dev marker plus the prod name refuses, the dev marker plus
      the dev name passes, no marker plus the prod name passes (prod), and an unparseable URL
      refuses.
- [ ] `.env.dev.example`, `docs/LOCAL_DEV.md`, CLAUDE.md and GOTCHAS updated (diff).
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `4.32.0`. `uv lock` is in sync. `graphify update .` has been run.
