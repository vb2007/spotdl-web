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
    alone rather than archived out from under it."""
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


@celery_app.task(name="app.tasks.library.sort_library")
def sort_library(admin_user_id: str) -> None:
    """Admin-triggered, on-demand sweep (v28) -- runs on worker-meta like every other
    housekeeping task. Iterates the dedup ledger (one row per unique physical file,
    never the tracks table -- multiple tracks/users can share the same downloaded_tracks
    row via dedup), skipping rows already marked in_library by a prior run."""
    db = SessionLocal()
    try:
        run = _get_run(db)
        settings_row = app_settings.get_library_settings(db)
        target_dir = Path(settings_row.library_target_dir)
        quarantine_dir = Path(settings_row.library_quarantine_dir)
        quarantine_enabled = settings_row.library_quarantine_enabled
        folder_template = settings_row.library_folder_template

        ledger_rows = (
            db.query(DownloadedTrack).filter(DownloadedTrack.in_library.is_(False)).all()
        )
        run.total = len(ledger_rows)
        db.commit()
        events.publish_library_progress(
            admin_user_id, processed=0, total=run.total, moved=0, skipped_present=0, quarantined=0
        )

        moved_spotify_ids: set[str] = set()

        for row in ledger_rows:
            source = Path(row.file_path)
            try:
                if not source.exists():
                    _record_error(run, row.file_path, "source file missing on disk")
                    continue

                tags = library.read_sort_tags(source)
                if tags is None:
                    _record_error(
                        run, row.file_path, "unsupported or unreadable format for tag read"
                    )
                    continue

                dest = library.destination_path(target_dir, folder_template, tags, source)

                if dest.exists():
                    # Folder+filename conflict -- treated as "already present" regardless
                    # of the two files' actual content (the plan's dedup rule). The
                    # existing target file becomes this track's new canonical location
                    # either way, so the ledger is repointed to it in both branches below.
                    if quarantine_enabled:
                        library.quarantine(source, quarantine_dir)
                        run.quarantined += 1
                    else:
                        source.unlink()
                        run.skipped_present += 1
                else:
                    if not library.copy_verify(source, dest):
                        _record_error(
                            run,
                            row.file_path,
                            "copy verification failed; source left intact",
                        )
                        continue
                    source.unlink()
                    run.moved += 1

                row.file_path = str(dest)
                row.in_library = True
                moved_spotify_ids.add(row.spotify_track_id)
            except Exception as exc:
                logger.exception("library: error processing %s", row.file_path)
                _record_error(run, row.file_path, str(exc))
            finally:
                run.processed += 1
                db.commit()
                events.publish_library_progress(
                    admin_user_id,
                    processed=run.processed,
                    total=run.total,
                    moved=run.moved,
                    skipped_present=run.skipped_present,
                    quarantined=run.quarantined,
                    current_file=source.name,
                )

        if moved_spotify_ids:
            _sync_tracks_and_archive_jobs(db, moved_spotify_ids)

        run.state = LibrarySortState.IDLE
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        events.publish_library_progress(
            admin_user_id,
            processed=run.processed,
            total=run.total,
            moved=run.moved,
            skipped_present=run.skipped_present,
            quarantined=run.quarantined,
            done=True,
        )
    finally:
        db.close()
