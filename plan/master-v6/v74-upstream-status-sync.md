# v74 — Upstream Status Sync

Branch: `dev-upstream-status-sync` → PR into `main`
Version: `6.74.0`
Wave / slot: 3 / 2 (may run beside v75; may start before v73 if API-3 ships first)
Depends on: v72 merged; upstream **API-3** (vb2007.hu-api#576) merged **and deployed**, with
spotdl's client credentials configured

## Scope

spotdl sessions last until they go idle (`SESSION_IDLE_TIMEOUT`). Nothing tells spotdl when
vb2007.hu suspends or deletes an account, renames it, or moves the superuser. This slice reads
that state periodically in **one bulk call**, and acts on it. It never uses an `admin:read` key,
which can sign every private upload URL (vb2007.hu-api #536).

**Before starting, re-read API-3's shipped docs** and follow them where they differ.

## Tasks

1. **The status client.** `upstream_auth.account_status(emails) -> dict[email, Status | Missing]`.
   - One request, or a few if API-3 caps the batch.
   - Client-authenticated with the credentials v73 added. If v74 lands first, it adds them,
     following the same checklist; whichever slice is second reuses them.
   - Unconfigured means **off**, like Matrix alerts.
2. **The beat task** `sync_upstream_status`, on the `meta` queue every few minutes. It's a
   setting, and its interval rule goes in `celery_app.beat_schedule`. For every `users` row:
   - **Suspended, or missing upstream:** end the user's sessions, close their open streams and
     revoke their API keys, through **v69's revocation path** (`services/allowlist.py`). The
     allowlist row and jobs stay. Unsuspending upstream lets the user sign in again with no
     spotdl action.
     - Before v75, `sdw_` keys are revoked.
     - After v75, there are no local keys, so this step has nothing to revoke.
   - **`username` changed:** update it (a truthy value only, as `get_or_create_user` already
     does).
   - **`isSuperuser` changed:** update `is_admin` by v72's rules, including the loss path (stream
     scope, 403/404).
3. **Failure is never a verdict.** A timeout, `5xx`, malformed body or rate limit changes
   nothing and logs once, throttled like v59's Redis-outage logging. A single entry missing from
   a successful answer counts as "deleted" only if API-3 documents that.
4. **Observability.** Count the actions per run and log them. A failed sync streak over an hour
   raises a Matrix alert through the v59 outbox (one category, deduplicated).
5. **Docs.** GOTCHAS v74, `docs/DEPLOYMENT.md` (what the sync does, how to turn it off), and
   CLAUDE.md's locked-decision row (upstream state).

## Files owned

`backend/app/services/upstream_auth.py` (`account_status` only), `backend/app/tasks/beat.py`
(the new task), `backend/app/tasks/celery_app.py` (its schedule), `backend/app/config.py` (the
interval, and the credentials if first), `backend/app/services/alerts.py` (one category), new
`backend/tests/test_status_sync.py`, plus the shared hotspots.

## Out of scope

- Pushing anything to the upstream.
- Back-channel logout. If API-3 offers it later, it comes in as an Amendment.

## Deploy notes

The client credentials, if v74 merges before v73. No migration.

## Done when

- [ ] **Against the real upstream:** one sync run over the slot's identities answers every
      identity and changes nothing (log evidence).
- [ ] **A suspended test identity:** suspended upstream (owner-assisted, or the dev
      `vb2007.hu-api` instance with its superuser), it loses its sessions and its open
      `/api/stream` within one sync interval. Evidence: a raw `curl -N` capture, and the session
      rows gone. Its jobs and allowlist row stay. After unsuspending, it signs in again.
- [ ] **Unit tests against a mocked upstream** cover deleted (missing), renamed, superuser
      gained and lost, and the outage, `5xx` and malformed cases (no change).
- [ ] **No `admin:read` key** is used anywhere (grep).
- [ ] **The alert:** a failing sync streak raises one alert through the outbox (test).
- [ ] **Checks:**
  - `pytest`, the cross-user sweep, `verify_separation_sse.sh`;
  - lint, check and build if the frontend changed.
- [ ] **Version and graph:** `6.74.0` in both files, `uv lock`, `graphify update .`.
