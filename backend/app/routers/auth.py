from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.db import get_db
from app.errors import ApiError
from app.models import ApiKey, User, UserSession
from app.services import allowlist, api_keys, rate_limit, upstream_auth, user_settings
from app.services.sessions import SESSION_IDLE_TIMEOUT, create_session, delete_session, get_valid_session
from app.services.spotify_urls import storable
from app.services.users import get_or_create_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "SPOTDL_SESSION"
# v71: the id of a login's waiting second step (services/upstream_auth.py's challenge store).
MFA_COOKIE_NAME = "SPOTDL_MFA"



# v71: a fresh error per raise, never one shared instance: raising the same exception object
# chains every raising request's traceback onto it, so its frames (passwords, upstream tokens)
# would stay in memory for the process's life (review round 3).
def _invalid_credentials() -> ApiError:
    return ApiError(401, "invalid_credentials", "Invalid credentials")


def _login_unavailable() -> ApiError:
    """The second step can't go on (the upstream or the challenge store isn't answering)."""
    return ApiError(503, "login_unavailable", "Sign-in is unavailable; try again later")


def _no_session(db: Session, request: Request, token: str | None) -> ApiError:
    """The 401 for a cookie that names no live session. v69: `access_removed` when a removal
    ended it and the address is still off the allowlist (services/allowlist.py), so the page can
    say why; otherwise `not_authenticated`. Never to the browser extension (`X-Spotdl-Client:
    extension/...`): its cookie-then-key fallback (v53) knows only `not_authenticated` and
    `api_key_invalid`, and must try its key on a dead cookie (review round 5)."""
    from_extension = request.headers.get("x-spotdl-client", "").startswith("extension")
    if not from_extension and allowlist.session_was_revoked(db, token):
        return ApiError(401, "access_removed", "Your access was removed")
    return ApiError(401, "not_authenticated", "Not authenticated")


class LoginRequest(BaseModel):
    email: str
    password: str


def current_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    token = request.cookies.get(COOKIE_NAME)
    if token is None:
        raise ApiError(401, "not_authenticated", "Not authenticated")

    # v69: no `last_seen_at` touch here: `require_session` writes and commits it in one call, once
    # the allowlist check passed, so a refused request never keeps an off-list session alive
    # (review round 7) and the session row's lock never spans two threadpool calls (round 8).
    # `logout` needs no touch; it commits its own delete.
    session = get_valid_session(db, token, touch=False)
    if session is None:
        raise _no_session(db, request, token)
    return session


def _off_the_allowlist(request: Request) -> ApiError:
    """v69: a live session whose address is off the allowlist (its row deleted outside /users,
    which ends no session): refused like a removed one, so the session can't outlive its access
    and the page's stream doesn't reconnect into it forever (live review round 2)."""
    if request.headers.get("x-spotdl-client", "").startswith("extension"):
        return ApiError(401, "not_authenticated", "Not authenticated")
    return ApiError(401, "access_removed", "Your access was removed")


def require_session(
    request: Request, session: UserSession = Depends(current_session), db: Session = Depends(get_db)
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
    if not allowlist.is_allowed(db, user.email):
        db.rollback()
        raise _off_the_allowlist(request)
    # A conditional UPDATE, not an ORM write: a removal (or a logout) that deleted the session
    # meanwhile matches no row, and that's a 401, never a StaleDataError 500 (review round 9).
    touched = db.execute(
        update(UserSession)
        .where(UserSession.id == session.id)
        .values(last_seen_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    ).rowcount
    if not touched:
        db.rollback()
        raise _no_session(db, request, request.cookies.get(COOKIE_NAME))
    db.commit()
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
            user = db.get(User, session.user_id)
            if user is not None:
                if not allowlist.is_allowed(db, user.email):
                    # The touch isn't kept: a refused request never extends an off-list session.
                    db.rollback()
                    raise _off_the_allowlist(request)
                db.commit()
                return Principal(user)

    bearer = _bearer_token(request)
    if bearer is None:
        raise _no_session(db, request, token)
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
            raise _no_session(db, request, token)

        user = db.get(User, session.user_id)
        if user is None:
            raise ApiError(401, "not_authenticated", "Not authenticated")
        if not allowlist.is_allowed(db, user.email):
            raise _off_the_allowlist(request)
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


def _set_mfa_cookie(response: Response, challenge_id: str) -> None:
    response.set_cookie(
        MFA_COOKIE_NAME,
        challenge_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=upstream_auth.CHALLENGE_TTL_SECONDS,
    )


def _cleared_mfa_cookie() -> str:
    """The `Set-Cookie` that removes `SPOTDL_MFA`, as a header an `ApiError` can carry (a raised
    error drops whatever the route set on its injected `Response`)."""
    cleared = Response()
    cleared.delete_cookie(MFA_COOKIE_NAME, secure=True, httponly=True, samesite="lax")
    return cleared.headers["set-cookie"]


def _mfa_expired(reason: str) -> ApiError:
    return ApiError(
        401,
        "mfa_expired",
        "The sign-in's second step expired; sign in again",
        {"reason": reason},
        headers={"set-cookie": _cleared_mfa_cookie()},
    )


def _rejected_logging_out(session: str | None, *, clear_mfa: bool = False) -> JSONResponse:
    """`invalid_credentials`, byte for byte what the raised error answers, for an upstream session
    an off-list address got: it's logged out upstream once the answer is sent, so the refusal
    takes no longer than a wrong password's (v71, owner's call over task 2's literal order)."""
    refusal = _invalid_credentials()
    response = JSONResponse(
        {"detail": refusal.detail, "code": refusal.code},
        status_code=refusal.status_code,
        background=BackgroundTask(upstream_auth.logout, session),
    )
    if clear_mfa:
        response.headers.append("set-cookie", _cleared_mfa_cookie())
    return response


async def _complete_login(db: Session, response: Response, email: str, address: str, username: str | None) -> dict:
    """The login tail both the password and the second step end in (v71)."""
    await run_in_threadpool(rate_limit.clear_login_failures, email, address)
    # Read again, now locked (FOR SHARE) until this login commits its session, and only now: a
    # removal meanwhile waits for it, then ends that session with the others. Not across the
    # Redis call above (a stalled Redis would hold a removal for its retries). Off the event
    # loop, since it may wait on a removal's row lock.
    if not await run_in_threadpool(allowlist.is_allowed, db, email, lock=True):
        db.rollback()
        raise _invalid_credentials()
    user = get_or_create_user(db, email, username)
    session = create_session(db, user.id)
    db.commit()
    _set_session_cookie(response, session.token)
    return {"email": user.email, "username": user.username, "is_admin": user.is_admin}


@router.post("/login", response_model=None)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict | JSONResponse:
    # v53: failed logins are limited per email and client address, counted before the
    # upstream is asked at all. The Redis client is sync, so it runs off the event loop.
    # An email or password no one can have (a NUL, a lone surrogate) is rejected like any
    # wrong one, before it reaches a hash, the upstream or Postgres (each would be a 500).
    if not (storable(payload.email) and storable(payload.password)):
        raise _invalid_credentials()
    address = rate_limit.client_address(request)
    await run_in_threadpool(rate_limit.hit_login, payload.email, address)

    result = await upstream_auth.login(payload.email, payload.password)
    # Upstream limits failed logins before it checks the password, so its 429 says nothing about
    # the address either way.
    if isinstance(result, upstream_auth.RateLimited):
        raise rate_limit.rate_limited(result.retry_after)
    # v69: the allowlist table, read now (never cached), so an address added in /users signs
    # in on its next attempt. Read for every answer, so each takes the same path.
    allowed = await run_in_threadpool(allowlist.is_allowed, db, payload.email)
    db.commit()

    # v71: no oracle. Upstream answers a session, an MFA challenge or "suspended" only after a
    # right password; for an off-list address each is exactly a wrong password's answer: no
    # challenge kept, no SPOTDL_MFA cookie, no upstream session left. An unreachable upstream
    # reads as a refusal too, as before (`login_error_rejected` says the service may be down).
    if not allowed or isinstance(result, (upstream_auth.Invalid, upstream_auth.Unavailable)):
        if isinstance(result, upstream_auth.Ok):
            return _rejected_logging_out(result.session)
        raise _invalid_credentials()
    if isinstance(result, upstream_auth.Suspended):
        raise ApiError(403, "account_suspended", "This vb2007.hu account is suspended")
    if isinstance(result, upstream_auth.MfaRequired):
        methods = upstream_auth.proxied_methods(result.methods)
        if not methods:
            raise ApiError(403, "mfa_unsupported", "This account's second step can't be used here yet")
        try:
            challenge_id = await run_in_threadpool(upstream_auth.store_challenge, result.challenge, payload.email)
        except upstream_auth.ChallengeStoreError:
            raise _login_unavailable() from None
        _set_mfa_cookie(response, challenge_id)
        return {"mfa_required": True, "methods": methods}

    username = await upstream_auth.finish(result.session)
    return await _complete_login(db, response, payload.email, address, username)


class MfaVerifyRequest(BaseModel):
    method: Literal["totp", "email", "recovery"]
    code: str


async def _stored_challenge(request: Request) -> tuple[str, str, str]:
    """(SPOTDL_MFA id, upstream challenge, email) for an `/api/auth/mfa` request, counted by the
    limits first. Its cookie is the only credential these routes take: never a session or a key."""
    challenge_id = request.cookies.get(MFA_COOKIE_NAME)
    if not challenge_id:
        raise _mfa_expired("noChallenge")
    await run_in_threadpool(rate_limit.hit_mfa, challenge_id, rate_limit.client_address(request))
    try:
        stored = await run_in_threadpool(upstream_auth.load_challenge, challenge_id)
    except upstream_auth.ChallengeStoreError:
        raise _login_unavailable() from None
    if stored is None:
        raise _mfa_expired("expired")
    return challenge_id, *stored


async def _ended(challenge_id: str, reason: str) -> ApiError:
    await run_in_threadpool(upstream_auth.drop_challenge, challenge_id)
    return _mfa_expired(reason)


@router.post("/mfa/verify", response_model=None)
async def mfa_verify(
    payload: MfaVerifyRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict | JSONResponse:
    """v71: the login's second step (TOTP, an emailed code or a recovery code), forwarded to
    upstream with the challenge `login` stored."""
    challenge_id, upstream_challenge, email = await _stored_challenge(request)
    if not storable(payload.code):
        raise ApiError(400, "mfa_code_invalid", "Wrong code")
    result = await upstream_auth.verify(upstream_challenge, payload.method, payload.code)
    if isinstance(result, upstream_auth.CodeRejected):
        params = {} if result.attempts_left is None else {"attempts_left": result.attempts_left}
        headers = None
        if result.attempts_left == 0:
            # That was the last try: upstream has ended the challenge, so it goes here too.
            await run_in_threadpool(upstream_auth.drop_challenge, challenge_id)
            headers = {"set-cookie": _cleared_mfa_cookie()}
        raise ApiError(400, "mfa_code_invalid", "Wrong code", params, headers=headers)
    if isinstance(result, upstream_auth.ChallengeEnded):
        raise await _ended(challenge_id, result.reason)
    if isinstance(result, upstream_auth.RateLimited):
        raise rate_limit.rate_limited(result.retry_after)
    if not isinstance(result, upstream_auth.Ok):
        raise _login_unavailable()

    await run_in_threadpool(upstream_auth.drop_challenge, challenge_id)
    # Off the allowlist since the password step (a removal in those minutes): refused like then.
    allowed = await run_in_threadpool(allowlist.is_allowed, db, email)
    db.commit()
    if not allowed:
        return _rejected_logging_out(result.session, clear_mfa=True)
    username = await upstream_auth.finish(result.session)
    try:
        answer = await _complete_login(db, response, email, rate_limit.client_address(request), username)
    except ApiError as refused:
        # Removed meanwhile (the locked re-check): its challenge is gone, so is its cookie.
        raise ApiError(
            refused.status_code,
            refused.code,
            refused.detail,
            refused.params,
            headers={**(refused.headers or {}), "set-cookie": _cleared_mfa_cookie()},
        ) from None
    response.delete_cookie(MFA_COOKIE_NAME, secure=True, httponly=True, samesite="lax")
    return answer


@router.post("/mfa/email")
async def mfa_email(request: Request) -> dict:
    """v71: mails a fresh code for the waiting second step (upstream's 1 a minute, 10 a day)."""
    challenge_id, upstream_challenge, _ = await _stored_challenge(request)
    result = await upstream_auth.send_email_code(upstream_challenge)
    if isinstance(result, upstream_auth.Sent):
        return {"status": "sent"}
    if isinstance(result, upstream_auth.MethodOff):
        raise ApiError(400, "mfa_method_off", "Email codes are off for this account")
    if isinstance(result, upstream_auth.MailUnavailable):
        raise ApiError(503, "mail_unavailable", "The code couldn't be mailed; try again later")
    if isinstance(result, upstream_auth.ChallengeEnded):
        raise await _ended(challenge_id, result.reason)
    if isinstance(result, upstream_auth.RateLimited):
        raise rate_limit.rate_limited(result.retry_after, result.reason)
    raise _login_unavailable()


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
