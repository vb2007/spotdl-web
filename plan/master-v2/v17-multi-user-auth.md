# v17 — Multi-User Auth & Ownership Enforcement

Branch: `dev-multi-user-auth` → PR into `main`

## Scope

Make v16's schema real: users get created, admin gets designated, and **every** data path becomes
owner-scoped — REST, SSE, and the Celery tasks that publish events. This is the version where data
separation either works or silently doesn't, so it gets the heaviest verification in v2.

## The threat model, stated plainly

There are three separate people using one deployment. The property to guarantee is: *a
non-admin user cannot observe or affect another user's jobs, tracks, or downloads through any
surface the app exposes.* Three surfaces exist, and it is easy to fix only the first:

1. **List endpoints** — the obvious one.
2. **Direct-id endpoints** — `GET /api/jobs/{id}`, `DELETE /api/tracks/{id}`,
   `POST /api/tracks/{id}/retry`, `PATCH /api/jobs/{id}/priority`, `POST /api/jobs/{id}/bump`.
   Filtering lists while leaving `_get_job_or_404` unscoped means anyone who learns a uuid gets
   full access. **These must return 404 (not 403) for a non-owner**, so the endpoint doesn't
   confirm the id exists.
3. **The SSE stream** — currently the worst of the three, see below.

## SSE is the non-obvious one

`app/services/events.py:21` publishes everything to a single `CHANNEL = "spotdl:events"`, and
`app/routers/stream.py:25` subscribes every connected client to it. Today every logged-in user
already receives every other user's track ids, job ids, titles, and error strings live on the wire.
Adding `user_id` to the database without fixing this produces an app that *looks* separated while
still leaking through the live stream — and no REST-level test would catch it.

**Fix**: channel per user — `spotdl:events:{user_id}`. Publishers must therefore know the owning
user. `download_track` and `beat.dispatch_due_tracks` have the `Track`, so they resolve
`track.job.user_id` (one join, or carried on the already-loaded job); `expand_job` has the `Job`
directly. `publish_track_event`/`publish_job_event` take the owner as a required argument rather
than an optional one, so a new call site cannot forget it and silently fall back to broadcasting.

Admin's "all users" view subscribes to a pattern (`psubscribe spotdl:events:*`) only when the
session is admin *and* the toggle is on — decided server-side from the session, never from a
client-supplied flag.

## Tasks

1. **`app/services/users.py`** — `get_or_create_user(db, email)`: normalizes the email, returns the
   existing row or creates one, sets `last_login_at`. Admin designation on creation: `is_admin =
   (email == ADMIN_EMAIL)`. On every login, reconcile the flag against `ADMIN_EMAIL` so changing
   the env var takes effect without manual SQL, and so exactly one admin exists.
2. **`ADMIN_EMAIL` env var** (`config.py`, `.env.example`, both compose files). It must also be
   present in `ALLOWED_EMAILS` — validate this at settings load and fail loudly at startup if not,
   rather than producing a deployment where the admin can't log in.
3. **`routers/auth.py`** — `login` calls `get_or_create_user` after the allowlist check and binds
   the session to `user_id`. `require_session` resolves and returns the `User` (not the
   `UserSession`) so every downstream route has the owner and the admin flag in one object. Add a
   `require_admin` dependency alongside it. `GET /api/auth/me` returns `{email, is_admin}` so the
   frontend can hide admin-only UI — hiding it is cosmetic, the server-side gate is the real one.
4. **Scope every query** in `routers/jobs.py` and `routers/tracks.py`:
   - `_get_job_or_404` / `_get_track_or_404` gain an owner check → 404 on mismatch.
   - `create_job` sets `user_id` from the session.
   - List endpoints filter by owner (pagination arrives in v18; keep the current shape here).
5. **Admin-gate** `routers/settings.py`, `routers/proxies.py`, and `routers/worker.py` behind
   `require_admin`. Worker pause/resume and breaker release are global controls affecting everyone's
   downloads — they belong to admin, not to whoever clicks first.
   Exception: `GET /api/worker/status` stays readable by any authenticated user, since v20's UI
   needs it to explain *why* a queue looks stalled. Read-only, no ids, no cross-user data.
6. **Per-user SSE** as described above, including the admin pattern-subscribe path.
7. **Frontend**: `api.ts` gains `is_admin` on the session type; the settings link and worker
   controls render only for admins; a "showing: mine / all users" toggle appears for admins only.

## Done when

Each bullet verified individually, against the real stack with two real allowlisted accounts —
not extrapolated from one another:

- User A's `GET /api/jobs` and `GET /api/tracks` contain zero rows belonging to user B.
- **Direct-id access**: with a job id and a track id belonging to A, every one of `GET
  /api/jobs/{id}`, `GET /api/jobs/{id}/tracks`, `DELETE /api/jobs/{id}`, `DELETE /api/tracks/{id}`,
  `POST /api/tracks/{id}/retry`, `PATCH /api/jobs/{id}/priority`, `POST /api/jobs/{id}/bump`
  returns **404** for B's session. Tested endpoint by endpoint — one passing endpoint proves
  nothing about the others.
- **SSE**: `curl -N /api/stream` as B, captured raw for the full duration of a real download
  belonging to A, contains **zero** of A's track or job ids. Captured from the wire, not judged
  from the UI.
- **Admin gating from a real non-admin session**: every `settings`/`proxies`/`worker` mutation
  endpoint returns 403, verified against the running API; `GET /api/worker/status` still returns
  200.
- Admin's default view shows only their own jobs; the "all users" toggle reveals others' and the
  admin SSE pattern-subscribe delivers their events.
- A user whose email is in `ALLOWED_EMAILS` but who has never logged in gets a `users` row created
  on first successful login, with `is_admin` false.
- Startup fails loudly and clearly when `ADMIN_EMAIL` is absent from `ALLOWED_EMAILS`.
- `graphify update .`
