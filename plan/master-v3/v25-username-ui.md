# v25 — Usernames & Control Placement

Branch: `dev-username-ui` → PR into `main`
Version: `3.25.0`

## Scope

Two small, unrelated-but-both-daily UX fixes: show usernames instead of email addresses, and move
the worker pause/resume control off the dashboard.

Grouped because each is too small to justify its own PR and neither touches the other's code. If
either grows during implementation, split it out rather than letting a "small UX" PR quietly become
a large one.

## Part 1 — Usernames

The upstream `vb2007.hu-api` already returns the username: `GET /user` behind `isAuthenticated`
reads the `VB-AUTH` cookie and returns the full user document, which includes `username`
(confirmed in `src/controllers/users.ts` and `src/database/users.ts`).

**Store it**, despite the initial instinct not to. The admin's all-users view needs *other* users'
usernames, and the upstream API has no batch endpoint — live-fetching N usernames per page load
would add real latency and load to an API this project doesn't control. Email is already stored, so
username is not a new category of data.

- `users.username` (text, nullable — a user row can exist before a successful `GET /user`).
- `upstream_auth` gains a call to `GET /user` using the `VB-AUTH` cookie the login response
  returned. **The upstream token still never reaches the browser** (the v03 invariant): this is a
  server-to-server call inside the login flow.
- `get_or_create_user` refreshes `username` on every login — the same reconciliation pattern it
  already applies to `is_admin`, so a username changed upstream propagates on next login.
- Degrade gracefully: if the `GET /user` call fails, log it and fall back to email. A flaky upstream
  call must never block a login that already succeeded.
- `GET /api/auth/me` and the admin all-users projection return `username`; the frontend shows
  username with email as the `title` tooltip so the mapping is still discoverable.

## Part 2 — Worker control placement

`WorkerStatus.svelte` currently renders as a full panel at `+page.svelte:168`, between the submit
form and the queue. Its only always-visible content is the admin-only "Receiver power" toggle — a
rarely-used control occupying prime dashboard space, while the genuinely live information (breaker
tripped, worker paused) only appears conditionally.

Split it:

- **The pause/resume toggle and the breaker "release now" button move to `/settings`**, with the
  other admin controls. Both are admin-only already.
- **A compact status pill stays on the dashboard**, visible to everyone: normally a quiet
  one-line indicator, expanding to the breaker countdown when something is actually tripped or
  paused. A non-admin watching a stalled queue must still be able to see *why* — that was the
  original reason this component was visible to everyone (v17) and it stays true.
- Place the pill in the header row alongside the settings/account links rather than as its own
  panel.

Design constraints (`frontend/src/DESIGN.md`): `--signal` amber marks things live *right now*, never
permanent chrome — a paused worker is a stopped receiver, not a live signal, and `WorkerStatus.svelte`
already gets this right today. Preserve it. Mobile stays one cell per line below 640px.

Keep the existing 5s poll (`worker.refresh()`); there is still no SSE event for worker state, and
inventing one is out of scope here.

## Done when

- A real login against the real upstream API populates `username`; the dashboard, `/account`, and
  the admin all-users view all show it instead of the email.
- Changing the username upstream and logging in again updates it — verified against the real API,
  not a mock. (`docs/GOTCHAS.md` v15's testing entry: at least one identity must go through the
  real upstream, not the direct-session-mint fallback.)
- A user whose upstream `GET /user` fails still logs in successfully and shows their email —
  verified by deliberately breaking the call.
- `VB-AUTH` still appears nowhere in any response to the browser (re-grep; this version adds a new
  upstream call, which is a new chance to leak it).
- The pause/resume toggle and breaker release work from `/settings` and are 403 for a non-admin
  against the real API.
- The dashboard pill shows paused/breaker state to a **non-admin** session, with a live countdown,
  and takes visibly less space than the old panel — before/after screenshots.
- Mobile at 390px: header with the pill, real screenshots.
- Keyboard-only reachable (PRODUCT.md requirement) with a visible focus ring.
- Migration round-trips; both version files read `3.25.0`; `graphify update .`
