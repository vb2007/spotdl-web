from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import ApiKey, User, UserSession
from app.services import allowlist, api_keys, rate_limit, upstream_auth, user_settings
from app.services.sessions import SESSION_IDLE_TIMEOUT, create_session, delete_session, get_valid_session
from app.services.spotify_urls import storable
from app.services.users import get_or_create_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "SPOTDL_SESSION"

_INVALID_CREDENTIALS = ApiError(401, "invalid_credentials", "Invalid credentials")


def _no_session(token: str | None) -> ApiError:
    """The 401 for a cookie that names no live session. v69: `access_removed` when a removal
    ended it (services/allowlist.py), so the page can say why; otherwise `not_authenticated`."""
    if allowlist.session_was_revoked(token):
        return ApiError(401, "access_removed", "Your access was removed")
    return ApiError(401, "not_authenticated", "Not authenticated")


class LoginRequest(BaseModel):
    email: str
    password: str


def current_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    token = request.cookies.get(COOKIE_NAME)
    if token is None:
        raise ApiError(401, "not_authenticated", "Not authenticated")

    session = get_valid_session(db, token)
    if session is None:
        raise _no_session(token)

    db.commit()
    return session


def require_session(
    session: UserSession = Depends(current_session), db: Session = Depends(get_db)
) -> User:
    """Every owner-scoped route depends on this, not `current_session` directly --
    `session.user_id` is only ever a means to reach the `User` that actually carries
    ownership and the admin flag (v17)."""
    user = db.get(User, session.user_id)
    if user is None:
        # The session outlived its user (never expected in practice -- ON DELETE CASCADE
        # isn't set up, so this would mean a row was deleted out from under a live
        # session), but "not authenticated" is the correct response either way.
        raise ApiError(401, "not_authenticated", "Not authenticated")
    return user


def require_admin(user: User = Depends(require_session)) -> User:
    """v56 (A6): for an admin action whose path names no id (settings, worker controls, the
    proxy list, the library sweep). A non-admin's 403 there confirms nothing."""
    if not user.is_admin:
        raise ApiError(403, "admin_required", "Admin access required")
    return user


def require_admin_hidden(user: User = Depends(require_session)) -> User:
    """v56 (A6): for an admin route whose path names an id (a job's priority or bump, one
    proxy), and the test-alert send v36 hid, answering a non-admin exactly like a route that
    doesn't exist, so neither the route nor the id is confirmed (CLAUDE.md's v2 invariant:
    ids are never confirmed). `/api/admin/stats` has its own copy (admin.py, v44).
    Unauthenticated is still 401, from require_session."""
    if not user.is_admin:
        # Deliberately no `code` (v46): it must read exactly like an unknown route's 404.
        raise HTTPException(status_code=404, detail="Not Found")
    return user


@dataclass
class Principal:
    """Who a `require_session_or_api_key` route is acting for, and how they got in."""

    user: User
    # Set when the request authenticated with an API key rather than the session cookie.
    api_key: ApiKey | None = None


def _bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def require_session_or_api_key(request: Request, db: Session = Depends(get_db)) -> Principal:
    """v53: the session cookie first, then `Authorization: Bearer sdw_...` (the browser
    extension's fallback when the cookie doesn't reach the API). Only job create,
    `GET /api/jobs/{id}` (a key: its own jobs only) and `GET /api/auth/me` depend on this. Every other route keeps `require_session` (cookie
    only), so a key can't reach it at all, and `require_admin` sits on top of that: an
    admin's key is never admin."""
    token = request.cookies.get(COOKIE_NAME)
    if token is not None:
        session = get_valid_session(db, token)
        if session is not None:
            db.commit()
            user = db.get(User, session.user_id)
            if user is not None:
                return Principal(user)

    bearer = _bearer_token(request)
    if bearer is None:
        raise _no_session(token)
    key = api_keys.authenticate(db, bearer)
    user = db.get(User, key.user_id) if key is not None else None
    # A key outlives a login, so it re-checks the allowlist a login checks. v69: a removal
    # revokes the user's keys too; this stays as the second line (an address taken off the
    # table by hand, say).
    if user is not None and not allowlist.is_allowed(db, user.email):
        user = None
    if user is None:
        # Never echoes the key back, not even its prefix.
        raise ApiError(401, "api_key_invalid", "Invalid or revoked API key")
    db.commit()
    return Principal(user, key)


def require_session_for_streaming(request: Request) -> User:
    """v31: root-caused a Postgres connection sitting `idle in transaction` for hours
    (docs/GOTCHAS.md's v23 entry) to `/api/stream`. Starlette doesn't tear down a
    `yield`-based dependency like `get_db` until the *whole* response completes -- for a
    `StreamingResponse` that's when the SSE connection itself closes, not when the route
    function returns. `require_session`'s shared per-request `db` (via `Depends(get_db)`)
    would therefore sit open, holding `require_session`'s own post-commit `SELECT ...
    FROM users` transaction, for as long as the browser tab stays open. This variant
    drives `get_db` (or its test override, resolved the same way FastAPI itself would)
    by hand instead of through `Depends`, so the generator's `finally: db.close()` runs
    right after the auth check -- not deferred to the end of the streamed response. Only
    `/api/stream` should use this -- every other route's response completes immediately
    after the handler returns, so `require_session` there is correctly scoped already."""
    token = request.cookies.get(COOKIE_NAME)
    if token is None:
        raise ApiError(401, "not_authenticated", "Not authenticated")

    db_factory = request.app.dependency_overrides.get(get_db, get_db)
    db_gen = db_factory()
    db = next(db_gen)
    try:
        session = get_valid_session(db, token)
        if session is None:
            raise _no_session(token)

        user = db.get(User, session.user_id)
        if user is None:
            raise ApiError(401, "not_authenticated", "Not authenticated")
        db.commit()
        # Re-touch *after* commit, while the session is still open -- `expire_on_commit`
        # (the sessionmaker default) marks attributes stale on commit, and reading them
        # here while still attached reloads them so they survive the session closing
        # below (a detached instance raises on any access that would otherwise re-query).
        _ = (user.id, user.is_admin)
        return user
    finally:
        next(db_gen, None)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=int(SESSION_IDLE_TIMEOUT.total_seconds()),
    )


@router.post("/login")
async def login(
    payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict:
    # v53: failed logins are limited per email and client address, counted before the
    # upstream is asked at all. The Redis client is sync, so it runs off the event loop.
    # An email or password no one can have (a NUL, a lone surrogate) is rejected like any
    # wrong one, before it reaches a hash, the upstream or Postgres (each would be a 500).
    if not (storable(payload.email) and storable(payload.password)):
        raise _INVALID_CREDENTIALS
    address = rate_limit.client_address(request)
    await run_in_threadpool(rate_limit.hit_login, payload.email, address)

    upstream_ok, username = await upstream_auth.login(payload.email, payload.password)
    # v69: the allowlist table, read now (never cached), so an address added in /users signs
    # in on its next attempt.
    allowed = allowlist.is_allowed(db, payload.email)
    db.commit()

    # Upstream failure and allowlist rejection must be indistinguishable to the caller.
    if not upstream_ok or not allowed:
        raise _INVALID_CREDENTIALS

    await run_in_threadpool(rate_limit.clear_login_failures, payload.email, address)
    # Read again, now locked (FOR SHARE) until this login commits its session, and only now: a
    # removal meanwhile waits for it, then ends that session with the others. Not across the
    # Redis call above (a stalled Redis would hold a removal for its retries). Off the event
    # loop, since it may wait on a removal's row lock.
    if not await run_in_threadpool(allowlist.is_allowed, db, payload.email, lock=True):
        db.rollback()
        raise _INVALID_CREDENTIALS
    user = get_or_create_user(db, payload.email, username)
    session = create_session(db, user.id)
    db.commit()
    _set_session_cookie(response, session.token)
    return {"email": user.email, "username": user.username, "is_admin": user.is_admin}


@router.post("/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    session: UserSession = Depends(current_session),
) -> dict:
    delete_session(db, session.token)
    db.commit()
    response.delete_cookie(COOKIE_NAME)
    return {"status": "ok"}


@router.get("/me")
def me(principal: Principal = Depends(require_session_or_api_key), db: Session = Depends(get_db)) -> dict:
    user = principal.user
    if principal.api_key is not None:
        # v53: a key reads who it belongs to and nothing else. `is_admin` is reported as
        # it is, but grants nothing through a key.
        return {"email": user.email, "username": user.username, "is_admin": user.is_admin}
    # v45: the keyboard-shortcut preference rides along, so the app shell knows it on every
    # route load without a second request. v46: so do the language and the clock (`null`:
    # none saved, the browser decides). v66: and the job-notifications switch.
    return {
        "email": user.email,
        "username": user.username,
        "is_admin": user.is_admin,
        "keyboard_shortcuts": user_settings.keyboard_shortcuts_enabled(db, user.id),
        "language": user_settings.language_preference(db, user.id),
        "clock": user_settings.clock_preference(db, user.id),
        "job_notifications": user_settings.job_notifications_enabled(db, user.id),
    }
