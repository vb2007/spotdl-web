import hashlib
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal, engine
from app.models import DownloadedTrack, LibrarySortRun, LibrarySortState, Track, TrackState
from app.services import alerts, app_settings, archive, dedup, events, library
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Only these track states carry a real, currently-valid output_path -- see download.py's
# state machine. Anything else (e.g. a stale WAITING track that shares this
# spotify_track_id via a since-superseded dedup path) must never be repointed.
_MOVED_TRACK_STATES = (TrackState.COMPLETED, TrackState.SKIPPED_DUPLICATE)


# One sweep at a time, whatever the deliveries (v57, review round 7): a session-level advisory
# lock, held for the whole run on a connection of its own in autocommit (never idle in a
# transaction), released by the unlock or with the connection if the worker dies.
_SWEEP_LOCK_KEY = int.from_bytes(hashlib.sha256(b"spotdl-web:library-sweep").digest()[:8], "big", signed=True)


@contextmanager
def _sweep_lock() -> Iterator[bool]:
    """Yields whether this delivery holds the sweep lock."""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        held = conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _SWEEP_LOCK_KEY}).scalar()
        try:
            yield bool(held)
        finally:
            if held:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _SWEEP_LOCK_KEY})


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


def _repoint(db, rows: list[DownloadedTrack], source: Path, dest: Path) -> list[DownloadedTrack]:
    """Every ledger row sharing the moved file follows it (v48, F34): a row left on the
    old path would read as deleted to reconcile_disk and be pruned into a re-download.
    The rows are re-read here, not only taken from the sweep's starting snapshot: worker-dl
    can record another row on the same file while the sweep runs (spotdl's skip-existing
    hands back the file already on disk). Returns every row it moved."""
    current = (
        db.query(DownloadedTrack)
        .filter(DownloadedTrack.file_path == str(source), DownloadedTrack.in_library.is_(False))
        .all()
    )
    moved = list({id(row): row for row in [*rows, *current]}.values())
    for row in moved:
        row.file_path = str(dest)
        row.in_library = True
    return moved


def _mark_in_place(db, rows: list[DownloadedTrack]) -> None:
    """v57 (L2): rows whose file is already inside the library are filed where they are."""
    for row in rows:
        row.in_library = True
    db.commit()


def _sync_tracks_and_archive_jobs(db, moved_spotify_ids: set[str], admin_user_id: str) -> None:
    """Repoints every affected Track.output_path to the ledger's new location (the
    ledger row itself is already repointed by the caller) -- every user's, since the
    moved file is shared across the whole dedup ledger regardless of who originally
    downloaded it -- and archives the settled jobs among them that belong to the admin
    who ran the sweep. v48 (F34, owner decision): another user's job is never archived by
    a sweep; it keeps its repointed tracks and is left to that user and their own
    retention setting. Reuses archive.archive_jobs, which re-derives eligibility from
    real track states -- a job with another still-active/waiting track is correctly
    left alone rather than archived out from under it.

    Called only after every ledger repoint in this sweep has already been committed
    (see sort_library) -- a failure in here (caught by the caller) leaves that real,
    correct ledger state untouched. A later sweep does *not* redo this bookkeeping (it
    only reads rows still `in_library=False`); a track left on its old output_path still
    downloads, because the file endpoint resolves through the ledger first."""
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

    admin_id = uuid.UUID(admin_user_id)
    # archive_jobs is itself scoped to admin_id, so another user's id here is dropped.
    archived = archive.archive_jobs(db, admin_id, job_ids=list(job_ids))
    for job in archived:
        events.publish_job_event(admin_id, job.id, job.state.value, archived=True)


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


_RELATION_TEXT = {"equal": "the same directory as", "inside": "inside", "contains": "a parent of"}


def describe_conflict(conflict: dict) -> str:
    """One library.path_conflicts entry in words, for a report row or an API error detail."""
    return f"{conflict['field']} is {_RELATION_TEXT[conflict['relation']]} {conflict['other']}"


def _cancel_requested(db, run: LibrarySortRun) -> bool:
    # Re-read from the row: POST /api/library/sort/cancel sets it from another session.
    db.refresh(run, ["cancel_requested"])
    return run.cancel_requested


def _finish(db, run: LibrarySortRun, admin_user_id: str) -> None:
    run.state = LibrarySortState.IDLE
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    _publish_progress(run, admin_user_id, done=True)
    _alert_sweep_finished(run)


def _run_sweep(db, run: LibrarySortRun, admin_user_id: str) -> None:
    settings_row = app_settings.get_library_settings(db)
    target_dir = Path(settings_row.library_target_dir)
    quarantine_dir = Path(settings_row.library_quarantine_dir)
    quarantine_enabled = settings_row.library_quarantine_enabled
    folder_template = settings_row.library_folder_template
    # The mount point too (review round 6): a root seeded as a folder inside it would otherwise
    # leave the rest of the mount open to a move, and a move deletes its source.
    library_roots = [
        root.resolve() for root in [*dedup.known_library_roots(settings_row), library.library_mount()]
    ]

    # v57 (L2): the settings were checked when saved and when the sweep was started, but a
    # value saved before v57 (or changed since the start) is checked here too. A library that
    # overlaps the downloads dir would have the sweep moving files onto themselves.
    conflicts = library.path_conflicts(
        Path(get_settings().download_output_dir), target_dir, quarantine_dir
    )
    refusals = [f"refused to start: {describe_conflict(conflict)}" for conflict in conflicts]
    # Owner decision (2026-10-26): only the library volume's mount point, or a folder inside it.
    # After the overlap checks, in the same order as the API's.
    if library.outside_library_mount(target_dir):
        refusals.append(
            f"refused to start: library_target_dir is outside the library mount {library.library_mount()}"
        )
    if refusals:
        for message in refusals:
            _record_error(run, "<sweep>", message)
        _finish(db, run, admin_user_id)
        return

    # v57 (L4): the target must be known to be mounted: its own sentinel, or one of an
    # enclosing known root (the mount point, for a folder inside it, which is created as needed).
    # Otherwise it gets one here under reconcile_disk's rule, or the sweep is refused: filling an
    # unattached mountpoint whose ledger files are all missing would put new files on the wrong
    # filesystem, and the next reconcile would take them as proof the volume is there. (A target
    # no ledger row points into at all still gets a sentinel: the documented gap.)
    # The mount point's sentinel counts too, known root or not (read only here: reconcile_disk,
    # which creates sentinels, sticks to the ledger's own roots).
    if not dedup.covered(target_dir, [*dedup.known_library_roots(settings_row), library.library_mount()]):
        # Every ledger file under the target or a root around it counts (review round 6, the
        # same rule as reconcile_disk's): a new, empty folder on an unattached mountpoint must
        # not look like a fresh volume while the mount's own rows say otherwise.
        enclosing = [
            root
            for root in [*dedup.known_library_roots(settings_row), library.library_mount()]
            if target_dir.is_relative_to(root)
        ]
        under_target = [
            Path(path)
            for (path,) in db.query(DownloadedTrack.file_path).all()
            if any(Path(path).is_relative_to(root) for root in enclosing)
        ]
        db.commit()
        if not dedup.ensure_sentinel(target_dir, under_target, caller="library sweep"):
            _record_error(
                run,
                "<sweep>",
                f"refused to start: {target_dir} has no {dedup.SENTINEL_NAME}, so it isn't known to "
                "be mounted (create the folder if it's new; worker-expand's log says more)",
            )
            _finish(db, run, admin_user_id)
            return

    # v48 (review round 4): a fixed order, so which of two colliding files is filed and which
    # is flagged doesn't depend on how Postgres happens to return the rows -- the earlier
    # download wins.
    ledger_rows = (
        db.query(DownloadedTrack)
        .filter(DownloadedTrack.in_library.is_(False))
        .order_by(DownloadedTrack.downloaded_at, DownloadedTrack.spotify_track_id)
        .all()
    )
    # v48 (F34): one entry per source *file*, not per ledger row. Two ledger rows (two Spotify
    # ids, e.g. a single and its album cut) can share one downloaded file. Handled row by row,
    # the first row moved the file and the second was stranded as "source file missing", its
    # ledger row left on a deleted path for reconcile_disk to prune into a re-download, and
    # the error log listed one file twice. Each file is now decided once, every row sharing it
    # is repointed in the same commit (before the source is ever deleted, so a crash can't
    # split them), and every count in the report is a count of files.
    groups: dict[Path, list[DownloadedTrack]] = {}
    for row in ledger_rows:
        groups.setdefault(Path(row.file_path), []).append(row)
    run.total = len(groups)
    db.commit()
    _publish_progress(run, admin_user_id)

    moved_spotify_ids: set[str] = set()
    # Destinations already claimed by an earlier file *in this same sweep* -- distinct
    # from "already exists" (a file present before this sweep even started, e.g. a
    # manual library import or an earlier run). Two different files that compute the same
    # destination in one sweep are a genuine collision (e.g. an old, pre-v28-template
    # filename shared by two otherwise-unrelated tracks) and must be flagged as an error,
    # never silently merged the way a real pre-existing duplicate is -- merging would
    # repoint the second file's ledger rows onto the first file and quarantine/delete the
    # second file's own, actually-different audio.
    claimed_destinations: dict[Path, str] = {}

    def _mark_filed(rows: list[DownloadedTrack], dest: Path) -> None:
        # Recorded as soon as the repoint is committed, before the source is touched: a
        # failure deleting or quarantining it (caught below as this file's error) must not
        # leave dest unclaimed -- a later file mapping there would read as "already exists"
        # and be silently merged -- nor skip the tracks' output_path repoint.
        claimed_destinations[dest] = rows[0].spotify_track_id
        moved_spotify_ids.update(row.spotify_track_id for row in rows)

    for source, rows in groups.items():
        # v57 (L1): between files only, never mid-file, so every file already moved keeps its
        # committed repoint and the tracks still follow it below.
        if _cancel_requested(db, run):
            run.cancelled = True
            db.commit()
            logger.info("library: sweep cancelled after %d of %d files", run.processed, run.total)
            break
        file_path = str(source)
        try:
            if not source.exists():
                _record_error(run, file_path, "source file missing on disk")
                continue

            tags = library.read_sort_tags(source)
            if tags is None:
                _record_error(run, file_path, "unsupported or unreadable format for tag read")
                continue

            dest = library.destination_path(target_dir, folder_template, tags, source)

            # v57 (L2): a source already at its own destination would be read as "already
            # there" and quarantined or deleted: the library's only copy. A source anywhere
            # else in a library root is skipped too: nothing on the library filesystem is ever
            # moved or deleted by a sweep.
            # The rows are marked filed (nothing on disk changes), so the next sweep doesn't
            # report the same file again.
            resolved_source = source.resolve()
            if dest.resolve() == resolved_source:
                _mark_in_place(db, rows)
                _record_error(
                    run, file_path, "destination is the source file itself; marked filed, nothing moved"
                )
                continue
            if any(resolved_source.is_relative_to(root) for root in library_roots):
                _mark_in_place(db, rows)
                _record_error(
                    run, file_path, "source is already inside the library; marked filed, nothing moved"
                )
                continue

            claimant = claimed_destinations.get(dest)
            if claimant is not None:
                _record_error(
                    run,
                    file_path,
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
                # v57 (L3): the re-read, the repoint and the source's removal hold the file's
                # lock, so worker-dl can't record a row on this file in between.
                with dedup.file_lock(source):
                    rows = _repoint(db, rows, source, dest)
                    db.commit()
                    _mark_filed(rows, dest)
                    if quarantine_enabled:
                        library.quarantine(source, quarantine_dir)
                        run.quarantined += 1
                    else:
                        source.unlink()
                        run.skipped_present += 1
            else:
                if not library.copy_verify(source, dest):
                    # v31: copy_verify itself renames the corrupt copy off dest's exact
                    # path (never deletes it) precisely so this failure can never be
                    # mistaken for "already exists" by a later sweep -- see its docstring.
                    _record_error(
                        run,
                        file_path,
                        f"copy verification failed; source left intact, corrupt "
                        f"partial copy renamed under {dest.parent}",
                    )
                    continue
                # Same crash-safety ordering as the conflict branch above: the ledger
                # is repointed and committed to the *verified* copy before the source
                # is ever deleted. Under the file's lock, as above (v57, L3).
                with dedup.file_lock(source):
                    rows = _repoint(db, rows, source, dest)
                    db.commit()
                    _mark_filed(rows, dest)
                    source.unlink()
                    run.moved += 1
        except Exception as exc:
            logger.exception("library: error processing %s", file_path)
            _record_error(run, file_path, str(exc))
        finally:
            run.processed += 1
            db.commit()
            _publish_progress(run, admin_user_id, current_file=source.name)

    if moved_spotify_ids:
        try:
            _sync_tracks_and_archive_jobs(db, moved_spotify_ids, admin_user_id)
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

    _finish(db, run, admin_user_id)


def _alert_sweep_finished(run: LibrarySortRun, crash: str | None = None) -> None:
    """v36: one Matrix alert per sweep, keyed on its finish time so no two runs share a
    cooldown. Enqueued only after the run's final state is committed. Fire and forget --
    alerts.enqueue never raises and is a no-op when alerts are off."""
    counts = (
        f"{run.processed}/{run.total} processed, {run.moved} moved, "
        f"{run.skipped_present} already present, {run.quarantined} quarantined, "
        f"{len(run.errors)} errors"
    )
    if crash is not None:
        text = f"Library sweep failed: {crash} ({counts})."
    elif run.cancelled:
        text = f"Library sweep cancelled after {run.processed} of {run.total} files: {counts}."
    elif run.errors:
        first = run.errors[0]
        text = (
            f"Library sweep finished with errors: {counts}. First: {first['file']}: "
            f"{first['error']}"
        )
    else:
        text = f"Library sweep finished: {counts}."
    fingerprint = run.finished_at.isoformat() if run.finished_at else uuid.uuid4().hex
    alerts.enqueue(alerts.CATEGORY_LIBRARY, fingerprint, text)


@celery_app.task(name="app.tasks.library.sort_library")
def sort_library(admin_user_id: str) -> None:
    """Admin-triggered, on-demand sweep (v28) -- runs on worker-expand's `expand` queue
    since v34.1 (it can run for minutes; on worker-meta it held a slot beat's dispatch
    needs). Iterates the dedup ledger (never the tracks table -- multiple tracks/users can
    share the same downloaded_tracks row via dedup), grouped by source file since v48 (two
    ledger rows can also share one file), skipping rows already marked in_library by a
    prior run.

    Everything past the per-file loop (which already catches its own exceptions) is
    wrapped in a second, outer guard: a crash while loading settings, querying the
    ledger, or elsewhere outside that loop must still reset `run.state` back to IDLE,
    or `POST /api/library/sort`'s 409-if-running gate wedges permanently with no
    recovery short of a manual DB edit."""
    with _sweep_lock() as held:
        if not held:
            # Another delivery is sweeping: a message redelivered after its worker died
            # (acks_late) or after the 6 h visibility timeout, beside the sweep it belongs to or a
            # newer one. Two at once raced each other's files (review round 7, live).
            logger.warning("sort_library: another sweep holds the lock; dropping this delivery")
            return
        _sort_library_locked(admin_user_id)


def _sort_library_locked(admin_user_id: str) -> None:
    db = SessionLocal()
    try:
        run = _get_run(db)
        # v57 (live review): POST /api/library/sort sets the row running before it sends this.
        # A delivery that finds it idle is stale: a message redelivered after its worker died
        # (acks_late), arriving after an admin reset the wedged row by hand. Running it would
        # be a sweep no page shows and no cancel reaches (409, "not running").
        if run.state != LibrarySortState.RUNNING:
            logger.warning(
                "sort_library: the run row is %s, not running; dropping a stale delivery", run.state.value
            )
            db.commit()
            return
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
            # Redacted on the way out by alerts.format_body, like every alert body.
            _alert_sweep_finished(run, crash=f"{type(exc).__name__}: {exc}")
    finally:
        db.close()
