# v21 — Release Automation

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

Found during this slice's live-host investigation, deliberately not fixed here:

- `worker-meta` was observed `Restarting (137)` (OOM-killed against its 768M prod resource
  limit) on the live host.
- `DOWNLOADS_DIR` (`/home/vb2007/spotdl`) was empty despite 8 days of container uptime at the
  time of inspection.

Both predate this slice and are unrelated to release automation; see `docs/GOTCHAS.md`'s v21
section.

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

- [ ] `backend/pyproject.toml` and `frontend/package.json` both read `2.21.0`.
- [ ] CI's `version` job passes on matched versions, fails on deliberate drift, fails on a
      `backend/`-touching diff with no bump, and passes on a docs-only diff with no bump.
- [ ] `docker compose ... config --quiet` renders cleanly for both the dev and prod overlays
      against the rewired `docker-compose.prod.yml`.
- [ ] A manual `workflow_dispatch` of "Publish & Deploy" against this branch successfully builds
      and pushes both images to GHCR (verified via `docker manifest inspect` and an
      unauthenticated `docker pull` after flipping to public).
- [ ] The same manual dispatch deploys cleanly to the real host: all services healthy,
      `/api/health` returns `ok`, the v20 UI loads through the tunnel, `.env`/`proxies.txt`
      survive `git clean -fd`, and a fresh Postgres dump lands in `/srv/spotdl-web/backups`.
- [ ] A deliberately-broken manual dispatch triggers the rollback path: health gate fails,
      previous `IMAGE_TAG` is restored, the stack comes back healthy, the workflow run itself is
      marked failed.
- [ ] `release.yml`'s tag-exists guard and asset generation verified (draft release, deleted
      after).
- [ ] The real chain runs unattended end-to-end once merged: `v2.21.0` released with notes and
      assets, images published, host detached at `v2.21.0`, stack healthy.
- [ ] `graphify update .` run; this checklist re-read fresh before calling the PR merge-ready.
