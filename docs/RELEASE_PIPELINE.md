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
`frontend/package.json` must always agree.

`.github/scripts/check_version.py` (stdlib-only, no dependencies needed) is the single parser for
both files — every workflow that needs the version calls it rather than re-deriving it, so there's
no second implementation that could disagree:

```bash
python3 .github/scripts/check_version.py            # validate + print the version
python3 .github/scripts/check_version.py origin/main # also fail if backend/ or frontend/
                                                      # changed since origin/main without a bump
```

`ci.yml`'s `version` job runs the second form on every PR (comparing against the PR's base
branch) and the first form on every push to `main`. **A PR is not merge-ready until this job is
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
PR that added this sentence) needs no version bump at all. `release.yml`'s tag-exists check
finds the current version already released and skips cutting a new one; `publish-deploy.yml`
still runs (the upstream `Release` run still completes successfully) but both its
already-published and already-deployed idempotency checks skip everything else — no new image,
no host change. `ci.yml`'s `version` job passing on a docs-only diff with no bump was confirmed
live on PR #24; the full skip-the-whole-chain behavior on merge is the same idempotency path
already verified during v21's own pre-merge and post-merge testing (see the Idempotency section
above).

---

## The chain

```
ci.yml              on: push (main), pull_request, workflow_dispatch
   │
   │  workflow_run: completed && success && event == 'push' && head_branch == 'main'
   ▼
release.yml          "Release"
   │  1. check_version.py -> VERSION, TAG=vVERSION
   │  2. git ls-remote --tags origin -> already released? skip the rest if so
   │  3. build deploy bundle + requirements.txt
   │  4. gh release create --generate-notes --latest --target <commit>
   │
   │  workflow_run: completed && success
   ▼
publish-deploy.yml   "Publish & Deploy"
   │
   ├─ job: resolve   -> mode, commit, version, image_tags, persist
   ├─ job: publish   -> docker build + push both images to GHCR, record digests on the release
   ├─ job: deploy    -> required-var preflight -> pg_backup -> checkout on the host -> pull
   │                    -> up -d -> health gate -> .last-good (release mode)
   │                    -> on failure: migration guard -> roll back commit + tag together
   └─ job: notify    -> Matrix message on any failure/cancel, and on every real deploy (v33)
```

`release.yml` has its own `notify` job too (v33): a failed release skips everything in
`publish-deploy.yml`, so that workflow's `notify` never sees it.

Two `workflow_run` hops — inside GitHub's documented three-level chain limit (a workflow can't
`workflow_run`-trigger more than three levels deep).

**Why chain from CI, not straight from `push`:** a release created with the default
`GITHUB_TOKEN` does **not** trigger other workflows (GitHub's own loop-prevention rule), so
`release: [published]` can't drive `publish-deploy.yml` without adding a personal access token.
Chaining via `workflow_run` needs no PAT anywhere in the pipeline. It also structurally enforces
"only deploy code that passed CI" without polling: there is exactly **one** self-hosted runner for
this repo, so a `deploy` job that *polled* `ci.yml`'s conclusion while holding that runner's only
slot would deadlock against `ci.yml` itself queuing behind it.

**Why `workflow_run`'s own `github.sha`/`github.ref` aren't trusted directly:** GitHub sets both
to the default branch's current head for a `workflow_run` event, not necessarily the commit that
triggered the upstream run. `release.yml` explicitly checks out
`github.event.workflow_run.head_sha`; `publish-deploy.yml` resolves the tag from the release
itself (`gh release view --json tagName`) and checks out its exact commit. The image that gets
published is therefore always tied to a specific commit by construction, never "whatever main's
head happened to be when the job started."

---

## Publish & Deploy — two modes

`publish-deploy.yml` has one `resolve` job that decides which mode applies and computes
everything the `publish`/`deploy` jobs need, so those jobs never branch on `github.event_name`
themselves.

| | Release mode (`workflow_run`) | Manual mode (`workflow_dispatch`) |
|---|---|---|
| Trigger | `release.yml` ("Release") completing successfully | `-f ref=<branch/tag/sha>`, any time |
| `version` | the release's tag, stripped of `v` | `manual-<short-sha>` |
| Image tags pushed | `$version`, `latest` | `$version` only — **never `latest`** |
| `persist` | `true` — becomes the host's new baseline `IMAGE_TAG` | `false` |
| Skip if already done | yes (see Idempotency) | never — every dispatch always builds + deploys fresh |

Manual mode exists specifically so a branch can be tried on the real host **before its PR
merges** — there's no CI gate on it, since it's an explicit, on-demand request, not something
that should wait on anything:

```bash
gh workflow run "Publish & Deploy" --repo vb2007/spotdl-web -f ref=<branch-or-tag-or-sha>
```

The image never gets tagged `latest`, so a plain `docker compose pull` elsewhere can never pick it
up by accident. The *next* release-mode deploy always supersedes whatever a manual dispatch left
running — a `manual-*` version string never equals a real semver `IMAGE_TAG`, so the skip check
never suppresses that following real deploy.

---

## Idempotency

`release.yml` skips creating a release when the tag already exists (a docs-only merge with no
version bump) but the run still concludes `success` — so `publish-deploy.yml` fires regardless.
In **release mode**, two independent skip checks handle that:

- `publish`: `docker manifest inspect ghcr.io/vb2007/spotdl-web-{backend,frontend}:$VERSION` both
  succeed → already published, skip the build/push.
- `deploy`: the host's `.env` already has `IMAGE_TAG=$VERSION` **and**
  `.github/scripts/wait_for_stack_health.sh` reports the stack healthy → skip. If the tag matches
  but the stack *isn't* healthy, it deploys anyway — that's the recovery path after a previously
  failed deploy.

**Manual mode never applies either skip** — every dispatch is explicit and always builds/deploys
fresh, which is the entire point of being able to test a branch on demand.

---

## GHCR packages

Two public packages, `ghcr.io/vb2007/spotdl-web-backend` and `ghcr.io/vb2007/spotdl-web-frontend`.
Public means **no `docker login` needed to pull**, anywhere — the host's `deploy` job never
authenticates to read; only `publish` logs in (with the job's own `GITHUB_TOKEN`, no separate
secret) to push.

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
3. **Required-variable preflight** (v33), still before anything on the host moves. It fetches,
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
4. **Skip check** (release mode only) — see Idempotency above.
5. **Back up Postgres** — runs `$DEPLOY_DIR/scripts/pg_backup.sh` (the *currently deployed*
   version of the script, since this runs before the checkout below switches it), before anything
   can touch the schema. Both modes run this — a manual dispatch can still carry a pending
   migration. The dump's path is kept (v33): a refused rollback has to hand it to a human.
6. **Update the checkout** (already fetched by the preflight, so this step's first command
   moves the host, and "the deploy step ran" means "the host moved"):
   `git checkout --detach --force <commit-sha>` (the exact commit resolved by the `resolve` job,
   not a human-readable ref — see the chain section above for why), `git reset --hard`, **`git
   clean -fd -e /.last-good`**. Deliberately **not** `-fdx`: `.env` and `proxies.txt` are
   gitignored, and `-x` would delete both along with the host's real secrets and proxy pool.
7. **Write `IMAGE_TAG`** into `.env` (idempotent upsert — replaces the line if present, appends if
   not). Safe to leave there permanently: `Settings.model_config` in `backend/app/config.py` is
   `extra="ignore"`, so the extra key reaching containers via `env_file: .env` is inert; Compose
   itself reads it for the `${IMAGE_TAG}` interpolation in `docker-compose.prod.yml`.
8. **Pull + up**: `docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile
   tunnel pull` then `... up -d --no-build --remove-orphans`.
9. **Health gate** — `.github/scripts/wait_for_stack_health.sh`, polling up to 420s. That budget
   isn't arbitrary: `worker-dl`/`worker-meta`'s healthchecks have a 90s `start_period` and a 120s
   interval, so a genuinely healthy worker can take ~3.5 minutes to even report it. Checks:
   `redis`/`api`/`worker-dl`/`worker-meta`/`web` → `healthy`; `migrate` → `exited 0`;
   `beat`/`cloudflared` (deliberately no healthcheck) → `running`; plus a direct
   `curl http://localhost:8000/api/health`. Since v33 a compose **error** (an interpolation
   failure, a bad file, no daemon) fails it immediately with exit 2, instead of reading as "not
   healthy yet" and waiting out the timeout.
10. **Rollback on failure** — see "Rollback" below.
11. **Record last-known-good** (release mode, on success only) — see below.
12. **Prune** (on success only): `docker image prune -f` + `docker builder prune -f
    --keep-storage 5GB`, so the ~800MB backend image doesn't accumulate a new dangling layer set
    on every release. A prune error is only a warning (v33): the deploy is already healthy.
13. **Summary** (always): version, mode, skipped, the rollback result, and the host's end
    state (checkout `HEAD`, the `.env` `IMAGE_TAG` line, `.last-good`, `compose ps`), both on the
    run's summary page and in the log. None of it is secret, and it means a run's outcome can be
    read without SSHing into the host.

### Rollback

Only runs when the deploy step (6–8) actually started, since a failure in the preflight or the
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
- A failed run never writes it.
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

## Notifications (v33)

Both `publish-deploy.yml` and `release.yml` end with a `notify` job that posts one plain-text
message to a Matrix room through `.github/scripts/matrix_notify.py` (stdlib-only):
`PUT {homeserver}/_matrix/client/v3/rooms/{room}/send/m.room.message/{txn}`, with the bot's token
as `Authorization: Bearer`. `txn` is `gha-<run id>-<run attempt>`, so a retried request is
deduplicated by the homeserver, while a re-run (a new attempt) posts again, on purpose.

| Workflow | Sends when | Message carries |
|---|---|---|
| `publish-deploy.yml` | any of `resolve`/`publish`/`deploy` failed or was cancelled | workflow, failed job(s), release tag + version + mode, rollback result, run URL |
| `publish-deploy.yml` | a release-mode deploy succeeded and wasn't idempotency-skipped | version, release tag, run URL |
| `release.yml` | the `release` job failed or was cancelled | workflow, version tag, run URL |

So silence means "nothing happened", never "maybe it failed". A skipped run (a docs-only merge)
sends nothing. Messages never contain `.env` content.

**Secrets**, as repository secrets (Settings → Secrets and variables → Actions):
`MATRIX_HOMESERVER_URL`, `MATRIX_ACCESS_TOKEN`, `MATRIX_ROOM_ID`. Setting up the bot and the
room is in `docs/DEPLOYMENT.md`, "Matrix alert bot". **Unconfigured means off**: if any of the
three is unset, `notify` prints a `::warning::` and exits 0, so missing alert config can never
turn a green run red. A configured send that fails (a revoked token, Synapse down) is a
`::warning::` on the `notify` job, which still passes (v33.1, the owner's call): a Synapse or
Cloudflare outage takes the runner and the app down with it anyway, and a red run for a healthy
deploy would only mislead. The trade-off is that a failure isolated to the alert channel (a
revoked token, the bot kicked from the room, v33's Cloudflare User-Agent ban) only shows as that
warning, and the room goes quiet, so "silence means nothing happened" holds only while the
channel works. Check that a real deploy's success message still arrives now and then.

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
   changed: add it, then re-run the failed run.
4. **Nothing to do for rollback.** Rollback restores the previous commit's compose files, which
   don't reference the new variable, so a leftover key in `.env` is harmless.

---

## Manual recovery levers

- **Re-run a failed deploy**: fix whatever broke, then **re-run the failed run** from the Actions
  UI. That re-resolves the same release in release mode, so it also records `.last-good`, and a
  clean re-run of an already-correctly-deployed version is a no-op. A fresh dispatch
  (`gh workflow run "Publish & Deploy" -f ref=main`) works too, but it's a `manual-*` deploy: it
  never skips and never updates `.last-good`.
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
