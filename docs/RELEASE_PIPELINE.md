# Release pipeline (v21)

How a merge into `main` becomes a versioned GitHub release, two public GHCR container images,
and a running deploy on the production host — fully automated, with a manual escape hatch for
testing a branch before it merges. This doc is the reference for the mechanics; `docs/DEPLOYMENT.md`
covers what's specific to running this on the real host, and `docs/CI_SELF_HOSTED_RUNNER.md`
covers the runner itself.

---

## Versioning contract

Every version slice bumps **both** `backend/pyproject.toml`'s `version` and
`frontend/package.json`'s `version` to the same `major.minor.patch` string —
`major.minor` = `master series . roadmap slice` (e.g. this slice, v21, ships `2.21.0`), `patch` =
a fix on top of an already-shipped slice. `backend/pyproject.toml` is the canonical source;
`frontend/package.json` must always agree. `backend/uv.lock` records the backend's version too, so a
bump also needs `uv lock` in `backend/`: CI's `deps-sync` job (`uv lock --check`) fails a PR whose
lock still names the old version.

`.github/scripts/check_version.py` (stdlib-only, no dependencies needed) is the single parser for
both files — every workflow that needs the version calls it rather than re-deriving it, so there's
no second implementation that could disagree:

```bash
python3 .github/scripts/check_version.py            # validate + print the version
python3 .github/scripts/check_version.py origin/main # also fail if backend/ or frontend/
                                                      # changed since origin/main without a bump
```

`ci.yml`'s `version` job runs the second form on every PR (comparing against the PR's base
branch) and the first form on every push to `main` (as part of "Release & Deploy"'s `checks`). **A PR is not merge-ready until this job is
green** — this is a standing project requirement (`CLAUDE.md`), not specific to this slice.

**One shared app version, not independent backend/frontend versions.** `check_version.py`
doesn't care *which* side a diff touches, only whether it touches `backend/` or `frontend/` at
all — so a PR that changes only the backend still has to bump `frontend/package.json` to the
same new string, and vice versa. The practical effect for `publish-deploy.yml`: it builds and
pushes **both** images under the new tag every time, even when only one side's source actually
changed. The unchanged side's build produces the exact same Docker layers as before, just
published under a new version tag — a legitimate, expected redundant rebuild (Docker's
content-addressed layers mean this costs registry storage overhead, not real work), not a sign
the pipeline mis-detected what changed.

A PR that touches **neither** `backend/` nor `frontend/` (docs, workflows, plan files — like the
PR that added this sentence) needs no version bump at all. Its merge is still one "Release &
Deploy" run: the checks run, the `plan` job finds the current version already tagged, and the
`release` and `deploy` jobs show as skipped inside that run (v49). No other run is created, no new
image, no host change. `ci.yml`'s `version` job passing on a docs-only diff with no bump was
confirmed live on PR #24.

---

## The chain

Since v49, one event starts one run, and every run in the Actions list is one that does
something:

| Event | Workflow (run name) | What runs |
|---|---|---|
| `pull_request` | `ci.yml` **"CI"** | The checks only: `version`, `pytest`, `deps-sync`, `compose-config`, `frontend`, `summary` |
| `push` to `main` | `release-deploy.yml` **"Release & Deploy"** | The chain below, in one run |
| `schedule` (`17 4 * * *`) | `nightly.yml` **"Nightly"** | `yt-dlp-freshness` and its notice |
| manual | `workflow_dispatch` on any of them | "Release & Deploy": the chain again on `main` (with `redeploy`: deploy the current release again). "Publish & Deploy": deploy any ref (manual mode, below). "Release": cut `main`'s release, nothing else. "CI", "Nightly": the checks |

```
push to main
   │
release-deploy.yml   "Release & Deploy" (one run, jobs ordered by `needs:`)
   │
   ├─ checks    uses: ci.yml            the PR checks, on the pushed commit
   ├─ plan      check_version.py -> VERSION; is vVERSION tagged yet? -> release = true/false
   │              (a `redeploy` dispatch with the tag present: redeploy = true, commit = the tag's)
   ├─ release   uses: release.yml       only when release == true
   │              gh release create vVERSION --generate-notes --target <commit>
   │              (+ deploy bundle, requirements.txt; "Latest" only for the newest tag)
   ├─ deploy    uses: publish-deploy.yml   only after this run's own release, or for a redeploy
   │              ├─ resolve -> commit, version, image tags, persist (release mode)
   │              ├─ publish -> docker build + push both images to GHCR, images.json on the release
   │              └─ deploy  -> stale guard -> required-var preflight -> pg_backup -> checkout on
   │                            the host -> pull -> up -d -> health gate -> .last-good
   │                            -> on failure: migration guard -> roll back commit + tag together
   └─ notify    one curl to Matrix: any failed or cancelled job (named), or a real deploy
```

A merge with no version bump (docs, workflows, plans) is still exactly **one** run: `checks`
passes, `plan` says `release=false`, and `release` and `deploy` show as skipped *jobs* inside it.

**Why the stages are jobs of one run, not chained workflows (v49).** Until v49 the chain was
`ci.yml` → `workflow_run` → `release.yml` → `workflow_run` → `publish-deploy.yml`. A
`workflow_run` trigger fires on **every** completion of the workflow it names, whatever its
event or branch: every PR's CI run, every scheduled run and every dispatch fired Release, which
then skipped itself. A skipped run still *completes*, so it fired Publish & Deploy, which skipped
too. Of the last 1000 runs when v49 was planned, Release was 160 skipped of 212 and Publish &
Deploy 158 of 228. Calling the workflows from one run (`uses:` on a job, `workflow_call` in the callee)
keeps both reasons the chain was built for, without that noise:

- **It can't release code that failed its checks.** `release` `needs:` the checks, in the same
  run, on the same commit (`github.sha` of the push, passed down as an input).
- **No personal access token.** A release created with the default `GITHUB_TOKEN` doesn't trigger
  other workflows (GitHub's loop prevention), so a `release: [published]` trigger would need a
  PAT. Nothing has to be triggered now: the deploy is the next job. The caller grants the called
  jobs `contents: write` (and `packages: write` for the deploy) and passes `secrets: inherit`.
- **No polling deadlock.** A deploy job that polled CI's conclusion while holding the one
  runner would block CI itself (v21). `needs:` waits without holding a runner.

Called workflows see the **caller's** `github` context: `github.event_name` is `push` (or
`workflow_dispatch` when "Release & Deploy" is dispatched), and `github.workflow` is
"Release & Deploy". So `release.yml` and `publish-deploy.yml` never decide their mode from the
event. They use their inputs: a `commit` input means "called by the chain". The commit is always
passed explicitly; nothing looks the release up again (`gh release view`) or reads
`github.event.workflow_run.*`.

**Never chain workflows through `workflow_run` again** (`docs/GOTCHAS.md`, v49). A later slice
that adds a stage (v61's extension signing) adds a job to "Release & Deploy", gated on a `plan`
output.

---

## Publish & Deploy — two modes

`publish-deploy.yml` has one `resolve` job that decides which mode applies and computes
everything the `publish`/`deploy` jobs need, so those jobs never branch on the mode themselves.
The mode comes from the inputs (a `commit` input is release mode), never `github.event_name`,
which is the caller's event when it's called.

| | Release mode (`workflow_call`) | Manual mode (`workflow_dispatch`) |
|---|---|---|
| Trigger | the `deploy` job of "Release & Deploy", right after its release (or a `redeploy` dispatch) | `-f ref=<branch/tag/sha>`, any time |
| `version` | `check_version.py` at the release's commit, which must equal its tag without the `v` | `manual-<short-sha>` |
| Image tags pushed | `$version`, plus `latest` unless a newer `v*` tag exists at push time (v49) | `$version` only — **never `latest`** |
| `persist` | `true` — becomes the host's new baseline `IMAGE_TAG` | `false` |
| Skip if already done | yes (see Idempotency) | never — every dispatch always builds + deploys fresh |

Manual mode exists specifically so a branch can be tried on the real host **before its PR
merges** — there's no CI gate on it, since it's an explicit, on-demand request, not something
that should wait on anything:

```bash
gh workflow run "Publish & Deploy" --repo vb2007/spotdl-web -f ref=<branch-or-tag-or-sha>
```

v49 didn't change what this path does: the same `resolve` outputs (`manual-<short-sha>`,
`persist=false`, no `latest`), the same publish and deploy steps, and its own Matrix notice on a
failure (now sent with an inline `curl`, see Notifications). Two things around it did change:

- **No `deploy-prod` concurrency group.** A dispatch's jobs now interleave with a merge's on the
  one runner instead of waiting as a whole run (two deploys still never run at once). Dispatched
  while a merge's run is in flight, whichever deploy job runs *last* is what stays on the host,
  and the version guard doesn't apply to a dispatch. Don't dispatch over an in-flight merge.
- **A merge no longer puts the release back by itself.** Before v49 every merge, bumped or not,
  re-deployed the latest release. Now only a merge that cuts a new release deploys, so a
  `manual-*` build stays until the next version bump, or until you put the release back with
  `gh workflow run "Release & Deploy" -f redeploy=true` (see "Manual recovery levers").

The image never gets tagged `latest`, so a plain `docker compose pull` elsewhere can never pick it
up by accident. A `manual-*` version string never equals a real semver `IMAGE_TAG`, so the skip
check never suppresses the release-mode deploy that replaces it.

---

## Idempotency

The `plan` job of "Release & Deploy" only calls the release when `vVERSION` isn't tagged yet, and
the deploy only runs after that release (or for a `redeploy` dispatch), so an unbumped merge
never reaches either. The skip
checks below cover a **re-run** of a run whose release or deploy already happened, and a race
between two runs carrying the same version. In **release mode**:

- `release`: the tag already exists on the remote → nothing is created; the job still succeeds
  and outputs the tag. It also outputs `owned`: whether that tag points at **this run's**
  commit. A re-run finds its own tag (`owned=true`, the deploy goes ahead). A second run carrying
  the same version (a bump, then an unbumped merge whose `plan` ran before the first one's
  release) finds the first run's tag (`owned=false`), and its `deploy` job is skipped: it never
  publishes or deploys its own commit under a tag that points elsewhere.
- `publish`: `docker manifest inspect ghcr.io/vb2007/spotdl-web-{backend,frontend}:$VERSION` both
  succeed → already published, skip the build/push.
- `deploy`: the host's `.env` already has `IMAGE_TAG=$VERSION` **and**
  `.github/scripts/wait_for_stack_health.sh` reports the stack healthy → skip. If the tag matches
  but the stack *isn't* healthy, it deploys anyway — that's the recovery path after a previously
  failed deploy.

**Manual mode never applies either skip** — every dispatch is explicit and always builds/deploys
fresh, which is the entire point of being able to test a branch on demand.

### No cancelling, no stale deploys (v49)

No workflow has a `concurrency` group. Before v49, CI's `cancel-in-progress` (grouped by ref)
applied to `main` too, so a second merge cancelled the first merge's run, release included, and
the Release and Publish & Deploy groups could cancel a *pending* run (GitHub keeps one running
and one pending per group). Now two merges in a row both run in full. What keeps them from
hurting each other:

- **One runner.** Two jobs never run at the same time, so two deploys (or a deploy and a manual
  dispatch) never overlap on the host.
- **The version guard** (deploy step 3 below). The runner takes jobs roughly in the order they
  became ready, not strictly, so an older run's deploy could come after a newer one's. A
  release-mode deploy whose version is lower than the production baseline (`.last-good`) ends
  as a **successful no-op**, with one line in the job summary ("Not deployed: X is older than
  the production baseline Y"). Nothing on the host moves, `.last-good` stays, and no notice is
  sent.
- **`latest` and the "Latest" release badge go to the newest version only.** `release` (before
  creating the release) and `publish` (right before pushing `latest`) compare against every `v*`
  tag on the remote, so an older run finishing last doesn't take either from the newer one.
- **Only `main` is released.** `plan` fails a "Release & Deploy" dispatched from any other
  branch, so an unmerged commit can't take a version's tag (and with it, the real merge's
  release). Try a branch on the host with a manual "Publish & Deploy" instead.

---

## GHCR packages

Two public packages, `ghcr.io/vb2007/spotdl-web-backend` and `ghcr.io/vb2007/spotdl-web-frontend`.
Public means **no `docker login` needed to pull**, anywhere — the host's `deploy` job never
authenticates to read; only `publish` logs in (with the job's own `GITHUB_TOKEN`, no separate
secret) to push.

Both jobs run with a **job-private `DOCKER_CONFIG`** (`$RUNNER_TEMP/docker-config`, set by their
first step), never the runner user's `~/.docker/config.json`: other repositories' runners on the
same host share that file, and their `docker login`/`logout` once broke this pipeline's push
mid-job (`docs/GOTCHAS.md`, v21 entry, 2026-10-19 note).

```bash
docker pull ghcr.io/vb2007/spotdl-web-backend:2.21.0    # a specific release
docker pull ghcr.io/vb2007/spotdl-web-backend:latest    # whatever release-mode last pushed
docker pull ghcr.io/vb2007/spotdl-web-backend@sha256:...  # pin to an exact digest, see images.json below
```

> **First-run note:** a brand-new GHCR package always lands **private** on its first push,
> regardless of the repo's own visibility. After the first successful `publish` job, flip both
> packages to public by hand: GitHub → your profile → **Packages** → the package → **Package
> settings** → **Change visibility → Public**.

Every image carries OCI labels — `org.opencontainers.image.source` (links the package to this
repo on GitHub's Packages UI), `.version`, and `.revision` (the exact commit).

**`images.json`**, uploaded to the GitHub release by the `publish` job (release mode only, since
the digests don't exist until the images are actually pushed):

```json
{
  "version": "2.21.0",
  "commit": "8e0e867...",
  "backend": "ghcr.io/vb2007/spotdl-web-backend@sha256:...",
  "frontend": "ghcr.io/vb2007/spotdl-web-frontend@sha256:..."
}
```

Use this to pin or roll back to an exact immutable image rather than a mutable tag.

---

## The deploy job, step by step

Runs directly against `/mnt/raid1/spotdl-web` on the host — no separate Actions workspace
checkout for the deploy target itself, since the runner user (`vb2007`) already owns that
directory and is in the `docker` group (no `sudo` needed anywhere in this job). The job's own
workspace *does* get a checkout of the commit being deployed, for its scripts
(`.github/scripts/`).

1. **Preflight** — confirm `DEPLOY_DIR` is a real git checkout with `.env` and `proxies.txt`
   present. Fails loudly rather than guessing if either is missing.
2. **Record the current deployment and the rollback target** (v33), before anything moves:
   the `IMAGE_TAG` running now (for the skip check), and the rollback target, a **tag and commit
   together**, read from `.last-good` (see below). It falls back to `.env`'s `IMAGE_TAG` plus the
   checkout's `HEAD` only when `.last-good` doesn't exist yet. Since v33.1 it also records the
   pre-deploy version and an instant verdict on whether it's healthy *and* really what's running
   (the `api` container's image tag), for the rollback's fallback.
3. **Stale-version guard** (v49, release mode only): a version lower than `.last-good`'s
   `IMAGE_TAG` turns the rest of the job into a no-op (see "No cancelling, no stale deploys").
   It reads `.last-good` only, so the very first release after the file exists is compared, and
   a `manual-*` `IMAGE_TAG` in `.env` never blocks a release.
4. **Required-variable preflight** (v33), still before anything on the host moves. It fetches,
   reads the *new* commit's `docker-compose.yml` and `docker-compose.prod.yml` out of git into a
   temp dir (`git show <sha>:<file>`, so the deploy checkout stays where it is), and checks them
   against the host's real `.env`:
   - `check_required_env.py --require-value` (from the workflow's own commit, like the guard)
     lists every `${VAR:?}` the files
     need that `.env` lacks (or has empty), **by name**, plus "add to `.env`, see
     docs/DEPLOYMENT.md". It prints names only, never values.
   - `docker compose ... config --quiet` then catches anything else a render can trip on. Its
     stdout is suppressed (a full render holds every secret), and its stderr goes through
     `redact_env.py`, which masks every `.env` value: compose echoes a bad value, or a whole
     malformed line, back in its errors. The Summary's `compose ps` stderr goes through it too.

   A failure here ends the run with nothing changed: no backup, no checkout, no `IMAGE_TAG`
   write. That's the gap that broke v28's deploy *and* its rollback on 2026-09-27.
5. **Skip check** (release mode only) — see Idempotency above.
6. **Back up Postgres** — runs `$DEPLOY_DIR/scripts/pg_backup.sh` (the *currently deployed*
   version of the script, since this runs before the checkout below switches it), before anything
   can touch the schema. Both modes run this — a manual dispatch can still carry a pending
   migration. The dump's path is kept (v33): a refused rollback has to hand it to a human.
7. **Update the checkout** (already fetched by the preflight, so this step's first command
   moves the host, and "the deploy step ran" means "the host moved"):
   `git checkout --detach --force <commit-sha>` (the exact commit resolved by the `resolve` job,
   not a human-readable ref — see the chain section above for why), `git reset --hard`, **`git
   clean -fd -e /.last-good`**. Deliberately **not** `-fdx`: `.env` and `proxies.txt` are
   gitignored, and `-x` would delete both along with the host's real secrets and proxy pool.
8. **Write `IMAGE_TAG`** into `.env` (idempotent upsert — replaces the line if present, appends if
   not). Safe to leave there permanently: `Settings.model_config` in `backend/app/config.py` is
   `extra="ignore"`, so the extra key reaching containers via `env_file: .env` is inert; Compose
   itself reads it for the `${IMAGE_TAG}` interpolation in `docker-compose.prod.yml`.
9. **Pull + up**: `docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile
   tunnel pull` then `... up -d --no-build --remove-orphans`.
10. **Health gate** — `.github/scripts/wait_for_stack_health.sh`, polling up to 420s. That budget
   isn't arbitrary: `worker-dl`/`worker-meta`/`worker-expand`'s healthchecks have a 90s `start_period` and a 120s
   interval, so a genuinely healthy worker can take ~3.5 minutes to even report it. Checks:
   `redis`/`api`/`worker-dl`/`worker-meta`/`worker-expand`/`web` → `healthy`; `migrate` → `exited 0`;
   `beat`/`cloudflared` (deliberately no healthcheck) → `running`; plus a direct
   `curl http://localhost:8000/api/health`. Since v33 a compose **error** (an interpolation
   failure, a bad file, no daemon) fails it immediately with exit 2, instead of reading as "not
   healthy yet" and waiting out the timeout.
11. **Rollback on failure** — see "Rollback" below.
12. **Record last-known-good** (release mode, on success only) — see below.
13. **Prune** (on success only): `docker image prune -f` + `docker builder prune -f
    --keep-storage 5GB`, so the ~800MB backend image doesn't accumulate a new dangling layer set
    on every release. A prune error is only a warning (v33): the deploy is already healthy.
14. **The notice's rollback line** (always, v49): the "Rollback:" text of the Matrix
    notice, composed from this job's step outcomes and handed to whichever `notify` reports it.
15. **Summary** (always): version, mode, skipped, the rollback result, and the host's end
    state (checkout `HEAD`, the `.env` `IMAGE_TAG` line, `.last-good`, `compose ps`), both on the
    run's summary page and in the log. None of it is secret, and it means a run's outcome can be
    read without SSHing into the host.

### Rollback

Only runs when the deploy step (7–9) actually started, since a failure in the preflight or the
backup left nothing to undo. A run **cancelled** by hand rolls back too, since a cancel mid-`up`
leaves the host half-deployed. The job's `timeout-minutes` is 40 so that a failing deploy's two
420s health waits (gate, then rollback) fit with room to spare. Code/image rollback only: Alembic migrations are never downgraded
automatically (too risky unattended); the pre-deploy `pg_backup` is the recovery path for a bad
migration.

1. **Migration guard first**, before anything moves (after letting a still-running new
   `migrate` container exit, which a cancel mid-`up` can leave behind) (`.github/scripts/migration_guard.sh`). It
   extracts the *rollback commit's* compose files into a temp dir and, with `IMAGE_TAG` set to
   the rollback tag, runs one read-only probe in the rollback image's `migrate` service: the
   database's `alembic_version` against that image's own revision graph. If the database holds
   a revision the old image doesn't know (the failed deploy's `migrate` already upgraded it),
   starting the old stack is doomed, because its own `migrate` would refuse and nothing would
   come up.
   - **Fallback (v33.1):** when the database is ahead of `.last-good` (a `manual-*` dispatch
     migrated it since the last release, say), the guard runs again against **the version that
     was running just before this deploy** (pre-deploy HEAD + `IMAGE_TAG`), provided that version
     was healthy before the run (an instant health check in the "record" step) and isn't the very
     build that just failed. If it knows the schema, the rollback goes there instead, since the
     aim is the least downtime. Only a
     refusal triggers it, never a guard error, and `.last-good` isn't changed by it, so a
     throwaway tag still never becomes the baseline. The Matrix message says when it happened.
   - Otherwise the rollback **stops there**: it leaves the failed deploy's checkout and
     containers as they are and fails with "restore the pre-deploy pg_backup at `<path>` or roll
     forward".
   It also fails closed when it can't tell (Postgres unreachable, the old image unpullable),
   reported separately as a guard error rather than as "the database is ahead". The guard comes
   from the commit the workflow runs from (a second, sparse checkout at `.pipeline/`), never the
   ref being deployed, so a dispatch of a pre-v33 tag still has it.
2. **Restore commit and tag together**: `git checkout --detach --force <prev-commit>`,
   `git reset --hard`, `git clean -fd -e /.last-good`, then `IMAGE_TAG=<prev-tag>` into `.env`,
   then `up -d --no-build --remove-orphans`. Before v33 only `IMAGE_TAG` was reset, and `up` ran
   in the *new* checkout against the very compose file that had just failed.
3. **Health wait with the previous commit's own** `wait_for_stack_health.sh`, since its compose
   files are the ones in effect now.
4. **Still exits non-zero**: the deploy failed even when the rollback worked, and the run must
   show red.

The step's `result` (`succeeded`, `not-started`, `refused`, `guard-error`, `failed`, the last
only once the checkout has begun moving) goes into the Matrix message. A new `migrate` still
running 5 minutes after a cancel is a `guard-error` too: nothing is started over a migration in
flight. The manual
recovery for each case is in `docs/DEPLOYMENT.md`, "Rollback / recovery".

### `.last-good`

`/mnt/raid1/spotdl-web/.last-good` is the durable rollback baseline (v33), two lines:

```
IMAGE_TAG=4.33.0
COMMIT=<sha of the deploy checkout's HEAD>
```

- Written only when the job succeeds **and** `persist == 'true'`, meaning a release-mode deploy
  that passed its health gate. An idempotency-skipped release run writes it too, since its skip
  check has just confirmed that same version healthy. That's also how it first appears: the
  first release-mode run after v33 lands. Either way, only when the deploy checkout's `HEAD`
  *is* the release's commit; otherwise it warns and leaves the file alone.
- A `manual-*` dispatch (`persist=false`) **never** writes it. So a throwaway dispatch tag can't
  become the rollback target, the way `manual-fe6a30d` did on 2026-09-27 when the rollback read
  `.env` instead.
- A failed run never writes it, and neither does a stale one (v49): that would move the
  baseline back to an older version.
- Gitignored (`/.last-good`), and every `git clean` in the job also passes `-e /.last-good`, so a
  dispatch of a pre-v33 *ref* (whose `.gitignore` lacks the entry) can't delete it either. A
  dispatch run *from* a pre-v33 copy of the workflow (`gh workflow run --ref <old tag>`) still
  uses its old plain `git clean -fd` and will delete it; the next release-mode run recreates it.
- Only release mode writes it. After a recovery by dispatch or by hand onto a newer healthy
  version, it still names the previous release; update it by hand if that matters. Written
  to `.last-good.tmp` and renamed into place.

### First deploy

The very first automated run has no previous `IMAGE_TAG` to roll back to. If it fails its health
gate, the rollback step detects the empty previous tag, prints an explicit error rather than
guessing, and exits non-zero — manual recovery via `docs/DEPLOYMENT.md`'s fallback steps is the
answer in that specific case, not a silent no-op.

---

## Notifications (v33, curl-only since v49)

Each notice is one plain-text message to the pipeline's Matrix room, sent by a `notify` job that
is a **single `run:` step with no `uses:`**: no checkout, no action at all. The runner downloads
nothing for it, so a GitHub-side failure on an action download (the `429` that killed 4.40.2's
deploy at "Set up job", v48) can't take the notice down with the job it reports on. The step
sends it with `curl`:
`PUT {homeserver}/_matrix/client/v3/rooms/{room}/send/m.room.message/{txn}`, the bot's token as
`Authorization: Bearer`, the JSON body and the room id encoded by a one-line `python3`. The URL
and the token reach curl on stdin (`--config -`), never its command line, and nothing prints
them (curl runs with `-s`, since its error text names the host). `txn` is
`gha-<run id>-<run attempt>`, so a retried request is deduplicated by the homeserver, while a
re-run (a new attempt) posts again, on purpose. The same sender is inlined in all three files
that notify. `.github/scripts/matrix_notify.py` no longer runs in any workflow; it stays as the
manual test in `docs/DEPLOYMENT.md`, "Matrix alert bot".

| Workflow | Sends when | Message carries |
|---|---|---|
| "Release & Deploy" | any of `checks`/`plan`/`release`/`deploy` failed or was cancelled | workflow, the failed job(s), with the failed check's name (`checks: pytest`), tag + version, the rollback line, run URL |
| "Release & Deploy" | a release-mode deploy succeeded and wasn't skipped (idempotent or stale) | version, tag, run URL |
| "Publish & Deploy" (dispatch only) | any of `resolve`/`publish`/`deploy` failed or was cancelled | workflow, failed job(s), version (manual dispatch), the rollback line, run URL |
| "Nightly" | `yt-dlp-freshness` failed or was cancelled | workflow, failed job, run URL |

One run sends at most one notice. Called from "Release & Deploy", `publish-deploy.yml`'s own
`notify` stays skipped; the caller's reads the deploy's outputs (`version`, `published`,
`skipped`, `rollback_note`) instead. The rollback line comes from the deploy job itself
(step 14 above), so both senders word it the same. Without a rollback line, the chain's notice
falls back on the other outputs: no `version` means `resolve` didn't finish (nothing was built
or deployed), no `published` means `publish` didn't finish (the host deploy never started), and
otherwise the deploy job reported nothing (the runner died, or GitHub failed the job before its
first step): check the host. A standalone "Release" dispatch has no notice (v49): the person who
dispatched it is watching it, and the automatic path is covered by "Release & Deploy".

So silence is meant to mean "nothing happened", never "maybe it failed" (one exception below: an
outage of the alert channel itself). A merge with nothing to release sends nothing. Messages
never contain `.env` content.

The running app's own alerts (v36: breaker, failure spikes, stale beat, library sweeps) use the
same bot and room, configured in the host's `.env` rather than these secrets; see
`docs/DEPLOYMENT.md`, "App alerts (v36)".

**Secrets**, as repository secrets (Settings → Secrets and variables → Actions):
`MATRIX_HOMESERVER_URL`, `MATRIX_ACCESS_TOKEN`, `MATRIX_ROOM_ID`. Setting up the bot and the
room is in `docs/DEPLOYMENT.md`, "Matrix alert bot". **Unconfigured means off**: if any of the
three is unset, `notify` prints a `::warning::` and exits 0, so missing alert config can never
turn a green run red. A configured send that fails (a revoked token, Synapse down) is a
`::warning::` with the HTTP status and Matrix `errcode` on the `notify` job, which still passes
(v33.1, the owner's call): a Synapse or Cloudflare outage takes the runner and the app down with
it anyway, and a red run for a healthy deploy would only mislead. The trade-off is that a failure
isolated to the alert channel (a revoked token, the bot kicked from the room, v33's Cloudflare
User-Agent ban) only shows as that warning, and the room goes quiet, so "silence means nothing
happened" holds only while the channel works. Check that a real deploy's success message still
arrives now and then.

---

## Adding a required env var

A version that adds a variable Compose refuses to render without (`${VAR:?message}` in a compose
file) changes what the host's `.env` must contain *before* that version can deploy. That's
exactly what broke v28's deploy and its rollback on 2026-09-27. The checklist:

1. **Add the key to the template.** `.env.example` for the prod compose pair
   (`docker-compose.yml` + `docker-compose.prod.yml`), `.env.dev.example` for the dev pair
   (`docker-compose.yml` + `docker-compose.override.yml`). CI's `compose-config` job fails
   otherwise (v33 drift check, `check_required_env.py`), naming the missing key.
2. **List it under "Deploy notes" in the version's plan and PR**, with the value production
   needs. The owner reads that before merging.
3. **Add it to the host's `.env` before merging** (`/mnt/raid1/spotdl-web/.env`). If it's
   forgotten, the deploy's preflight fails naming the variable, with nothing on the host
   changed: add it, then re-run the failed run's failed jobs (not "all jobs", see "Manual
   recovery levers").
4. **Nothing to do for rollback.** Rollback restores the previous commit's compose files, which
   don't reference the new variable, so a leftover key in `.env` is harmless.

---

## Manual recovery levers

- **Re-run a failed deploy**: fix whatever broke, then **re-run the failed jobs** of that
  "Release & Deploy" run from the Actions UI (`gh run rerun <run id> --failed`). The release is
  already done, so only the deploy runs again, in release mode with the same commit and tag: it
  also records `.last-good`, and a clean re-run of an already-correctly-deployed version is a
  no-op. Re-run the *failed* jobs, not all of them: "Re-run all jobs" re-runs `plan`, which
  now finds the tag, so the run ends green with nothing deployed and no notice. Don't wait for
  the next merge to pick it up either: a merge whose version is already tagged deploys nothing.
  A re-run uses the workflow files of the run's own commit and is possible for 30 days; when
  the fix is in the workflow files or the `.pipeline` scripts (no version bump), use the
  redeploy below.
- **Redeploy the current release** (v49, the owner's lever):
  `gh workflow run "Release & Deploy" --repo vb2007/spotdl-web -f redeploy=true`. On `main`,
  with the version already tagged, `plan` skips the release and the `deploy` job deploys the
  **tag's commit** in release mode (preflight, backup, health gate, rollback, `.last-good`, the
  ✅ notice). Only the workflow files and the deploy's `.pipeline` scripts
  (`check_required_env.py`, `migration_guard.sh`, `redact_env.py`) come from `main`'s head.
  What the deploy checks out (the compose files, `wait_for_stack_health.sh`) is the tag's, and
  `pg_backup.sh` is the host's, so a fix to those still needs a version bump. It's the way to put the release back after a `manual-*` dispatch, and to ship a
  workflow-side fix to the current release. A host already on that version and healthy is
  skipped (and `.last-good` recorded, when the host checkout is on the tag's commit; otherwise
  it only warns). `main`'s checks must pass first, so a red `main` blocks it. Without a tag
  yet, the input changes nothing: the run releases and deploys as a merge would. A fresh
  `gh workflow run "Publish & Deploy" -f ref=main` works too, but it's a `manual-*` deploy: it
  never skips and never updates `.last-good`.
- **Re-run a failed release**: re-run that "Release & Deploy" run's failed jobs the same way; the
  deploy follows it in the same run. Dispatching "Release & Deploy" on `main` works too (the
  checks run again first). Dispatching "Release" alone (`gh workflow run release.yml`) only cuts
  the tag and deploys nothing, and the next "Release & Deploy" then sees the tag and skips the
  deploy as well (until a `redeploy` dispatch), so use it only when you want a release without
  a deploy.
- **Deploy a branch before it merges**: `gh workflow run "Publish & Deploy" -f ref=<branch>`
  (manual mode above). Dispatch it from `main` (the default), whose workflow file has v49's
  pipeline; `--ref <old tag>` would run that tag's copy of the workflow.
- **Deploy an older release by hand**: see `docs/DEPLOYMENT.md`'s manual fallback section — same
  `git checkout --detach vX.Y.Z` + `IMAGE_TAG` + `pull`/`up` sequence the workflow itself runs.
- **Delete a bad release**: `gh release delete vX.Y.Z --repo vb2007/spotdl-web --cleanup-tag` —
  removes the GitHub release and its tag. The GHCR image tags are separate and need deleting
  independently from the package's own **Versions** page if they should also go away (a delisted
  release does not retroactively unpublish an already-pulled image).
- **Delete a bad GHCR package version**: GitHub → your profile → **Packages** → the package →
  **Package settings** → find the version → delete. Do this before re-running `publish` for the
  same version tag, or the new push will simply overwrite it (which is usually what you want
  anyway — GHCR tags are mutable, just like Docker Hub's).
