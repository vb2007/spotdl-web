# spotdl-web — Master Plan v6

> This is the master v6 roadmap, approved by the owner and committed **verbatim** as the project's
> permanent record, with the same treatment masters v1–v5 got. Individual version plans
> (`plan/master-v6/v71-*.md` … `v75-*.md`) expand the roadmap below. `IMPLEMENTATION_PROMPT.md`
> in this folder is the template prompt for every v6 implementation agent. `CLAUDE.md` carries the
> durable summary. Master v1–v5 plans are never edited again.
>
> **Master v6 is open.** Unlike v1–v5 it has no planned close slice. `vb2007.hu-api` and
> `vb2007.hu-vue` keep developing, and the changes spotdl-web needs from them arrive as
> Amendments (the way #77 and #81 amended v5). The owner adds a close slice when the master ends.

## Context

spotdl-web logs users in by proxying their e-mail and password server-side to `vb2007.hu-api`
(`backend/app/services/upstream_auth.py`, v03 and v25). That API was at about v1.x when spotdl was
built. It is now at **v3.4.0** (2026-11-23). The changes that matter here:

- **MFA** (v3.0): email codes and links, TOTP, passkeys and recovery codes.
- **Passkey login** (v3.0).
- **Upstream API keys** (`vbk_`, v3.3).
- **Account suspension** (v2.6).
- The session cookie, now **host-only** and renamed `__Host-VB-AUTH` (v2.6).
- A remembered-device cookie (v2.5).
- **Email-verified registration** (v2.2).
- Public OpenAPI docs at `/docs` (v3.4).

**Login to spotdl-web is broken for the owner.** Their account has TOTP and a passkey on, so
upstream answers the password with an MFA challenge, and spotdl reads anything but `200` as wrong
credentials.

The owner's direction for this master:
- **Fix auth first**, as a slice that deploys alone.
- **Use the upstream instead of reimplementing it.** Where existing spotdl code duplicates
  something the upstream now does, replace it.
- **Ask the upstream for what's missing.** Code changes go in as issues in `vb2007.hu-api` /
  `vb2007.hu-vue` (their templates, detailed requirements), big asks included: "if you need a
  complete IdP, ask for it". Config-only upstream changes are done over SSH, or the owner is
  asked.
- **Slices may be bulky.** They shouldn't be spread out just because earlier masters did.
- **Proposals welcome.** New ideas come to the owner as proposals, and accepted ones get their own
  slice in this master.

---

## Verified current state

Read from both repos, GitHub and the live API this session (2026-11-24, spotdl `main` at
`fb39829e`, `vb2007.hu-api` `dev` at `fe19ae2` = v3.4.0):

| Finding | Evidence |
|---|---|
| **An MFA account gets `202`, which spotdl reads as a failure** | `vb2007.hu-api/src/controllers/authentication.ts` `login`: with a method on, `202 {"mfaRequired": true, "methods": [...]}` plus a `__Host-VB-MFA` cookie and no session. `upstream_auth.login` returns `False` on any status but `200`. The owner (TOTP + passkey) sees `login_error_rejected` |
| **The username fetch fails for every login** | Upstream reads `__Host-VB-AUTH` (`src/helpers/session.ts:17`). spotdl sends `VB-AUTH` to `GET /user`, which answers `403`, so `_fetch_username` returns `None` (it degrades silently, by design since v25) |
| **One upstream session per account** | `setUserSession` (`src/database/users.ts:394`) overwrites one `sessionToken`. So every spotdl login logs the user out of vb2007.hu, and spotdl leaves its own upstream session dangling (it never logs it out) |
| **Methods a server-side proxy can't reach** | Passkeys accept only `https://vb2007.hu` (`docs/passkeys.md:9`, origin from `BASE_SITE_URL`). The GitHub callback redirects to the main site. The mailed MFA link is `<BASE_SITE_URL>/login/mfa#token=…` and needs that browser's challenge cookie (`docs/mfa.md`). Password-less (GitHub-made) accounts have nothing to proxy |
| **Email MFA needs a confirmed address** | `PUT /user/mfa/email` answers `409` unless `emailVerified`. Accounts made before upstream v2.2 report `emailVerified: false` (`src/helpers/accountStatus.ts:27`, from `emailVerifiedAt`) |
| **Registration changed** | `POST /auth/register` now mails a code (`202`), and `POST /auth/register/verify` creates the account. Reserved test domains are never mailed, and a local instance without SMTP prints each mail with its code outside production (`docs/email-setup.md:19`). `docs/LOCAL_DEV.md` §4 and the GOTCHAS v17 rule still say "register freely" |
| **The live API answers normally** | A throwaway `POST https://api.vb2007.hu/auth/login` for a nonexistent address with httpx's default client: `403` JSON `Incorrect e-mail address or password…`. No Cloudflare block |
| **Unverified: the client address upstream sees** | Upstream `trust proxy` is `loopback, uniquelocal` (`src/index.ts:33`), and production spotdl reaches `https://api.vb2007.hu` through Cloudflare. Its per-IP limiters likely see every spotdl user as spotdl's one address (100 failed logins / 15 min per IP, codes shared likewise). v71 checks this first |
| **Upstream API keys can't serve spotdl yet** | Fixed scope list with no app scope (`src/constants/limits.ts` `API_KEY_SCOPES`). The only identity read is `GET /user` (`account:read`). Rejected keys are limited per client IP (`docs/api-keys.md`). The main site has no API key UI (`vb2007.hu-vue` has no key component) |
| **`admin:read` is too broad for an app** | It can fetch signed URLs to every private upload (`vb2007.hu-api` #536) |
| **spotdl's admin is the upstream superuser** | Owner confirmed 2026-11-24: production `ADMIN_EMAIL` = upstream `SUPERUSER_EMAIL`. `GET /user` answers `isSuperuser` |

---

## Design: vb2007.hu becomes the identity provider

Fixing each unreachable method on its own would take five upstream changes:
- a second passkey origin;
- a per-client MFA link base;
- a GitHub login hand-off;
- several sessions per account;
- trusted client-IP forwarding.

A **browser-redirect identity provider** replaces all five: OAuth 2.0 authorization code + PKCE,
OIDC-shaped.
- The user signs in **on vb2007.hu itself**, from their own browser and IP, with every method it
  has today or adds later.
- spotdl gets a one-time code and exchanges it server-to-server for the identity.
- spotdl never sees a password, never replaces the main-site session, and the shared-IP problem
  is gone for login.

The owner had first picked the point fixes and a "forward client IP" slice. After the owner's
"ask for a full IdP if needed", this plan takes the IdP instead:
- **Client-IP forwarding** is resolved without a slice of its own. Login moves into the browser,
  and key checks become client-authenticated (API-2).
- **Passkey and GitHub-only accounts** wait for v73. Until then the owner signs in with password
  plus TOTP or a recovery code (v71).

v71 stays a **server-side proxy**, because auth must work again before any upstream change ships.
v73 deletes that proxy.

---

## Upstream dependency ledger

Filed 2026-11-24 with each repo's `feature.yml` template. A slice that depends on one starts only
once the issue is **merged and deployed** upstream (the public OpenAPI at
`https://api.vb2007.hu/docs/openapi.json` lists the route).

| Id | Issue | What it gives spotdl | Consumer |
|---|---|---|---|
| API-1 | [vb2007.hu-api#575](https://github.com/vb2007/vb2007.hu-api/issues/575) Identity provider for first-party apps (authorization code + PKCE) | Client registry with several redirect URIs (incl. a dev client for `localhost:5173`–`5178`), `GET /oauth/authorize`, `POST /oauth/token` → `sub`, `email`, `email_verified`, `username`, `isSuperuser`. No upstream session for the client | v73 |
| VUE-1 | [vb2007.hu-vue#358](https://github.com/vb2007/vb2007.hu-vue/issues/358) Authorization page for first-party app sign-in | The `/authorize` page: every login method, then consent, then the redirect back | v73 |
| API-3 | [vb2007.hu-api#576](https://github.com/vb2007/vb2007.hu-api/issues/576) Client-authenticated account status | One bulk call: exists / `username` / `isSuperuser` / `suspendedAt` per e-mail, without `admin:read` | v74 |
| API-2 | [vb2007.hu-api#577](https://github.com/vb2007/vb2007.hu-api/issues/577) App-scoped API keys and key introspection | A `spotdl:submit` scope granting nothing on the main site. `POST /oauth/introspect` authenticated by the client. Rejected keys limited per client | v75 |
| VUE-2 | [vb2007.hu-vue#359](https://github.com/vb2007/vb2007.hu-vue/issues/359) API key management on /account | The key UI the main site lacks, plus a pre-filled deep link | v75 |

Not filed (config, done over SSH or asked of the owner when its slice needs it): registering
spotdl's production and dev clients, their secrets and redirect URIs.

---

## Locked decisions for v6

| Area | Decision |
|---|---|
| Version numbers | Slices continue at **v71**; releases are `6.NN.0`. Patch slices `vNN.1` as before |
| Login | **Sign in with vb2007.hu** (authorization code + PKCE) from v73. Until then, the v71 proxy: password plus email code, TOTP or recovery code. spotdl keeps its own `SPOTDL_SESSION` and the allowlist either way |
| Allowlist | Unchanged (v69): the upstream decides *who you are*, spotdl's allowlist decides *whether you may use spotdl*. No upstream answer may reveal more to an off-list address than a wrong password does |
| Admin source | `is_admin` follows the upstream `isSuperuser` (v72). A failed or missing upstream read never changes it. `ADMIN_EMAIL` survives only as a dev override under `SPOTDL_ENV=dev` |
| Upstream state | spotdl learns suspensions, deletions, usernames and the superuser flag from API-3 (v74), never from an `admin:read` key |
| API keys | From v75, the extension authenticates with an upstream `vbk_` key holding the spotdl app scope, checked by client-authenticated introspection and cached briefly. spotdl's own `sdw_` keys go. The key boundary (`test_key_boundary.py`, deny-by-default, three routes) stays |
| Upstream changes | Code or functionality spotdl needs from `vb2007.hu-api`/`-vue` is requested as a detailed issue there. Config-only changes are done over SSH or asked of the owner |
| Parallel implementation | v5's slot model and rebase protocol carry over unchanged (≤4 agents, own worktree, own compose project, own local Postgres, `realdl` lock) |
| Production data | Still not disposable. A migration that drops or rewrites data says so and takes a `pg_backup` first (v75's `api_keys` drop) |

---

## Version roadmap

| # | Branch | Wave / slot | Upstream dep | Scope |
|---|---|---|---|---|
| **v71** | `dev-upstream-login` | 0 / 1 | none | **Ships first.** Interim proxy: the cookie rename, the MFA second step (TOTP, email code, recovery), suspended/429 answers, no dangling upstream session, test identities and docs |
| **v72** | `dev-upstream-identity` | 1 / 1 | none | `is_admin` from `isSuperuser`; `ADMIN_EMAIL` becomes dev-only; vb2007.hu account links on `/account` and `/login` |
| **v72.1** | `dev-worker-boot-memory` | patch / 5 | none | **Inserted 2026-11-26 (incident).** Worker healthchecks stop importing the app; `reconcile_disk` streams two columns; `beat` 384M. Ships before any other deploy |
| **v73** | `dev-idp-login` | 2 / 1 | API-1, VUE-1 | "Sign in with vb2007.hu"; v71's proxy deleted; passkeys, GitHub and the MFA link work; the e2e harness signs in through the real authorize page |
| **v74** | `dev-upstream-status-sync` | 3 / 2 | API-3 | A beat task syncs suspension/deletion (ends sessions, streams and keys), usernames and `is_admin` |
| **v75** | `dev-upstream-api-keys` | 3 / 3 | API-2, VUE-2 | `sdw_` keys → upstream `vbk_` keys via introspection; the extension switches and ships a signed release |

### Why this order

- **v71 alone first.** Auth is down. It has no upstream dependency and no migration, so it can be
  reviewed and deployed fast.
- **v72 next, serially.** It needs no upstream change either, but it edits the same login path
  (`routers/auth.py`, `upstream_auth.py`) right after v71.
- **v73–v75 wait for the upstream.** They're numbered in the expected order, and each starts once
  its issues are merged and deployed upstream. If one lags, the owner reorders them by Amendment.
  - **v74 and v75 may run in parallel** after v73: v74 owns `tasks/` and the status client, v75 the
    key path and `extension/`.
  - **v74 may start before v73** if API-3 ships first, because it doesn't touch the login path.
- **No close slice yet.** The master stays open (see the banner).

---

## Critical interactions to design around

- **The allowlist must not become an oracle.**
  - Upstream answers `202` (MFA) or "suspended" only after a correct password. For an off-list
    address, spotdl answers exactly `invalid_credentials`, as for a wrong password. It keeps no
    challenge, triggers no MFA mail, and takes no different time path beyond the upstream call
    both cases share.
  - v73's callback checks the allowlist after the code exchange. An off-list identity gets the
    same refusal page whatever its upstream state.
- **Holding upstream secrets.**
  - v71 holds the upstream `__Host-VB-MFA` token server-side only (Redis, 10 min TTL), keyed by a
    random id in an httponly `SPOTDL_MFA` cookie. Neither upstream token ever reaches the
    browser, a log or the database.
  - v73's client secret and v75's tokens get the same treatment: `redact` covers the `vbk_`
    pattern, and the key cache keys on a hash of the token.
- **Session and stream revocation reuse v69's machinery.** v74's suspension handling ends
  sessions, closes open `/api/stream` connections and revokes keys through the same path v69's
  removal uses, minus the allowlist delete. An upstream outage never ends anything.
- **`is_admin` changes are security changes.**
  - Gaining admin happens only from a successful upstream read that says `isSuperuser: true`.
  - Losing it (v74 sync, or a login whose read says `false`) ends that user's admin-only SSE
    scope on their next request. The v56 403/404 rule still governs the routes.
- **The key boundary survives the key swap.** v75 changes how a Bearer token is resolved, never
  which routes accept one. `test_key_boundary.py`'s deny-by-default parametrization keeps failing
  a new unguarded route.
- **Scripted logins (e2e, `verify_separation_sse.sh`, slot seeding)** use `/api/auth/login` today.
  - v71 keeps them working and adds a dedicated TOTP identity.
  - v73 replaces them with Playwright driving the real authorize page against the dev client,
    with no dev-only login backdoor.
  - Shared slot identities (slot 3 reuses slot 5's) never get MFA turned on, since that would
    break every login that uses them.

---

## Critical files

- **Login:** `backend/app/services/upstream_auth.py`, `backend/app/routers/auth.py`,
  `backend/app/services/{rate_limit,sessions,users,allowlist}.py`, `backend/app/config.py`,
  `frontend/src/routes/login/+page.svelte`, `frontend/src/lib/api.ts`,
  `frontend/src/lib/i18n/errors.ts`, `frontend/messages/{en,hu}.json`, `frontend/nginx.conf`
- **Identity:** `backend/app/models/user.py`, a new Alembic migration (v72),
  `frontend/src/routes/account/+page.svelte`
- **Status sync:** `backend/app/tasks/beat.py`, `backend/app/tasks/celery_app.py`
- **Keys:** `backend/app/services/api_keys.py`, `backend/app/routers/account_keys.py`,
  `backend/app/models/api_key.py`, `frontend/src/lib/components/ApiKeys.svelte`,
  `backend/app/services/redaction.py`, `extension/{background,options,shared,_locales,test}/`
- **Harness and docs:** `frontend/e2e/global-setup.ts`, `frontend/e2e/support/stack.ts`,
  `scripts/{agent_stack.sh,agent_seed.py,verify_separation_sse.sh}`, `docs/LOCAL_DEV.md`,
  `docs/GOTCHAS.md`, `docs/DEPLOYMENT.md`, `docs/RELEASE_PIPELINE.md`, `.env*.example`

Reuse rather than rewrite:
- `require_session`, `require_session_or_api_key` and `_no_session` (`routers/auth.py`);
- the login tail: allowlist lock → `get_or_create_user` → `create_session`;
- `rate_limit.hit_login` / `client_address`;
- v69's revocation path in `services/allowlist.py`;
- `job_status.publish_change`;
- `proxies.redact()` / `redact_text`;
- the keyboard registry and Paraglide messages;
- `scripts/verify_separation_sse.sh`.

---

## Verification

The standing rules apply to every slice: a real stack (the agent's slot stack), real Postgres, the
real network, and each Done-when bullet evidenced individually this session. v6-specific:

1. **Every login path is proven against the real upstream** with a named test identity and
   method:
   - v71: password only, password + TOTP, password + recovery code;
   - v71, on a local `vb2007.hu-api`: email code;
   - v73: password + TOTP, passkey and GitHub, through the authorize page.

   Never the owner's own account.
2. **The no-oracle rule is tested directly.** An off-list identity with a correct password gets a
   byte-identical answer to a wrong password, for the plain, MFA and suspended cases (v71) and on
   the callback (v73).
3. **Upstream secrets never leak.** The upstream tokens, the client secret and `vbk_` keys are
   absent from every response to the browser, every log line and every table (grep the captured
   responses and the logs, as v03 did).
4. **The cross-user sweep and `verify_separation_sse.sh` re-run** for every slice touching auth,
   sessions or streams (all five).
5. **UI slices** (v71, v72, v73) go through impeccable and keep the e2e suite green on desktop,
   mobile and `hu`.

---

## Owner housekeeping (not agent work)

- [ ] Register spotdl's clients with the upstream once API-1 ships: production
      (`https://spotdl.vb2007.hu/login/callback`) and dev (`http://localhost:5173`–`5178`).
      Config only, done over SSH or by the owner.
- [ ] Decide when master v6 ends, and add its close slice then.

---

## Amendments

The plan above is the approved text, kept verbatim. Changes directed after approval are recorded
here, including new upstream changes that need spotdl work.

### 2026-11-25 (v71, owner-directed)

- **The login proxy reads the allowlist before the username fetch.** Task 2's literal order
  (`GET /user`, then `POST /auth/logout`, on every upstream `200`) would give an off-list address
  with a right password a longer path than a wrong password, against "Critical interactions". The
  owner chose: `upstream_auth.login` returns the upstream session, the router reads the allowlist,
  an allowed address gets `finish()` (username, then logout), and an off-list one its byte-identical
  `invalid_credentials` with the upstream logout in a background task after the answer is sent.
- **Every saved slot identity is dead upstream.** All `v5s<slot>{admin,user}@example.com` accounts
  answer `403` on `api.vb2007.hu` and on the local dev upstream, and `example.com` can't be
  registered any more. With the owner's OK, slot 1 now signs in on a local `vb2007.hu-api`
  (`host.docker.internal:3000`, dev Mongo) with `.test` identities (`v6s1{admin,user,mfa,mfb}`),
  allowlisted through `AGENT_ADMIN_EMAIL`/`AGENT_EXTRA_EMAILS`. The dedicated live TOTP identity
  (task 7) is shared by every implementation agent in `.git/agent-stack/live-mfa.env` (owner). The
  dead accounts were removed (owner): slots 2–5 have no saved identities, so **a slice using any
  other slot first registers `.test` identities on the local upstream** (GOTCHAS v71); v73's e2e
  against the real authorize page will need an identity on the upstream its dev client is
  registered with.

### 2026-11-25 (v72, owner-confirmed)

- **No admin is removable on `/users`**, including one the upstream stopped calling superuser who
  hasn't signed in since (their `is_admin` stays set until their next login). DEPLOYMENT.md has the
  hand demotion steps.
- **An upstream grant demotes nobody.** The pre-v72 "one admin, demote the rest" sweep applies only
  to the dev `ADMIN_EMAIL` override.
- **A fresh install lists the superuser's address in `ALLOWED_EMAILS`.** The login reads the allowlist
  before it asks the upstream, so an unlisted superuser gets `invalid_credentials` like anyone else.
- **An admin without an allowlist row can be given one** (`add` no longer answers `409`).
- v74's sync demotion publishes `admin_lost`, and calls `allowlist.cut_off` when the demoted admin has
  no allowlist row, the way v72's login does.

### 2026-11-26 (v72.1, owner-directed)

- **v72.1 inserted as a patch before v73** (`plan/master-v6/v72.1-worker-boot-memory.md`). The
  `6.72.0` deploy failed and its rollback to `6.71.0` looped too. `worker-meta` was OOM-killed every
  ~20 s, and downloads weren't dispatched for 76 minutes, until the owner raised its limit by hand.
  - Its boot peaks at 827 MiB against a 768M limit. That only fit while the host's swap had room,
    and the swap is now full.
  - Most of the peak is the healthcheck probe, which imports the whole app inside the cgroup
    (233 MiB against 47 MiB broker-only).
- **Any deploy before v72.1 ships hits the same loop**, rollbacks included. v73 waits for it.
- The host's memory (the Elasticsearch heap, swap) is the owner's, not the slice's. The fix must
  hold with no swap.

### 2026-11-28 (v72.1, owner-merged)

The owner merged #109 with these deviations from the v72.1 plan, as listed in its PR body.

- **The repro adds the alert watchdog.** The plan's boot breakdown missed it: production has Matrix
  configured, so `worker-meta` also runs `app.services.alert_watchdog` (~88 MiB). Without it `main`
  peaked at 719 MiB and didn't reproduce. The agent went past the plan's "stop and report" gate and
  gave the repro a fake, unreachable homeserver (`http://127.0.0.1:9`, nothing sent): `main` then
  looped like production (every probe exit 137, 7 OOM kills in 180 s), and the branch peaked at
  ~571 MiB with none, three runs of three restarts. The repro ran the locally built image with the
  code mounted, not the GHCR one.
- **`reconcile_disk` doesn't stream with `yield_per`.** Both of its passes need every row, so it holds
  `(spotify_track_id, file_path)` tuples instead of ORM rows: +72 → +28 MiB at 23k rows, +335 → +112
  at 110k. It still grows with the ledger (tight near ~200k rows; a `shortcut:` comment says so).
- **A prune deletes on `(spotify_track_id, file_path)`**, the path it just re-checked, so a row
  repointed by a concurrent move survives (`test_reconcile_disk_keeps_a_row_repointed_after_the_recheck`
  fails on the old code).
- **The probe guard is a CI script, not a pytest** (`.github/scripts/check_healthchecks.py`, in the
  `compose-config` job over the rendered dev and prod configs). It is deny-by-default: a celery
  probe must be exactly the app-less template, any rendered `redis://` is refused, and so is any
  celery CLI default (`APP`, `BROKER_URL`, …, every `CELERY_*`) in a probed service's environment.
  Its docstring lists what it can't see.
