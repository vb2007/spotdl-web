# v51 — pytest on Real Postgres

Branch: `dev-pytest-postgres` → PR into `main`
Version: `5.51.0`
Wave / slot: 1 / 1
Depends on: v50

## Scope

Ledger items **P10** and **D8**.

Every backend test runs on in-memory SQLite (`ci.yml:101-103`). SQLite ignores `FOR UPDATE`, has
no native enums, and compares differently. Several fixed races are therefore "proven" only by
asserting that a lock was *requested* (GOTCHAS:4535, D8). Wave 2 (v55–v57) is mostly race fixes.
They need a real database to prove anything. This slice makes Postgres the test database,
in CI and locally.

## Tasks

1. **The CI `pytest` job gets a Postgres service container**, on the same major version as
   production (v50 pins it). It runs on the self-hosted runner, which has Docker.
   - Use a job-scoped container with **no fixed host port**, so concurrent CI jobs can't collide.
   - Before adding it, check the runner's Docker setup (#71's job-private `DOCKER_CONFIG`).
     Document what's needed in `docs/CI_SELF_HOSTED_RUNNER.md`.
2. **conftest.**
   - A session-scoped database created per test run (a unique name, dropped at the end).
   - Schema built by **Alembic `upgrade head`**, not `create_all`, so migrations are exercised on
     every run.
   - Per-test isolation by transaction rollback (or truncate where a test commits across
     connections on purpose).
   - Read `TEST_DATABASE_URL` from env. Locally it defaults to the agent slot's Postgres
     (`agent_stack.sh <n> pytest` helper).
   - Running pytest against a database whose name lacks a `test` marker, or matches a production
     name, is refused, reusing v32's guard logic.
3. **Race helpers** (`backend/tests/concurrency.py`): run two real sessions or threads that
   interleave at named points (a barrier, or an injectable hook), so a test can reproduce
   "B commits between A's read and A's write" deterministically.
4. **Port the hollow tests.**
   - Every test that today asserts only "`with_for_update` was requested" or skips an enum
     comparison gets a real-concurrency version: `cancel_job` lock, the v34.1 cancel race, the
     v35(c) redelivery gate, and enum casts.
   - List every converted test in the PR.
   - Keep each existing assertion unless it's meaningless on Postgres; justify any deletion.
5. **Deterministic speed.** If the suite now takes markedly longer, mark the slow concurrency
   tests, and keep the default run under a documented budget. **Don't skip anything in CI.**
6. Remove the SQLite engine path from conftest, or keep it only behind an explicit flag nobody's
   default uses. Record the decision.

## Files owned

`scripts/agent_stack.sh` (the `pytest` subcommand only), `backend/tests/conftest.py`, new `backend/tests/concurrency.py`, the converted tests in
`backend/tests/` (list them in the PR), `.github/workflows/ci.yml` (the `pytest` job only),
`backend/pyproject.toml` (test deps), `docs/CI_SELF_HOSTED_RUNNER.md`, `docs/LOCAL_DEV.md` (the
pytest paragraph).

## Out of scope

Fixing any race this exposes. That's v55/v56/v57. Record it as a failing `xfail(strict=True)` test
naming the owning slice, so the owning slice turns it green.

## Done when

- [ ] CI `pytest` runs on Postgres: the job log shows the service container and Alembic
      `upgrade head`, and the suite is green.
- [ ] Locally, `agent_stack.sh <n> pytest` runs the full suite against the slot's Postgres while
      another slot runs its own suite at the same time, with no interference (both outputs).
- [ ] The safety refusal: pytest against a production-named or non-`test` database refuses
      (output).
- [ ] At least the four named hollow tests (`cancel_job` lock, the v34.1 cancel race, the v35(c)
      gate, enum casts) now reproduce their race with the concurrency helper. Each **fails** when
      the guarding code is reverted locally (shown), and passes with it.
- [ ] Any newly exposed race is an `xfail(strict=True)` naming its owning slice (listed in the
      PR), or there are none.
- [ ] Suite duration before and after is recorded, within the documented budget.
- [ ] `npm run lint`, `npm run check` and `npm run build` pass. Both version files read `5.51.0`.
      `uv lock` is in sync. `graphify update .` has been run.
