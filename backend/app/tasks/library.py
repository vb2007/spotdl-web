import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.db import SessionLocal
from app.models import DownloadedTrack, Job, LibrarySortRun, LibrarySortState, Track, TrackState
from app.services import app_settings, archive, events, library
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Only these track states carry a real, currently-valid output_path -- see download.py's
# state machine. Anything else (e.g. a stale WAITING track that shares this
# spotify_track_id via a since-superseded dedup path) must never be repointed.
_MOVED_TRACK_STATES = (TrackState.COMPLETED, TrackState.SKIPPED_DUPLICATE)


def _get_run(db) -> LibrarySortRun:
    run = db.get(LibrarySortRun, 1)
    if run is None:
        run = LibrarySortRun(id=1, state=LibrarySortState.IDLE, errors=[])
        db.add(run)
        db.flush()
    return run


def _record_error(run: LibrarySortRun, file_path: str, message: str) -> None:
    # Reassigned wholesale, never appended in place -- see LibrarySortRun's own
    # docstring on why (JSONB change tracking).
    run.errors = [*run.errors, {"file": file_path, "error": message}]


def _sync_tracks_and_archive_jobs(db, moved_spotify_ids: set[str]) -> None:
    """Repoints every affected Track.output_path to the ledger's new location (the
    ledger row itself is already repointed by the caller) and archives the settled jobs
    those tracks belong to -- including another user's job, since the moved file is
    shared across the whole dedup ledger regardless of who originally downloaded it.
    Reuses archive.archive_jobs, which already re-derives eligibility from real track
    states per user -- a job with another still-active/waiting track is correctly left
    alone rather than archived out from under it.

    Called only after every ledger repoint in this sweep has already been committed
    (see sort_library) -- a failure in here (caught by the caller) leaves that real,
    correct ledger state untouched; only this secondary output_path/archival bookkeeping
    is left for a future sweep to redo, since it re-derives moved_spotify_ids fresh from
    `in_library` each run rather than depending on this function ever completing."""
    ledger_rows = (
        db.query(DownloadedTrack)
        .filter(DownloadedTrack.spotify_track_id.in_(moved_spotify_ids))
        .all()
    )
    new_path_by_id = {row.spotify_track_id: row.file_path for row in ledger_rows}

    tracks = (
        db.query(Track)
        .filter(
            Track.spotify_track_id.in_(moved_spotify_ids),
            Track.state.in_(_MOVED_TRACK_STATES),
        )
        .all()
    )
    job_ids: set[uuid.UUID] = set()
    for track in tracks:
        track.output_path = new_path_by_id[track.spotify_track_id]
        job_ids.add(track.job_id)
    db.commit()

    if not job_ids:
        return

    jobs_by_user: dict[uuid.UUID, list[uuid.UUID]] = {}
    for job_id, user_id in db.query(Job.id, Job.user_id).filter(Job.id.in_(job_ids)).all():
        jobs_by_user.setdefault(user_id, []).append(job_id)

    for user_id, ids in jobs_by_user.items():
        archived = archive.archive_jobs(db, user_id, job_ids=ids)
        for job in archived:
            events.publish_job_event(user_id, job.id, job.state.value, archived=True)


def _publish_progress(run: LibrarySortRun, admin_user_id: str, **kwargs) -> None:
    events.publish_library_progress(
        admin_user_id,
        processed=run.processed,
        total=run.total,
        moved=run.moved,
        skipped_present=run.skipped_present,
        quarantined=run.quarantined,
        **kwargs,
    )


def _run_sweep(db, run: LibrarySortRun, admin_user_id: str) -> None:
    settings_row = app_settings.get_library_settings(db)
    target_dir = Path(settings_row.library_target_dir)
    quarantine_dir = Path(settings_row.library_quarantine_dir)
    quarantine_enabled = settings_row.library_quarantine_enabled
    folder_template = settings_row.library_folder_template

    ledger_rows = db.query(DownloadedTrack).filter(DownloadedTrack.in_library.is_(False)).all()
    run.total = len(ledger_rows)
    db.commit()
    _publish_progress(run, admin_user_id)

    moved_spotify_ids: set[str] = set()
    # Destinations already claimed by an earlier row *in this same sweep* -- distinct
    # from "already exists" (a file present before this sweep even started, e.g. a
    # manual library import or an earlier run). Two different spotify_track_ids that
    # compute the same destination in one sweep are a genuine collision (e.g. an old,
    # pre-v28-template filename shared by two otherwise-unrelated tracks) and must be
    # flagged as an error, never silently merged the way a real pre-existing duplicate
    # is -- merging would repoint the second track's ledger row onto the first track's
    # file and quarantine/delete the second track's own, actually-different audio.
    claimed_destinations: dict[Path, str] = {}

    for row in ledger_rows:
        source = Path(row.file_path)
        try:
            if not source.exists():
                _record_error(run, row.file_path, "source file missing on disk")
                continue

            tags = library.read_sort_tags(source)
            if tags is None:
                _record_error(run, row.file_path, "unsupported or unreadable format for tag read")
                continue

            dest = library.destination_path(target_dir, folder_template, tags, source)

            claimant = claimed_destinations.get(dest)
            if claimant is not None:
                _record_error(
                    run,
                    row.file_path,
                    f"destination collides with track {claimant} moved earlier in this sweep",
                )
                continue

            if dest.exists():
                # Pre-existing (from before this sweep) -- folder+filename match is
                # enough regardless of content (the plan's dedup rule). Repoint the
                # ledger to the existing target *before* touching the source and
                # commit it immediately: a crash between this commit and the
                # quarantine/delete below leaks a redundant source file (recoverable
                # manually), instead of losing track of the real, already-correct file
                # the way committing only at the end of the row would.
                row.file_path = str(dest)
                row.in_library = True
                db.commit()
                if quarantine_enabled:
                    library.quarantine(source, quarantine_dir)
                    run.quarantined += 1
                else:
                    source.unlink()
                    run.skipped_present += 1
            else:
                if not library.copy_verify(source, dest):
                    _record_error(
                        run, row.file_path, "copy verification failed; source left intact"
                    )
                    continue
                # Same crash-safety ordering as the conflict branch above: the ledger
                # is repointed and committed to the *verified* copy before the source
                # is ever deleted.
                row.file_path = str(dest)
                row.in_library = True
                db.commit()
                source.unlink()
                run.moved += 1

            claimed_destinations[dest] = row.spotify_track_id
            moved_spotify_ids.add(row.spotify_track_id)
        except Exception as exc:
            logger.exception("library: error processing %s", row.file_path)
            _record_error(run, row.file_path, str(exc))
        finally:
            run.processed += 1
            db.commit()
            _publish_progress(run, admin_user_id, current_file=source.name)

    if moved_spotify_ids:
        try:
            _sync_tracks_and_archive_jobs(db, moved_spotify_ids)
        except Exception as exc:
            # The ledger repoint for every moved track is already committed above --
            # this is secondary bookkeeping (Track.output_path, job archiving), and a
            # failure here must not be reported as though the move itself failed.
            logger.exception("library: track/job sync-and-archive failed after a successful move pass")
            db.rollback()
            _record_error(
                run,
                "<post-move sync>",
                f"repointing Track.output_path / archiving jobs failed: {exc}",
            )
            db.commit()

    run.state = LibrarySortState.IDLE
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    _publish_progress(run, admin_user_id, done=True)


@celery_app.task(name="app.tasks.library.sort_library")
def sort_library(admin_user_id: str) -> None:
    """Admin-triggered, on-demand sweep (v28) -- runs on worker-meta like every other
    housekeeping task. Iterates the dedup ledger (one row per unique physical file,
    never the tracks table -- multiple tracks/users can share the same downloaded_tracks
    row via dedup), skipping rows already marked in_library by a prior run.

    Everything past the per-row loop (which already catches its own exceptions) is
    wrapped in a second, outer guard: a crash while loading settings, querying the
    ledger, or elsewhere outside that loop must still reset `run.state` back to IDLE,
    or `POST /api/library/sort`'s 409-if-running gate wedges permanently with no
    recovery short of a manual DB edit."""
    db = SessionLocal()
    try:
        run = _get_run(db)
        try:
            _run_sweep(db, run, admin_user_id)
        except Exception as exc:
            logger.exception("sort_library: sweep crashed outside the per-row loop")
            db.rollback()
            run = _get_run(db)
            _record_error(run, "<sweep>", f"sweep crashed: {exc}")
            run.state = LibrarySortState.IDLE
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            _publish_progress(run, admin_user_id, done=True)
    finally:
        db.close()
