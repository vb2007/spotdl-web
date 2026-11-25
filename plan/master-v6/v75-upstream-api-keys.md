# v75 — Upstream API Keys

Branch: `dev-upstream-api-keys` → PR into `main`
Version: `6.75.0` (extension: next minor in `extension/manifest.json`)
Wave / slot: 3 / 3 (may run beside v74)
Depends on: v73 merged (its client credentials); upstream **API-2** (vb2007.hu-api#577) and
**VUE-2** (vb2007.hu-vue#359) merged **and deployed**

## Scope

The owner chose to replace spotdl's own `sdw_` keys (v53) with upstream `vbk_` keys.
- A key holding the spotdl app scope grants nothing on vb2007.hu. spotdl checks it by
  client-authenticated introspection.
- Revocation, expiry, rotation and suspension come from vb2007.hu, and the key UI lives there.

The **key boundary is unchanged**: a key still reaches only job create, its own jobs'
`GET /api/jobs/{id}` and `GET /api/auth/me`, and is never admin.

**Before starting, re-read API-2's and VUE-2's shipped docs** (scope name, introspection shape,
deep-link format).

## Tasks

1. **Resolving a Bearer token.**
   - `require_session_or_api_key` resolves `Authorization: Bearer vbk_…` through
     `upstream_auth.introspect(token)`. `active` plus the spotdl scope → the `users` row for that
     email (created on first use, like a login), then the allowlist check as today.
   - Results are cached in Redis for about 60 s, keyed by a SHA-256 of the token. Both active and
     inactive results are cached, so a bad key can't hammer the upstream.
   - An upstream outage answers `503 upstream_unavailable` to a key request. The cookie path is
     unaffected.
   - The token never reaches a log: extend `redact_text` to the `vbk_` pattern.
2. **Delete the local keys.**
   - `models/api_key.py`, `services/api_keys.py`, `routers/account_keys.py` and
     `ApiKeys.svelte` with its `/account` section and the v67 "uncopied key" leave guard.
   - The Alembic migration **drops the `api_keys` table**. That is data loss: its docstring says
     so, and Deploy notes require a `pg_backup` first. `downgrade()` recreates the empty table.
   - Users re-create keys on vb2007.hu.
3. **`/account`:** the keys section becomes a short explanation plus a "Create a key on
   vb2007.hu" button using VUE-2's pre-filled deep link (name, spotdl scope). Use the impeccable
   skill (`polish`). Strings in `en` and `hu`, keyboard-reachable.
4. **The key boundary.** `test_key_boundary.py` keeps its deny-by-default parametrization, now
   with introspection mocked:
   - a `vbk_` key is accepted only on the three routes;
   - an admin's key is never admin;
   - a key without the spotdl scope (introspection `active: false`) is `api_key_invalid`.

   `test_extension_jobs.py` and the ownership suite follow.
5. **The extension.**
   - The options page accepts `vbk_` keys and links to vb2007.hu to create one.
   - The `_locales` texts are updated (`en`, `hu`), and the cookie-then-key order is unchanged.
   - Bump `extension/manifest.json` and ship the signed release through v61's pipeline.
6. **Docs.** CLAUDE.md's v5 "Firefox extension" locked decision (key source),
   `docs/EXTENSION.md`, GOTCHAS v75.

## Files owned

`backend/app/routers/auth.py` (Bearer resolution), `backend/app/services/upstream_auth.py`
(`introspect` only), the deleted key files, a new migration, `backend/app/services/redaction.py`,
`backend/app/models/__init__.py`, `backend/app/routers/__init__`/`main.py` (router removal),
`backend/tests/{test_key_boundary,test_extension_jobs}.py` and the key tests,
`frontend/src/routes/account/+page.svelte` (keys section),
`frontend/src/lib/components/ApiKeys.svelte` (deleted), `frontend/src/lib/api.ts` (key calls),
`extension/**`, `docs/EXTENSION.md`, plus the shared hotspots.

## Out of scope

- Changing which routes accept a key.
- Migrating old `sdw_` keys: they can't become upstream keys.
- An OAuth flow inside the extension.

## Deploy notes

- **`pg_backup` before deploy:** the migration drops `api_keys`.
- Tell users of the extension to create a vb2007.hu key with the spotdl scope.
- Release the extension in the same window, since old builds only know `sdw_` keys.

## Done when

- [ ] **A real `vbk_` key** with the spotdl scope, created on vb2007.hu through VUE-2's deep link
      for a test identity, submits a job and reads it back on the slot stack (curl evidence) and
      from the extension in real Firefox (`web-ext run`, screenshot).
- [ ] **Keys that must fail:** a key without the scope, a revoked key and an expired key each get
      `api_key_invalid` within the cache TTL (real upstream, revoke on vb2007.hu then wait out
      the TTL).
- [ ] **The key boundary holds:** `test_key_boundary.py` passes and still fails for a deliberately
      unguarded scratch route (shown, then removed). An admin's key is non-admin.
- [ ] **Outage:** introspection returns `503 upstream_unavailable`. The cookie path keeps working
      (test).
- [ ] **No leaked keys:** `vbk_` tokens never appear in logs or Postgres (grep), and the cache key
      is a hash.
- [ ] **The migration** drops the table. The round trip `upgrade` → `downgrade -1` → `upgrade` is
      run on the slot DB, and the PR's Deploy notes require a `pg_backup`.
- [ ] **The extension:** lint, tests and the `_locales` key parity pass. The signed XPI installs
      and auto-updates from the release (v61 checks).
- [ ] **`/account`:** the keys section shows the deep link, with desktop and mobile, `en` and `hu`
      screenshots and the impeccable output.
- [ ] **Checks:**
  - `pytest`, the cross-user sweep, `verify_separation_sse.sh`;
  - lint, check, build, e2e (all projects).
- [ ] **Version and graph:** `6.75.0` in both files, `uv lock`, the extension version bumped,
      `graphify update .`.
