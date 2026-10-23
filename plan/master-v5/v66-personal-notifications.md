# v66 — Personal Notifications & "My Stats"

Branch: `dev-personal-notifications` → PR into `main`
Version: `5.66.0`
Wave / slot: 4 / 4
Depends on: waves 0–3 merged

## Scope

Alerts (v36/v59) serve the operator only. A regular user who queues an album and walks away has no
way to learn that it's done short of checking back. The stats page (v44) is admin-only and
global. This version adds, per user:

1. **Browser notifications** when one of *their own* jobs settles (complete or partial). A
   watched job (v63, same wave) that finds new tracks goes back to `active` and settles again, so
   it's covered by the same settle notification with no dependency on v63's code.
2. **"My stats"**: a non-admin view of their own downloads.

## Design

- **Notifications.**
  - The Notification API, in-page, driven by the user's **own** SSE stream. That stream is already
    owner-scoped: `view=mine` always, even for an admin who's currently viewing all or others
    (v54). It never announces someone else's job.
  - No Web Push or server push infrastructure: notifications work while an app tab (or the
    installed PWA, v65) is open.
  - A per-user setting on `/account` (stored server-side like the other per-user prefs), off by
    default. Turning it on calls `Notification.requestPermission()` from the user's click, and a
    denied permission is explained.
  - Content: the job title plus the outcome ("Done — 9 of 10"), localized (en/hu), matching the
    rollup copy. Clicking focuses the tab and the job.
  - De-duplicated across multiple open tabs via v62's `BroadcastChannel`: one tab announces.
- **My stats.**
  - `GET /api/stats/me?window=…`, owner-scoped by construction (the session user only, no
    parameter for another user).
  - Same windows as admin stats: completed tracks, failures by class, time-to-complete median,
    jobs by outcome, and total library contribution (files and size).
  - Aggregated in SQL in **one request** (the bulk invariant), reusing `services/stats.py`'s
    builders with an owner predicate rather than a parallel implementation.
  - **Frontend:** `/stats` renders "my stats" for everyone. Admins additionally see the existing
    global sections, plus a toggle between mine and global. No new route, so no new nginx
    location; confirm `/stats` is reachable for non-admins at the nginx level (today it may 404 or
    redirect non-admins, so check).
  - impeccable plus the dataviz skill for any chart, keyboard-reachable charts with text
    alternatives (v44's pattern), en/hu.

## Files owned

`backend/app/services/{stats,user_settings}.py`, `backend/app/routers/admin.py` (only if the
admin stats builder is refactored for reuse; the new endpoint goes in a new
`backend/app/routers/stats.py`), migration if a new per-user setting column is needed,
`frontend/src/routes/stats/+page.svelte` and `frontend/src/lib/components/stats/*` (v59's history
panel is already merged), new `frontend/src/lib/notifications.ts`,
`frontend/src/routes/account/+page.svelte` (notifications toggle block only; v65 touches the
install block), `frontend/src/routes/+page.svelte` (wiring only), message JSONs (hotspot), tests.

## Out of scope

Email, Matrix-per-user or Web Push. Notifications for other users' jobs. Per-user stats visible to
others.

## Done when

- [ ] With notifications on in a real Firefox and a real Chrome, the user's own album job
      settling on the slot stack shows exactly one notification across two open tabs
      (screenshot). Another user's job settling shows none (two identities).
- [ ] An admin in `all`/`others` view gets notified only for their own jobs.
- [ ] A denied permission shows the explanation, and the toggle state stays truthful.
- [ ] The preference persists server-side and is owner-scoped (pytest plus `test_ownership.py`).
- [ ] `GET /api/stats/me` matches hand-written SQL for that user (both outputs). No request
      parameter can target another user (pytest). One request per load (network panel).
- [ ] A non-admin sees "my stats" on `/stats` through the **nginx build** by hard navigation. The
      admin sees mine and global, plus the toggle (screenshots).
- [ ] Charts follow dataviz, with text alternatives; impeccable output recorded; en/hu; keyboard
      journey extended in e2e.
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `5.66.0`. `uv lock` is in sync. `graphify update .` has been run.
