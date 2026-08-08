# v10 — Queue Controls

Branch: `dev-queue-controls` → PR into `main`

## Scope

Manual intervention controls: cancel, retry-now, and pause/resume the whole worker. Per your
answer, reorder/priority is deliberately **not** in this version — it's split out to v11 so this
one ships sooner.

## Tasks

1. **Cancel job/track**
   - `DELETE /api/jobs/{id}` — sets the job and every non-terminal track under it (anything not
     `completed`/`skipped_duplicate`) to `cancelled`. If a track is currently mid-download, mark it
     for cancellation and have `download_track` check a `cancelled` flag after the (blocking)
     `search_and_download` call returns, discarding the result rather than trying to interrupt
     spotdl mid-download (spotdl's call is synchronous and not cleanly interruptible).
   - `DELETE /api/tracks/{id}` — same, single track.
2. **Retry now**
   - `POST /api/tracks/{id}/retry` — valid for `waiting`, `lookup_failed`, or `failed` tracks:
     resets `scheduled_at = now()` (and for `lookup_failed`, flips `state` back to `waiting` since
     it's normally excluded from dispatch) so the next `dispatch_due_tracks` tick picks it up
     immediately. Explicitly bypasses both the per-track ladder wait and — if the breaker is
     tripped — still respects the breaker (a manual retry shouldn't be able to defeat the breaker
     that exists specifically to stop hammering a rate-limited provider). Document this precedence
     clearly in the endpoint's response if it's deferred rather than dispatched immediately.
3. **Pause / resume worker**
   - `POST /api/worker/pause` / `POST /api/worker/resume` — toggles `worker_state.paused`.
     `dispatch_due_tracks` already checks this column (seam left in v06) — confirm/wire it fully
     here.
   - `GET /api/worker/status` — returns `{paused, breaker_tripped_until, breaker_trip_count,
     consecutive_failures}` so the UI can show the breaker countdown even without a dedicated
     event type.
   - `POST /api/worker/breaker/release` — manually clears `breaker_tripped_until` early (the "end
     it early" option from your answer). Does not reset `consecutive_failures` or
     `breaker_trip_count` — a manual release is not the same as an earned recovery, so the next
     failure re-trips at the *next* escalation step, not back at 30m.
4. **Frontend**: cancel buttons on job rows and track rows; a "retry now" action on
   `waiting`/`lookup_failed`/`failed` rows; a global pause/resume toggle with a live breaker
   countdown (reusing v09's countdown component) and a "release now" button when tripped.
5. `graphify update .`

## Files touched (new)

`backend/app/routers/worker.py`; edits to `backend/app/routers/jobs.py` (cancel), a new
`backend/app/routers/tracks.py` (retry/cancel single track), edits to `backend/app/tasks/beat.py`
(confirm paused-check), frontend queue table + a new worker-status widget.

## Done when

- Cancelling a job stops all its non-terminal tracks from ever being dispatched again; a track
  mid-download at cancel time still finishes but its result is discarded and state ends
  `cancelled`.
- Retry-now on a `waiting` track dispatches within one beat tick regardless of how far out
  `scheduled_at` was, but is correctly held if the global breaker is tripped (verified by tripping
  the breaker first, then confirming retry-now doesn't dispatch until release/expiry).
- Pause stops all dispatch immediately (verified: no new `download_track` invocations while
  `paused=true`, even for due `waiting` tracks); resume picks back up without duplicate dispatch.
- Manual breaker release clears the countdown immediately in the UI and a subsequent failure
  re-trips at the next escalation step (not reset to 30m).
