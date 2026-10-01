# v36 — App Alerting (Matrix)

Branch: `dev-alerting` → PR into `main`
Version: `4.36.0`

## Scope

The app fails silently. The retry ladder makes a 100%-failing download look identical to a slow
one, which is exactly how v23's outage and v31.1's `android_vr` block went unnoticed until someone
looked. This version pushes the conditions that need a human into the same Matrix room v33's
pipeline uses.

## Design

- **`backend/app/services/alerts.py`**: a single `send_alert(category, text)` built on `httpx` (the
  backend's existing HTTP stack). It calls
  `PUT {MATRIX_HOMESERVER_URL}/_matrix/client/v3/rooms/{MATRIX_ROOM_ID}/send/m.room.message/{txn}`
  with `Authorization: Bearer {MATRIX_ACCESS_TOKEN}`, `msgtype: m.notice`, and a
  uuid/deterministic `txn`.
- **Never in the hot path.** Alerts are sent from a Celery task on the `meta` queue
  (`worker-meta`), enqueued fire-and-forget. A send failure is logged once and dropped. It never
  raises into, delays, or retries a download.
- **Configuration.**
  - `MATRIX_HOMESERVER_URL`, `MATRIX_ACCESS_TOKEN` and `MATRIX_ROOM_ID` in `app/config.py`, all
    **optional** (no `:?` in compose). Absent means alerts are off, logged once at startup.
  - These are the first new `.env` variables since v33, and the first real test of v33's
    preflight in the safe direction: it must pass with them absent.
  - Add them to `.env.example`/`.env.dev.example` (commented) and to `docs/DEPLOYMENT.md`.
  - The access token is a secret: never logged, never returned by any endpoint.
- **Redaction.** Every alert body goes through `proxies.redact()` before sending. spotdl's errors
  echo proxy credentials (the CLAUDE.md invariant).
- **Dedupe/cooldown per category**, stored in Redis (a TTL key per category plus fingerprint), so a
  restart doesn't re-fire and two workers can't double-send. Defaults are documented and
  overridable by settings.
- **Admin settings.** Per-category on/off toggles in the `app_settings` singleton (reuse its
  get-or-create), plus a **"send test alert"** button in `/settings` (`POST
  /api/settings/alerts/test`, admin-only, non-admin 404). Minimal UI in the existing settings style.
  The visual redesign of settings is v42.

## Categories

1. **Breaker tripped / escalated / released**, at the existing trip point in
   `backend/app/services/retry.py`: the step (30m/2h/6h) and the last error class. Release is
   included so the room shows recovery.
2. **Failure-class spike**: N consecutive attempts (any track) failing with the same `error_type`,
   e.g. `NO_OUTPUT` or a 403. This is the early warning that YouTube changed something and
   `YOUTUBE_PLAYER_CLIENTS` needs retuning (v31.1). N and the window are settings. Computed from
   `track_attempts` (v35's `error_type`), not a new counter.
3. **Beat stale**: beat writes a heartbeat (Redis key with a timestamp) on every
   `dispatch_due_tracks` tick. A check outside beat raises an alert when the heartbeat is older
   than a threshold. The check runs in `worker-meta`, on a lightweight interval *not* driven by
   beat itself, since beat is the thing that's dead. Implement it as a tiny loop or a timer in a
   process that isn't beat, and record the choice.
4. **Library sweep finished or failed** (v28's task): counts and, on failure, the redacted error.
5. **Worker down** (optional, only if cheap): `worker-dl` hasn't consumed a due track for longer
   than a threshold while the breaker is closed. Skip it if it needs more than an existing signal,
   and record why.

## Out of scope

- Per-user notifications (job finished), email, or push to anything except the one admin room.
- An alert history UI (v43 shows breaker history; alert history isn't planned).
- Changing the breaker or ladder behavior.

## Deploy notes

New **optional** `.env` variables `MATRIX_HOMESERVER_URL`, `MATRIX_ACCESS_TOKEN` and
`MATRIX_ROOM_ID`, using the same bot and room as v33's repository secrets. Leaving them unset must
deploy cleanly.

## Done when

- [ ] Each category 1–4 fires **once, for real**, on the dev stack into a real Matrix room
      (screenshot or room export per category):
  - [ ] **1:** a real trip from a lowered threshold and induced `AudioProviderError`s;
  - [ ] **2:** a spike from a deliberately broken `YOUTUBE_PLAYER_CLIENTS` value;
  - [ ] **3:** stopping `beat`;
  - [ ] **4:** a real sweep against the test library copy.

  Category 5 is either implemented and evidenced the same way, or its skip is recorded.
- [ ] **Cooldown:** a second identical trigger inside the window sends nothing (worker log shows
      it suppressed, and the room shows one message). After a `worker-meta` restart, still nothing
      within the window.
- [ ] **Never blocks:** with `MATRIX_HOMESERVER_URL` pointed at an unreachable host, a real
      download completes normally and on time, and the failure is logged once.
- [ ] **Off when unconfigured:** all three variables unset, the stack boots, the startup log says
      alerts are off, and v33's deploy preflight passes (real or simulated preflight run).
- [ ] **Redaction:** an alert built from an error containing a proxy URL with credentials arrives
      redacted (unit test, plus one real message).
- [ ] The test-alert button delivers for an admin, and a non-admin gets 404 on the endpoint
      (two real sessions).
- [ ] The token never appears in any log line or API response (grep the `api`/`worker-meta` logs
      and the settings GET body).
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `4.36.0`. `uv lock` is in sync. `graphify update .` has been run.
