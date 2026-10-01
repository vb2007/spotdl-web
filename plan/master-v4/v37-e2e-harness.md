# v37 — Playwright E2E Harness

Branch: `dev-e2e-harness` → PR into `main`
Version: `4.37.0`

## Scope

There are no committed browser tests (`frontend/package.json` has no test runner). Every UI
version so far was verified with ad-hoc Playwright scripts in session scratchpads, which were thrown
away afterwards. v31 recorded that v25's UI checks were never re-run in a browser. v38–v45 rewrite
most of the frontend's markup, so they need a regression net that already exists **before** the
first redesign commit.

## Design

- **`@playwright/test`** as a frontend devDependency, with config in
  `frontend/playwright.config.ts` and specs in `frontend/e2e/`. Run with `npm run test:e2e`.
- **Target: the real local stack** (`docker compose up`, the dev database from v32, the real
  backend, the real network). No mocked API, no stubbed SSE. The base URL comes from an env var
  (default: the local `web` origin).
- **Identities.** Two test identities that log in through the **real** `/api/auth/login` (real
  upstream). Credentials come from a gitignored `frontend/e2e/.env.e2e`, with a committed
  `.env.e2e.example`. One is admin on dev, one isn't. Never the owner's real account.
- **Selectors target roles and accessible names** (`getByRole`, `getByLabel`), never CSS classes,
  so v39–v42's restyling doesn't rewrite the suite. Where no accessible name exists, add one.
  That's an accessibility fix, not a test hack, and it also feeds v44.
- **Real downloads are slow and rate-limited.** The suite must not trigger a fresh YouTube
  download per run. Use tracks already in the dev ledger (`skipped_duplicate` resolves
  instantly), plus one opt-in tagged `@network` spec that does a real download, excluded by
  default.
- Desktop (1280×800) and mobile (390×844) projects.

## Baseline specs

1. Login and logout. After logout plus a second identity's login on the same page, no first
   identity rows flash (the v22 `queue.reset()` invariant).
2. Submit a URL. The job appears without a refetch (v23.1's regression), reaches settled, and
   its counts match the API.
3. Expand a job and expand a track. Attempt history loads and the network path renders (v35).
4. File download: the downloaded file's sha256 matches the API-side file (read via a test-only
   path or `docker compose exec`).
5. Hard reload with an incoming or active item still shows it (v34's regression).
6. Admin: `/settings` loads and saving is round-tripped; `/library` loads. Non-admin: direct
   navigation to `/settings`/`/library` yields the app's non-admin behavior, and the admin API
   calls return 404.
7. Cross-user UI: identity B never sees identity A's job title anywhere (jobs scope, tracks
   scope, search).
8. Archive and unarchive round trip, plus "show archived".

## Out of scope

- A CI browser job. The self-hosted runner is the production host, which also runs Synapse and
  Vaultwarden: no browsers or test traffic there. Documented in `docs/LOCAL_DEV.md`, with the
  reason.
- Visual-regression snapshots (pixel diffs churn through the redesign). UI slices attach
  screenshots as evidence instead.
- Backend unit tests (pytest already covers them).

## Done when

- [ ] `npm run test:e2e` runs all eight baseline specs green against the real local stack, on
      both projects (output pasted).
- [ ] Each spec fails when its feature breaks. For specs 1, 2, 5 and 7, temporarily revert the
      relevant fix or filter locally, show the red run, then restore.
- [ ] No spec uses a CSS-class selector (`grep` for `locator('.` in `frontend/e2e/`).
- [ ] The default run makes zero YouTube downloads (worker-dl log shows no download during the
      run). The `@network` spec runs on demand and passes once.
- [ ] Credentials are gitignored (`git check-ignore frontend/e2e/.env.e2e`), with the example file
      committed.
- [ ] `docs/LOCAL_DEV.md` documents running the suite and why it's local-only. The
      implementation prompt's checks line already lists `npm run test:e2e` from v37 on.
- [ ] `npm run lint` and `npm run check` cover `e2e/` too (eslint and tsconfig include it).
      `npm run build` passes. `pytest` passes.
- [ ] Both version files read `4.37.0`. `uv lock` is in sync. `graphify update .` has been run.
