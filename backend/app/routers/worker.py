from fastapi import APIRouter, Depends
from sqlalchemy import exists
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Track, TrackState, User, WorkerState
from app.routers.auth import require_admin, require_session
from app.services import retry

router = APIRouter(prefix="/api/worker", tags=["worker"])


def _status_dict(worker_state: WorkerState, busy: bool) -> dict:
    return {
        "paused": worker_state.paused,
        "breaker_tripped_until": (
            worker_state.breaker_tripped_until.isoformat()
            if worker_state.breaker_tripped_until is not None
            else None
        ),
        "breaker_trip_count": worker_state.breaker_trip_count,
        "consecutive_failures": worker_state.consecutive_failures,
        "busy": busy,
    }


def _is_busy(db: Session) -> bool:
    """`worker-dl` runs `--concurrency=1` (CLAUDE.md invariant), so at most one track
    across *every* user is ever `downloading` at once -- this is a global signal, not
    scoped to the caller, and deliberately carries no id/title so it can't leak which
    user or track is running (v20's "worker busy elsewhere" indicator, see
    `Waterfall.svelte`)."""
    return db.query(exists().where(Track.state == TrackState.DOWNLOADING)).scalar()


@router.get("/status")
def worker_status(
    db: Session = Depends(get_db),
    # Deliberately not admin-gated (v17): read-only, no ids, no cross-user data, and
    # v20's UI needs every user able to see why a queue looks stalled.
    _: User = Depends(require_session),
) -> dict:
    worker_state = retry.get_worker_state(db)
    db.commit()
    return _status_dict(worker_state, _is_busy(db))


@router.post("/pause")
def pause_worker(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    worker_state = retry.get_worker_state(db)
    worker_state.paused = True
    db.commit()
    return _status_dict(worker_state, _is_busy(db))


@router.post("/resume")
def resume_worker(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    worker_state = retry.get_worker_state(db)
    worker_state.paused = False
    db.commit()
    return _status_dict(worker_state, _is_busy(db))


@router.post("/breaker/release")
def release_breaker(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Clears the countdown early without resetting `consecutive_failures` or
    `breaker_trip_count` — a manual release is not an earned recovery, so the next
    failure re-trips at the *next* escalation step, not back at 30m."""
    worker_state = retry.get_worker_state(db)
    worker_state.breaker_tripped_until = None
    db.commit()
    return _status_dict(worker_state, _is_busy(db))
