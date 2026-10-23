# v61 — Frontend Store & Navigation Fixes

Branch: `dev-frontend-store-fixes` → PR into `main`
Version: `5.61.0`
Wave / slot: 3 / 4
Depends on: v53 (the store's `view`), v55 (the single-track GET, the breaker flag)

## Scope

Ledger items **F1–F10**: live-store desyncs, navigation data loss and resilience gaps left by
v40.2–v47. Each is its own commit and its own bullet. The owner's v45 decision stands: a row that
stops matching the active filter stays until reload. Don't "fix" that.

## Items

- **F1. Off-page chip move.** A job not on the loaded page can't move its status chip until
  reload. The SSE `job.state` event already says old → new, so adjust `countsByStatus` from the
  event even when the row isn't loaded. Guard against double-counting with the existing
  `lastKnown…` maps, extended to jobs.
- **F2. The load-more race.** "Load more" in the same second as a status change moves a chip
  twice. Fix with an epoch or sequence: counts from a page response older than the latest applied
  event for that job are ignored.
- **F3. `refreshJobRow` error ≠ gone.** Only a **404** drops the row. A network error or 5xx keeps
  it and retries on the next event or reconnect.
- **F4. SSE after sleep.**
  - On `visibilitychange` → visible and `online`: if the stream's last event is older than its
    heartbeat interval, close and reconnect immediately, instead of waiting for the socket timeout.
  - Reconnect triggers the existing resync-on-connect contract.
- **F5. `+error.svelte`.**
  - A root error page in the app's design system (impeccable), en/hu, keyboard-reachable, with a
    way home.
  - It must work under adapter-static for hard navigations, alongside nginx's `try_files`.
  - Verify a hard navigation to an unknown route renders it, not the browser's or nginx's 404.
- **F6. An unsaved-edits guard** on `/settings` and `/account`.
  - `beforeNavigate` plus `beforeunload` when the form is dirty, through `ConfirmDialog` for
    in-app navigation.
  - Keyboard-complete. The shortcut chords (`g s`, etc.) go through the same guard.
- **F7. One `/account` save model.**
  - Today two models coexist (auto-save toggles vs a save button). Pick one with impeccable's
    `clarify`, then apply it consistently to retention, keyboard, language, clock and v52's
    keys section.
  - Record the rule in DESIGN.md.
- **F8. Clear log is disabled when there's nothing to clear** (no settled jobs in the current
  view), with an accessible explanation.
- **F9. Cross-tab identity by push.**
  - A `BroadcastChannel('spotdl-session')` message on login and logout, so other tabs reset their
    stores (`queue.reset()`) and redirect immediately.
  - The existing poll stays as a fallback.
- **F10. A stale progress cache after a re-run.** The progress cache keys on `attempt_count`,
  which a re-run doesn't always bump. Key it on the attempt id or the latest attempt's
  `started_at` instead (v54 may change counting; rebase onto it).

## Files owned

`frontend/src/lib/stores/queue.ts`, `frontend/src/routes/+page.svelte` (stream lifecycle only),
new `frontend/src/routes/+error.svelte`, `frontend/src/routes/{settings,account}/+page.svelte`
(guard and save model), `frontend/src/lib/components/{QueueControls,ConfirmDialog}.svelte`,
`frontend/src/lib/session*.ts` (or wherever the identity poll lives; locate with graphify),
`frontend/nginx.conf` (only if F5 needs it), `frontend/src/DESIGN.md` (the F7 rule), message
JSONs (hotspot), unit tests (`queue.test.ts`) and e2e specs.

## Out of scope

List virtualization (v67). Visual redesigns beyond F5/F7 (v66). Dropping non-matching rows (owner:
keep).

## Done when

- [ ] **F1/F2:** store unit tests reproduce both (they fail before, pass after). On the live slot
      stack, a job settling on page 2 moves its chip immediately (screenshot pair), and a forced
      same-second load-more and settle yields correct counts (e2e).
- [ ] **F3:** with `api` stopped while an event triggers a refresh, the row stays. After restart,
      it updates (e2e or a manual recording).
- [ ] **F4:** after suspending the laptop, or simulating with devtools offline for longer than the
      heartbeat, then coming back online, the stream reconnects within about 2s and the state
      resyncs (timestamps).
- [ ] **F5:** hard navigation to `/does-not-exist` on the **nginx build** (not just Vite) renders
      the app error page in en and hu (screenshots), and home is reachable by keyboard.
- [ ] **F6:** editing `/settings`, then navigating away by link, browser back and a `g d` chord,
      each asks first. Cancel keeps the edit (e2e).
- [ ] **F7:** a single save model is applied across every `/account` section. DESIGN.md is
      updated, with impeccable output recorded.
- [ ] **F8:** clear log is disabled with an explanation on an empty view (screenshot plus an
      accessibility-tree check).
- [ ] **F9:** logging out in tab A resets tab B within 1s, without waiting for the poll
      (two-tab e2e).
- [ ] **F10:** a re-run track shows fresh progress (unit test plus a live check).
- [ ] Full e2e is green on desktop, mobile and `hu`.
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `5.61.0`. `uv lock` is in sync. `graphify update .` has been run.
