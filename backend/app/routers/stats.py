from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import begin_snapshot, get_db
from app.models import User
from app.routers.auth import require_session
from app.services import stats

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/me")
def my_stats(
    window: Literal["24h", "7d", "30d"] = "24h",
    # The viewer's clock, as /api/admin/stats takes it.
    utc_offset_minutes: int = Query(0, ge=-720, le=840),
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """v66: the session user's own downloads, open to every user, aggregated in SQL in this
    one request. Owner-scoped by construction: the user is the session's, and no parameter
    names another (an admin included; the global numbers stay on /api/admin/stats)."""
    # Several statements, one consistent snapshot (begin_snapshot's docstring).
    begin_snapshot(db)
    result = stats.my_stats(db, user.id, window, utc_offset_minutes=utc_offset_minutes)
    db.commit()
    return result
