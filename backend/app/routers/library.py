from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import LibrarySortRun, LibrarySortState, User
from app.routers.auth import require_admin
from app.services import app_settings, library
from app.tasks.library import describe_conflict, sort_library

router = APIRouter(prefix="/api/library", tags=["library"])


def _get_or_create_run(db: Session, *, for_update: bool = False) -> LibrarySortRun:
    run = db.get(LibrarySortRun, 1, with_for_update=for_update)
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
        "cancel_requested": run.cancel_requested,
        "cancelled": run.cancelled,
    }


def check_library_paths(*, downloads_dir: str, library_dir: str, quarantine_dir: str) -> None:
    """v57 (L2): 422 `library_path_not_absolute` for a relative library or quarantine dir,
    422 `library_paths_overlap` for the first way the sweep's directories overlap, then
    `library_dir_outside_mount` for a library dir outside the library volume's mount point. The
    quarantine dir is checked whether or not quarantine is on (L2, literally)
    (library.path_conflicts), naming both settings and how they relate. Shared by the settings
    PATCH and the sweep's start."""
    # A relative path would resolve against each container's own working directory, so the
    # overlap check couldn't mean anything for it.
    for field, value in (("library_target_dir", library_dir), ("library_quarantine_dir", quarantine_dir)):
        if not Path(value).is_absolute():
            raise ApiError(422, "library_path_not_absolute", f"{field} must be an absolute path", {"field": field})
    conflicts = library.path_conflicts(Path(downloads_dir), Path(library_dir), Path(quarantine_dir))
    if conflicts:
        conflict = conflicts[0]
        raise ApiError(422, "library_paths_overlap", describe_conflict(conflict), conflict)
    if library.outside_library_mount(Path(library_dir)):
        mount = str(library.library_mount())
        raise ApiError(
            422,
            "library_dir_outside_mount",
            f"library_target_dir must be {mount} or a folder inside it",
            {"field": "library_target_dir", "mount": mount},
        )


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
    rather than racing the task's own first commit.

    `for_update=True` takes a row lock on this singleton row (a real `SELECT ... FOR
    UPDATE` against Postgres) so two concurrent POSTs can't both observe IDLE and both
    dispatch a sweep -- the second blocks until the first's transaction commits, then
    correctly sees RUNNING and 409s. Doesn't protect the one-time, first-call-ever race
    before any row exists at all (nothing to lock yet); that's an astronomically
    narrower window than the routine "double-clicked the button" case this guards."""
    run = _get_or_create_run(db, for_update=True)
    if run.state == LibrarySortState.RUNNING:
        raise ApiError(409, "library_sort_running", "A library sort is already running")
    settings_row = app_settings.get_library_settings(db)
    check_library_paths(
        downloads_dir=get_settings().download_output_dir,
        library_dir=settings_row.library_target_dir,
        quarantine_dir=settings_row.library_quarantine_dir,
    )

    run.state = LibrarySortState.RUNNING
    run.started_at = datetime.now(timezone.utc)
    run.finished_at = None
    run.total = 0
    run.processed = 0
    run.moved = 0
    run.skipped_present = 0
    run.quarantined = 0
    run.errors = []
    run.cancel_requested = False
    run.cancelled = False
    db.commit()

    sort_library.delay(str(admin.id))
    return _run_to_dict(run)


@router.post("/sort/cancel", status_code=202)
def cancel_sort(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """v57 (L1): asks the running sweep to stop. It stops between files, never mid-file, so
    the answer is 202 and the sweep's own done event (or the status row) says when it has:
    `cancelled` with "N of M" in `processed`/`total`. 409 when no sweep is running. The same
    row lock as the start, so a cancel can't land between a start's check and its commit."""
    run = _get_or_create_run(db, for_update=True)
    if run.state != LibrarySortState.RUNNING:
        raise ApiError(409, "library_sort_not_running", "No library sort is running")
    run.cancel_requested = True
    db.commit()
    return _run_to_dict(run)
