# v58 — Durable Alert Delivery

Branch: `dev-alert-delivery` → PR into `main`
Version: `5.58.0`
Wave / slot: 3 / 1
Depends on: v54 (beat.py reclaim edits merged), v50

## Scope

Ledger items **O1, O2, O4, O5, O6**. A real production breaker trip on 2026-10-18 reached
`breaker_events`, but **never reached the Matrix room**, and its cause can't be reconstructed
(the logs are gone). Today, alerts are fire-and-forget Celery sends:

- `retry=False`, `expires=300`, on the shared `meta` queue (`services/alerts.py:88,272-278`);
- nothing records whether one was sent, failed or got suppressed.

This version makes alert delivery durable and visible. O3 (logs surviving deploys) is v59.

## Tasks

1. **Investigate O1 first.**
   - Reproduce on the slot stack every plausible loss path:
     - the `meta` queue backlog exceeding `expires=300` (e.g. a long library sweep or a
       housekeeping task occupying `worker-meta`);
     - `worker-meta` restarting with the message prefetched;
     - the cooldown key suppressing a first alert;
     - a Matrix 429 or 5xx.
   - Record which ones reproduce. The fix below must cover every reproduced path.
2. **A Postgres alert outbox**, in line with the CLAUDE.md "Postgres is the schedule source of
   truth" principle.
   - New `alert_outbox` table: `id`, `category`, `fingerprint`, `body` (already redacted),
     `created_at`, `state` (`pending`/`sent`/`failed`/`suppressed`), `attempts`,
     `next_attempt_at`, `last_error` (redacted), `sent_at`.
   - `send_alert` **inserts a row** (cooldown and dedupe are decided here, and `suppressed` rows
     are recorded too) and returns.
   - A beat-driven `deliver_alerts` task (on `worker-meta`, every tick) sends due rows with backoff
     (e.g. 30s → 2m → 10m → 1h, give up after 24h → `failed`).
   - It **never blocks or fails** any download, request or deploy (a v4 locked decision). A send
     failure stays a log warning plus a row state.
   - Matrix `txn` id = the outbox row id, so a retry can't double-post.
   - Retention: keep 30 days of rows (an hourly prune).
3. **O4: the worker-down category.**
   - Alert when `worker-dl` hasn't consumed a due track for longer than a threshold while the
     breaker is closed and due tracks exist.
   - Signal: `track_attempts` max `started_at` vs the oldest due `scheduled_at`. No new heartbeat
     unless that's insufficient; record the reasoning.
   - Admin toggle in the existing alert settings.
4. **O5: throttle Redis-outage logging.** One traceback, then a single "still down (N checks)" line
   every 10 min, plus a recovery line.
5. **O6: alert history.**
   - A panel on `/stats` (admin) listing recent outbox rows: time, category, state, attempts, and
     a body preview.
   - Server-side paging in one request (the bulk invariant).
   - Designed with impeccable in the existing stats surface, en/hu, keyboard-reachable.
6. Update the watchdog (`services/alert_watchdog.py`) and the existing categories to go through the
   outbox. Change no category's semantics.

## Files owned

`backend/app/services/{alerts,alert_watchdog}.py`, `backend/app/tasks/alerts.py`,
`backend/app/tasks/beat.py` (the schedule entry and alert hooks only), `backend/app/routers/admin.py`
(the alert-history endpoint), new model plus migration, `frontend/src/routes/stats/+page.svelte`
and `frontend/src/lib/components/stats/*` (the new panel), message JSONs (hotspot), tests.

## Deploy notes

A new table (additive). No new required env vars.

## Done when

- [ ] **O1 investigation:** each candidate loss path was tried on the slot stack, and the result
      for each is recorded in GOTCHAS. Each reproduced path is now covered by a test that loses
      the alert before the fix (shown) and delivers it after.
- [ ] **Outbox:** a real breaker trip on the slot stack produces a `pending` row → `sent`, and the
      message arrives in a **dev** Matrix room (screenshot). The room must not be production's
      alert room. The owner provides or approves the test room, or the agent uses the dev room
      already configured.
- [ ] **Retry:** with the homeserver unreachable, the row backs off (`attempts` and
      `next_attempt_at` advance). After restoring it, exactly one message arrives (no duplicate
      `txn`).
- [ ] **Never blocks:** with Matrix unreachable, a real download completes on time (`realdl`).
- [ ] **Cooldown** decisions are recorded as `suppressed` rows (DB query).
- [ ] **Worker-down** fires when `worker-dl` is stopped with due tracks and the breaker closed,
      and doesn't fire while the breaker is tripped (two real runs).
- [ ] **Redis outage:** stopping Redis for 25 min logs one traceback, ≤3 "still down" lines and
      one recovery line (log excerpt).
- [ ] **History panel:** shows sent, failed and suppressed rows. Non-admin gets 404 on its
      endpoint (pytest). Screenshots in en/hu; impeccable output recorded.
- [ ] Every alert body in the outbox is redacted (test with a credential-bearing proxy error).
- [ ] `pytest`, `npm run lint`, `npm run check`, `npm run build` and e2e pass. Both version files
      read `5.58.0`. `uv lock` is in sync. `graphify update .` has been run.
