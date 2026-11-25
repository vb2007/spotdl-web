# v72 — Identity from Upstream

Branch: `dev-upstream-identity` → PR into `main`
Version: `6.72.0`
Wave / slot: 1 / 1 (serial, after v71)
Depends on: v71 merged

## Scope

Two accepted proposals that need no upstream change:

1. **Admin from upstream.** spotdl's `is_admin` comes from `ADMIN_EMAIL` (v17, v69). The owner
   confirmed (2026-11-24) that this is the same account as upstream's `SUPERUSER_EMAIL`, and
   `GET /user` answers `isSuperuser`. spotdl follows the upstream instead of keeping a second
   copy.
2. **Account security links.** spotdl reimplements none of the account security vb2007.hu now
   has: password, email change, MFA, passkeys, GitHub link, password reset, registration. It
   links to them.

## Tasks

1. **Store the upstream flag.**
   - `upstream_auth`'s `GET /user` read (v71) also returns `isSuperuser`. A non-boolean or
     missing value counts as "unknown".
   - The login tail sets `user.is_admin` from it **only when it's known**. An unknown value (a
     failed read, odd JSON) **never changes** `is_admin`, the same way the username already
     degrades.
   - A migration is needed only if the model can't express this as is. If it is needed, it
     documents in its docstring that it rewrites no data.
2. **`ADMIN_EMAIL` becomes a dev override.**
   - In production it's no longer read: remove it from `.env.example`, `config.py`'s required
     checks, and the boot check that it's on the allowlist.
   - With `SPOTDL_ENV=dev` it's still honored: a dev test identity is never the upstream superuser
     of `api.vb2007.hu`, so the dev and slot stacks need it. This covers `.env.dev.example`,
     `scripts/agent_stack.sh`, `scripts/agent_seed.py` and the e2e support.
   - If it's listed in compose as `${ADMIN_EMAIL:?}` anywhere, follow
     `docs/RELEASE_PIPELINE.md`'s checklist in reverse (removing a required variable), and put
     it under Deploy notes.
   - Existing production data needs nothing: the owner's row already has `is_admin = true`, and
     their allowlist row exists (v69 seed). Confirm both read-only in the PR evidence (only with
     the owner's OK for a production read, per memory).
3. **v69's protections key on `is_admin`.** "The admin is always allowed and can't be removed
   from `/users`" now checks the user's `is_admin`, not `ADMIN_EMAIL`. Audit every
   `admin_email` / `ADMIN_EMAIL` use (`config.py`, `services/users.py`, `services/allowlist.py`,
   `tasks/beat.py`, tests, scripts) and keep each behavior.
4. **Revoke admin scope on loss.** A login whose read says `isSuperuser: false` for a current
   admin clears `is_admin`. Their next request gets the non-admin view: the v56 403/404 rule, and
   their open stream re-scoped or closed the way v69's revocation does. Test it.
5. **Links.** Use the impeccable skill (`polish`).
   - `/account` gains a "vb2007.hu account" section that says these settings live on vb2007.hu,
     with links to `https://vb2007.hu/account` (password, email, two-step login, passkeys,
     GitHub).
   - `/login` gains "Forgot password?" (`https://vb2007.hu/reset-password`) and "Create an
     account" (`https://vb2007.hu/register`). The hint keeps saying access is by invitation.
   - The base URL is one frontend constant.
   - Links open in the same tab, and are keyboard-reachable. Strings are in `en` and `hu`.
6. **Docs.** `CLAUDE.md`'s locked-decision rows for the admin source (v2 "Admin", v69's
   `ADMIN_EMAIL` sentence); `docs/DEPLOYMENT.md` and `docs/LOCAL_DEV.md` where they describe
   `ADMIN_EMAIL`; a GOTCHAS v72 entry.

## Files owned

`backend/app/services/upstream_auth.py` (the `isSuperuser` read), `backend/app/routers/auth.py`
(the login tail), `backend/app/config.py`, `backend/app/services/{users,allowlist}.py`,
`backend/app/tasks/beat.py` (only where it reads `admin_email`), a migration if needed, `backend/tests/{test_users,test_config,test_allowlist,test_auth}.py`,
`.env.example`, `.env.dev.example`, `scripts/{agent_stack.sh,agent_seed.py}`,
`frontend/e2e/support/stack.ts`, `frontend/e2e/.env.e2e.example`,
`frontend/src/routes/{account,login}/+page.svelte`, plus the shared hotspots.

## Out of scope

- Periodic sync of the flag without a login (v74).
- Showing the upstream MFA or passkey status inside spotdl: spotdl holds no upstream session to
  read it with.

## Deploy notes

`ADMIN_EMAIL` is no longer read in production. Say whether the host `.env` line should be
removed, and whether a compose check changed.

## Done when

- [ ] **Admin through the real upstream:** a real-upstream login of an identity whose `GET /user`
      says `isSuperuser: false` leaves a non-admin non-admin. The dev override makes the dev admin
      identity admin, and it stays admin across a login.
- [ ] **Admin, unit tests against a mocked upstream:**
  - `isSuperuser: true` grants admin;
  - `false` revokes it, and that user's next admin request gets 403/404 per v56 and their
    stream loses admin scope;
  - a failed or odd read changes nothing.
- [ ] **`ADMIN_EMAIL` is dev-only:** production config (`SPOTDL_ENV` unset) boots without it, and
      ignores it if set (test). Dev still honors it.
- [ ] **v69's protection keys on `is_admin`:** "can't remove the admin" now keys on `is_admin`.
      `test_allowlist.py` covers it, and the `/users` UI still disables removing yourself.
- [ ] **Production data:** read-only evidence (with the owner's OK) that the owner's account is
      `is_admin` and on the allowlist before deploy. If the owner declines the read, state the
      risk instead.
- [ ] **Links:** the `/account` section and the `/login` links work, keyboard-only, with desktop
      and mobile, `en` and `hu` screenshots, and the impeccable output.
- [ ] **Checks:**
  - `pytest` (full, Postgres), the cross-user sweep, `verify_separation_sse.sh`;
  - lint, check, build, e2e (all projects).
- [ ] **Version and graph:** both version files read `6.72.0`, `uv lock` is in sync, and
      `graphify update .` has been run.
