# v71 — Upstream Login (interim proxy, MFA)

Branch: `dev-upstream-login` → PR into `main`
Version: `6.71.0`
Wave / slot: 0 / 1 (serial, first; deploys alone)
Depends on: nothing (master v5 merged)

## Scope

Login has been broken since upstream `vb2007.hu-api` v3.0 (00-master-plan.md, "Verified current
state"):
- **MFA accounts:** `POST /auth/login` answers `202 {"mfaRequired": true, "methods": [...]}` and
  sets a `__Host-VB-MFA` challenge cookie. `upstream_auth.login` treats any non-`200` as wrong
  credentials.
- **Usernames:** the upstream session cookie is now `__Host-VB-AUTH`, so the `GET /user` username
  fetch fails for everyone.

This slice makes the **server-side proxy** cover everything a proxy can reach:
- the password;
- the second step with **TOTP, an email code or a recovery code**;
- the suspended and rate-limited answers;
- no upstream session left dangling.

Passkeys, GitHub login and the mailed MFA link can't be proxied. They arrive with v73's identity
provider, which also deletes this proxy. So build it to work and be safe, not to last.

## Tasks

1. **Check which address upstream sees** (00-master-plan.md's unverified row).
   - Run one spotdl login against a local `vb2007.hu-api` with a temporary `req.ip` log line. Do
     it in the upstream checkout, never committed.
   - Production's path goes through Cloudflare. Ask the owner for one line from the production
     API's log if needed, or record "assumed shared" with the reason.
   - Write the finding into GOTCHAS. If the address is shared, the PR says so under Deploy notes,
     as a known interim risk until v73.

2. **`upstream_auth`: one typed result.**
   - `login(email, password)` returns one of: `Ok(identity)`, `MfaRequired(methods, challenge)`,
     `Invalid`, `Suspended`, `RateLimited(retry_after)` or `Unavailable`.
   - Mapping:

     | Upstream answer | Result |
     |---|---|
     | `200` | `Ok` |
     | `202` | `MfaRequired` |
     | `403` with the documented suspended message (`Responses.Authentication.accountSuspended`, matched by its stable prefix and pinned in a test fixture) | `Suspended` |
     | any other `403` or `400` | `Invalid` |
     | `429` | `RateLimited`, from `retryAfter` / `Retry-After` |
     | a transport error or `5xx` | `Unavailable` |

   - **The session token** is read from `Set-Cookie: __Host-VB-AUTH=…`, with the cookie name
     matched exactly (anchored), not by substring.
   - **On `Ok`:**
     - Call `GET /user` with that cookie for `username`. It degrades to `None` exactly as today.
     - Then call **`POST /auth/logout`** with the same cookie, so spotdl leaves no upstream
       session behind.
     - Both calls are best-effort and never fail the login.
     - The main-site session was already replaced by the login. Record that in GOTCHAS: a spotdl
       login logs the user out of vb2007.hu until v73.
   - **On `202`:** read `methods` and the `__Host-VB-MFA` value. Neither ever leaves the backend.
   - The token values are never logged. Add the `VB-AUTH`/`VB-MFA` cookie values to `redact_text`
     if any log path could carry a header.

3. **The MFA challenge store.**
   - On `MfaRequired`, check the allowlist **first**. **An off-list address gets exactly today's
     `invalid_credentials`**: no challenge kept, no MFA mail.
   - For an allowed address, store `{upstream_mfa_token, email}` in Redis under a random id, with
     a TTL of upstream's `MFA_CHALLENGE_MINUTES` (10).
   - Set an httponly, Secure, SameSite=Lax `SPOTDL_MFA` cookie with that id, and answer `200`
     `{"mfa_required": true, "methods": [...]}`.
   - `methods` drops `passkey` (unreachable until v73) and keeps upstream's order.
   - If only `passkey` and `recovery` would remain, keep `recovery`. Never answer an empty list:
     an account that can only do passkeys gets a `mfa_unsupported` code whose text points to v73's
     method and to recovery codes.

4. **The suspended answer.** `Suspended` for an **allowed** address gets
   `403 account_suspended`. For an off-list address it gets `invalid_credentials`, the same no-oracle
   rule as above.

5. **New routes in `routers/auth.py`**, both public, keyed by the `SPOTDL_MFA` cookie, and both
   counted by `rate_limit` (per challenge id and per client address):
   - **`POST /api/auth/mfa/verify` `{method: "totp"|"email"|"recovery", code}`**
     - Forwards to upstream `POST /auth/mfa/verify` with the stored `__Host-VB-MFA` cookie.
     - On `200`:
       - read `__Host-VB-AUTH`;
       - fetch the username, then log the upstream session out, as in task 2;
       - delete the challenge;
       - finish through the **shared login tail**: the locked allowlist re-check →
         `get_or_create_user` → `create_session` → the cookie. Factor this tail out of `login()`;
         don't copy it.
     - `400` with `attemptsLeft` → `400 mfa_code_invalid` with `attempts_left`.
     - `403` with `reason` → `401 mfa_expired` with `reason` (`noChallenge` / `triesUsedUp` /
       `expired` / `ended`), and the challenge is deleted.
     - `429` → `rate_limited` with `retry_after`.
     - No `SPOTDL_MFA` cookie, or an expired one → `401 mfa_expired`.
   - **`POST /api/auth/mfa/email`**
     - Forwards to upstream `POST /auth/mfa/email`. `202` → `200`.
     - `429` → `rate_limited` with `retry_after`, and `reason`
       (`resendCooldown` / `mfaEmailLimit`).
     - `503` → `503 mail_unavailable`.
     - `400` (email MFA off) → `400 mfa_method_off`.
   - `test_key_boundary.py`'s public-route set gains both. Neither accepts an API key.

6. **Frontend `/login`: the second step.** Use the impeccable skill (`shape` then `polish`), and
   keep the existing look of `/login`.
   - **The method:** after a password answer with `mfa_required`, the same card shows the
     second step:
     - a method choice when there is more than one (TOTP / email code / recovery code, in
       upstream's order, defaulting to the first);
     - a single code field with `autocomplete="one-time-code"`, `inputmode="numeric"` for
       6-digit codes, and text for recovery codes.
   - **Email:** "Send code" calls `/api/auth/mfa/email`, with the resend cooldown shown from
     `retry_after`.
   - **Feedback:**
     - a wrong code shows `attempts_left`;
     - `mfa_expired` returns to the password step with an explanation;
     - "Back" returns to the password step.
   - **New messages:** suspended, rate-limited (the existing `login_error_rate_limited_for`),
     mail unavailable, and `mfa_unsupported`.
   - **Generic rejection:** `login_error_rejected` stays the text for `invalid_credentials`.
   - **Strings:** every new string in `en` **and** `hu`, and error `code`s in `i18n/errors.ts`.
   - **Keyboard:** fully reachable, Enter submits, Hungarian QWERTZ rules. The single-key
     shortcuts stay inert in the code field.
   - **Unchanged flows:** the `/share` round trip (v65) and the `next` redirect still work after
     the second step.

7. **The harness and identities.**
   - Register **one new dedicated test identity** with TOTP on, on the live API:
     - `POST /auth/register` → the code mailed to a real mailbox the owner provides, or ask →
       `/auth/register/verify`;
     - then `POST /user/mfa/totp` and `/confirm`;
     - keep its recovery codes.
   - Its email, password, TOTP secret and recovery codes go **only** into the untracked
     `.git/agent-stack/e2e.s<slot>.env` (and the owner's copy). Never into a tracked file.
   - **Never turn MFA on for a shared slot identity.** Slot 3 reuses slot 5's, so turning it on
     would break every login that uses them.
   - **e2e:**
     - a new spec logs that identity in through the real second step, computing the TOTP with
       node `crypto` (RFC 6238, SHA-1, 30 s, 6 digits) and no new dependency;
     - one recovery-code run (spending one code; note how many remain).
   - The existing plain identities keep passing through `global-setup.ts` unchanged.

8. **Docs.**
   - `docs/LOCAL_DEV.md` §4 and the GOTCHAS v17 rule, corrected in place with a dated note:
     - registration is now register → mailed code → verify;
     - `api.vb2007.hu` refuses reserved and example domains;
     - a local `vb2007.hu-api` without SMTP prints the code;
     - reuse the existing slot identities.
   - A GOTCHAS v71 section covering:
     - the `202` contract;
     - the cookie names;
     - the single upstream session;
     - the client-address finding;
     - the email-MFA-needs-`emailVerified` rule (accounts older than upstream v2.2 report
       `false`).

## Files owned

`backend/app/services/upstream_auth.py`, `backend/app/routers/auth.py`,
`backend/app/services/rate_limit.py`, `backend/app/services/redaction.py` (cookie values only),
`backend/tests/test_auth.py`, a new `backend/tests/test_upstream_auth.py`,
`backend/tests/test_key_boundary.py` (public set), `frontend/src/routes/login/+page.svelte`,
`frontend/src/lib/api.ts` (login/MFA calls), `frontend/src/lib/i18n/errors.ts`, a new
`frontend/e2e/*-mfa-login.e2e.ts`, `frontend/e2e/support/*` (TOTP helper), `docs/LOCAL_DEV.md`
§4, plus the shared hotspots.

## Out of scope

- Passkeys (login or second factor), GitHub login and the mailed MFA link (v73).
- `is_admin` from upstream, and any migration (v72).
- The remembered-device cookie (`VB-DEVICE`), which only matters for the interim proxy.
- Any upstream code change. If one turns out to be needed, file it as an issue (CLAUDE.md) and
  ask.

## Deploy notes

None expected: no migration, no new required variable. If task 1 finds the client address
shared, say so here as an interim risk.

## Done when

- [ ] **The client address upstream sees** for a spotdl login is recorded, with its evidence
      (local log line, or the owner's production line, or "assumed shared" with the reason).
- [ ] **A password-only test identity** logs in through the real upstream. Its username is
      populated (it was `None` before), and the upstream session is logged out afterwards. Show
      the upstream `GET /user` with that token answering `403` after the login.
- [ ] **The dedicated TOTP identity** logs in through the real upstream with password + TOTP, in
      a real browser (screenshot) and in the new e2e spec.
- [ ] **The same identity logs in with a recovery code** through the real upstream.
- [ ] **The email-code path works against a local `vb2007.hu-api`** with a freshly registered
      identity: email MFA on, the code taken from the upstream's printed mail. Resend cooldown
      and wrong-code `attempts_left` are shown.
- [ ] **Wrong TOTP code:** a wrong code shows the attempts left. A used-up or expired challenge
      returns to the password step with its reason (each `reason` covered by a unit test
      against a mocked upstream).
- [ ] **No oracle, against the mocked upstream:** an off-list address with a correct password
      gets a byte-identical answer to a wrong password in three cases:
      - plain `200`;
      - MFA `202`: no `SPOTDL_MFA` cookie set, no challenge stored;
      - suspended `403`.
- [ ] **Suspended:** a suspended, allowed identity sees the suspended message. Shown against the
      mocked upstream, or a real suspended test account if the owner suspends one.
- [ ] **Rate limits:** upstream `429` and spotdl's own limit both show the rate-limited message
      with the wait time.
- [ ] **No leaked upstream tokens:** `__Host-VB-AUTH` and `__Host-VB-MFA` values never appear in
      any response to the browser, in any log line of the run, or in Postgres (grep evidence).
- [ ] **The key boundary holds:** `test_key_boundary.py` passes with the two new public routes,
      and both reject an API key.
- [ ] **The `/share` round trip** works through the MFA step (e2e or a recorded browser run).
- [ ] **UI quality:** impeccable `shape`/`polish` outputs are in the PR. Desktop and mobile, `en`
      and `hu` screenshots of both steps. Keyboard-only run of the second step.
- [ ] **Docs:** LOCAL_DEV §4 and the GOTCHAS v17 rule corrected in place, and the GOTCHAS v71
      section has its index line.
- [ ] **Checks:**
  - `pytest` (full, Postgres), the cross-user sweep, `verify_separation_sse.sh`;
  - `npm run lint`, `npm run check`, `npm run build`, `npm run test:e2e` (desktop, mobile, `hu`).
- [ ] **Version and graph:** both version files read `6.71.0`, `uv lock` is in sync, and
      `graphify update .` has been run.
