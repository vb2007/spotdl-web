# v35 — Correctness Sweep

Branch: `dev-correctness-sweep` → PR into `main`
Version: `4.35.0`

## Scope

A bounded set of real defects found while planning master v4. The list below is closed. Nothing
else gets folded in. **Each item is its own commit (`v35: (a) …`) and has its own Done-when
bullet.** They land before the redesign (v40), because the redesign renders this data and should
render it correctly.

## Items

### (a) Attempt counting and numbering

- `tracks.attempt_count` is incremented only by `retry.record_failure`
  (`backend/app/services/retry.py:79-80`).
- Every `download_track` invocation writes a `track_attempts` row numbered with the
  *pre-attempt* count (`backend/app/tasks/download.py:60`).
- So a first-try success shows **"passes attempted: 0"** beside one completed attempt (the owner's
  screenshot).
- The breaker-hold and cancelled rows (`download.py:88-101`) also don't increment, so their
  `attempt_number` collides with the next real attempt (`docs/GOTCHAS.md` v24 entry).

Fix:

- Make `track_attempts.attempt_number` a strictly increasing per-track sequence (1-based), assigned
  at row creation, so every row has a unique number. Backfill existing rows in the migration by
  `started_at` order. This rewrites a column on real data, so take a `pg_backup` first, and list
  it under the plan's deploy notes.
- Expose the counts the UI needs: **attempts made** (rows that actually tried the network) and
  **failures**. A breaker-hold row isn't an attempt. Decide whether it's a row at all or a
  distinct `outcome` (`held`), and record the decision.
- **The retry ladder's input must not move.** The ladder step is derived from failures. Whatever
  the UI now calls "attempts", the value feeding `LADDER_SECONDS` indexing must produce the
  identical step it does today. Write a test pinning that, for every existing waiting track
  shape.

### (b) Attempt detail in the API

`TrackAttempt.network_path` (`backend/app/models/track_attempt.py:72`) is stored but omitted by
`track_attempt_to_dict` (`backend/app/services/serializers.py:104-113`) and by `api.ts`'s
`TrackAttempt` (`frontend/src/lib/api.ts:124-133`).

- Expose `network_path` (direct-ipv4 / direct-ipv6 / proxy), the proxy's **redacted** label (never
  its URL, per `proxies.redact()`), `error_type`, and a duration (`finished_at - started_at`).
- Update `TrackRow.svelte`'s via-label to use it. A minimal text change only: the visual redesign
  is v40.

### (c) Redelivery must not rewrite a completed track

`download.py:66` gates only on `CANCELLED`. A redelivered Celery message for an already-`COMPLETED`
track falls through to dedup, and `:117` rewrites it to `SKIPPED_DUPLICATE` (flagged in
`plan/master-v2/00-master-plan.md:253-258`, never fixed). Gate terminal successes the same way as
cancelled: a completed or skipped track is a no-op on redelivery. Write no attempt row and publish
no event.

### (d) Warning vs failure on attempt messages

v26's tag-repair notes are stored in `error_message` on **completed** attempts, and render in
failure red (`TrackRow.svelte:199-200,408-409`; `docs/GOTCHAS.md:3307-3315`). Add an explicit
severity to the attempt (e.g. a `message_kind` of `error` or `warning`, or a separate
`warning_message` column). Set it at the write site, never inferred from text. Render warnings in
a neutral or `--waiting` style. The full visual treatment is v40.

### (e) Streamed file download

`TrackRow.svelte`'s `handleDownload` fetches the whole file into a `Blob`, then clicks an object
URL. That holds a whole FLAC in tab memory and throws away v27's `X-Accel-Redirect` streaming.

- Use a real navigation or anchor `href` to `/api/tracks/{id}/file`, so the browser streams it
  straight to disk.
- **Keep the error surface.** A plain navigation to a 404 replaces the page. Options: a cheap
  `HEAD` (or an `?check=1` probe) before navigating, or an `iframe`/`download` attribute with a
  failure fallback. Pick one, and prove a missing file still shows the inline notice and doesn't
  navigate away.
- It must still work through the Vite dev fallback (v27/v28's `vite.config.ts` handling).

### (f) Image `.pyc` hygiene

v31 found stale root-owned `.pyc` files from the image build (`docs/GOTCHAS.md` v31 section).
Set `PYTHONDONTWRITEBYTECODE=1`, or precompile as the runtime user, in `backend/Dockerfile`. Show
no root-owned `__pycache__` in a running container.

### (g) Live counts for the tracks-scope state filter

The jobs scope shows per-status counts. The tracks scope's state chips have none
(`docs/GOTCHAS.md:2597-2600`). Return `counts_by_state` from the tracks list endpoint in the
**same** query, or one bulk aggregate (never per state). It must be owner-scoped. Render it in the
existing chips with the minimal visual change.

## Out of scope

- Any visual redesign of TrackRow or QueueControls (v40/v41).
- v31's open "file missing after COMPLETED" question (v46 observes it).
- Retuning `YOUTUBE_PLAYER_CLIENTS`.

## Deploy notes

(a) and (d) add migrations. (a) rewrites `attempt_number` on existing rows, so a pre-deploy
`pg_backup` is required (the pipeline already takes one; confirm it ran). No new `.env`
variables.

## Done when

- [ ] **(a)** A real first-try download shows attempts = 1 and failures = 0 in the API and the UI.
      A real track with 2 failures, then a success, shows 3 and 2. Attempt numbers are unique and
      increasing across a breaker hold (unit test plus a real DB query on dev). The migration's
      backfill is checked on a copy of real-shaped data (dev rows), with `downgrade` working.
- [ ] **(a)** Ladder pinning: `pytest` proves every ladder step is unchanged, for 0–6 failures
      including breaker-held and cancelled rows.
- [ ] **(b)** `GET /api/tracks/{id}/attempts` returns `network_path`, the redacted proxy label,
      `error_type` and duration on a **real** attempt row written by a real dev download
      (response captured), and on a proxy attempt shows the label with no credentials. The UI
      shows the path.
- [ ] **(c)** Re-sending a `download_track` message for a `COMPLETED` track leaves its state, row
      count and events unchanged (unit test, plus one real `celery call` on dev with before and
      after DB rows).
- [ ] **(d)** A completed attempt with a tag-repair note is stored as a warning and renders
      non-red (screenshot). Real failures still render as failures.
- [ ] **(e)** A large real file downloads with flat tab memory (browser task manager or a
      performance memory snapshot, before and after) and its checksum matches the file on disk.
      A deleted-file track shows the inline notice and stays on the page. This works through both
      the dev Vite fallback and the nginx path.
- [ ] **(f)** No root-owned `__pycache__` in a freshly built running `worker-dl` (`find` output).
- [ ] **(g)** The tracks scope shows state counts that match a real DB count, update after an
      action, and are owner-scoped (cross-user test in `test_ownership.py`).
- [ ] `pytest backend/tests/test_ownership.py` passes, plus `scripts/verify_separation_sse.sh`.
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `4.35.0`. `uv lock` is in sync. `graphify update .` has been run.
