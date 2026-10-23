# v55 — Download Engine Races & Bookkeeping

Branch: `dev-engine-races` → PR into `main`
Version: `5.55.0`
Wave / slot: 2 / 1
Depends on: v51 (real-Postgres race tests)

## Scope

Ledger items **E2–E12**: the download task's and beat's remaining races, plus attempt-bookkeeping
inaccuracies, each found and deferred across v34–v48. Every race fix is **proven on real Postgres**
with v51's concurrency helpers, never with a "lock was requested" assertion. Each item is its own
commit (`v55: (E2) …`).

## Items

- **E2. The reclaim `UPDATE` re-checks state.** `tasks/beat.py:55-58` updates
  `WHERE id IN (snapshot)`. Add `AND state = <the stale state snapshotted>`, or lock
  `FOR UPDATE SKIP LOCKED` in the same statement, so a track that committed `COMPLETED` after the
  snapshot is never reset.
- **E3. Reclaim double-count.** Reclaiming a still-running download writes a `failed` attempt row,
  and then the real outcome writes another. Make the reclaim row's outcome distinct
  (`reclaimed`, not counted as a network attempt), or have the late real outcome supersede it.
  Either way, one network attempt is counted once. Record the choice.
- **E4. Pacing-sleep reclaim.** `download.py:237` re-checks only `CANCELLED` after the pacing
  sleep. Re-check that the track is still `QUEUED` and owned by this invocation (the reclaim
  generation or attempt token). Otherwise exit without downloading.
- **E5. Guarded `DOWNLOADING` write.** `download.py:308` is a plain assignment. Make it a
  conditional transition (`UPDATE … WHERE id=… AND state='queued' RETURNING`). If 0 rows come back,
  a cancel or reclaim won, so exit cleanly.
- **E6. The cancel event carries counters.** A mid-download cancel publishes before
  `record_attempt`. Publish after the attempt row exists, with `attempt_count`/failures, so the UI
  isn't off by one until reload.
- **E7. No transaction idles during the download.** `download.py:317` reads `track.song_json`
  right after the `DOWNLOADING` commit, opening a transaction that idles for the whole download.
  Load what's needed **before** commit (or `expire_on_commit=False` plus an explicit close), so
  the session holds no transaction across the network call. As a result, the completed row's
  `updated_at` reflects completion. Prove it with `pg_stat_activity` during a real download.
- **E8. spotdl's "file already exists" skip isn't a network attempt.** Detect the skip (spotdl's
  return or log signal, verified against real behavior). Record it as a `skipped_existing` outcome
  with no network path, or as the existing dedup outcome. It must not count as
  `completed direct-ipv4`.
- **E9. Success clears `last_error`/`last_error_type`.**
- **E10. `lookup_failed` clears or ignores `scheduled_at`.** `services/retry.py:205` says "never
  touch scheduled_at" for a reason; read GOTCHAS v40.1 first. Either null it on the terminal
  verdict, or make every reader ignore it for terminal states. Pick the one that doesn't fight
  that reason, and record it.
- **E11. Breaker-held row growth.** One `held` row per track per tick (about 460 in one trip).
  Collapse consecutive holds of the same track into a single row whose `finished_at`/`hold_count`
  advances. Keep the information "held N times from T1 to T2". A migration may add `hold_count`.
- **E12. IPv6 rung where IPv6 isn't routable.** Today the forced-IPv6 rung costs a full ladder wait
  on hosts without IPv6 (accepted in v29, GOTCHAS:3925).
  - Add a cheap, cached routability probe: a UDP connect to a well-known v6 address, which sends
    no packet, with a TTL of minutes.
  - When IPv6 isn't routable, skip the rung. `network_path` shows the skip in attempt history.
  - Verify the real connection destination per the CLAUDE.md network invariant
    (`socket.connect` observation).

## Files owned

`backend/app/tasks/download.py`, `backend/app/tasks/beat.py` (the reclaim and dispatch functions
only; v59 owns the alert watchdog bits later), `backend/app/services/{retry,attempts,network_path,downloads}.py`,
`backend/app/models/track_attempt.py`, one Alembic migration (if E11 needs it), tests.

## Out of scope

`expand.py` (v56). The library and dedup reconcile (v57). Alerting (v59).

## Done when

- [ ] Each of E2, E4 and E5 has a **real-Postgres concurrency test** (v51 helpers) that fails with
      the fix reverted (shown) and passes with it.
- [ ] **E3:** a reclaim of a live download followed by its real completion yields exactly one
      counted network attempt (test, plus a DB query from a real run with a lowered
      `STALE_TRACK_AFTER_SECONDS`).
- [ ] **E6:** a real mid-download cancel's SSE event carries correct counters (a raw `curl -N`
      capture).
- [ ] **E7:** during a real download (`realdl` lock), `pg_stat_activity` shows no
      `idle in transaction` session from worker-dl. A completed row's `updated_at` is ≥ its last
      attempt's `finished_at`.
- [ ] **E8:** a real re-download of an existing file is recorded without a network path, and the
      counters don't increase.
- [ ] **E9/E10:** a fail-then-succeed track has null `last_error`. A `lookup_failed` track never
      reports a next retry in the API or UI.
- [ ] **E11:** a simulated 10-tick breaker hold over 3 tracks writes 3 held rows with
      `hold_count=10`, not 30. The migration up/down/up works on the slot DB.
- [ ] **E12:** on a stack with IPv6 disabled, the IPv6 rung is skipped (attempt history plus a
      `socket.connect` observation). With IPv6 available, it's still used (observation, or a probe
      mock plus a real check on a v6-capable host if available; say which).
- [ ] The ladder is unchanged: v35's ladder-pinning tests pass unmodified.
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `5.55.0`. `uv lock` is in sync. `graphify update .` has been run.
