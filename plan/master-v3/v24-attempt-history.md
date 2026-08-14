# v24 — Per-Attempt History

Branch: `dev-attempt-history` → PR into `main`
Version: `3.24.0`

## Scope

Record what each download attempt actually did, and surface it in the UI. Today `tracks.last_error`
holds only the most recent message — a track on its fifth attempt shows no history of the previous
four, so "why does this one keep failing?" is answerable only by SSH-ing to the host and reading
worker logs.

This lands right after the v23 fix precisely because v23's investigation would have been far
cheaper with it, and because every version after this one benefits from being debuggable.

## Schema

### `track_attempts` (new)

- `id` (uuid, pk)
- `track_id` (uuid, fk → `tracks.id`, indexed)
- `attempt_number` (int) — mirrors `tracks.attempt_count` at the time of the attempt
- `started_at`, `finished_at` (timestamptz)
- `outcome` (enum: `completed`, `failed`, `cancelled`, `skipped_duplicate`)
- `error_type` (existing `TrackErrorType` enum, nullable)
- `error_message` (text, nullable) — **redacted** via `proxies.redact()` before storage, same
  contract as `tracks.last_error` (`docs/GOTCHAS.md` v07)
- `proxy_id` (uuid, fk → `proxies.id`, nullable) — `NULL` means the attempt went direct
- `created_at` (timestamptz)

Index on `(track_id, attempt_number)`. Enum columns use `values_callable` and the migration's
`downgrade()` carries an explicit `DROP TYPE` (`docs/GOTCHAS.md` v02).

**Retention**: attempts are never auto-pruned in this version. A track in the 24h-forever ladder
accrues roughly one row per day, which is negligible; add pruning only if it ever proves otherwise,
and never prune in a way that touches `downloaded_tracks`.

## Tasks

1. Write the model + one Alembic migration.
2. `download_track` writes exactly one row per attempt, on **every** exit path — success, failure,
   cancellation, dedup skip, and the breaker/pause re-queue. The paths that return early are the
   easy ones to miss, and a history with silent gaps is worse than no history because it reads as
   complete.
3. Record `proxy_id` so "direct failed, proxy also failed" is visible — the direct-first escalation
   strategy is otherwise invisible after the fact.
4. `GET /api/tracks/{id}/attempts` — owner-scoped exactly like every other direct-id endpoint:
   **404, not 403**, for a non-owner (the standing v2 invariant).
5. Frontend: render the attempt list in the existing track detail panel. Compact — timestamp,
   outcome, direct-or-proxy, error. It's diagnostic, not a headline feature; it must not compete
   visually with the track's current state.
6. `graphify update .`

## Done when

- A track taken through several real ladder steps has one attempt row per attempt, in order, with
  correct outcomes and timestamps — verified by SQL against the real DB.
- Each early-return path is exercised and produces its row: cancel-before-dispatch, breaker
  re-queue, dedup skip, cancel-mid-download, success, failure. Six paths, six explicit checks —
  testing one and assuming the rest is exactly the failure mode `CLAUDE.md` warns about.
- A proxied attempt records its `proxy_id`; a direct attempt records `NULL`.
- No proxy credentials appear in any `error_message` — grep the real table after a deliberately
  failed proxied attempt.
- A non-owner gets 404 from `GET /api/tracks/{id}/attempts`; the owner and admin get the history.
- The attempt list renders in the real UI for a genuinely multi-attempt track.
- Migration round-trips (`upgrade head` → `downgrade -1` → `upgrade head`) against real Postgres.
- Both version files read `3.24.0`; `graphify update .`
