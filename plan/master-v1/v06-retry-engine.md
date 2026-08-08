# v06 — Retry Engine

Branch: `dev-retry-engine` → PR into `main`

## Scope

Replace v05's naive `except Exception → failed` with real error classification, the per-track
backoff ladder, `scheduled_at`-driven dispatch (not Celery ETA — see master plan), and the global
circuit breaker. This is the heart of the tool's stated purpose.

## Why not Celery `eta`/`countdown`

With the Redis broker, ETA-scheduled tasks are held in worker memory until due. A worker restart
during a 24-hour wait silently drops or duplicates that wait. Postgres `tracks.scheduled_at` is
therefore the only source of truth; Celery Beat polls it.

## Tasks

1. `app/services/retry.py`:
   - `classify_error(exc) -> Literal["audio_provider", "lookup", "other"]` — `AudioProviderError`
     → `audio_provider`; `LookupError` → `lookup`; anything else → `other`.
   - `LADDER = [timedelta(minutes=15), timedelta(hours=1), timedelta(hours=4), timedelta(hours=12),
     timedelta(hours=24)]` (overridable via `LADDER_SECONDS` env for tests — a comma-separated list
     that replaces the ladder wholesale when set, so a 5-step ladder can run in under a minute).
   - `next_delay(attempt_count) -> timedelta` — `LADDER[min(attempt_count, len(LADDER)-1)]`.
   - `record_failure(track, error_type, message)`:
     - `lookup` → `state=lookup_failed` (terminal), `last_error`/`last_error_type` set. Never
       touch `scheduled_at`. Notify (v08's event stream will pick this up).
     - `audio_provider` → `attempt_count += 1`, `state=waiting`,
       `scheduled_at = now() + next_delay(attempt_count)`, increment global
       `worker_state.consecutive_failures`, call `maybe_trip_breaker()`.
     - `other` → same ladder as `audio_provider` for now (simplest correct behavior; the master
       plan allows a shorter ladder + eventual `failed` here, but infinite retry is the safer
       default for "never lose a track").
   - `record_success(track)` — `worker_state.consecutive_failures = 0`, clears any breaker trip
     (`breaker_tripped_until = NULL`, `breaker_trip_count = 0`) since the master plan specifies the
     breaker resets on first success.
   - `maybe_trip_breaker()` — if `consecutive_failures >= 5`: `breaker_trip_count += 1`,
     `breaker_tripped_until = now() + [30m, 2h, 6h][min(trip_count-1, 2)]`.
2. Rework `app/tasks/download.py`'s error handling to call `classify_error` +
   `retry.record_failure`/`record_success` instead of the v05 placeholder branch. Also check
   `worker_state` at task start: if `breaker_tripped_until > now()` or `paused` (column exists from
   v02, real pause behavior lands in v10), re-schedule the track to `waiting` at
   `breaker_tripped_until` and return without attempting — covers the race where a task was queued
   just before the breaker tripped.
3. `app/tasks/beat.py` — `dispatch_due_tracks` Celery Beat task, every 30s:
   `SELECT ... FROM tracks WHERE state='waiting' AND scheduled_at <= now() FOR UPDATE SKIP LOCKED`,
   flip to `queued`, enqueue `download_track` on the `downloads` queue. Skips entirely (no query)
   while the breaker is tripped or the worker is paused, to avoid a thundering herd exactly when
   the breaker releases.
4. Proxy escalation seam (attempt-count → direct/proxy decision) is a one-line hook here
   (`use_proxy = track.attempt_count >= 1`) but proxy **selection** itself is v07 — until then this
   just means "second+ attempts are marked as wanting a proxy" with no proxy pool to draw from yet;
   leave a clear `# TODO(v07)` rather than half-implementing pool logic.
5. Celery Beat schedule config (`beat_schedule`) registering `dispatch_due_tracks` at a 30s
   interval.
6. `graphify update .`

## Files touched (new)

`backend/app/services/retry.py`, `backend/app/tasks/beat.py`; edits to
`backend/app/tasks/download.py`, Celery app config.

## Done when

- With `LADDER_SECONDS` shortened for testing and `FAULT_INJECT` (or an equivalent manual trigger)
  forcing `AudioProviderError`, a track's `attempt_count`/`scheduled_at` progresses through the
  full ladder and settles at the final step, retrying forever.
- 5 consecutive `AudioProviderError`s (any tracks) trip `worker_state`; `dispatch_due_tracks`
  dispatches nothing while tripped; a manual success clears the trip and resets the counter.
- `docker compose restart worker-dl beat` mid-wait: on restart, the same track resumes at the
  correct `scheduled_at` with no duplicate dispatch and no lost wait — verified via SQL, not logs.
- A `LookupError` track moves to `lookup_failed` and is never touched again by
  `dispatch_due_tracks` (its `scheduled_at` stays untouched/null).
