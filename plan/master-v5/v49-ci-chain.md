# v49 — CI Workflow Chain: Run Only What Has Work to Do

Branch: `dev-ci-chain` → PR into `main`
Version: **no bump.** The slice touches only `.github/` and docs, never `backend/` or `frontend/`.
If it must touch either, bump both to `5.49.0` and say why.
Wave / slot: **0, alongside v50. No slot and no local stack** (v50 holds the default dev stack).
**Merged first** in master v5.
Depends on: —

## Scope

Ledger items **P1** and **P11–P14**. The owner's ask: workflows are called and run only when
they're actually ready to run, and the run list is no longer filled with cancelled or never-ran
runs. This comes first, so that every later v5 slice (twenty merges, four PRs at a time) runs on a
clean pipeline.

Today's chain (`docs/RELEASE_PIPELINE.md`) is CI → `workflow_run` → Release → `workflow_run` →
Publish & Deploy:

- **P11:**
  - `release.yml:18` fires on **every** CI completion: PR, schedule, dispatch or push. Its job
    `if:` (`:39`) then skips everything but a successful push to `main`.
  - A skipped Release still "completes", so `publish-deploy.yml:16` fires and skips too (`:44`).
  - Of the last 1000 runs, Release has **160 skipped of 212**, and Publish & Deploy **158 skipped
    of 228**.
- **P12:** "Deploy checks" (`deploy-checks.yml`, folded into `ci.yml` long ago; last run
  2026-08-04) and "Backend tests" still show in the Actions sidebar, because their old runs keep
  them alive.
- **P13:** `ci.yml:26-28` (`cancel-in-progress: true`, grouped by ref) applies to `main` as well,
  so a second merge cancels the first merge's run, release included. Master v5's owner merges
  whole waves in a row, so this will happen.
- **P14:** the `17 4 * * *` schedule (`ci.yml:23`) re-runs the whole suite on unchanged `main`
  every day, starting about 5 hours late. Only `yt-dlp-freshness` (`ci.yml:243`) needs a schedule.
  Each scheduled run also spawns the two empty runs above.
- **P1:** `notify` starts with `actions/checkout` (`publish-deploy.yml:656`, `release.yml:130`), so
  a GitHub 429 on the action download killed a deploy *and* its notice (run 38581543804; 4.40.2
  sat undeployed for about 30h). The notify jobs get rewritten here anyway.

Facts to design around:
- There is **one self-hosted runner** (`vbServer`), and a CI run takes 4–9 minutes.
- `workflow_run` was originally chosen (`release.yml:7-13`) to avoid both racing CI and needing a
  personal access token. Calling reusable workflows (`workflow_call`) **from the same run** solves
  both: `needs:` orders the jobs, and `GITHUB_TOKEN` is enough.

**Owner decision (2026-10-23):** besides fixing this going forward, delete the existing noise
from the run history. Real runs (success, failure, cancelled) of live workflows are always kept.

## Target layout

**There is no `workflow_run` anywhere.** Every run in the list is a run that does something.

| Event | Workflow (run name) | Runs |
|---|---|---|
| `pull_request` | `ci.yml` **"CI"** | The checks only: `version`, `pytest`, `deps-sync`, `compose-config`, `frontend`, `summary`. Triggers: `pull_request`, `workflow_dispatch`, `workflow_call`. No `push`, no `schedule` |
| `push` to `main` | new `release-deploy.yml` **"Release & Deploy"** | `checks` (`uses: ./.github/workflows/ci.yml`) → `plan` (reads the version and decides whether its tag still has to be cut) → `release` (`uses: release.yml`, only when due) → `deploy` (`uses: publish-deploy.yml`, only after a release) → `notify` (curl-only, on any failed job) |
| `schedule` | new `nightly.yml` **"Nightly"** | `yt-dlp-freshness`, moved over unchanged with its notice. `workflow_dispatch` too |
| manual | `release.yml`, `publish-deploy.yml` | Both remain `workflow_dispatch`-able. Publish & Deploy's "deploy any branch/tag/commit" path (`manual-<sha>` tag, never `latest`, no persist) behaves **exactly** as today |

A docs-only merge produces **one** run: the checks pass, and the `release` and `deploy` *jobs*
show as skipped inside that run. No other workflow run is created.

## Tasks

1. **Turn `release.yml` and `publish-deploy.yml` into callable workflows.**
   - Replace their `workflow_run` triggers with `workflow_call`, with typed inputs: the commit SHA
     to release or deploy, and for the deploy, the tag the release job cut.
   - Remove every `github.event.workflow_run.*` read, the `head_sha` checkout trick and the
     "latest release" lookup (`gh release view`) in the merge path. The caller passes the exact
     commit and tag.
   - The caller job grants `permissions: contents: write, packages: write` and passes
     `secrets: inherit`.
   - Rewrite every comment that justifies `workflow_run` (`release.yml:7-16`,
     `publish-deploy.yml:3-14`) to the new rationale.
2. **`release-deploy.yml`.**
   - `on: push: branches: [main]` plus `workflow_dispatch` (a re-run of the whole chain on `main`).
   - The `plan` job outputs `release` (`true` when `v<version>` has no tag yet). v61 later adds an
     `extension` output to it. Keep the job small and readable.
   - `deploy` keeps the persist/`.last-good` semantics of today's merge-driven path.
3. **No cancelling, no stale deploys.**
   - Remove `cancel-in-progress` for runs on `main`, and don't put it on PR runs either. Every PR
     push gets one complete run. The implementation prompt now requires batched pushes, so the
     queue on the one runner stays short.
   - The deploy must never race a manual Publish & Deploy dispatch, and must never deploy an older
     version over a newer one. Do this **without a cancelling construct**:
     - a deploy whose version is lower than the persisted production baseline ends as a
       **successful no-op**, with one line in the job summary;
     - if you keep a `deploy-prod` concurrency group, check in the burst test (below) whether
       GitHub's rule of one pending run per group cancels anything. If it does, drop the group, and
       rely on the single runner plus the version guard.
     - Record the outcome in GOTCHAS.
4. **Notify (P1).**
   - Every notify job is a single `run:` step using `curl` against the Matrix API with the existing
     secrets. **No `uses:`, no checkout.** If it needs `matrix_notify.py`'s formatting, inline the
     minimum in shell.
   - One `notify` at the end of "Release & Deploy" covers a failure in any of its jobs and names
     the failed job. The manual Publish & Deploy and "Nightly" keep their own.
   - A notice never prints a secret (grep the run logs).
5. **Required status checks.**
   - Read `main`'s branch protection (`gh api repos/vb2007/spotdl-web/branches/main/protection`,
     read-only).
   - The check names a PR needs must still be produced by "CI" under the same names. If a name has
     to change, stop and ask the owner to update the protection. Record which of the two happened.
6. **History cleanup** (owner-approved):
   - Before deleting, put in the PR the count of each class: Release/`skipped`, Publish &
     Deploy/`skipped`, "Deploy checks"/all, "Backend tests"/all.
   - Delete them: list run ids via `gh api --paginate repos/vb2007/spotdl-web/actions/workflows/<id>/runs`,
     filtered by `conclusion == "skipped"` (or every run, for the two leftover workflows), then
     `gh api -X DELETE repos/vb2007/spotdl-web/actions/runs/<id>`.
   - **Never** delete a success, failure or cancelled run of a live workflow. The filter is
     printed and reviewed before the delete loop runs.
   - Afterwards, re-count. `gh workflow list --all` no longer shows "Deploy checks" or "Backend
     tests". If one still shows with zero runs, disable it (`gh workflow disable`) and say so.
7. **Docs and knowledge.**
   - `docs/RELEASE_PIPELINE.md`: the new chain diagram, the trigger and run per event, why it
     calls workflows in-run instead of chaining them, how to deploy a branch manually, and how
     to re-run a failed release.
   - `docs/CI_SELF_HOSTED_RUNNER.md`: what queues on the one runner, and why nothing cancels.
   - A GOTCHAS **v49** entry with its index line. The rule: **never chain workflows through
     `workflow_run`.** It fires on every completion and leaves a skipped run behind, and a skipped
     run completes too, so the next link fires as well.
   - `CLAUDE.md`'s CI locked decision gains "chained in-run, no `workflow_run`". Edit that line
     only, staying ≤250 lines.

## Verifying without touching production

The real chain only runs on a `main` push, and the deploy targets production. So the agent proves
the behavior on a scratch copy instead:

- **Branch `ci-chain-scratch`**, holding copies of the new workflows:
  - `push` limited to that branch, and `pull_request` limited to PRs from it;
  - the GHCR push, the host deploy and `.last-good` are replaced by **stubs that echo their
    inputs** (nothing reaches production);
  - notify points at the **dev** Matrix room (a repository-variable override, never the
    production room).
- Run this matrix, attaching `gh run list --branch ci-chain-scratch --json
  workflowName,event,conclusion,createdAt` after each step:
  1. **PR:** a draft PR from the scratch branch, then 2 pushes. Exactly 2 "CI" runs, both
     `success`. No Release, no Publish & Deploy, and nothing cancelled.
  2. **Burst:** 3 pushes within a minute, each bumping a scratch version. Exactly 3 "Release &
     Deploy" runs, all `success`, none cancelled or skipped. The stub deploys ran in push order,
     or the version guard turned a stale one into a no-op (job summary shown).
  3. **Docs-only push:** 1 run. The checks ran, and release and deploy are skipped *jobs*.
     No other run exists.
  4. **Failing check:** a deliberately failing test. No release job runs, and the dev-room notice
     arrives naming the job (screenshot).
  5. **Unavailable checkout:** an invalid action ref in a scratch job makes it fail. The notice
     still arrives.
- Afterwards, close the scratch PR, delete the branch, and delete the scratch runs (list them
  first). The scratch work never reaches `main`.

## Files owned

`.github/workflows/{ci,release,publish-deploy}.yml`, new
`.github/workflows/{release-deploy,nightly}.yml`, `.github/scripts/matrix_notify.py` (only if
notify still uses it), `docs/RELEASE_PIPELINE.md`, `docs/CI_SELF_HOSTED_RUNNER.md`,
`docs/GOTCHAS.md` (the v49 entry), `CLAUDE.md` (the CI decision line).

v50 runs alongside and owns `.github/scripts/check_version.py`, compose and `docs/LOCAL_DEV.md`.
There's no overlap.

## Out of scope

- Runner starvation (P2) and the deploy failure paths P3–P8 (v60).
- pytest on Postgres (v51's `pytest` job).
- Extension signing (v61 adds a job to "Release & Deploy").
- Any change to what the deploy does on the host.

## Deploy notes

None on the host. The first merge after this one is the first real "Release & Deploy" run. The
v50 agent records it, and so does each later slice's precondition check.

## Done when

- [ ] `grep -rn workflow_run .github/` is empty, and no `cancel-in-progress` applies to a `main` run
      (grep output).
- [ ] Every workflow parses (`actionlint` output, or `gh workflow view` for each).
- [ ] Scratch matrix 1–5 passes, each with its run list (and screenshots for 4–5).
- [ ] The manual Publish & Deploy dispatch path is unchanged: the diff of that path is shown and
      explained, and a scratch dispatch against the stubs shows the `manual-<sha>` tag and no
      persist.
- [ ] Every `notify` contains no `uses:` (grep), and the run logs above print no secret (grep for
      the token).
- [ ] The branch protection's required checks still match "CI"'s job names (API output), or the
      owner updated them (linked).
- [ ] **Cleanup:** counts before, the reviewed filter, counts after; `gh workflow list --all`
      without the two leftover workflows.
- [ ] Docs, GOTCHAS v49 (with its index line) and the `CLAUDE.md` line are in the diff.
      `CLAUDE.md` ≤ 250 lines.
- [ ] `check_version.py origin/main` passes with no bump. `graphify update .` has been run.
- [ ] **After merge** (recorded in v50's PR): v49's own merge produced exactly one "Release &
      Deploy" run on `main`, with the checks green, the release and deploy jobs skipped
      (the version is unchanged), and no other run.
