# v52 — Extension API (keys, cascades, allowlist, rate limits)

Branch: `dev-extension-api` → PR into `main`
Version: `5.52.0`
Wave / slot: 1 / 3
Depends on: v49

## Scope

Everything the Firefox extension (v57) needs from the backend. This is the **contract** v57 builds
on, so it lands a wave earlier. Today there's cookie-only auth (`routers/auth.py:15,25-35`), no
API keys, no rate limits, and job create accepts any text as a `SEARCH` job
(`routers/jobs.py:44-54`).

Owner decision: **the session cookie is tried first**, with a per-user **API key** as the
fallback.

## Tasks

1. **Spike first: does a Firefox extension's background fetch carry `SPOTDL_SESSION`?**
   - Build a throwaway minimal MV3 extension in the scratchpad (not committed).
   - Give it `host_permissions` for the slot's web origin, and have its background script call
     `fetch(..., {credentials: 'include'})` against `GET /api/auth/me` (task 3) while logged in on
     the same profile.
   - Record the result in GOTCHAS for: plain HTTP on 127.0.0.1, the HTTPS production origin
     (read-only `me` call with a test identity), and Total Cookie Protection on and off.
   - v57's cookie path depends on this answer. If cookies don't flow, v57 still ships with keys
     only, and this is recorded as such.
2. **Per-user API keys.**
   - New `api_keys` table: `id`, `user_id` FK (cascade on user delete), `label`, `prefix`
     (the first 8 chars, for display), `hash` (SHA-256 of a 32-byte random secret, so it's never
     stored raw), `created_at`, `last_used_at`, `revoked_at`.
   - Key format `sdw_<prefix>_<secret>`, shown **once** on creation.
   - `POST/GET/DELETE /api/account/api-keys`: owner-scoped, non-owner 404, max N active keys per
     user.
   - `/account` gets a section to create (label), list (prefix, created, last used) and revoke,
     with en/hu strings, keyboard-reachable, and designed with impeccable in the existing system.
3. **Auth path.**
   - A `require_session_or_api_key` dependency: `Authorization: Bearer sdw_…` **or** the cookie.
   - Used only on `POST /api/jobs` and a new `GET /api/auth/me` (`{email, username, is_admin}`;
     `is_admin` is reported but grants nothing via a key).
   - **A key never satisfies `require_admin` or any other endpoint**, even when its user is an
     admin. Admin power needs the cookie session.
   - `last_used_at` updates at most once a minute (no write per request).
   - Every log line and error passing a key goes through `redact_text`. Add the `sdw_` pattern to
     `redact_text`.
4. **Extension-origin requests.**
   - The extension sends `X-Spotdl-Client: extension/<version>`.
   - Requests with that header, or authenticated by a key, go through the **Spotify allowlist**:
     only `open.spotify.com` (including `intl-xx` paths, `?si=` stripped) track/album/artist/
     playlist URLs. Anything else gets 422 with code `url_not_spotify` (`SEARCH` isn't available
     to the extension).
   - Normalize to `https://open.spotify.com/<type>/<id>` before storing.
   - Cookie requests *without* the header keep today's behavior (the web UI's search still
     works).
5. **Server-side cascades.**
   - `POST /api/jobs {url, cascade?: "album" | "artist"}`.
   - For a track URL with `cascade=album`, resolve its album URL via spotdl's Spotify client
     (through `expansion._ensure_spotify_client()`, the invariant), then create the job for the
     album.
   - For `cascade=artist` on a track or album, resolve the **primary** artist. Multiple artists
     return 409 `cascade_ambiguous` with the candidate list (`[{name, url}]`), so the client can
     ask the user.
   - Resolution happens in the request (one metadata call, with a timeout) or as part of
     expansion. Pick one, record why, and keep the request bounded.
6. **Duplicate hint.**
   - The create response gains `hint: "already_queued" | "in_library" | null`:
     - `already_queued`: an active job with the same normalized URL for this user;
     - `in_library`: for a track URL, the ledger already has it.
   - The job is still created unless `already_queued`, which returns the existing job with
     **200, not 201**. Record this behavior choice in GOTCHAS.
7. **Rate limits** (Redis-backed, per user and per key; for login, per email plus IP):
   - login: N failures per 15 min;
   - job create: M per minute.
   - Returns 429 with code `rate_limited` and `Retry-After`.
   - Defaults are documented, overridable by env and **optional** (no `:?`).
8. Stable error `code`s for every new error (v46 rule). The web UI maps any it surfaces.

## Files owned

`backend/app/routers/auth.py`, `backend/app/routers/jobs.py` (the create endpoint only), new
`backend/app/routers/account_keys.py` (or similar), new `backend/app/services/api_keys.py`, new
`backend/app/services/rate_limit.py`, new `backend/app/services/spotify_urls.py`,
`backend/app/services/sessions.py`, `backend/app/models/` (the new model), one Alembic migration,
`backend/app/services/redaction.py` (only the new `sdw_` pattern),
`frontend/src/routes/account/+page.svelte` (a new section only), `frontend/src/lib/api.ts`
(key + me functions), the message JSONs (shared hotspot), new tests.

## Out of scope

The extension itself (v57). Key scopes beyond "submit + me". OAuth.

## Deploy notes

A new migration (additive, no data rewrite). New **optional** env vars for rate limits.

## Done when

- [ ] **The spike is recorded:** cookie-carrying from an extension background fetch observed for
      HTTP loopback and for HTTPS production (`me` response with a test identity), with TCP on
      and off. The verdict and evidence are in GOTCHAS.
- [ ] **Key lifecycle on the slot stack:**
  - create → shown once → listed by prefix only;
  - submit a real Spotify album with `curl -H 'Authorization: Bearer …'` → job created and
    expanded;
  - revoke → the same key gets 401.
- [ ] **A key never grants admin:** an admin's key gets non-admin answers on every admin endpoint
      (`test_ownership.py`-style parametrized test over all admin routes, plus two real curls).
- [ ] **Cross-user:** user A's key can't list, revoke or see B's keys or jobs (pytest), and key
      endpoints return 404 for non-owners.
- [ ] **Allowlist:** with the extension header or key auth, search text, a non-Spotify URL and
      `spotify:` URIs get 422 `url_not_spotify`, while `intl-hu` and `?si=` URLs normalize
      correctly (pytest table, plus one real call each). The cookie web UI's search job still
      works (e2e).
- [ ] **Cascades against real Spotify metadata:**
  - a track → its album job;
  - a single-artist track → the artist job;
  - a multi-artist track → 409 with candidates;
  - an album → artist.
- [ ] **Hint:** a re-submit returns 200 with the existing job and `already_queued`. A
      ledger-present track returns `in_library` (real calls).
- [ ] **Rate limits:** the (N+1)th failed login and the (M+1)th create get 429 with
      `Retry-After`, and the limits reset after the window (real calls, with low test limits).
- [ ] **No key in logs:** grep every container log after the run finds no `sdw_` secret, and
      `redact_text` unit-tests the pattern.
- [ ] The `/account` keys section works keyboard-only in en and hu, with impeccable output and
      screenshots recorded. The e2e spec has been added.
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `5.52.0`. `uv lock` is in sync. `graphify update .` has been run.
