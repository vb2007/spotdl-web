# v33 — Deploy Safety

Branch: `dev-deploy-safety` → PR into `main`
Version: **no bump**. This slice touches only `.github/`, root files and docs, never `backend/` or
`frontend/`. CI's `version` job (`check_version.py`) is path-aware and doesn't require a bump, and
`release.yml`/`publish-deploy.yml` correctly skip cutting a release for it. If implementation finds
it *must* touch `backend/` or `frontend/`, bump both to `4.33.0` and say why in the PR.

## Scope

Fix every link in the chain that failed on 2026-09-27 (`00-master-plan.md`, "The pipeline
incident"):

1. a new required variable failing the deploy,
2. the rollback failing identically,
3. the rollback target being a stale throwaway tag,
4. a rollback that can't work across a migration, and
5. nobody being told.

## Tasks

All in `.github/workflows/publish-deploy.yml` unless noted.

1. **Required-variable preflight, before any host mutation.**
   - Today the deploy step checks out the new commit (`:241-251`) and writes `IMAGE_TAG`
     (`:253-257`) *before* `pull` discovers a missing variable.
   - Add a step **before the backup and before checkout**. It reads the new commit's compose files
     without moving the deploy checkout (`git -C "$DEPLOY_DIR" fetch` then
     `git show <sha>:docker-compose.yml` / `:docker-compose.prod.yml` into a temp directory), and
     validates them against the host's real `.env`, for example with
     `docker compose --env-file "$DEPLOY_DIR/.env" -f … config --quiet`, or by extracting every
     `${VAR:?…}` and checking each key.
   - Either way, fail with a message listing **each missing variable by name** plus
     "add to `$DEPLOY_DIR/.env`, see docs/DEPLOYMENT.md".
   - The step must not print `.env` values, and `config` output can contain secrets: never echo
     it.
2. **Rollback restores the previous commit and tag together.**
   - Record the deploy checkout's current commit alongside the previous tag, before anything
     moves.
   - On failure, `git checkout --detach --force <prev-commit>` and `git reset --hard`, then restore
     `IMAGE_TAG`, then `up -d --no-build`.
   - The health wait during rollback uses **the previous commit's**
     `.github/scripts/wait_for_stack_health.sh`, since its compose files are the ones in effect.
3. **Durable last-known-good.**
   - After the health gate passes **and** `persist == 'true'`, write `$DEPLOY_DIR/.last-good`
     (tag plus commit).
   - Add it to `.gitignore`, because `git clean -fd` at `:251` deletes untracked, unignored files
     (the `/backups/` precedent).
   - The "previous" step reads `.last-good`, falling back to `.env` only when it doesn't exist
     yet (the first deploy after this lands). A `manual-*` (`persist=false`) deploy never updates
     it, so a throwaway dispatch tag can't become the rollback baseline.
4. **Migration guard on rollback.**
   - Before rolling back, compare the database's current revision with the rollback image's
     Alembic heads, e.g. `docker compose run --rm migrate alembic current` against
     `alembic heads` in the previous image.
   - If the database is ahead, **don't start the old stack**. Fail with an explicit "restore the
     pre-deploy pg_backup at <path> or roll forward" message, plus the notification. The
     pre-deploy backup path from `:233-235` must be printed so the human has it.
5. **Matrix notification.**
   - A final `notify` job, `needs: [resolve, publish, deploy]`, with
     `if: always() && (contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled'))`.
   - It `curl`s the Matrix client-server API:
     `PUT {homeserver}/_matrix/client/v3/rooms/{room}/send/m.room.message/{txn}`, with the
     `Authorization: Bearer` access token and `txn` = the run id plus the attempt number
     (idempotent on re-run).
   - Message: workflow, run URL, which job failed, release tag, and whether rollback succeeded.
     Never `.env` content.
   - Secrets: `MATRIX_HOMESERVER_URL`, `MATRIX_ACCESS_TOKEN`, `MATRIX_ROOM_ID` (repository
     secrets). If they're unset, the job prints a warning and exits 0. A missing alert config must
     not turn a green deploy red.
   - Add the same `notify` to `release.yml`. Today a release failure skips `resolve`, so it's
     silent too.
   - Also send one success message per *real* (`persist=true`) deploy, so silence means "nothing
     happened", never "maybe it failed".
6. **Harden the summary and health script.**
   - Guard `publish-deploy.yml:300`'s `compose ps` with `|| true`.
   - Review the `|| true`s in `wait_for_stack_health.sh` (`:29,34,39`): they currently swallow
     compose errors, so an interpolation failure reads as "not healthy yet" and waits out the
     timeout. Fail fast on a compose *error*, and keep waiting on not-yet-healthy.
7. **CI drift check** (`ci.yml` `compose-config`).
   - Add a step that extracts every `${VAR:?` name from both compose files and asserts each has a
     key in `.env.example`. Do the same for `.env.dev.example` against the dev override if it
     uses any.
   - Prove the check works: on a scratch commit, add a throwaway `${V33_PROBE:?x}` and show CI
     failing. That commit is not merged.
   - Fix the stale comment at `ci.yml:355-361`.
8. **Docs.**
   - `docs/RELEASE_PIPELINE.md`: the deploy steps, rollback semantics, `.last-good`, notification
     secrets, and the "a new required variable" procedure.
   - `docs/DEPLOYMENT.md` "Rollback / recovery": the manual recovery for the migration-ahead case.
   - A short "adding a required env var" checklist in `docs/RELEASE_PIPELINE.md`, linked from
     `CLAUDE.md`'s workflow rules line on versioning. A plan that adds a `:?` variable must list
     it under its own "Deploy notes".
9. **Matrix bot setup (owner, with agent instructions).** Document in `docs/DEPLOYMENT.md` how to
   create the bot user on the host's Synapse, create the room, invite the bot, and get the access
   token and room id. The agent writes the instructions; the owner runs them, because they touch
   the production Synapse.

## Out of scope

- App-level alerts (v36), which reuse the same room and bot but are separate code.
- Blue/green or zero-downtime deploys.
- Auto-restoring `pg_backup`. Restore stays a deliberate human action.

## Deploy notes

No new `.env` variable. Three new **repository secrets** (`MATRIX_*`), which the owner adds.

## Done when

Every bullet is evidenced on the **real self-hosted runner**. Use `workflow_dispatch` with
`persist=false` where possible, so production's baseline isn't disturbed. Batch any host-side
check into as few SSH round trips as possible.

- [ ] **Preflight blocks a missing variable before mutation.** On a scratch branch dispatch, add a
      throwaway `${V33_PROBE:?…}` to the prod compose file. The run fails in the preflight step,
      naming `V33_PROBE`. Afterwards, the host's deploy checkout commit and `.env` `IMAGE_TAG` are
      unchanged (show both before and after).
- [ ] **Rollback restores commit and tag together.** Force a health failure on a scratch dispatch
      (for example a deliberately bad healthcheck). The rollback leaves `DEPLOY_DIR` at the
      previous commit and `IMAGE_TAG` at the previous tag, and the stack is healthy (show
      `git rev-parse HEAD`, the `.env` line, and `compose ps`).
- [ ] **`.last-good` is written only on a healthy `persist=true` deploy.** It doesn't change after
      a `manual-*` dispatch or after a failed run (show its content across runs).
- [ ] **The migration guard stops a doomed rollback.** Simulate a database ahead of the rollback
      image. This may be done on the local stack with the dev database, by running the guard
      script directly: show it refusing and printing the backup path.
- [ ] **A Matrix message arrives** for a failed run, for a successful real deploy, and for a
      `release.yml` failure (screenshot or room export). The notify job exits 0 with secrets unset
      (a run with the secrets temporarily removed, or a fork).
- [ ] **The CI drift check fails on a missing `.env.example` key** (the scratch PR's red run
      linked) and passes on `main`'s files.
- [ ] `wait_for_stack_health.sh` fails fast on a compose interpolation error, instead of timing
      out (local run output).
- [ ] No step prints secret values: grep the logs of every run above for the password and token.
- [ ] Docs updated (diff). `graphify update .` has been run.
