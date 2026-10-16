from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import begin_snapshot, get_db
from app.models import User
from app.routers.auth import require_session
from app.services import stats

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin_hidden(user: User = Depends(require_session)) -> User:
    """Admin-only, answering a non-admin exactly like a route that doesn't exist (v44's
    plan: 404, not `require_admin`'s 403), so the page's existence isn't confirmed to
    anyone who can't use it. Unauthenticated is still 401, from require_session."""
    if not user.is_admin:
        raise HTTPException(status_code=404, detail="Not Found")
    return user


@router.get("/stats")
def admin_stats(
    window: Literal["24h", "7d", "30d"] = "24h",
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_hidden),
) -> dict:
    """v44: global download observability (every user's attempts together, hence
    admin-only), aggregated in SQL in this one request. Counts only: no identity, no
    title, no proxy URL (services/stats.py)."""
    # Several statements, one consistent snapshot (begin_snapshot's docstring).
    begin_snapshot(db)
    result = stats.admin_stats(db, window)
    db.commit()
    return result
