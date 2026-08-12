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
   └─ job: deploy     -> pg_backup -> checkout on the host -> pull -> up -d -> health gate
                         -> rollback to the previous image on failure
```

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
directory and is in the `docker` group (no `sudo` needed anywhere in this job).

1. **Preflight** — confirm `DEPLOY_DIR` is a real git checkout with `.env` and `proxies.txt`
   present. Fails loudly rather than guessing if either is missing.
2. **Read the previous `IMAGE_TAG`** from the host's `.env` (empty on the very first automated
   run — see "First deploy" below).
3. **Skip check** (release mode only) — see Idempotency above.
4. **Back up Postgres** — runs `$DEPLOY_DIR/scripts/pg_backup.sh` (the *currently deployed*
   version of the script, since this runs before the checkout below switches it), before anything
   can touch the schema. Both modes run this — a manual dispatch can still carry a pending
   migration.
5. **Update the checkout**: `git fetch origin --tags --prune`, then
   `git checkout --detach <commit-sha>` (the exact commit resolved by the `resolve` job, not a
   human-readable ref — see the chain section above for why), `git reset --hard`, **`git clean
   -fd`**. Deliberately **not** `-fdx`: `.env` and `proxies.txt` are gitignored, and `-x` would
   delete both along with the host's real secrets and proxy pool.
6. **Write `IMAGE_TAG`** into `.env` (idempotent upsert — replaces the line if present, appends if
   not). Safe to leave there permanently: `Settings.model_config` in `backend/app/config.py` is
   `extra="ignore"`, so the extra key reaching containers via `env_file: .env` is inert; Compose
   itself reads it for the `${IMAGE_TAG}` interpolation in `docker-compose.prod.yml`.
7. **Pull + up**: `docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile
   tunnel pull` then `... up -d --no-build --remove-orphans`.
8. **Health gate** — `.github/scripts/wait_for_stack_health.sh`, polling up to 420s. That budget
   isn't arbitrary: `worker-dl`/`worker-meta`'s healthchecks have a 90s `start_period` and a 120s
   interval, so a genuinely healthy worker can take ~3.5 minutes to even report it. Checks:
   `redis`/`api`/`worker-dl`/`worker-meta`/`web` → `healthy`; `migrate` → `exited 0`;
   `beat`/`cloudflared` (deliberately no healthcheck) → `running`; plus a direct
   `curl http://localhost:8000/api/health`.
9. **Rollback on failure**: restores the previous `IMAGE_TAG` into `.env`, `up -d --no-build`
   again, waits for health again, then still exits non-zero — the deploy itself failed even though
   the rollback succeeded, and that must surface as a failed workflow run. **Code/image rollback
   only** — Alembic migrations are never downgraded automatically (too risky unattended); the
   pre-deploy `pg_backup` in step 4 is the recovery path for a bad migration (see
   `docs/DEPLOYMENT.md`'s Rollback / recovery section for the manual restore procedure).
10. **Prune** (on success only): `docker image prune -f` + `docker builder prune -f
    --keep-storage 5GB`, so the ~800MB backend image doesn't accumulate a new dangling layer set
    on every release.

### First deploy

The very first automated run has no previous `IMAGE_TAG` to roll back to. If it fails its health
gate, the rollback step detects the empty previous tag, prints an explicit error rather than
guessing, and exits non-zero — manual recovery via `docs/DEPLOYMENT.md`'s fallback steps is the
answer in that specific case, not a silent no-op.

---

## Manual recovery levers

- **Re-run a failed deploy**: fix whatever broke, then re-dispatch — `gh workflow run "Publish &
  Deploy" -f ref=main` (or re-run the failed run from the Actions UI, which re-resolves the same
  release). Idempotency means a clean re-run of an already-correctly-deployed version is a no-op.
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
