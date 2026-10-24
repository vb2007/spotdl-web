# v69 — Admin-Managed User Access

Branch: `dev-user-access` → PR into `main`
Version: `5.69.0`
Wave / slot: 5 / 3
Depends on: v53 (API keys, the key boundary), v56 (A6's admin 403/404 rule), v62 (F9's cross-tab
identity), and waves 0–4 merged

## Scope

The owner's request (2026-10-24): the admin adds e-mail addresses to the login allowlist **from
the app**, and that person can sign in right away. No `.env` edit, no redeploy.

Today:
- `ALLOWED_EMAILS` is an env list (`backend/app/config.py:75`), checked on each login at
  `routers/auth.py:114`. A rejection is indistinguishable from bad credentials
  (`_INVALID_CREDENTIALS`).
- Boot refuses to start unless `ADMIN_EMAIL` is in it (`config.py:198-212`).
- Adding someone means editing the host `.env` and recreating `api`
  (`docs/DEPLOYMENT.md:655-663`).
- Removing someone from the env list doesn't end their existing sessions.
- An open `/api/stream` checks its session only at connect.

**Owner decisions (2026-10-24):**
- **Import once, then the app owns it.** A migration copies today's `ALLOWED_EMAILS` (plus
  `ADMIN_EMAIL`) into a table. From then on the env list is **ignored**. `ADMIN_EMAIL` stays in
  env, is always allowed, and can't be removed.
- **Removal cuts access at once:**
  - all of the person's sessions end;
  - an open live stream closes;
  - their API keys (v53) are revoked.

  Their jobs and files stay. Adding the address again restores the same `users` row and its
  history.

The `users` table is untouched in meaning: it still decides what someone owns and may do, and
`is_admin` still comes from `ADMIN_EMAIL`. Only "who may log in" moves from env to the database.

## Tasks

1. **Schema and migration.**
   - A new `allowed_emails` table:
     - `email`: text primary key, stored normalized (lowercase, trimmed, via
       `services.users.normalize_email`);
     - `added_by`: FK `users.id`, `ON DELETE SET NULL`, nullable, since imported rows have none;
     - `added_at`: `server_default=now()`.
   - A data step imports `get_settings().allowed_emails ∪ {ADMIN_EMAIL}`, normalized, with
     `ON CONFLICT DO NOTHING`. Running it twice changes nothing.
   - `downgrade()` drops the table. The env list still exists then, so behavior falls back to
     today's.
   - The migration only adds data. Say so in its docstring, and take a `pg_backup` before the
     production deploy anyway (the master-v4 rule).
2. **`services/allowlist.py`.**
   - `is_allowed(db, email) -> bool`: true when the normalized address is `ADMIN_EMAIL`, or a row
     exists. It's read from the DB **on every login, never cached**, so an addition counts on the
     next attempt.
   - `add(db, email, by: User)`:
     - minimal syntax validation (one `@`, a dot in the domain, no whitespace), else 422
       `invalid_email`;
     - an existing row gives 409 `email_already_allowed`.
   - `remove(db, email)`:
     - `ADMIN_EMAIL` gives 409 `cannot_remove_admin`, and an unknown address 404;
     - otherwise, in **one transaction**: delete the row, delete every `user_sessions` row of the
       matching user (if a user row exists), and set `revoked_at` on all of that user's `api_keys`;
     - after commit, publish the revocation (task 4).
3. **Login and config.**
   - `login()` in `routers/auth.py` uses `allowlist.is_allowed`, and keeps the single
     indistinguishable 401.
   - Remove `_check_admin_email_is_allowlisted` from `config.py`. `ALLOWED_EMAILS` becomes
     optional, an import source only. Its field comment says so.
   - At `api` startup, log **one warning** when the env list holds an address that isn't in the
     table: "ALLOWED_EMAILS is ignored since v69, manage users in /users". Without it, a later
     `.env` edit would silently do nothing. The warning never prints the addresses (they count as
     personal data); it prints only the count.
4. **Live revocation.**
   - **A separate control channel** `spotdl:control:{user_id}` (`services/events.py`). It must
     **never** match the admin's `spotdl:events:*` pattern subscription. Otherwise removing
     someone would deliver the revocation to the admin's own tab, which would log itself out.
   - `/api/stream` subscribes to the caller's own control channel too (a second, exact
     subscription), and ends the stream on `revoked`.
   - **The safety net:** pub/sub is fire-and-forget. So the stream loop also re-validates the
     session on every heartbeat (15s), with a **short-lived** DB session in the
     `require_session_for_streaming` pattern, never one held open for the stream's life (v31's
     idle-in-transaction bug, GOTCHAS v23/v31).
   - **Frontend:** a stream that ends and reconnects into a 401, or any API call that gets a 401
     after a session existed, runs the existing logout path:
     - `queue.reset()`;
     - v62's `BroadcastChannel('spotdl-session')` push, so other tabs follow;
     - a redirect to `/login` with "Your access was removed", in en and hu.

     Reuse whatever single logout function exists; don't add a second one.
5. **The admin API**, in new `routers/admin_users.py`:
   - `GET /api/admin/allowlist`: **one** bulk query joining `users` by email. Each row has email,
     `added_at`, the `added_by` email, username, `last_login_at` (null means "never signed in"), and
     `is_admin_email`.
   - `POST /api/admin/allowlist` `{email}`: 201 with the row.
   - `DELETE /api/admin/allowlist/{email}`: 204.
   - Admin-only, answering a non-admin per **v56's A6 table**. An API key is refused on all three
     (v53's boundary; v70's deny-by-default test will check it).
6. **The `/users` page** (admin-only; impeccable `shape` → `critique` → `audit`, outputs recorded):
   - A new route with the SvelteKit `ssr`/`prerender` exports **and** its own `frontend/nginx.conf`
     `location` (CLAUDE.md invariant). The page guards non-admins the way `/settings` does today.
   - An admin-only nav entry in `+layout.svelte`, **absent** from a non-admin's DOM (not just
     hidden).
   - **Add:** an e-mail input plus a button. Enter submits, and the error `code`s map to messages.
     A note says the person signs in with their vb2007.hu account; the app sends no invitation.
   - **List:**
     - address and name;
     - "last signed in", in the user's format settings (language + region + 12h/24h);
     - "never signed in" when there's no user row;
     - "added by / when";
     - the `ADMIN_EMAIL` row has a badge and no remove control.
   - **Remove:** through the existing `ConfirmDialog`. The dialog states the consequence: signed
     out everywhere now, extension keys revoked, data kept.
   - **Keyboard:** a go-to binding registered in the shortcut registry, collision-checked there,
     following the Hungarian QWERTZ rules (no AltGr, no `Y`/`Z`, `event.key`). It's listed in the
     help overlay. Every control is keyboard-reachable.
   - All strings go in both `en.json` and `hu.json`. Phone width is handled.
7. **Docs and knowledge.**
   - `docs/DEPLOYMENT.md`: replace the "add an address to `ALLOWED_EMAILS`" section with
     `/users`, and state that the env list is import-only.
   - `.env.example` and `.env.dev.example`: comments that `ALLOWED_EMAILS` only seeds a fresh
     database.
   - `docs/LOCAL_DEV.md`: slot stacks import their test identities on the first `migrate`; later
     ones are added in `/users`, or with a `down --volumes` reset.
   - `CLAUDE.md`: edit the master-v2 "User identity" and "Admin" rows, keeping the file ≤250 lines.
     The allowlist is a DB table managed in `/users`, and `ADMIN_EMAIL` is always allowed.
   - A GOTCHAS **v69** entry with its index line.

## Files owned

- **Backend:**
  - the new Alembic migration;
  - new `backend/app/models/allowed_email.py`, plus `models/__init__.py`;
  - new `backend/app/services/allowlist.py`, plus `services/users.py`;
  - `routers/auth.py` (the login check only);
  - new `backend/app/routers/admin_users.py`, plus `main.py` (the include);
  - `config.py` (the validator and the warning);
  - `routers/stream.py` (the control subscription and the re-check);
  - `services/events.py` (the control publish).
- **Frontend:**
  - new `frontend/src/routes/users/*`, plus `frontend/nginx.conf` (one `location`);
  - `frontend/src/routes/+layout.svelte` (the nav entry only);
  - `frontend/src/lib/api.ts` (the new calls);
  - `frontend/src/lib/keyboard/bindings.ts` (one binding);
  - `frontend/src/lib/stores/queue.ts` (the revoke-handling block only; v68 may touch the store
    for windowing, a declared wave-5 hotspot).
- **Tests:**
  - new `frontend/e2e/user-access.spec.ts` (v68 owns the rest of `frontend/e2e/`);
  - new `backend/tests/test_allowlist.py`;
  - `scripts/verify_separation_sse.sh` (the revocation case).
- **Docs:** `docs/DEPLOYMENT.md`, `docs/LOCAL_DEV.md`, `.env.example`, `.env.dev.example`,
  `CLAUDE.md`, plus the message JSONs and GOTCHAS (hotspots).

## Out of scope

- Invitations by e-mail (the app sends no mail).
- Creating vb2007.hu accounts upstream.
- Roles beyond the single admin.
- Deleting a user's data, and a user-list view beyond the allowlist rows.

## Deploy notes

- The migration imports production's `ALLOWED_EMAILS` on deploy. Take a `pg_backup` first.
- Keep the `.env` line until the owner has confirmed the import in `/users`; it's ignored after
  that and may be deleted.
- After deploy, the owner removes `v48smoke@example.com` in `/users` (housekeeping item).

## Done when

- [ ] **Migration:** on a fresh slot DB with a 3-address env list (mixed case, spaces), the table
      holds the normalized list plus `ADMIN_EMAIL`. A second `upgrade` changes nothing.
      `upgrade` → `downgrade -1` → `upgrade` is clean, and `alembic heads` shows one head
      (outputs).
- [ ] **Real-time add:** the admin adds a freshly registered **real-upstream** test address in
      `/users`, and that address signs in within seconds, **with no restart** (`agent_stack.sh <n>
      ps` uptime unchanged, plus the login response and a screenshot).
- [ ] **Removal cuts off at once,** each with its own evidence:
  - the removed user's next request is 401;
  - their open `curl -N /api/stream` ends (a raw capture);
  - their API key is refused;
  - **the admin's own pattern stream stays open** through it (a raw capture of both).
- [ ] **The safety net:** with the publish suppressed (a test hook), the removed user's stream
      still ends within one heartbeat (a capture with timestamps). No connection sits `idle in
      transaction` meanwhile (`pg_stat_activity`).
- [ ] **Re-add** restores the same `users.id` and its jobs (ids before and after).
- [ ] `ADMIN_EMAIL` can't be removed (409). A duplicate gets 409, a malformed address 422, and an
      unknown one 404 (pytest plus one real call each).
- [ ] **Boundaries:**
  - a non-admin gets v56's A6 answer on every allowlist method;
  - an admin's **API key** is refused on all of them;
  - login rejection stays indistinguishable: an unlisted address and a wrong password give the
    same status and body.
- [ ] **The startup warning** appears with the count when env lists an un-imported address, and
      never prints an address (log line).
- [ ] **UI:**
  - impeccable output recorded;
  - screenshots at 390 and 1440 px in `en` and `hu`;
  - keyboard-only add and remove (e2e);
  - the nav entry is absent from a non-admin's DOM (e2e);
  - a hard reload of `/users` through nginx works;
  - a second browser context signed in as the removed user is sent to `/login` live, with the
    message, and its other tab follows (e2e).
- [ ] The ownership suite, `verify_separation_sse.sh` (including the new revocation case), and the
      full e2e on desktop, mobile and `hu` all pass.
- [ ] Docs, GOTCHAS v69 and the `CLAUDE.md` rows are in the diff. `CLAUDE.md` ≤ 250 lines.
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `5.69.0`. `uv lock` is in sync. `graphify update .` has been run.
