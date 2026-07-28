from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import UserSession
from app.services import upstream_auth
from app.services.sessions import SESSION_IDLE_TIMEOUT, create_session, delete_session, get_valid_session

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "SPOTDL_SESSION"

_INVALID_CREDENTIALS = HTTPException(status_code=401, detail="Invalid credentials")


class LoginRequest(BaseModel):
    email: str
    password: str


def require_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    token = request.cookies.get(COOKIE_NAME)
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = get_valid_session(db, token)
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    db.commit()
    return session


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

    session = create_session(db, payload.email)
    db.commit()
    _set_session_cookie(response, session.token)
    return {"email": payload.email}


@router.post("/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    session: UserSession = Depends(require_session),
) -> dict:
    delete_session(db, session.token)
    db.commit()
    response.delete_cookie(COOKIE_NAME)
    return {"status": "ok"}


@router.get("/me")
def me(session: UserSession = Depends(require_session)) -> dict:
    return {"email": session.email}
