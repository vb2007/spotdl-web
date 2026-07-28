# Setting up the self-hosted GitHub Actions runner

This project's PR tests run on a **self-hosted GitHub Actions runner installed on the same
Debian 12 host** used for deployment (`docs/DEPLOYMENT.md`, `192.168.100.200`) — not a
GitHub-hosted runner. That's deliberate: it's the same principle behind "develop locally, verify
on the real host" (see `CLAUDE.md`'s workflow rules), extended to automated testing instead of
only manual pre-merge checks.

This doc is a reproducibility record — how the runner was set up, and how to rebuild it from
scratch if the host is ever reprovisioned — not a strict "do this now" checklist, since the
runner package download and registration (`config.sh`) are already done on the real host as of
writing this. The remaining steps (running it as a persistent service, confirming the security
settings below) still need doing there.

---

## Security considerations — read this before enabling the workflow

A self-hosted runner executes arbitrary workflow-defined code **directly on this host**, with
whatever access that host's user account has — which, here, is the same physical machine
running the production Docker stack and (per the locked decision) a host-native PostgreSQL
instance potentially shared with other services. This is a materially bigger blast radius than a
GitHub-hosted runner, which is a disposable VM torn down after each job.

This repo is public. GitHub's own guidance is to avoid self-hosted runners on public repos
*specifically because* a pull request from an outside contributor can otherwise run arbitrary
code on your infrastructure via `pull_request`-triggered workflows. Since this is currently a
single-contributor project, the realistic risk today is low, but the setting that prevents it
should be verified explicitly rather than assumed:

- GitHub repo → **Settings → Actions → General → Fork pull request workflows from outside
  collaborators** — confirm this is set to **"Require approval for all outside collaborators"**
  (the stricter of the two non-"run automatically" options), not just the first-time-contributor
  default. This means any PR from an account that isn't you sits with its workflow run queued
  until manually approved from the **Actions** tab — it never runs unattended.
- Never change that setting to "Require approval for first-time contributors" or weaker while
  this runner stays registered against a production host.
- If this project ever gains outside contributors, revisit whether a self-hosted runner on the
  production box is still the right call before loosening that setting.

Beyond that repo setting, keep the blast radius contained on the host itself:

- Run the runner as a **dedicated, unprivileged OS user** — not `root`, and ideally not the same
  user that owns the `/opt/spotdl-web` deployment checkout. It needs `docker` group membership
  only if a future workflow job needs `docker compose` (the current workflow doesn't).
- The runner's own working directory (`/opt/actions-runner` below) is intentionally **separate
  from** the deployed app's checkout (`/opt/spotdl-web`, per `docs/DEPLOYMENT.md`). Actions
  checks out a fresh copy of the repo per job under its own `_work` directory — it never touches
  `/opt/spotdl-web`, and the two should never be pointed at the same path.

---

## 1. Download and register the runner (already done)

From the GitHub repo → **Settings → Actions → Runners → New self-hosted runner**, which gives a
one-time registration token and the exact `curl`/`tar` commands for Linux x64. In outline, this
is what already happened on the host:

```bash
sudo useradd -m -s /bin/bash github-runner   # dedicated unprivileged user, if not done already
sudo -iu github-runner
mkdir -p /opt/actions-runner && cd /opt/actions-runner    # requires the directory owned by github-runner
# (download + extract the runner tarball GitHub's UI gives you)
./config.sh --url https://github.com/vb2007/spotdl-web --token <REGISTRATION_TOKEN>
```

`config.sh` prompts for a runner name (default: hostname) and labels (default: none extra) — the
workflow in this repo targets the always-present `self-hosted` label only, so no custom labels
are required.

## 2. Install OS-level runner dependencies

The extracted runner package ships a helper for the handful of system packages the runner binary
itself needs (independent of anything this project's tests need):

```bash
cd /opt/actions-runner
sudo ./bin/installdependencies.sh
```

## 3. Run it as a persistent service, not an interactive session

`./run.sh` alone only runs in the foreground, tied to the SSH session that started it — it dies
the moment that session closes. Install it as a systemd service instead so it survives reboots
and SSH disconnects:

```bash
cd /opt/actions-runner
sudo ./svc.sh install github-runner   # runs as the github-runner user, not root
sudo ./svc.sh start
sudo ./svc.sh status
```

## 4. Verify registration

GitHub repo → **Settings → Actions → Runners** should show the runner listed with a green
**Idle** status. If it shows **Offline**, the systemd service isn't running — check
`sudo ./svc.sh status` and `journalctl -u actions.runner.* -n 50` on the host.

## 5. Project test dependencies

Unlike the runner binary's own OS dependencies (step 2), this project's *test* dependencies are
handled entirely inside the workflow (`.github/workflows/backend-tests.yml`), not as manual host
setup:

- **Python 3.12**: Debian 12 ships Python 3.11 by default, which doesn't satisfy this project's
  `requires-python = ">=3.12,<3.13"` (`backend/pyproject.toml`). The workflow uses
  `actions/setup-python@v5` to download a self-contained CPython 3.12 build rather than relying
  on a system-wide install — this only needs outbound HTTPS from the runner host to GitHub's
  release CDN, which this host already has (it already pulls Docker images and clones this repo
  over HTTPS).
- **`uv`**: installed fresh into a per-run virtualenv by the workflow itself
  (`.venv/bin/pip install uv`), not a manual host-level install. Required because plain `pip
  install .` can't see `pyproject.toml`'s `[tool.uv] override-dependencies` — the same reason
  `backend/Dockerfile` uses `uv` instead of bare `pip` (see `CLAUDE.md`'s v04 gotchas for why
  spotdl needs that override at all).
- **Everything else** (`fastapi`, `spotdl`, `pytest`, etc.) comes from `uv pip install
  ".[dev]"` against `backend/pyproject.toml`, same as local dev's `backend/.venv`.

**Nothing else needs installing on the host for this test job specifically** — no PostgreSQL, no
Redis, no `ffmpeg` binary. This is a property of the current test suite, not an oversight:

- Every test uses an in-memory SQLite engine (`backend/tests/conftest.py`'s `db_session`
  fixture) rather than the real Postgres instance — `DATABASE_URL`/`REDIS_URL` env vars are set
  to harmless placeholder values purely to satisfy `Settings()`'s required fields at import time;
  nothing ever actually connects using them (SQLAlchemy's `create_engine()` and Celery's app
  construction are both lazy).
- No test constructs a real `spotdl.download.downloader.Downloader` or calls a real Spotify/
  YouTube endpoint — `SpotifyClient.init`, `get_simple_songs`, `Downloader`, and
  `search_and_download` are all monkeypatched at the call site in every test that touches them.
  `ffmpeg` is only ever needed inside a real `Downloader`, which the test suite never builds.

**If a future test needs one of these for real** (e.g. an actual integration test against
Postgres, mirroring the manual verification `CLAUDE.md`'s workflow rules already require before
a PR is merge-ready): add it as a GitHub Actions **service container** in the workflow, or point
it at this same host's existing Postgres instance the way `docs/DEPLOYMENT.md` does for the
deployed app — don't reach for either preemptively while the suite doesn't need it.

## 6. What the workflow actually runs

`.github/workflows/backend-tests.yml`:

- Triggers on every pull request (any target branch — this project only ever PRs into `main`),
  every push to `main`, and manual `workflow_dispatch` (useful for smoke-testing the runner setup
  itself without opening a PR).
- `concurrency` cancels a still-running job for the same ref if a new commit supersedes it, so
  pushing twice to the same PR doesn't queue two redundant runs.
- Single job, `runs-on: self-hosted`, working directory `backend/`: checkout → Python 3.12 →
  fresh venv + `uv pip install ".[dev]"` → `pytest -v`.

Only the backend has tests today (the frontend, from v09 onward, currently has no test script in
`frontend/package.json` beyond lint/typecheck) — extend this same workflow with a second job once
that changes, rather than standing up a separate one preemptively.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Runner shows **Offline** in the GitHub UI | systemd service not running | `sudo ./svc.sh status`; `sudo ./svc.sh start` if stopped; `journalctl -u actions.runner.* -n 50` for why it died |
| Workflow run stays queued forever | No idle self-hosted runner available, or it's registered to the wrong repo | Confirm **Idle** status in Settings → Actions → Runners; re-run `config.sh` if it was registered against a different repo/org |
| A PR's workflow run sits "waiting for approval" | Expected for outside-collaborator PRs (see Security considerations above) | Review the diff, then approve manually from the PR's **Checks** tab — never approve a fork PR's run without reading its workflow-file changes first, since that file itself is part of the diff |
| `uv pip install ".[dev]"` fails with a fastapi/uvicorn conflict | `pyproject.toml`'s `[tool.uv] override-dependencies` didn't get picked up | Confirm the install used `uv`, not plain `pip` — the workflow's `.venv/bin/uv pip install` step, not `.venv/bin/pip install` |
| `pytest` fails on a fresh runner but passed locally | Dependency versions drifted between the runner's fresh venv and a stale local `backend/.venv` | Trust the runner — recreate the local venv (`rm -rf backend/.venv && uv venv` equivalent) and compare |
| Runner works, but a *new* test needs real Postgres/Redis/ffmpeg | Expected — the current suite deliberately avoids needing any of these (see Section 5) | Add a GitHub Actions service container or point at the host's existing Postgres, scoped to that new test only |
