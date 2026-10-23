# v56 — API Gaps & Expansion Recovery

Branch: `dev-api-gaps` → PR into `main`
Version: `5.56.0`
Wave / slot: 2 / 2
Depends on: v51

## Scope

Ledger items **A1–A8** (API and state-integrity gaps v43–v48 left "for a future master") and **E1**
(expansion stranding). Each is its own commit and its own Done-when bullet.

## Items

- **A1. Conditional `cancel_job`.** `routers/jobs.py:236-262` sets `CANCELLED` unconditionally.
  Only an `expanding`/`active`/`waiting` job can be cancelled, under the existing row lock. A
  settled job returns 409 `job_not_cancellable` with its current state. The frontend re-read
  workaround (`JobRow.svelte:171-174`) is removed.
- **A2. `lookup_failed` cancel consistency.** `_CANCELLABLE_TRACK_STATES` (`jobs.py:21-24`) and
  `_TERMINAL_TRACK_STATES` (`tracks.py:21`) disagree with the UI, which never offers cancel on
  not-found. Make one shared definition (for example `services/track_states.py`). `lookup_failed`
  is terminal and not cancellable, matching the UI. Job cancel leaves those tracks as they are.
- **A3. Single-track GET.** Add `GET /api/tracks/{id}` (owner or admin; non-owner 404) returning
  `track_to_dict` plus the job summary. `TrackRow.svelte:347-354` uses it instead of re-reading up
  to 1000 tracks of the job.
- **A4. Deleting a used proxy.** The FKs `track.used_proxy_id` (`track.py:79`) and
  `track_attempt.proxy_id` (`track_attempt.py:84`) get `ON DELETE SET NULL`, in a migration.
  Attempt history keeps a **denormalized redacted label** captured at write time, so deleting a
  proxy doesn't erase "which proxy". Add it if v35's `proxy_label` isn't already stored. Check
  first.
- **A5. A `retention_days` server bound.** `routers/settings.py:266` gets `1 ≤ days ≤ 36500`
  (matching the client), else 422 `retention_out_of_range`. Add a pytest proving a huge value no
  longer breaks the sweep.
- **A6. A consistent admin 403/404 rule.**
  - Inventory every admin endpoint and its non-admin answer, and pick one rule. The CLAUDE.md v2
    invariant says ids are never confirmed. Proposed: **404 for every admin-only resource**,
    except non-id admin actions where 403 is harmless. Present the table in the PR and apply it.
  - Update the CLAUDE.md invariant line to match.
- **A7. A "breaker active" flag in the API.** `/api/worker/status` returns `breaker_active: bool`
  and `breaker_remaining_seconds`, computed server-side, so the UI stops trusting the client clock
  (#63). Update the pill and `/settings` to use them.
- **A8. Non-admin "retry now".** Today it skips the ladder entirely (#69). **Rule:** a non-admin
  may retry-now a `waiting` track at most once per ladder step. It re-dispatches but doesn't
  reset the step; a second press in the same step returns 429 `retry_cooldown` with the remaining
  time. Admins keep an unrestricted retry. Present the rule to the owner in the PR's first
  comment. If they object, apply their rule instead.
- **E1. Expansion stranding.** A broker error inside `expand_job`'s enqueue loop
  (`tasks/expand.py:33-34, 104-107, 152-153`) leaves the remaining tracks `pending` forever.
  - The task is acked, and a generic "stale pending" sweep was ruled out (it would duplicate).
  - Fix with an **outbox marker**: tracks are created `pending` with an `enqueue_pending` flag (or
    use `scheduled_at = now`). Beat's existing `dispatch_due_tracks` picks them up, so Postgres
    stays the only schedule source (the CLAUDE.md invariant), and a broker failure simply delays
    dispatch to the next tick.
  - Prove no double-dispatch on the happy path.

## Files owned

`backend/app/routers/{jobs,tracks,proxies,settings,worker}.py` (the endpoints named above; v53's
create and v54's list-param edits are already merged), `backend/app/tasks/expand.py`,
`backend/app/models/{track,track_attempt}.py` (the FK only), new `backend/app/services/track_states.py`,
one Alembic migration, `frontend/src/lib/components/{TrackRow,JobRow,WorkerStatusPill,WorkerStatus}.svelte`
(the bits named above), `frontend/src/lib/api.ts`, message JSONs (hotspot), tests.

v55 owns `tasks/download.py` and `beat.py`. E1 needs `dispatch_due_tracks` to see the new marker.
If that requires editing `beat.py`, coordinate by keeping the change to the dispatch query's
`WHERE` clause and noting it in the PR. The rebase protocol handles the merge.

## Deploy notes

A migration altering two FKs (no data rewrite) and possibly a column for E1. Take a `pg_backup` as
usual.

## Done when

- [ ] **A1:** cancelling a settled job returns 409 with its state, and the job is unchanged. A
      concurrent cancel vs a completing last track is a real-Postgres race test (v51 helpers).
- [ ] **A2:** one shared state set. A job cancel leaves `lookup_failed` tracks unchanged, and
      `DELETE` on a `lookup_failed` track returns 409 (pytest plus a real call).
- [ ] **A3:** `GET /api/tracks/{id}` works for the owner and admin and returns 404 for a non-owner
      (the `test_ownership.py` direct-id case). The UI no longer calls the 1000-track re-read
      (network panel).
- [ ] **A4:** deleting a proxy used by real attempts returns 2xx. The attempts keep their redacted
      label (DB query plus UI screenshot).
- [ ] **A5:** `retention_days=10**9` gets 422. Boundaries 1 and 36500 are accepted.
- [ ] **A6:** the admin-endpoint table (endpoint → non-admin status) is in the PR, applied and
      parametrized in pytest over every admin route. The CLAUDE.md line is updated.
- [ ] **A7:** the pill and `/settings` show the correct remaining time with the client clock
      skewed by +2h (browser devtools timezone/clock override, screenshot).
- [ ] **A8:** a non-admin's second retry-now in one step gets 429 `retry_cooldown`, and an admin's
      doesn't (real calls). The owner's response to the rule is linked.
- [ ] **E1:** with the broker made to fail mid-enqueue (Redis paused or a mocked `delay` raising
      after N), every track of the job is dispatched within two beat ticks after recovery, with no
      duplicates (DB plus worker logs on the slot stack).
- [ ] `pytest backend/tests/test_ownership.py` plus `scripts/verify_separation_sse.sh` pass.
- [ ] `pytest`, `npm run lint`, `npm run check`, `npm run build` and e2e pass. Both version files
      read `5.56.0`. `uv lock` is in sync. `graphify update .` has been run.
