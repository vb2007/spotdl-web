# v09 — Frontend

Branch: `dev-frontend` → PR into `main`

## Scope

The actual SvelteKit UI wired to everything built so far: login, URL submission, and a live queue
view. This is the first version a non-technical user (i.e. you) can drive end-to-end without curl.

## Tasks

1. **Login page** (`/login`) — email/password form → `POST /api/auth/login`; on success, redirect
   to the dashboard. Show the generic "invalid credentials" error from v03 without distinguishing
   causes (matches the backend's deliberate non-disclosure).
2. **Session guard** — a root `+layout.ts`/`+layout.server.ts` load function that calls `GET
   /api/auth/me`; redirects to `/login` on `401`. Applied to every route except `/login`.
3. **Submit form** (`/`) — single URL text input → `POST /api/jobs`. Shows the new job appearing in
   the queue immediately (optimistic or via the SSE `expanding` event).
4. **Live queue table** — subscribes to `GET /api/stream` via `EventSource`, seeded by `GET
   /api/jobs` + `GET /api/jobs/{id}/tracks` on load and on every stream reconnect (per v08's
   documented contract). Columns: title, artist, album, state (with a distinct visual treatment for
   `waiting` showing a **live countdown to `scheduled_at`**), job it belongs to.
5. **Failed views**: a filter/section for `lookup_failed` tracks (clearly marked as "given up —
   spotdl couldn't find this anywhere") and one for tracks currently in the `waiting` state with
   their next-attempt countdown and current `attempt_count` (so "how many times has this been
   tried" is visible).
6. **Svelte stores**: a single store holding the merged job/track state, updated by both the
   initial REST fetch and incoming SSE events — the store is the only thing components read from,
   so the SSE-vs-REST plumbing stays in one place.
7. Basic responsive layout — this is a personal tool, not a design showcase; prioritize legibility
   of a long scrolling table over visual polish. (Flag if you want an actual design pass — the
   `frontend-design` skill exists for that but wasn't requested.)
8. `graphify update .`

## Files touched (new)

`frontend/src/routes/login/+page.svelte`, `frontend/src/routes/+layout.server.ts`,
`frontend/src/routes/+page.svelte`, `frontend/src/lib/stores/queue.ts`,
`frontend/src/lib/api.ts` (typed fetch wrappers for every backend endpoint so far).

## Done when

- Full flow works in a real browser through the Cloudflare Tunnel: log in, paste a playlist URL,
  watch tracks appear as `pending`, then flow through `downloading` → `completed` live, with no
  manual refresh.
- A track that hits `waiting` shows a visibly ticking countdown that matches `scheduled_at` from
  the backend.
- Reloading the page mid-download resumes showing correct live state (proves the REST-refetch +
  SSE-resume contract from v08 actually works end-to-end).
- Logging out clears the session and redirects; navigating to `/` while logged out redirects to
  `/login` without ever rendering queue data.
