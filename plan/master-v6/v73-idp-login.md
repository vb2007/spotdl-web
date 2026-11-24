# v73 — Sign in with vb2007.hu

Branch: `dev-idp-login` → PR into `main`
Version: `6.73.0`
Wave / slot: 2 / 1
Depends on: v72 merged; upstream **API-1** (vb2007.hu-api#575) and **VUE-1** (vb2007.hu-vue#358)
merged **and deployed**: `https://api.vb2007.hu/docs/openapi.json` lists `/oauth/authorize` and
`/oauth/token`, and `https://vb2007.hu/authorize` renders. spotdl's production and dev clients
are registered (owner housekeeping, config only).

## Scope

Replace v71's password proxy with the browser-redirect identity provider
(00-master-plan.md, "Design").
- The user signs in **on vb2007.hu**, with any method: password + any MFA, passkey, GitHub, the
  mailed MFA link.
- spotdl exchanges a one-time code server-to-server for the identity.
- spotdl keeps its own `SPOTDL_SESSION` and the allowlist.
- Login stops logging users out of vb2007.hu, and spotdl no longer reaches upstream's per-IP
  login limiter.

**Before starting, re-read the shipped API-1/VUE-1 docs** (`src/docs/paths`, the issue's PR).
Where they differ from the assumptions below, follow what shipped and note the difference in the
PR.

## Tasks

1. **Configuration.**
   - `UPSTREAM_OAUTH_CLIENT_ID` and `UPSTREAM_OAUTH_CLIENT_SECRET` become new required variables
     (`${VAR:?}`). Follow `docs/RELEASE_PIPELINE.md`'s "Adding a required env var" checklist, and
     list them under Deploy notes.
   - Dev and slot stacks use the dev client. `agent_stack.sh` carries it through.
   - The secret is redacted wherever config is logged.
2. **Start: `GET /api/auth/login/start?next=…`.**
   - Generate:
     - `state` (random);
     - the PKCE verifier and its S256 challenge;
     - a `nonce`.
   - Store `{verifier, nonce, next}` in Redis under `state`, with a TTL of about 10 min.
   - `next` passes the existing `safeNext` rules. The v65 share payload rides in `next` as today.
   - Redirect (`302`) to `{UPSTREAM_AUTH_BASE_URL}/oauth/authorize` with the client id and the
     exact registered redirect URI for this origin.
3. **Callback: `/login/callback`.**
   - A SvelteKit route with its `ssr`/`prerender` exports **and** its own nginx `location`
     (CLAUDE.md invariant; `nginxRoutes.test.ts`).
   - It posts `code` and `state` to `POST /api/auth/login/callback`. The backend:
     - consumes the `state` entry (single use; a missing or used one → `login_expired`);
     - calls `POST /oauth/token` with the verifier and client credentials;
     - checks `nonce`;
     - **does not gate on `email_verified`** (accounts older than upstream v2.2 report `false`;
       the allowlist is the gate);
     - then runs the **shared login tail**: the locked allowlist check → `get_or_create_user`
       (username) → `is_admin` from `isSuperuser` (v72's rules) → `create_session` → the cookie;
     - then redirects to `next`.
   - Upstream `error=access_denied`, a suspended account, and an off-list identity each get one
     clear message. The off-list one is identical whatever the upstream state, so the no-oracle
     rule holds.
4. **Delete the proxy.**
   - v71's `POST /api/auth/login` password path, `/api/auth/mfa/*`, the `SPOTDL_MFA` store and
     its cookie, and `upstream_auth`'s password, MFA and logout calls.
   - `rate_limit`'s login limiter shrinks to the start and callback endpoints (per address).
   - `test_key_boundary.py`'s public set is updated: the new routes in, the deleted ones out.
5. **Frontend `/login`.** Use the impeccable skill (`shape`, `polish`).
   - The form becomes one "Sign in with vb2007.hu" action, keeping `/login`'s world.
   - It keeps:
     - the `session ended`, `access removed` and share-waiting notices;
     - v72's links.
   - Strings in `en` and `hu`. Keyboard-reachable.
   - The PWA (v65) works: start and callback stay in the installed app's scope.
6. **Scripted logins.** They all use `/api/auth/login` today: `frontend/e2e/global-setup.ts`,
   `27-user-access.e2e.ts`, `14-keyboard.e2e.ts`, `scripts/verify_separation_sse.sh` and
   `agent_seed.py`.
   - `global-setup.ts` drives the **real** authorize page with Playwright against the dev client:
     the vb2007.hu login form, then v71's TOTP helper for the MFA identity. It saves each
     identity's `SPOTDL_SESSION`.
   - The specs reuse those sessions. The curl scripts read the saved cookies, or fall back to the
     documented direct-session-mint.
   - **No dev-only login backdoor** is added to the API.
7. **Docs.**
   - CLAUDE.md: the auth locked decision ("Server-to-server login proxy" becomes the IdP) and the
     login part of the "Mocked verification" workflow rule.
   - `docs/LOCAL_DEV.md` (dev client, how e2e signs in), `docs/DEPLOYMENT.md` (the new
     variables), and GOTCHAS v73 (incl. v71's gotchas that no longer apply, corrected in place).

## Files owned

`backend/app/services/upstream_auth.py`, `backend/app/routers/auth.py`,
`backend/app/services/rate_limit.py`, `backend/app/config.py`, `backend/tests/test_auth.py`,
`backend/tests/test_upstream_auth.py`, `backend/tests/test_key_boundary.py`,
`frontend/src/routes/login/**`, `frontend/nginx.conf`, `frontend/src/lib/api.ts` (auth calls),
`frontend/e2e/global-setup.ts`, `frontend/e2e/support/*`, the e2e specs that log in by request,
`scripts/{agent_stack.sh,agent_seed.py,verify_separation_sse.sh}`, `.env*.example`,
`docker-compose*.yml` (the new variables), plus the shared hotspots.

## Out of scope

- The status sync (v74) and API keys (v75).
- Signed `id_token` verification beyond what API-1 ships: the token call is server-to-server over
  TLS, client-authenticated.
- Any upstream change: file an issue if one is needed.

## Deploy notes

Two new required variables (the client id and secret). The production client must be registered
upstream first.

## Done when

- [ ] **Password + TOTP:** the dedicated TOTP identity (v71) signs in through the real authorize
      page, in a real browser (screenshot of each step) and in `global-setup.ts`.
- [ ] **Passkey:** a test identity signs in through the real authorize page with a passkey.
      Firefox or Chromium virtual authenticator, or a real one; say which.
- [ ] **GitHub:** a test identity signs in with GitHub through the real authorize page, or the
      owner runs it and the PR records it.
- [ ] **The mailed MFA link:** it completes a sign-in. Against a local upstream with the printed
      mail, or owner-assisted.
- [ ] **No oracle:** an off-list identity with a valid upstream sign-in gets the same answer as
      any other refusal, plain and MFA alike, shown against the real upstream.
- [ ] **Wrong state:** a reused `state`, a missing `state`, a wrong `code` and an upstream
      `access_denied` each show their message, with no session created (tests plus one browser
      run).
- [ ] **The main-site session survives:** the vb2007.hu session in the same browser is still
      live after a spotdl sign-in (`GET /user` there answers `200`). This is the v71 regression,
      closed.
- [ ] **The proxy is gone:** grep shows no `/auth/login`, `/auth/mfa` or `__Host-VB-*` handling
      left in `backend/app`.
- [ ] **The key boundary holds:** `test_key_boundary.py` passes, deny-by-default intact.
- [ ] **No leaked secrets:** the client secret, `code` and verifier never appear in a browser
      response body, a log or Postgres (grep evidence).
- [ ] **The callback route:** hard-navigation to `/login/callback` returns the page, not a 404
      (`nginxRoutes.test.ts`).
- [ ] **Share and PWA:** the `/share` round trip and the installed PWA both sign in.
- [ ] **UI quality:** impeccable outputs, and desktop and mobile, `en` and `hu` screenshots.
- [ ] **Checks:**
  - `pytest`, the cross-user sweep, `verify_separation_sse.sh` (with its new login path);
  - lint, check, build, e2e (all projects).
- [ ] **Version and graph:** `6.73.0` in both files, `uv lock`, `graphify update .`.
