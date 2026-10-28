from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import begin_snapshot, get_db
from app.errors import ApiError
from app.models import User
from app.routers.auth import require_session
from app.services import alerts, stats
from app.services.pagination import InvalidCursor

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin_hidden(user: User = Depends(require_session)) -> User:
    """Admin-only, answering a non-admin exactly like a route that doesn't exist (v44's
    plan: 404, not `require_admin`'s 403), so the page's existence isn't confirmed to
    anyone who can't use it. Unauthenticated is still 401, from require_session."""
    if not user.is_admin:
        # v46: deliberately no `code` -- it must read exactly like an unknown route's 404.
        raise HTTPException(status_code=404, detail="Not Found")
    return user


@router.get("/stats")
def admin_stats(
    window: Literal["24h", "7d", "30d"] = "24h",
    # The viewer's clock, minutes east of UTC (Budapest: 60 or 120), so a day bucket is
    # their own day. Real offsets run from -12:00 to +14:00.
    utc_offset_minutes: int = Query(0, ge=-720, le=840),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_hidden),
) -> dict:
    """v44: global download observability (every user's attempts together, hence
    admin-only), aggregated in SQL in this one request. Counts only: no identity, no
    title, no proxy URL (services/stats.py)."""
    # Several statements, one consistent snapshot (begin_snapshot's docstring).
    begin_snapshot(db)
    result = stats.admin_stats(db, window, utc_offset_minutes=utc_offset_minutes)
    db.commit()
    return result


@router.get("/alerts")
def alert_history(
    cursor: str | None = None,
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin_hidden),
) -> dict:
    """v59 (O6): the alert outbox, newest first, one cursor page per request (the stats
    page's history panel). Every alert is global, hence admin-only, and answers a non-admin
    404 like the stats above. Bodies are stored redacted, and only a preview is returned."""
    try:
        result = alerts.outbox_page(db, cursor, limit)
    except InvalidCursor as exc:
        raise ApiError(400, "invalid_list_params", str(exc), {"reason": str(exc)}) from exc
    db.commit()
    return result
