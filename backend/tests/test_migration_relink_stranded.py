"""v48's one-shot data migration that relinks ledger rows stranded by pre-v48 library sweeps
(alembic revision cab1bff456eb), run against the test database's schema.

Since v51 that schema is real Postgres, so the migration's enum comparisons run against native
enums: a bound string won't compare with one (`operator does not exist`), which SQLite never
showed. These tests fail if either comparison loses its cast."""

import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.models import (
    DownloadedTrack,
    Job,
    JobSourceType,
    JobState,
    LibrarySortRun,
    LibrarySortState,
    Track,
    TrackAttempt,
    TrackAttemptOutcome,
    TrackState,
    User,
)

_MIGRATION = next((Path(__file__).parents[1] / "alembic" / "versions").glob("cab1bff456eb_*.py"))
_spec = importlib.util.spec_from_file_location("relink_stranded", _MIGRATION)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)

_LIB = "/mnt/raid1/media/music"
_SWEPT_AT = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)
_BEFORE = _SWEPT_AT - timedelta(days=1)


def _upgrade(db_session):
    with Operations.context(MigrationContext.configure(db_session.connection())):
        migration.upgrade()
    db_session.commit()
    db_session.expire_all()


def _ledger(db_session, spotify_track_id, file_path, *, in_library=False):
    db_session.add(
        DownloadedTrack(
            spotify_track_id=spotify_track_id,
            file_path=file_path,
            format="mp3",
            bitrate="320k",
            in_library=in_library,
            downloaded_at=_BEFORE,
        )
    )


def _last_sweep(db_session, *missing):
    db_session.add(
        LibrarySortRun(
            id=1,
            state=LibrarySortState.IDLE,
            started_at=_SWEPT_AT,
            errors=[{"file": path, "error": "source file missing on disk"} for path in missing],
        )
    )


def _track(db_session, spotify_track_id, output_path, state=TrackState.COMPLETED) -> Track:
    user = db_session.query(User).one_or_none() or User(email="owner@example.com", is_admin=True)
    db_session.add(user)
    db_session.flush()
    job = Job(
        id=uuid.uuid4(),
        user_id=user.id,
        source_url="https://open.spotify.com/album/abc",
        source_type=JobSourceType.ALBUM,
        state=JobState.EXPANDED,
    )
    db_session.add(job)
    db_session.flush()
    track = Track(
        job_id=job.id,
        spotify_track_id=spotify_track_id,
        song_json={"name": spotify_track_id},
        state=state,
        output_path=output_path,
    )
    db_session.add(track)
    return track


def test_the_columns_it_compares_are_native_enums(db_session):
    """What makes the casts load-bearing here: the columns are Postgres enums, not strings."""
    types = dict(
        db_session.execute(
            text(
                "SELECT table_name || '.' || column_name, data_type FROM information_schema.columns "
                "WHERE (table_name, column_name) IN "
                "(('tracks', 'state'), ('track_attempts', 'outcome'), ('library_sort_runs', 'state'))"
            )
        ).all()
    )
    assert types == {
        "tracks.state": "USER-DEFINED",
        "track_attempts.outcome": "USER-DEFINED",
        "library_sort_runs.state": "USER-DEFINED",
    }


def test_relinks_a_stranded_row_and_its_tracks_to_the_one_library_copy(db_session):
    filed = f"{_LIB}/Daft Punk - Discovery - (2001)/shared.mp3"
    _ledger(db_session, "single-cut", filed, in_library=True)
    _ledger(db_session, "album-cut", "/downloads/shared.mp3")
    _last_sweep(db_session, "/downloads/shared.mp3")
    done = _track(db_session, "album-cut", "/downloads/shared.mp3")
    waiting = _track(db_session, "album-cut", "/downloads/shared.mp3", state=TrackState.WAITING)
    db_session.commit()

    _upgrade(db_session)

    row = db_session.get(DownloadedTrack, "album-cut")
    assert (row.file_path, row.in_library) == (filed, True)
    assert db_session.get(Track, done.id).output_path == filed
    # Only a track whose output_path is real (completed / skipped duplicate) follows.
    assert db_session.get(Track, waiting.id).output_path == "/downloads/shared.mp3"


def test_leaves_every_row_outside_the_legacy_shape(db_session):
    _ledger(db_session, "a-filed", f"{_LIB}/A - X - (2001)/a.mp3", in_library=True)
    # Missing on disk now, but the last sweep never said so (e.g. deleted since, on purpose).
    _ledger(db_session, "a-unlisted", "/downloads/a.mp3")
    # Two library files share the name: which one it was can't be told.
    _ledger(db_session, "b-filed-1", f"{_LIB}/B - X - (2001)/b.mp3", in_library=True)
    _ledger(db_session, "b-filed-2", f"{_LIB}/B - Y - (2002)/b.mp3", in_library=True)
    _ledger(db_session, "b-listed", "/downloads/b.mp3")
    # Downloaded again since the sweep, so its file is back (the merge keeps the row's old
    # downloaded_at; the completed attempt is what shows it). A failed attempt doesn't count.
    _ledger(db_session, "c-filed", f"{_LIB}/C - X - (2001)/c.mp3", in_library=True)
    _ledger(db_session, "c-redownloaded", "/downloads/c.mp3")
    again = _track(db_session, "c-redownloaded", "/downloads/c.mp3")
    db_session.flush()
    for number, outcome in enumerate((TrackAttemptOutcome.FAILED, TrackAttemptOutcome.COMPLETED), 1):
        db_session.add(
            TrackAttempt(
                track_id=again.id,
                attempt_number=number,
                started_at=_SWEPT_AT + timedelta(hours=number),
                finished_at=_SWEPT_AT + timedelta(hours=number, minutes=1),
                outcome=outcome,
            )
        )
    # No library file with that name at all.
    _ledger(db_session, "d-listed", "/downloads/d.mp3")
    _last_sweep(db_session, "/downloads/b.mp3", "/downloads/c.mp3", "/downloads/d.mp3")
    db_session.commit()

    _upgrade(db_session)

    assert db_session.get(Track, again.id).output_path == "/downloads/c.mp3"
    for spotify_track_id, path in (
        ("a-unlisted", "/downloads/a.mp3"),
        ("b-listed", "/downloads/b.mp3"),
        ("c-redownloaded", "/downloads/c.mp3"),
        ("d-listed", "/downloads/d.mp3"),
    ):
        row = db_session.get(DownloadedTrack, spotify_track_id)
        assert (row.file_path, row.in_library) == (path, False), spotify_track_id


def test_relinks_when_the_only_attempt_since_the_sweep_failed(db_session):
    filed = f"{_LIB}/C - X - (2001)/c.mp3"
    _ledger(db_session, "c-filed", filed, in_library=True)
    _ledger(db_session, "c-stranded", "/downloads/c.mp3")
    retried = _track(db_session, "c-stranded", "/downloads/c.mp3", state=TrackState.WAITING)
    old = _track(db_session, "c-stranded", "/downloads/c.mp3")
    db_session.flush()
    db_session.add_all(
        [
            TrackAttempt(
                track_id=retried.id,
                attempt_number=1,
                started_at=_SWEPT_AT + timedelta(hours=1),
                finished_at=_SWEPT_AT + timedelta(hours=1, minutes=1),
                outcome=TrackAttemptOutcome.FAILED,
            ),
            # Completed, but before the sweep: the download the sweep later found gone.
            TrackAttempt(
                track_id=old.id,
                attempt_number=1,
                started_at=_BEFORE,
                finished_at=_BEFORE + timedelta(minutes=1),
                outcome=TrackAttemptOutcome.COMPLETED,
            ),
        ]
    )
    _last_sweep(db_session, "/downloads/c.mp3")
    db_session.commit()

    _upgrade(db_session)

    assert db_session.get(DownloadedTrack, "c-stranded").file_path == filed
    assert db_session.get(Track, old.id).output_path == filed


def test_one_ids_re_download_doesnt_block_another_rows_relink(db_session):
    """The re-download check is per row: a completed attempt for one Spotify id leaves every
    other stranded row (including a second row on the same source) to be relinked, and a
    skipped-duplicate track follows like a completed one."""
    _ledger(db_session, "e-filed", f"{_LIB}/E - X - (2001)/e.mp3", in_library=True)
    _ledger(db_session, "e-single", "/downloads/e.mp3")
    _ledger(db_session, "e-album", "/downloads/e.mp3")
    _ledger(db_session, "f-filed", f"{_LIB}/F - X - (2001)/f.mp3", in_library=True)
    _ledger(db_session, "f-redownloaded", "/downloads/f.mp3")
    duplicate = _track(db_session, "e-album", "/downloads/e.mp3", state=TrackState.SKIPPED_DUPLICATE)
    again = _track(db_session, "f-redownloaded", "/downloads/f.mp3")
    db_session.flush()
    db_session.add(
        TrackAttempt(
            track_id=again.id,
            attempt_number=1,
            started_at=_SWEPT_AT + timedelta(hours=1),
            finished_at=_SWEPT_AT + timedelta(hours=1, minutes=1),
            outcome=TrackAttemptOutcome.COMPLETED,
        )
    )
    _last_sweep(db_session, "/downloads/e.mp3", "/downloads/f.mp3")
    db_session.commit()

    _upgrade(db_session)

    for spotify_track_id in ("e-single", "e-album"):
        row = db_session.get(DownloadedTrack, spotify_track_id)
        assert (row.file_path, row.in_library) == (f"{_LIB}/E - X - (2001)/e.mp3", True)
    assert db_session.get(Track, duplicate.id).output_path == f"{_LIB}/E - X - (2001)/e.mp3"
    assert db_session.get(DownloadedTrack, "f-redownloaded").in_library is False


def test_matches_the_basename_exactly(db_session):
    _ledger(db_session, "near", f"{_LIB}/A - X - (2001)/xa_b.mp3", in_library=True)
    _ledger(db_session, "listed", "/downloads/a_b.mp3")
    _last_sweep(db_session, "/downloads/a_b.mp3")
    db_session.commit()

    _upgrade(db_session)

    assert db_session.get(DownloadedTrack, "listed").in_library is False


def test_is_a_no_op_without_a_sweep_or_its_errors(db_session):
    _ledger(db_session, "filed", f"{_LIB}/A - X - (2001)/a.mp3", in_library=True)
    _ledger(db_session, "stranded", "/downloads/a.mp3")
    db_session.commit()

    _upgrade(db_session)  # no library_sort_runs row at all
    db_session.add(LibrarySortRun(id=1, state=LibrarySortState.IDLE, errors=[]))
    db_session.commit()
    _upgrade(db_session)  # a run that never started, with no errors

    assert db_session.get(DownloadedTrack, "stranded").in_library is False
