from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User, UserSession
from app.services import upstream_auth
from app.services.sessions import SESSION_IDLE_TIMEOUT, create_session, delete_session, get_valid_session
from app.services.users import get_or_create_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "SPOTDL_SESSION"

_INVALID_CREDENTIALS = HTTPException(status_code=401, detail="Invalid credentials")


class LoginRequest(BaseModel):
    email: str
    password: str


def current_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    token = request.cookies.get(COOKIE_NAME)
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = get_valid_session(db, token)
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

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
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(user: User = Depends(require_session)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


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
        raise HTTPException(status_code=401, detail="Not authenticated")

    db_factory = request.app.dependency_overrides.get(get_db, get_db)
    db_gen = db_factory()
    db = next(db_gen)
    try:
        session = get_valid_session(db, token)
        if session is None:
            raise HTTPException(status_code=401, detail="Not authenticated")

        user = db.get(User, session.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
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
async def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()

    upstream_ok, username = await upstream_auth.login(payload.email, payload.password)
    allowed = payload.email.strip().lower() in {e.strip().lower() for e in settings.allowed_emails}

    # Upstream failure and allowlist rejection must be indistinguishable to the caller.
    if not upstream_ok or not allowed:
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
def me(user: User = Depends(require_session)) -> dict:
    return {"email": user.email, "username": user.username, "is_admin": user.is_admin}
