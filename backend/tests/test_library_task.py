import uuid

from app.models import (
    DownloadedTrack,
    Job,
    JobSourceType,
    JobState,
    Track,
    TrackState,
    User,
)
from app.services import app_settings, events
from app.services import library as library_service
from app.tasks import library as library_task

_FAKE_TAGS = {"artists": ["Daft Punk"], "album_name": "Discovery", "year": 2001}


class _NonClosingSession:
    """Same wrapper test_download_task.py uses -- db.close() inside the task must not
    detach objects the test still needs to assert against; the fixture handles real
    teardown instead."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


def _owner(db_session, email="owner@example.com") -> User:
    user = db_session.query(User).filter(User.email == email).one_or_none()
    if user is None:
        user = User(email=email, is_admin=False)
        db_session.add(user)
        db_session.flush()
    return user


def _configure(db_session, tmp_path, *, quarantine_enabled=True):
    app_settings.update_library_settings(
        db_session,
        library_target_dir=str(tmp_path / "library"),
        library_quarantine_enabled=quarantine_enabled,
        library_quarantine_dir=str(tmp_path / "quarantine"),
    )
    db_session.commit()


def _make_ledger_row(db_session, tmp_path, *, spotify_track_id="track1", in_library=False) -> DownloadedTrack:
    source = tmp_path / "downloads" / f"{spotify_track_id}.mp3"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"the real audio bytes")
    row = DownloadedTrack(
        spotify_track_id=spotify_track_id,
        file_path=str(source),
        format="mp3",
        bitrate="320k",
        in_library=in_library,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _capture_progress(monkeypatch):
    captured = []
    monkeypatch.setattr(
        events,
        "publish_library_progress",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )
    return captured


def _run(monkeypatch, db_session, admin_id=None):
    monkeypatch.setattr(library_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(library_service, "read_sort_tags", lambda path: dict(_FAKE_TAGS))
    library_task.sort_library(str(admin_id or uuid.uuid4()))


def test_sort_library_moves_a_file_and_repoints_ledger(db_session, tmp_path, monkeypatch):
    _configure(db_session, tmp_path)
    row = _make_ledger_row(db_session, tmp_path)
    _capture_progress(monkeypatch)
    source_path = row.file_path

    _run(monkeypatch, db_session)

    db_session.refresh(row)
    assert row.in_library is True
    assert row.file_path == str(tmp_path / "library" / "Daft Punk - Discovery - (2001)" / "track1.mp3")
    assert not (tmp_path / "downloads" / "track1.mp3").exists()
    assert (tmp_path / "library" / "Daft Punk - Discovery - (2001)" / "track1.mp3").read_bytes() == (
        b"the real audio bytes"
    )
    assert source_path != row.file_path

    run = library_task._get_run(db_session)
    assert (run.total, run.processed, run.moved, run.skipped_present, run.quarantined) == (1, 1, 1, 0, 0)
    assert run.errors == []


def test_sort_library_skips_rows_already_in_library(db_session, tmp_path, monkeypatch):
    _configure(db_session, tmp_path)
    row = _make_ledger_row(db_session, tmp_path, in_library=True)
    original_path = row.file_path
    _capture_progress(monkeypatch)

    _run(monkeypatch, db_session)

    db_session.refresh(row)
    assert row.file_path == original_path
    run = library_task._get_run(db_session)
    assert run.total == 0


def test_sort_library_conflict_with_quarantine_enabled(db_session, tmp_path, monkeypatch):
    _configure(db_session, tmp_path, quarantine_enabled=True)
    row = _make_ledger_row(db_session, tmp_path)
    dest = tmp_path / "library" / "Daft Punk - Discovery - (2001)" / "track1.mp3"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"pre-existing library copy, different bitrate")
    _capture_progress(monkeypatch)

    _run(monkeypatch, db_session)

    db_session.refresh(row)
    # The pre-existing target file is never touched.
    assert dest.read_bytes() == b"pre-existing library copy, different bitrate"
    # The source was quarantined, not deleted.
    assert not (tmp_path / "downloads" / "track1.mp3").exists()
    quarantined = list((tmp_path / "quarantine").iterdir())
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"the real audio bytes"
    # The ledger now points at the pre-existing target file, and is marked in-library.
    assert row.file_path == str(dest)
    assert row.in_library is True

    run = library_task._get_run(db_session)
    assert (run.moved, run.skipped_present, run.quarantined) == (0, 0, 1)


def test_sort_library_conflict_with_quarantine_disabled(db_session, tmp_path, monkeypatch):
    _configure(db_session, tmp_path, quarantine_enabled=False)
    row = _make_ledger_row(db_session, tmp_path)
    dest = tmp_path / "library" / "Daft Punk - Discovery - (2001)" / "track1.mp3"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"pre-existing library copy")
    _capture_progress(monkeypatch)

    _run(monkeypatch, db_session)

    db_session.refresh(row)
    assert dest.read_bytes() == b"pre-existing library copy"
    assert not (tmp_path / "downloads" / "track1.mp3").exists()
    assert not (tmp_path / "quarantine").exists() or not list((tmp_path / "quarantine").iterdir())
    assert row.file_path == str(dest)
    assert row.in_library is True

    run = library_task._get_run(db_session)
    assert (run.moved, run.skipped_present, run.quarantined) == (0, 1, 0)


def test_sort_library_missing_source_records_error_and_leaves_ledger_alone(db_session, tmp_path, monkeypatch):
    _configure(db_session, tmp_path)
    row = DownloadedTrack(
        spotify_track_id="ghost",
        file_path=str(tmp_path / "downloads" / "ghost.mp3"),
        format="mp3",
        bitrate="320k",
    )
    db_session.add(row)
    db_session.commit()
    _capture_progress(monkeypatch)

    _run(monkeypatch, db_session)

    db_session.refresh(row)
    assert row.in_library is False
    assert row.file_path == str(tmp_path / "downloads" / "ghost.mp3")

    run = library_task._get_run(db_session)
    assert len(run.errors) == 1
    assert "missing" in run.errors[0]["error"]


def test_sort_library_verification_failure_leaves_source_and_ledger_untouched(db_session, tmp_path, monkeypatch):
    _configure(db_session, tmp_path)
    row = _make_ledger_row(db_session, tmp_path)
    original_path = row.file_path
    _capture_progress(monkeypatch)
    monkeypatch.setattr(library_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(library_service, "read_sort_tags", lambda path: dict(_FAKE_TAGS))
    monkeypatch.setattr(library_service, "copy_verify", lambda source, dest: False)

    library_task.sort_library(str(uuid.uuid4()))

    db_session.refresh(row)
    assert row.file_path == original_path
    assert row.in_library is False
    assert (tmp_path / "downloads" / "track1.mp3").exists()

    run = library_task._get_run(db_session)
    assert len(run.errors) == 1
    assert "verification failed" in run.errors[0]["error"]


def test_sort_library_repoints_track_output_path_and_archives_settled_job(db_session, tmp_path, monkeypatch):
    _configure(db_session, tmp_path)
    row = _make_ledger_row(db_session, tmp_path)
    owner = _owner(db_session)
    job = Job(
        id=uuid.uuid4(),
        user_id=owner.id,
        source_url="https://open.spotify.com/track/track1",
        source_type=JobSourceType.TRACK,
        state=JobState.EXPANDED,
    )
    db_session.add(job)
    db_session.flush()
    track = Track(
        job_id=job.id,
        spotify_track_id="track1",
        song_json={"name": "One More Time"},
        state=TrackState.COMPLETED,
        output_path=row.file_path,
    )
    db_session.add(track)
    db_session.commit()

    captured_job_events = []
    monkeypatch.setattr(
        events, "publish_job_event", lambda *a, **kw: captured_job_events.append((a, kw))
    )
    _capture_progress(monkeypatch)

    _run(monkeypatch, db_session, admin_id=owner.id)

    db_session.refresh(track)
    db_session.refresh(job)
    assert track.output_path == str(tmp_path / "library" / "Daft Punk - Discovery - (2001)" / "track1.mp3")
    assert job.archived_at is not None
    assert any(kw.get("archived") is True for _, kw in captured_job_events)


def test_sort_library_does_not_archive_job_with_active_sibling_track(db_session, tmp_path, monkeypatch):
    _configure(db_session, tmp_path)
    row = _make_ledger_row(db_session, tmp_path)
    owner = _owner(db_session)
    job = Job(
        id=uuid.uuid4(),
        user_id=owner.id,
        source_url="https://open.spotify.com/album/abc",
        source_type=JobSourceType.ALBUM,
        state=JobState.EXPANDED,
    )
    db_session.add(job)
    db_session.flush()
    moved_track = Track(
        job_id=job.id,
        spotify_track_id="track1",
        song_json={"name": "One More Time"},
        state=TrackState.COMPLETED,
        output_path=row.file_path,
    )
    still_queued = Track(
        job_id=job.id,
        spotify_track_id="track2",
        song_json={"name": "Aerodynamic"},
        state=TrackState.QUEUED,
    )
    db_session.add_all([moved_track, still_queued])
    db_session.commit()
    original_path = row.file_path
    _capture_progress(monkeypatch)

    _run(monkeypatch, db_session, admin_id=owner.id)

    db_session.refresh(moved_track)
    db_session.refresh(job)
    assert moved_track.output_path != original_path  # still repointed
    assert moved_track.output_path == str(
        tmp_path / "library" / "Daft Punk - Discovery - (2001)" / "track1.mp3"
    )
    assert job.archived_at is None  # but the job itself stays active


def test_sort_library_publishes_a_final_done_progress_event(db_session, tmp_path, monkeypatch):
    _configure(db_session, tmp_path)
    _make_ledger_row(db_session, tmp_path)
    captured = _capture_progress(monkeypatch)

    _run(monkeypatch, db_session)

    assert captured  # at least the initial + per-file + final events
    _, last_kwargs = captured[-1]
    assert last_kwargs["done"] is True


def test_sort_library_flags_intra_sweep_destination_collision_as_an_error(db_session, tmp_path, monkeypatch):
    """Two different spotify_track_ids whose folder+filename resolve identically in the
    *same* sweep (e.g. two tracks that both predate the v28 filename template and share
    a generic name) must not be silently merged the way a real pre-existing library
    duplicate is -- that would repoint the second track's ledger row onto the first
    track's file and destroy the second track's own, genuinely different audio."""
    _configure(db_session, tmp_path)

    first_source = tmp_path / "downloads" / "first" / "song.mp3"
    first_source.parent.mkdir(parents=True)
    first_source.write_bytes(b"first track's real audio")
    second_source = tmp_path / "downloads" / "second" / "song.mp3"
    second_source.parent.mkdir(parents=True)
    second_source.write_bytes(b"second, genuinely different track's audio")

    db_session.add_all(
        [
            DownloadedTrack(
                spotify_track_id="collide-a", file_path=str(first_source), format="mp3", bitrate="320k"
            ),
            DownloadedTrack(
                spotify_track_id="collide-b", file_path=str(second_source), format="mp3", bitrate="320k"
            ),
        ]
    )
    db_session.commit()
    _capture_progress(monkeypatch)

    _run(monkeypatch, db_session)

    row_a = db_session.get(DownloadedTrack, "collide-a")
    row_b = db_session.get(DownloadedTrack, "collide-b")
    dest = tmp_path / "library" / "Daft Punk - Discovery - (2001)" / "song.mp3"
    # The first row to be processed wins the destination; the second is flagged, not
    # silently merged onto the first's file.
    assert {row_a.in_library, row_b.in_library} == {True, False}
    winner, loser = (row_a, row_b) if row_a.in_library else (row_b, row_a)
    assert winner.file_path == str(dest)
    assert loser.in_library is False

    run = library_task._get_run(db_session)
    assert run.moved == 1
    assert len(run.errors) == 1
    assert "collides with track" in run.errors[0]["error"]
    # The second track's real, distinct audio is never touched -- neither deleted nor
    # quarantined, since it was never treated as a duplicate of the first.
    assert second_source.exists()
    assert second_source.read_bytes() == b"second, genuinely different track's audio"


def test_sort_library_archives_only_the_sweeping_admins_jobs(db_session, tmp_path, monkeypatch):
    """v48 (F34, owner decision): a sweep repoints every user's moved tracks, but archives
    only the settled jobs of the admin who ran it. Another user's job keeps its
    repointed track and stays unarchived, and no archive event reaches that user."""
    _configure(db_session, tmp_path)
    admin = _owner(db_session, "admin@example.com")
    other = _owner(db_session, "other@example.com")

    rows = {}
    jobs = {}
    tracks = {}
    for label, owner in (("admin", admin), ("other", other)):
        row = _make_ledger_row(db_session, tmp_path, spotify_track_id=f"cross-user-{label}")
        job = Job(
            user_id=owner.id,
            source_url=f"https://open.spotify.com/track/{label}",
            source_type=JobSourceType.TRACK,
            state=JobState.EXPANDED,
        )
        db_session.add(job)
        db_session.flush()
        track = Track(
            job_id=job.id,
            spotify_track_id=f"cross-user-{label}",
            song_json={"name": label},
            state=TrackState.COMPLETED,
            output_path=row.file_path,
        )
        db_session.add(track)
        rows[label] = row
        jobs[label] = job
        tracks[label] = track
    db_session.commit()

    captured_job_events = []
    monkeypatch.setattr(
        events, "publish_job_event", lambda *a, **kw: captured_job_events.append((a, kw))
    )
    _capture_progress(monkeypatch)

    _run(monkeypatch, db_session, admin_id=admin.id)

    for label in ("admin", "other"):
        db_session.refresh(rows[label])
        db_session.refresh(tracks[label])
        db_session.refresh(jobs[label])
        assert rows[label].in_library is True
        assert tracks[label].output_path == rows[label].file_path
    assert jobs["admin"].archived_at is not None
    assert jobs["other"].archived_at is None

    event_owner_ids = {a[0] for a, _ in captured_job_events}
    assert event_owner_ids == {admin.id}


def test_sort_library_files_a_second_ledger_row_sharing_a_moved_file(db_session, tmp_path, monkeypatch):
    """v48 (F34): two ledger rows (two Spotify ids) can share one downloaded file. Once
    the first row moves it, the second follows it to the same destination instead of
    recording "source file missing" -- left behind, its ledger row would point at a
    deleted path, and reconcile_disk would prune it into a re-download."""
    _configure(db_session, tmp_path)
    first = _make_ledger_row(db_session, tmp_path, spotify_track_id="single-cut")
    second = DownloadedTrack(
        spotify_track_id="album-cut",
        file_path=first.file_path,
        format="mp3",
        bitrate="320k",
    )
    db_session.add(second)
    db_session.commit()
    _capture_progress(monkeypatch)

    _run(monkeypatch, db_session)

    dest = str(tmp_path / "library" / "Daft Punk - Discovery - (2001)" / "single-cut.mp3")
    for row in (first, second):
        db_session.refresh(row)
        assert row.in_library is True
        assert row.file_path == dest

    run = library_task._get_run(db_session)
    assert run.errors == []
    assert (run.total, run.processed, run.moved, run.skipped_present, run.quarantined) == (2, 2, 1, 1, 0)


def test_sort_library_lists_a_missing_shared_source_once(db_session, tmp_path, monkeypatch):
    """v48 (F34): two ledger rows sharing one missing file used to list the same path
    twice in the sweep's error log."""
    _configure(db_session, tmp_path)
    missing = str(tmp_path / "downloads" / "ghost.mp3")
    for spotify_track_id in ("ghost-single", "ghost-album"):
        db_session.add(
            DownloadedTrack(
                spotify_track_id=spotify_track_id,
                file_path=missing,
                format="mp3",
                bitrate="320k",
            )
        )
    db_session.commit()
    _capture_progress(monkeypatch)

    _run(monkeypatch, db_session)

    run = library_task._get_run(db_session)
    assert run.processed == 2
    assert run.errors == [{"file": missing, "error": "source file missing on disk"}]


def test_sort_library_resets_to_idle_when_sync_and_archive_raises(db_session, tmp_path, monkeypatch):
    """A crash in the secondary Track.output_path/job-archival bookkeeping must not
    wedge the run in RUNNING forever (which would permanently 409 every future sweep) --
    the already-committed ledger repoints from the per-row loop are the part that
    actually matters and must not be reported as failed."""
    _configure(db_session, tmp_path)
    _make_ledger_row(db_session, tmp_path)
    _capture_progress(monkeypatch)
    monkeypatch.setattr(library_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(library_service, "read_sort_tags", lambda path: dict(_FAKE_TAGS))

    def _boom(db, moved_spotify_ids, admin_user_id):
        raise RuntimeError("simulated crash syncing tracks/jobs")

    monkeypatch.setattr(library_task, "_sync_tracks_and_archive_jobs", _boom)

    library_task.sort_library(str(uuid.uuid4()))

    run = library_task._get_run(db_session)
    assert run.state.value == "idle"
    assert run.moved == 1  # the actual move already happened and is preserved
    assert any("sync" in e["error"] for e in run.errors)


def test_sort_library_resets_to_idle_when_settings_load_raises(db_session, tmp_path, monkeypatch):
    """A crash outside the per-row loop entirely (e.g. loading library settings) must
    still leave the run in a recoverable IDLE state, not permanently RUNNING."""
    _configure(db_session, tmp_path)
    _capture_progress(monkeypatch)
    monkeypatch.setattr(library_task, "SessionLocal", lambda: _NonClosingSession(db_session))

    def _boom(db):
        raise RuntimeError("simulated settings-load crash")

    monkeypatch.setattr(app_settings, "get_library_settings", _boom)

    library_task.sort_library(str(uuid.uuid4()))

    run = library_task._get_run(db_session)
    assert run.state.value == "idle"
    assert run.finished_at is not None
    assert any("crashed" in e["error"] for e in run.errors)
