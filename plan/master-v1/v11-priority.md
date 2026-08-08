# v11 — Job Priority / Reordering

Branch: `dev-priority` → PR into `main`

## Scope

Let a job jump the queue. The `jobs.priority` column already exists (added in v02 specifically to
avoid a migration here) — this version is purely the dispatch-order change plus the UI to control
it.

## Tasks

1. `dispatch_due_tracks` (v06/beat.py) ordering: change the "select due tracks" query from
   implicit/creation order to `ORDER BY jobs.priority DESC, tracks.scheduled_at ASC` (joining
   `tracks` to `jobs`), so higher-priority jobs' due tracks are dispatched first among everything
   currently eligible. Note this only reorders *among tracks that are already due* — it cannot make
   a `waiting` track with a future `scheduled_at` jump ahead of the ladder; that's intentional,
   priority controls dispatch order, not the backoff contract.
2. `PATCH /api/jobs/{id}/priority` — body `{priority: int}`, behind `require_session`. Simple set;
   no need for a complex ranking scheme at this scale (a handful of concurrent jobs, single user).
3. `POST /api/jobs/{id}/bump` — convenience endpoint: sets this job's priority to
   `max(all current priorities) + 1` — "move to front" as a one-click action, which is almost
   certainly the only interaction pattern actually needed day-to-day.
4. **Frontend**: a "bump to front" button per job in the queue view; an optional numeric priority
   display/edit for finer control.
5. `graphify update .`

## Files touched (new)

Edits to `backend/app/routers/jobs.py` (priority endpoints), `backend/app/tasks/beat.py` (order
by), frontend job row component.

## Done when

- With two jobs having due tracks simultaneously, bumping the newer job's priority causes its
  tracks to be dispatched first on the next beat tick, verified by dispatch order in logs/DB
  timestamps.
- Priority has no effect on tracks still waiting out their ladder delay — only reorders among
  currently-due tracks, confirmed by a test where a low-priority job's track is due and a
  high-priority job's track is not yet due: the low-priority one still dispatches (nothing to
  reorder against).
