# v21 — Release Automation

> **Not in the original master v2 roadmap.** `plan/master-v2/00-master-plan.md` originally
> planned v21 as `dev-multi-user-hardening` (now **v22**, `v22-multi-user-hardening.md`) — this
> slice was inserted as a side track once v20 merged, at the user's request, because deployment
> automation had become urgent enough to do before continuing the planned sequence (see "Why"
> below). It did **not** break or reorder anything else in the chain: v22 is unchanged in scope,
> only renumbered, and every other completed slice (v14–v20) is untouched. See
> `00-master-plan.md`'s dated addendum and `CLAUDE.md`'s roadmap table for the same note.

## Why

v20 shipped the job-centric UI; deployment to the Debian host is still entirely manual (`git
pull` + `docker compose up -d --build`), and there is no release history — zero git tags, zero
GitHub releases, and the two version fields in the repo (`backend/pyproject.toml`,
`frontend/package.json`) were stale and divergent. The practical consequence: the live host was
found running v12 code, eight slices behind `main`, because nothing automatically moved it
forward.

Inserted ahead of the previously-planned hardening slice (now v22) rather than after it — this is
infrastructure the project needs regardless of what ships next, and having it in place before
v22's real-stack verification work means that work itself deploys through the same pipeline it's
verifying.

## Scope

1. **Versioning contract** — `backend/pyproject.toml` and `frontend/package.json` carry the
   identical `major.minor.patch` version; CI enforces agreement and that any diff touching
   `backend/`/`frontend/` bumps it. `.github/scripts/check_version.py` is the single parser both
   CI and the release workflow use.
2. **`.github/workflows/release.yml`** — chained off `ci.yml` via `workflow_run`, cuts a tagged
   GitHub release with `--generate-notes`, a deploy bundle, and `requirements.txt`, whenever the
   version was bumped.
3. **`.github/workflows/publish-deploy.yml`** — chained off `release.yml` via `workflow_run` (plus
   its own `workflow_dispatch` for deploying any branch/tag/commit manually, ahead of a PR
   merging). Builds + pushes both container images to GHCR (public), then pulls them onto
   `/mnt/raid1/spotdl-web` and restarts the stack, with a pre-migration Postgres backup and
   automatic rollback on a failed health gate.
4. **`docker-compose.prod.yml`** rewired from `build: ./backend` to `image:
   ghcr.io/vb2007/spotdl-web-*:${IMAGE_TAG:-latest}` — prod always deploys a published, tested
   image, never an ad-hoc local build.
5. Docs: `docs/RELEASE_PIPELINE.md` (new — the pipeline reference), `docs/DEPLOYMENT.md` and
   `docs/CI_SELF_HOSTED_RUNNER.md` corrected against the real host (checkout at
   `/mnt/raid1/spotdl-web`, not `/opt/spotdl-web`; runner at
   `/home/vb2007/gh-actionrunners/spotdl-web` running as `vb2007`, not a dedicated
   `github-runner` user; `DOWNLOADS_DIR=/home/vb2007/spotdl`, not `/srv/spotdl-web/downloads`).

Full design rationale (the chain-from-CI reasoning, idempotency rules, the two Publish & Deploy
modes) lives in `docs/RELEASE_PIPELINE.md` — not duplicated here.

## Out of scope, flagged for later

Found during this slice's live-host investigation:

- **`worker-meta`'s OOM crash loop (`Restarting (137)`, `OOMKilled=true`) was pre-existing and
  originally flagged here as deferred — but it turned out to permanently block this slice's own
  health gate from ever converging, so it was fixed as part of this PR after all** (capped
  `--concurrency=2` in `docker-compose.yml`; see `docs/GOTCHAS.md`'s v21 section for the root
  cause). Not a scope decision reversed lightly — confirmed with the user first, since it's a
  base-file change outside release automation proper.
- `DOWNLOADS_DIR` (`/home/vb2007/spotdl`) was empty despite 8 days of container uptime at the
  time of inspection — still unexplained, still deferred. Unrelated to release automation and
  did not block this slice's verification, so left for v22 or a dedicated follow-up.

## Host pre-flight (one-time, done as part of this slice — see `docs/RELEASE_PIPELINE.md`)

- GitHub → Settings → Actions → General → Workflow permissions → "Read and write permissions".
- Add the missing `ADMIN_EMAIL` to the host's `.env` (v17+ makes it required; its absence would
  crash-loop every backend container on the first automated deploy).
- Add `IMAGE_TAG=latest` to the host's `.env`.
- Create `/srv/spotdl-web/backups` (root-owned parent — needs `sudo` once) and prove
  `scripts/pg_backup.sh` runs successfully before a deploy depends on it.
- Flip both GHCR packages to public after the first successful `publish` run (first push always
  lands private, regardless of repo visibility).

## Done when

- [x] `backend/pyproject.toml` and `frontend/package.json` both read `2.21.0`.
- [x] CI's `version` job passes on matched versions, fails on deliberate drift, fails on a
      `backend/`-touching diff with no bump, and passes on a docs-only diff with no bump — all
      four checked locally against `check_version.py` before relying on CI's own green run
      (PR #23, `version` job passed in 8s on the real PR diff).
- [x] `docker compose ... config --quiet` renders cleanly for both the dev and prod overlays
      against the rewired `docker-compose.prod.yml` — confirmed locally and via PR #23's
      `compose-config` job.
- [x] A manual `workflow_dispatch`-equivalent (a temporary `push` trigger, since
      `workflow_dispatch` can't be invoked via API until the workflow exists on `main` — see
      `docs/RELEASE_PIPELINE.md`) of "Publish & Deploy" successfully built and pushed both
      images to GHCR — confirmed via `docker manifest inspect` and an unauthenticated
      `docker pull` from an outside machine after flipping both packages to public.
- [x] The same run deployed cleanly to the real host: all services healthy (after fixing the
      pre-existing `worker-meta` OOM that blocked this), `/api/health` returned `ok`, the v20 UI
      loaded through the real tunnel, `.env`/`proxies.txt` survived `git clean -fd`, and a real
      Postgres dump landed in `/srv/spotdl-web/backups` (confirmed with `pg_restore --list`).
      The host was stuck on v12 eight slices behind `main` before this — its migrate step ran
      the real v16–v19 migrations for the first time, successfully.
- [x] A deliberately-broken push (a real crashing commit) triggered the rollback path: health
      gate correctly failed after its full ~7min timeout, the previous `IMAGE_TAG` was restored,
      the stack came back healthy, and the workflow run itself was still marked failed (by
      design — a successful rollback doesn't mean the deploy succeeded).
- [x] `release.yml`'s tag-exists guard and asset generation verified: a real `v2.21.0` release
      was cut with a correct `--generate-notes` changelog (every merged PR from v00–v20 listed)
      and both assets (deploy bundle extracted cleanly, `docker compose config` on its contents
      rendered); a second push with no version change correctly skipped release creation,
      image publish, and deploy alike (idempotency). Deleted (`gh release delete --cleanup-tag`)
      afterward so the real merge cuts `v2.21.0` fresh against the actual merged history.
- [ ] The real chain runs unattended end-to-end once merged: `v2.21.0` released with notes and
      assets, images published, host detached at `v2.21.0`, stack healthy. **Can only be proven
      after merge** — `workflow_run`/`workflow_dispatch` triggers only activate once the listening
      workflow file exists on the default branch, so the CI→Release→Publish&Deploy chain itself
      was untestable pre-merge by construction, not by oversight. This is the one open item.
- [x] `graphify update .` run; this checklist re-read fresh before calling the PR merge-ready.
