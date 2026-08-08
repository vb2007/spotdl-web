# v03 — Authentication

Branch: `dev-auth` → PR into `main`

## Scope

Login against the existing `vb2007.hu-api`, enforce the email allowlist, and issue our own session
cookie. No feature of spotdl-web should be reachable without a valid session after this version.

## Why server-to-server (recap from master plan)

`vb2007.hu-api`'s `POST /auth/login` (`src/controllers/authentication.ts:39`) sets
`Set-Cookie: VB-AUTH=...; Domain=localhost`, which a browser on any other domain can never store.
So the browser talks only to spotdl-web; spotdl-web talks to `vb2007.hu-api` server-side and never
forwards `VB-AUTH` anywhere.

`POST /auth/register` on the upstream API is public, so login success there is **not** sufficient
authorization — it only proves "this is a real vb2007.hu-api account." The allowlist is the actual
gate.

## Tasks

1. `app/services/upstream_auth.py` — `async def login(email, password) -> bool`: POST
   `{UPSTREAM_AUTH_BASE_URL}/auth/login` with `{email, password}` JSON. Success = `200`. Any
   `400/403/404` or network error = failed login (map to a generic "invalid credentials" — do not
   leak which of email/password was wrong, and do not leak whether the allowlist rejected it).
   Discard the response cookie/body entirely once the status is checked.
2. `ALLOWED_EMAILS` env var (comma-separated) — checked in the login flow *after* upstream success:
   upstream login failure and allowlist rejection must return the identical response so a
   non-allowlisted vb2007.hu-api user can't distinguish "wrong password" from "not allowed here."
3. `app/services/sessions.py` — issue: generate a random 256-bit token, insert into `sessions`
   (email, token, timestamps), set an `HttpOnly`, `Secure`, `SameSite=Lax` cookie
   (`SPOTDL_SESSION`) scoped to spotdl-web's own domain. Validate: look up by token, bump
   `last_seen_at`, 403 if missing/expired. No upstream call on every request — only at login time.
4. `require_session` FastAPI dependency wrapping session validation; every router added from v04
   onward depends on it.
5. Routes: `POST /api/auth/login` (email/password → cookie), `POST /api/auth/logout` (delete
   session row, clear cookie), `GET /api/auth/me` (return `{email}` from the current session or
   `401`).
6. Session expiry policy: idle timeout via `last_seen_at` (e.g. 30 days), enforced in
   `require_session`, not by Postgres TTL — keep it explicit and testable.
7. `graphify update .`

## Files touched (new)

`backend/app/services/upstream_auth.py`, `backend/app/services/sessions.py`,
`backend/app/routers/auth.py`, dependency wiring in `backend/app/main.py`.

## Done when

- Logging in with a real allowlisted `vb2007.hu-api` account returns `200` and a session cookie;
  `GET /api/auth/me` then returns that email.
- A valid `vb2007.hu-api` account **not** in `ALLOWED_EMAILS` gets the same rejection response as a
  wrong password — verified by comparing both responses byte-for-byte.
- `VB-AUTH` never appears in any response header or body returned to the browser (grep the
  response set in a test).
- Hitting any placeholder-protected route without a session returns `401`.
