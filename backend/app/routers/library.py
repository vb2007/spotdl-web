from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import LibrarySortRun, LibrarySortState, User
from app.routers.auth import require_admin
from app.tasks.library import sort_library

router = APIRouter(prefix="/api/library", tags=["library"])


def _get_or_create_run(db: Session) -> LibrarySortRun:
    run = db.get(LibrarySortRun, 1)
    if run is None:
        run = LibrarySortRun(id=1, state=LibrarySortState.IDLE, errors=[])
        db.add(run)
        db.flush()
    return run


def _run_to_dict(run: LibrarySortRun) -> dict:
    return {
        "state": run.state.value,
        "started_at": run.started_at.isoformat() if run.started_at is not None else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at is not None else None,
        "total": run.total,
        "processed": run.processed,
        "moved": run.moved,
        "skipped_present": run.skipped_present,
        "quarantined": run.quarantined,
        "errors": run.errors,
    }


@router.get("/sort/status")
def sort_status(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Progress while running, the last finished sweep's report once it's IDLE again --
    the same row serves both, since a sweep's final state *is* its own report."""
    run = _get_or_create_run(db)
    db.commit()
    return _run_to_dict(run)


@router.post("/sort", status_code=202)
def start_sort(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    """Admin-only, on-demand -- one sweep at a time (409 if one is already running).
    Resets the singleton run row up front, in this request, so a client polling
    /sort/status immediately after this returns already sees RUNNING/zeroed counts
    rather than racing the task's own first commit."""
    run = _get_or_create_run(db)
    if run.state == LibrarySortState.RUNNING:
        raise HTTPException(status_code=409, detail="A library sort is already running")

    run.state = LibrarySortState.RUNNING
    run.started_at = datetime.now(timezone.utc)
    run.finished_at = None
    run.total = 0
    run.processed = 0
    run.moved = 0
    run.skipped_present = 0
    run.quarantined = 0
    run.errors = []
    db.commit()

    sort_library.delay(str(admin.id))
    return _run_to_dict(run)
