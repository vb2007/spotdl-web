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

    upstream_ok = await upstream_auth.login(payload.email, payload.password)
    allowed = payload.email.strip().lower() in {e.strip().lower() for e in settings.allowed_emails}

    # Upstream failure and allowlist rejection must be indistinguishable to the caller.
    if not upstream_ok or not allowed:
        raise _INVALID_CREDENTIALS

    user = get_or_create_user(db, payload.email)
    session = create_session(db, user.id)
    db.commit()
    _set_session_cookie(response, session.token)
    return {"email": user.email, "is_admin": user.is_admin}


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
    return {"email": user.email, "is_admin": user.is_admin}
