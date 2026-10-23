# v52 — Dev Loop & E2E Stability

Branch: `dev-dev-loop` → PR into `main`
Version: `5.52.0`
Wave / slot: 1 / 2
Depends on: v50

## Scope

Close the dev-loop and test-suite friction GOTCHAS kept as workarounds (ledger D1–D7). Four
parallel agents would each hit every one of them, so they're worth fixing at the root.

## Items

- **D1: `uvicorn --reload` hangs while any SSE stream is open** (GOTCHAS:5507; the workaround is
  `docker compose restart api`).
  - Root-cause it: the reloader waits for open connections to close, and SSE never does.
  - Fix it in dev, for example `--timeout-graceful-shutdown`, or SSE generators that exit on
    shutdown.
  - Prove a reload completes with a stream open.
- **D2: Celery workers don't hot-reload** (GOTCHAS:337).
  - Dev-only autoreload, for example `watchfiles --filter python celery …` wrapping each worker
    command in the dev override (`!override` for the command).
  - Production commands stay unchanged (prove with `config`).
  - `worker-dl`'s `--concurrency=1 --prefetch-multiplier=1` is preserved in the wrapped command.
- **D3: a long-running Vite stops opening the confirmation dialog; root-owned
  `.svelte-kit/types` after a new route** (GOTCHAS:679, :5244).
  - Reproduce the dialog failure (keep a session open over hours, or force HMR cycles). Root-cause
    it (likely a stale module instance or a duplicated `<dialog>` after HMR). Fix it.
  - Run the dev `web` container as the host UID, or chown on start, so generated files aren't
    root-owned.
- **D4: dependency changes need `up -d --renew-anon-volumes`** (GOTCHAS:150).
  - Make the dev `node_modules`/`paraglide` volumes self-heal. For example, keyed on a lockfile
    hash, or an entrypoint that runs `npm ci` when `package-lock.json` changed.
  - Document what's left.
- **D5: e2e flakiness.**
  - Spec 12's "start sweep asks first" (2/19) and spec 14's load-more (1 fail). Find the actual
    race; don't add sleeps.
  - Set an explicit retry policy: `retries: 0` locally stays, but a flake then shows as a
    failure with a trace (`trace: 'retain-on-failure'`). Agents need diagnosable failures, not
    silent retries.
- **D6: `localhost:5173` resolving to another server on `[::1]`** (#64). E2E and docs use
  `127.0.0.1:<slot port>` explicitly, building on v50's slot ports.
- **D7.**
  - `svelte-kit sync` mid-suite breaks spec 1: isolate generated files from a running suite, or
    have the suite fail fast with a clear message.
  - Spec 3 needs a prior network pass: give it its own setup, so it runs standalone.

## Files owned

`docker-compose.override.yml` (worker/api/web commands, user and volumes; **not** ports, which
v50 owns and has merged), `frontend/Dockerfile` dev stage if any, `frontend/playwright.config.ts`
(retries/trace only), `frontend/e2e/**` (flaky specs and setup), the component behind D3's dialog
(`frontend/src/lib/components/ConfirmDialog.svelte`), `backend/app/routers/stream.py` (shutdown behavior only),
`docs/LOCAL_DEV.md`, `docs/GOTCHAS.md`.

## Out of scope

Feature changes; production compose (no diff in prod `config`).

## Done when

- [ ] **D1:** with `curl -N /api/stream` open, editing a backend file reloads `api` within a few
      seconds (log timestamps). Before the fix, the same procedure hangs (shown).
- [ ] **D2:** editing `backend/app/tasks/download.py` restarts `worker-dl`/`worker-meta`/
      `worker-expand` in dev (logs). Prod `config` is unchanged (diff). The `worker-dl` command
      still carries `--concurrency=1 --prefetch-multiplier=1` (`config` grep).
- [ ] **D3:** the dialog failure is reproduced before the fix, with the root cause recorded in
      GOTCHAS. After the fix, the dialog still opens after the same procedure. A new route created
      in dev leaves no root-owned files (`find -user root`).
- [ ] **D4:** adding a dev dependency and restarting the stack makes it available without
      `--renew-anon-volumes` (log), or the remaining manual step is documented with its reason.
- [ ] **D5:** spec 12 and spec 14 pass **30 consecutive runs** (loop output). Their race root
      causes are recorded. Failure traces are retained.
- [ ] **D6/D7:** the suite targets `127.0.0.1` with the slot port. Spec 3 passes standalone
      (`--grep`) on a fresh slot DB. `svelte-kit sync` during a run gives a clear failure, or no
      failure.
- [ ] Full e2e is green on desktop, mobile and `hu` against the slot stack.
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `5.52.0`. `uv lock` is in sync. `graphify update .` has been run.
