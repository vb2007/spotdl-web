# v59 — Pipeline Resilience, Persistent Logs & Docs Drift

Branch: `dev-pipeline-resilience` → PR into `main`
Version: **no bump.** The slice touches `.github/`, compose logging, scripts and docs, never
`backend/` or `frontend/`. If it must touch either, bump both to `5.59.0` and say why.
Wave / slot: 3 / 2
Depends on: wave 2 merged

## Scope

Ledger items **P1–P8**, **O3** and **X1–X4**. The v33 pipeline works, but its failure paths still
have holes:

- a GitHub 429 killed a deploy *and* its notice together;
- the single self-hosted runner sometimes never acquires the daily cron;
- logs vanish on every deploy, which is why O1 couldn't be root-caused.

The docs also still describe older realities.

## Items

- **P1: a 429-proof failure notice.**
  - `notify` in `publish-deploy.yml:656` and `release.yml:130` starts with `actions/checkout`. If
    the action download fails, nothing is sent.
  - Rewrite `notify` to need **no action download**: an inline `run:` step using `curl` with the
    secrets, and no `uses:`.
  - Also add a last-resort notice inside the `deploy` job itself (an `if: failure()` step, again
    `curl`-only), so a job that dies early still reports.
  - Prove it by making `actions/checkout` unavailable in a scratch dispatch (e.g. a deliberately
    invalid action ref in a scratch workflow copy). The notice still arrives.
- **P2: runner starvation of scheduled CI.**
  - The daily `17 4 * * *` jobs sometimes get "not acquired by Runner".
  - Diagnose from the runner's own logs on the host, in **one batched SSH round trip**. Likely
    causes: the runner is busy, or offline during a host task.
  - Fix it: move the cron off the host's busy window, add `concurrency`, and/or a lightweight
    re-dispatch on "not acquired". Make sure a cancelled-for-acquisition run notifies differently
    from a real failure.
- **P3:** a release changing `networks:` hits `guard-error` with no automatic rollback. Reproduce
  it in a scratch dispatch (`persist=false`). Either handle it or fail with an exact recovery
  message.
- **P4:** verify whether the `cancelled()` rollback path runs after a `timeout-minutes` cut, with a
  scratch dispatch using a tiny timeout. Fix if not.
- **P5:** the health gate retries a transient dockerd error (bounded, e.g. 3× with backoff) before
  failing.
- **P6:** `wait_for_stack_health.sh` redacts compose stderr on its error path (no `.env` value or
  URL credential printed).
- **P7:** a dispatch from a pre-v33 workflow copy deletes `.last-good`. Guard it: `.last-good` is
  written atomically, and a run whose workflow lacks the v33 marker refuses to touch it.
- **P8:** the pre-deploy health probe gets a real timeout, so a slow-but-healthy stack doesn't
  disable the fallback.
- **O3: logs survive deploys.**
  - Production containers log to the host's **journald** (`logging: driver: journald` with a
    `tag`), or to a persisted json-file location. Pick journald if the host uses it; the
    retention policy goes in `docs/DEPLOYMENT.md`.
  - Dev keeps json-file.
  - Only `docker-compose.prod.yml` changes. Verify with `config`, and in the first real deploy
    (owner-run or the next merge).
  - Provide a `scripts/prod_logs.sh` that reads the last N hours across a restart.
- **X1:** `README.md`: current status (masters v1–v4 complete, v5 in progress), what the app is,
  links to the docs. It points at `plan/master-v5/` and must not repeat CLAUDE.md.
- **X2:** `docs/GOTCHAS.md`: fix the title and caveat (it covers v01–v68+). The index stays.
- **X3:** `.env.example:10` and `docs/DEPLOYMENT.md` (`:562-587`, backup filenames `:365,374,795`)
  use the real production DB name `spotdlweb`. Check against the host `.env`'s **name only**, in
  the same batched SSH trip as P2.
- **X4:** `docs/DEPLOYMENT.md`'s "adding a required env var" callout is made prominent and linked
  from `docs/RELEASE_PIPELINE.md`'s checklist.

## Files owned

`.github/workflows/{publish-deploy,release,ci}.yml`, `.github/scripts/*` (except
`check_version.py`, which v49 and v60 own), `docker-compose.prod.yml` (logging only), new
`scripts/prod_logs.sh`, `README.md`, `docs/{GOTCHAS,DEPLOYMENT,RELEASE_PIPELINE,CI_SELF_HOSTED_RUNNER}.md`,
`.env.example`.

## Out of scope

Alert delivery inside the app (v58). Extension workflows (v60, which adds its own workflow file;
coordinate via separate files).

## Deploy notes

The production logging driver changes on the next deploy. Old json-file logs from before it
aren't migrated.

## Done when

- [ ] **P1:** a scratch dispatch whose checkout step is made to fail still delivers the Matrix
      notice (run link plus room screenshot). `notify` contains no `uses:` (grep).
- [ ] **P2:** the root cause is recorded (runner log excerpt from the single SSH trip) and the fix
      is in place. A forced "not acquired" (runner stopped briefly during a scheduled test
      dispatch) produces the distinct notice, or a re-dispatch.
- [ ] **P3/P4/P5/P7/P8:** each reproduced in a `persist=false` scratch dispatch (or locally, for
      script-only items) before and after. Every run is linked.
- [ ] **P6:** forcing the error path with a credential-bearing compose error prints it redacted
      (local script run).
- [ ] **O3:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` shows the
      new driver for every service. After the next real deploy, `scripts/prod_logs.sh` shows lines
      from **before** that deploy (one batched SSH check, or the owner runs it).
- [ ] **X1–X4:** diffs. `README.md` status matches `CLAUDE.md`. No `spotdl_web` remains as a
      production name in `.env.example`/`DEPLOYMENT.md` (grep).
- [ ] No secret printed in any run log above (grep for the token and password).
- [ ] `check_version.py origin/main` passes without a bump. `graphify update .` has been run.
