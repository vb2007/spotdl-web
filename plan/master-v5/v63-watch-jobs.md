# v63 — Watched Playlists & Artists, Job-Level Re-run

Branch: `dev-watch-jobs` → PR into `main`
Version: `5.63.0`
Wave / slot: 4 / 1
Depends on: waves 0–3 merged (v56's expansion outbox marker in particular)

## Scope

A job is a one-shot expansion today: a playlist that gains tracks next week, or an artist who
releases an album, is never picked up again. That runs against the app's core goal of getting
everything, over however long it takes. This version adds:

1. **Watched jobs:** a playlist or artist job can be marked *watched*. It's re-expanded on a
   schedule, and only tracks new to that job get queued.
2. **Re-run expansion** on any job, as a one-off (the same mechanism, run now).
3. **"Retry all failed"**: re-dispatch every `waiting` track of a job (and optionally
   `lookup_failed`, which is terminal by locked decision, so only via an explicit admin choice;
   see below).

## Design

- **Schema:** `jobs.watch_interval_hours` (null = not watched), `jobs.last_expanded_at`,
  `jobs.next_expand_at`. Only `playlist`/`artist` (and `album`, for deluxe re-releases? No: albums
  are immutable enough, so not offered) can be watched. Owner-settable on their own job; admin on
  any.
- **Scheduling:** beat's existing tick selects due watched jobs (`next_expand_at <= now`, jobs not
  archived and not cancelled), and dispatches `expand_job` in **re-expand mode** on the `expand`
  queue (`worker-expand`). `scheduled_at`-style Postgres scheduling only (the invariant: no Celery
  ETA).
- **Re-expand mode:** fetch the current track list and insert only tracks whose Spotify id isn't
  already in the job. Dedup still applies at download time (a ledger hit → `skipped_duplicate`
  instantly). Removed tracks aren't deleted from the job. The job's rollup returns to `active`
  while new tracks are pending, and the UI says "N new since <date>".
- **Rate-limit respect:** re-expansion is metadata-only (Spotify API), but has a global cap (at
  most K re-expansions per hour, default small), and a minimum interval of 24h (UI choices: daily,
  weekly, monthly). While the breaker is tripped, re-expansion may still run, but its new tracks
  wait like any other.
- **Re-run now:** `POST /api/jobs/{id}/reexpand` (owner/admin, non-owner 404) runs the same thing
  immediately. One at a time per job (409 `reexpand_running`).
- **Retry all failed:** `POST /api/jobs/{id}/retry-failed` re-dispatches every `waiting` track
  through the same rules as single retry, including v56's non-admin once-per-step rule, applied
  per track. Admin-only extra: `?include_not_found=true` resets `lookup_failed` tracks to `queued`
  for one more attempt. That's an explicit override of the "terminal" rule, so it's admin-only,
  behind `ConfirmDialog`, and recorded in attempt history as `manual_override`.
- **UI:** in the JobRow actions (impeccable, existing system):
  - a "watch" control with an interval (`ConfirmDialog` not needed);
  - a watched badge with the next check time;
  - "check now", and "retry failed" (with count).

  en/hu, keyboard bindings registered (Hungarian QWERTZ rules; proposed `w` = toggle watch,
  `Shift+R` = retry failed, checked against the registry), and the help overlay updates
  automatically.
- **Alerts:** none by default (a watched job finding new tracks isn't an operator event). v66's
  personal notifications may announce it.

## Files owned

`backend/app/tasks/expand.py` (re-expand mode), `backend/app/tasks/beat.py` (the watched-job
selection only), `backend/app/routers/jobs.py` (new endpoints), `backend/app/services/expansion.py`,
`backend/app/models/job.py`, a migration, `frontend/src/lib/components/JobRow.svelte` (watch and
retry controls; v64 adds an export control in the same wave, so keep to separate, clearly
delimited blocks), `frontend/src/lib/api.ts`, `frontend/src/lib/keyboard/bindings.ts`, message
JSONs (hotspot), tests.

## Out of scope

Removing tracks that disappeared from a playlist. Watching albums. Notifications (v66).

## Deploy notes

A migration adding three nullable columns (additive).

## Done when

- [ ] Watching a **real** playlist on the slot stack: set a 24h interval, then force
      `next_expand_at` to now. After one beat tick, the re-expansion ran and **only new tracks**
      were added. To simulate "new", delete one track row from the job first, and it comes back
      as exactly one new track (DB before and after).
- [ ] Re-expanding a real artist job adds nothing when nothing changed. Ledger-present tracks
      resolve `skipped_duplicate`.
- [ ] The global cap holds: K+1 due watched jobs in one hour → only K run, and the rest run next
      hour (test plus real beat logs with a low K).
- [ ] `reexpand` endpoint: owner and admin succeed, non-owner gets 404 (`test_ownership.py`),
      concurrent runs get 409.
- [ ] Retry failed:
  - re-dispatches every `waiting` track (count matches);
  - the non-admin per-step rule holds;
  - admin `include_not_found` requires the confirmation and records `manual_override`
    (attempt history screenshot).
- [ ] No Celery ETA/countdown is introduced (grep). Scheduling is Postgres-only.
- [ ] The UI works keyboard-only; en/hu screenshots; impeccable output recorded. An e2e spec
      covers watch and retry-failed.
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `5.63.0`. `uv lock` is in sync. `graphify update .` has been run.
