from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import exists
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Track, TrackState, User, WorkerState
from app.routers.auth import require_admin, require_session
from app.services import retry

router = APIRouter(prefix="/api/worker", tags=["worker"])


def _status_dict(worker_state: WorkerState, busy: bool) -> dict:
    # v56 (A7): whether the breaker's pause is running, and for how long yet, decided on the
    # server's clock. A client comparing `breaker_tripped_until` with its own clock showed a
    # wrong countdown (or none) whenever that clock was off (#63). `paused` is separate.
    now = datetime.now(timezone.utc)
    breaker_active = retry.breaker_tripped(worker_state, now)
    return {
        "paused": worker_state.paused,
        "breaker_active": breaker_active,
        "breaker_remaining_seconds": (
            round((worker_state.breaker_tripped_until - now).total_seconds(), 3)
            if breaker_active
            else None
        ),
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
    """Clears the countdown early and starts a fresh failure streak, exactly like a trip
    does (v40.1), but keeps `breaker_trip_count`: a manual release is not an earned
    recovery, so if a new streak re-trips it, that trip is the *next* escalation step,
    not back at 30m."""
    # v44: records the `released` breaker event (a pause that had already run out is
    # recorded as having ended on its own, at its own end time).
    retry.record_breaker_release(db, datetime.now(timezone.utc), end_running=True, manual=True)
    worker_state = retry.get_worker_state(db)
    worker_state.consecutive_failures = 0
    db.commit()
    return _status_dict(worker_state, _is_busy(db))
