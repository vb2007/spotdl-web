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

This project's *test* dependencies are handled entirely inside the workflow
(`.github/workflows/backend-tests.yml`) — **nothing needs manually apt-installing on the host
for Python itself**, which is a deliberate choice, not an oversight; see why below.

- **Python 3.12**: Debian 12 ships Python 3.11 by default, which doesn't satisfy this project's
  `requires-python = ">=3.12,<3.13"` (`backend/pyproject.toml`). The first real run of this
  workflow tried `actions/setup-python@v5` for this and failed outright:
  ```
  ##[error]The version '3.12' with architecture 'x64' was not found for Debian 12.
  ```
  `actions/setup-python`'s downloadable builds are keyed to the exact OS images GitHub's own
  *hosted* runners use (specific Ubuntu/Windows/macOS versions) — its manifest
  (`actions/python-versions`) simply has no entry for bare Debian, so it can never work here
  regardless of which Python version is requested. This is a real limitation of that action on
  non-Ubuntu self-hosted Linux runners, not a config mistake to retry differently.

  The fix: use **`uv`'s own Python management** instead
  (`uv python install 3.12` / `uv venv --python 3.12`), which downloads a portable,
  distro-agnostic CPython build (the same
  [python-build-standalone](https://github.com/astral-sh/python-build-standalone) project
  `pyenv`/`rye` use) rather than one of GitHub's OS-specific packages. It works identically
  regardless of which Linux distro or version the runner host is on, so there's no Debian
  package (backports or otherwise) to track or install — verified locally end-to-end
  (`uv python install 3.12` → `uv venv --clear --python 3.12 .venv` → `uv pip install --python
  .venv/bin/python ".[dev]"` → `.venv/bin/pytest -v`, all 32 tests passing) before this fix was
  pushed, not just assumed from reading `uv`'s docs.
- **`uv` itself**: installed via the official standalone installer script
  (`curl -LsSf https://astral.sh/uv/install.sh | sh`), not `pip install uv` — this needs no
  system Python at all (it downloads a static binary directly), which matters now that
  `actions/setup-python` is gone from this workflow and a working system `pip` can no longer be
  assumed. Installs to `$HOME/.local/bin` by default; the workflow appends that to
  `$GITHUB_PATH` so later steps can just call `uv` directly.
- **Everything else** (`fastapi`, `spotdl`, `pytest`, etc.) comes from `uv pip install
  ".[dev]"` against `backend/pyproject.toml`, same as local dev's `backend/.venv` — needed
  instead of plain `pip install .` because plain `pip` can't see `pyproject.toml`'s `[tool.uv]
  override-dependencies` (spotdl hard-pins fastapi/uvicorn for its own unused bundled web UI —
  see `CLAUDE.md`'s v04 gotchas), the same reason `backend/Dockerfile` uses `uv` too.

If a future project dependency genuinely needs an OS-level package (e.g. `ffmpeg`, if a test
ever exercises a real `Downloader` — see below), install that one specific package via apt on
the runner host and document it here, following the same pattern used for Android
platform-tools on other projects' runners — the point of this section is that Python 3.12
itself isn't one of those cases, not that apt has no place in runner setup at all.

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
- **`pytest` job** (`runs-on: self-hosted`, working directory `backend/`): checkout → install
  `uv` → `uv python install 3.12` → fresh venv + `uv pip install ".[dev,report]"` → `pytest -v`
  generating three report formats (`test-reports/junit.xml`, `report.html`, `report.ods` — see
  Section 8) → uploads each as its own artifact, even on test failure.
- **`publish-report` job**: `needs: pytest`, `if: always()` (runs even when `pytest` fails, so a
  failing PR still gets a rendered summary) — downloads all three artifacts and renders
  `junit.xml` as a markdown table directly on the run's **Summary** page via
  `$GITHUB_STEP_SUMMARY` (`.github/scripts/junit_to_summary.py`, stdlib-only — this job doesn't
  set up the backend venv at all). Its own pass/fail status only reflects whether the summary
  was published, not whether the tests passed — that's `pytest`'s job to signal, not duplicated
  here.

Only the backend has tests today (the frontend, from v09 onward, currently has no test script in
`frontend/package.json` beyond lint/typecheck) — extend the `pytest` job with a second matrix
entry (or a sibling job) once that changes, rather than standing up a separate workflow
preemptively.

## 7. Caching across runs — already automatic, no workflow change needed

On a GitHub-*hosted* runner, every job starts on a fresh disposable VM, so caching the
downloaded Python interpreter and packages requires an explicit `actions/cache` step. **This
self-hosted runner doesn't need that**: it's the same persistent host and the same OS user
account (`$HOME`) for every job — only the git working tree gets reset (`actions/checkout`'s
`clean: true` default runs `git clean -ffdx` there each run, which is what wipes the
workspace-local `backend/.venv` — nothing to do with uv's own cache). `uv` stores its downloaded
interpreters and packages under `$HOME` (`uv python dir` → `~/.local/share/uv/python`, `uv cache
dir` → `~/.cache/uv` by default), so they simply persist on disk across runs already, for free.

Verified with two consecutive real runs on the actual runner, not assumed from reading `uv`'s
docs — first run (cold, nothing cached yet on this host):

```
Downloading cpython-3.12.13-linux-x86_64-gnu (download) (32.6MiB)
 Downloaded cpython-3.12.13-linux-x86_64-gnu (download)
Installed Python 3.12.13 in 476ms
...
Downloading pydantic-core (2.0MiB)
Downloading pillow (6.6MiB)
Downloading curl-cffi (10.6MiB)
... (91 packages resolved, most downloaded individually)
```

Second run, moments later, same runner:

```
Python 3.12 is already installed
...
Resolved 91 packages in 15ms
Installed 91 packages in 19ms
```

Zero `Downloading` lines the second time — every package and the interpreter itself came from
the on-disk cache. **This also answers the "won't a version bump break the cache" question**:
`uv` names its Python installs by full version (`cpython-3.12.13-linux-x86_64-gnu`, visible in
the log above) and its package cache by exact name+version+hash, so bumping
`requires-python`/the workflow's hardcoded `3.12`, or bumping any dependency in
`backend/pyproject.toml`, just adds new cache entries alongside the old ones — it can't corrupt
or silently reuse a stale version, because a different version is a different cache key
entirely, not an overwrite of the same one.

If this ever needs revisiting (e.g. scaling out to multiple self-hosted runners later, where
each runner would have its own separate `$HOME` and thus its own separate cache instead of a
shared one): that's a real future consideration, but not one to solve preemptively while there's
only one runner.

## 8. Human-readable test reports

Beyond the raw `pytest -v` terminal log, every run also produces (via the `report` optional-
dependencies group in `backend/pyproject.toml` — `pytest-html`, `pytest-excel`, `odfpy`, and
pytest's built-in `--junit-xml`):

- **`report.html`** — a self-contained HTML page (`pytest-html`, `--self-contained-html`): one
  file, no external assets, safe to open directly from the downloaded artifact.
- **`report.ods`** — an OpenDocument Spreadsheet (`pytest-excel`, `--excel-report=...ods`) with
  one row per test: suite, name, result, duration, timestamp. `pytest-excel` writes via pandas'
  `DataFrame.to_excel()`, which auto-selects the write engine from the file extension — `odfpy`
  is what makes an `.ods` path genuinely produce ODS rather than an xlsx file with the wrong
  extension slapped on; verified with `file report.ods` → `OpenDocument Spreadsheet` and
  re-reading it back with `pandas.read_excel(..., engine="odf")`, not just trusted from the
  plugin's own (Excel-oriented) docs.
- **`junit.xml`** — the standard machine-readable format; this is what `publish-report`'s job
  summary is generated from, and what any future tool (a badge, a dashboard, `dorny/test-
  reporter`-style PR annotations) should consume instead of re-parsing pytest's own output.

**Each of these three is its own separate artifact** (`junit.xml`, `report.html`, `report.ods` —
named after the file itself), not one zip bundling all three. `actions/upload-artifact`'s
`archive: false` input uploads a single raw file as-is instead of zipping it, at the cost of one
file per artifact — exactly the trade wanted here. `publish-report`'s download step uses
`pattern: "*"` + `merge-multiple: true` to grab all three into one flat directory without having
to keep an explicit artifact-name list in sync between the upload and download steps.

Find them on the run's **Summary** page (Actions → this run → Artifacts, bottom of the page) —
each downloads and opens directly (`report.html` in a browser, `report.ods` in any spreadsheet
program that reads OpenDocument — LibreOffice Calc, Excel with the ODS filter, Google Sheets via
upload). The rendered markdown table on the Summary page itself (from `publish-report`) is
enough for an at-a-glance pass/fail count and a list of failing tests without downloading
anything.

Verified locally before wiring into the workflow (not assumed from the plugins' docs): ran
`pytest --junit-xml=... --html=... --self-contained-html --excel-report=...ods` for real against
a clean checkout, confirmed `report.ods` is a genuine OpenDocument Spreadsheet with one row per
test and `report.html` contains a real results table, and — deliberately breaking one test
temporarily — confirmed `junit_to_summary.py` renders a correct "Failed tests" table with the
real assertion message and exits `1`, then restored the test file with no diff left behind.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Runner shows **Offline** in the GitHub UI | systemd service not running | `sudo ./svc.sh status`; `sudo ./svc.sh start` if stopped; `journalctl -u actions.runner.* -n 50` for why it died |
| Workflow run stays queued forever | No idle self-hosted runner available, or it's registered to the wrong repo | Confirm **Idle** status in Settings → Actions → Runners; re-run `config.sh` if it was registered against a different repo/org |
| `##[error]The version '3.12' ... was not found for Debian 12` | `actions/setup-python`'s manifest has no build for bare Debian (only specific GitHub-hosted OS images) — hit on this workflow's first real run | Already fixed: the workflow uses `uv python install 3.12` instead (Section 5) — if this reappears, something re-added `actions/setup-python` for a Python version step |
| A PR's workflow run sits "waiting for approval" | Expected for outside-collaborator PRs (see Security considerations above) | Review the diff, then approve manually from the PR's **Checks** tab — never approve a fork PR's run without reading its workflow-file changes first, since that file itself is part of the diff |
| `uv pip install ".[dev]"` fails with a fastapi/uvicorn conflict | `pyproject.toml`'s `[tool.uv] override-dependencies` didn't get picked up | Confirm the install used `uv`, not plain `pip` — the workflow's `.venv/bin/uv pip install` step, not `.venv/bin/pip install` |
| `pytest` fails on a fresh runner but passed locally | Dependency versions drifted between the runner's fresh venv and a stale local `backend/.venv` | Trust the runner — recreate the local venv (`rm -rf backend/.venv && uv venv` equivalent) and compare |
| Runner works, but a *new* test needs real Postgres/Redis/ffmpeg | Expected — the current suite deliberately avoids needing any of these (see Section 5) | Add a GitHub Actions service container or point at the host's existing Postgres, scoped to that new test only |
| `publish-report` fails with "artifact not found" | The `pytest` job never reached its "Upload test reports" step (e.g. it failed before `mkdir -p test-reports`, or the whole job was cancelled) | Check the `pytest` job's own logs first — this is a downstream symptom, not the root cause |
| Job summary is missing but the artifact download succeeded | `junit_to_summary.py` itself errored (bad XML, wrong path) | Check `publish-report`'s "Publish job summary" step logs directly — it's `|| true`'d so the job stays green even here, which trades a hard failure for needing to actually look |
| `report.ods`/`report.html` artifacts missing but `junit.xml` is there | `pytest-html`/`pytest-excel` not installed — `uv pip install` used `.[dev]` instead of `.[dev,report]` | Confirm the "Install Python 3.12 and dependencies" step installs the `report` extra, not just `dev` |
| `report.ods` exists but a spreadsheet program can't open it / errors | Missing `odfpy` — without it, pandas would raise at write time rather than silently writing an xlsx file with the wrong extension, so this should fail loudly in the `pytest` job, not show up as a bad download | Confirm `odfpy` is listed in `backend/pyproject.toml`'s `report` extra |
