import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from concurrency import Gate, Thread
from spotdl.providers.audio.base import AudioProviderError

from app.config import get_settings

from app.models import (
    DownloadedTrack,
    Job,
    JobSourceType,
    NetworkPath,
    Proxy,
    ProxySource,
    Track,
    TrackAttempt,
    TrackAttemptOutcome,
    TrackErrorType,
    TrackState,
    User,
    WorkerState,
)
from app.services import dedup, downloads, events, proxies, retry, tagging
from app.tasks import download as download_task


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _owner(db_session) -> User:
    user = db_session.query(User).filter(User.email == "owner@example.com").one_or_none()
    if user is None:
        user = User(email="owner@example.com", is_admin=False)
        db_session.add(user)
        db_session.flush()
    return user


def _capture_events(monkeypatch):
    captured = []
    monkeypatch.setattr(
        events, "publish_track_event", lambda *args, **kwargs: captured.append((args, kwargs))
    )
    return captured


class _NonClosingSession:
    """Wraps db_session so download_track's db.close() doesn't detach objects the test
    still needs to assert against — the fixture handles real teardown instead."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


class _FakeProgressHandler:
    update_callback = None


class _FakeDownloader:
    """Stands in for a real spotdl Downloader — just enough surface for download_track
    to bind its progress_handler.update_callback hook (see v08's events.py wiring) and for
    proxies.force_proxy (v30) to walk .audio_providers (empty here -- none of these tests
    need a real YouTubeMusic instance to swap a client on)."""

    def __init__(self):
        self.progress_handler = _FakeProgressHandler()
        self.audio_providers = []


def _make_track(db_session):
    job = Job(
        source_url="https://open.spotify.com/track/abc",
        source_type=JobSourceType.TRACK,
        user_id=_owner(db_session).id,
    )
    db_session.add(job)
    db_session.commit()

    track = Track(job_id=job.id, spotify_track_id="abc123", song_json={"name": "Song A"})
    db_session.add(track)
    db_session.commit()
    return track


def _attempts(db_session, track):
    return (
        db_session.query(TrackAttempt)
        .filter(TrackAttempt.track_id == track.id)
        .order_by(TrackAttempt.started_at)
        .all()
    )


def _patch_common(monkeypatch, db_session):
    monkeypatch.setattr(download_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(download_task.Song, "from_dict", classmethod(lambda cls, data: data))
    # v26's tag verify/repair reads a real file off disk -- irrelevant to every test in
    # this module except the ones dedicated to it below, and these tests' fake
    # output_path values (e.g. "/downloads/song-a.mp3") never exist on disk. Defaulting
    # to "unsupported format" here is a real, reachable download_track code path (see
    # test_download_track_skips_tagging_for_unsupported_format), not a fake-only stub.
    monkeypatch.setattr(tagging, "is_supported_format", lambda path: False)


def test_download_track_skips_when_already_downloaded(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: Path("/downloads/existing.mp3"))

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("get_downloader should not be called for a duplicate")

    monkeypatch.setattr(downloads, "get_downloader", _fail_if_called)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.SKIPPED_DUPLICATE
    assert updated.output_path == "/downloads/existing.mp3"

    rows = _attempts(db_session, track)
    assert len(rows) == 1
    assert rows[0].outcome == TrackAttemptOutcome.SKIPPED_DUPLICATE
    assert rows[0].attempt_number == 1
    # v35: a dedup skip never touched the network -- neither an attempt nor a failure.
    assert (updated.attempts_made, updated.failure_count) == (0, 0)


class _FakeDownloadsSettings:
    def __init__(self, download_output_dir):
        self.download_output_dir = download_output_dir


def _moved_ledger_row(db_session, monkeypatch, tmp_path, *, library_dir, write_file):
    """v38: the real dedup gate (not a stub) over a ledger row the library sort moved."""
    from app.services import app_settings

    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    (downloads_dir / "other.mp3").write_text("audio")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeDownloadsSettings(str(downloads_dir)))
    app_settings.update_library_settings(db_session, library_target_dir=str(library_dir))
    file_path = library_dir / "Artist - Album - (2020)" / "01 - Artist - Song A.mp3"
    if write_file:
        file_path.parent.mkdir(parents=True)
        file_path.write_bytes(b"moved audio")
    db_session.add(
        DownloadedTrack(
            spotify_track_id="abc123",
            file_path=str(file_path),
            format="mp3",
            bitrate="320k",
            in_library=True,
        )
    )
    db_session.commit()

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("a moved track must never reach the downloader")

    monkeypatch.setattr(downloads, "get_downloader", _fail_if_called)
    return file_path


def test_download_track_resolves_a_moved_track_as_a_duplicate_of_its_library_file(
    db_session, monkeypatch, tmp_path
):
    """v38: worker-dl now sees the library, so a resubmitted moved track is a duplicate of
    the library copy -- no network attempt, and the ledger keeps pointing at the library."""
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    file_path = _moved_ledger_row(
        db_session, monkeypatch, tmp_path, library_dir=tmp_path / "library", write_file=True
    )

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.SKIPPED_DUPLICATE
    assert updated.output_path == str(file_path)
    rows = _attempts(db_session, track)
    assert [(r.outcome, r.network_path) for r in rows] == [
        (TrackAttemptOutcome.SKIPPED_DUPLICATE, None)
    ]
    assert db_session.get(DownloadedTrack, "abc123").file_path == str(file_path)


def test_download_track_holds_a_moved_track_when_the_library_root_is_not_mounted(
    db_session, monkeypatch, tmp_path, caplog
):
    """v38: an unmounted library root must not read as "file gone". The track is held as
    waiting (no network attempt, no ladder step, no breaker feed) and an error is logged."""
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    captured = _capture_events(monkeypatch)
    library_dir = tmp_path / "library-not-mounted"
    file_path = _moved_ledger_row(
        db_session, monkeypatch, tmp_path, library_dir=library_dir, write_file=False
    )
    before = datetime.now(timezone.utc)

    with caplog.at_level("ERROR", logger="app.tasks.download"):
        download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING
    scheduled_at = updated.scheduled_at.replace(tzinfo=timezone.utc)
    assert scheduled_at >= before + retry.next_delay(0) - timedelta(seconds=5)
    assert (updated.attempt_count, updated.attempts_made, updated.failure_count) == (0, 0, 0)
    rows = _attempts(db_session, track)
    assert [(r.outcome, r.network_path) for r in rows] == [(TrackAttemptOutcome.HELD, None)]
    assert str(library_dir) in rows[0].warning_message
    assert db_session.get(WorkerState, 1).consecutive_failures == 0
    assert db_session.get(DownloadedTrack, "abc123").file_path == str(file_path)
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1
    assert str(track.id) in errors[0].getMessage()
    assert str(library_dir) in errors[0].getMessage()
    assert captured[-1][0][3] == TrackState.WAITING.value


def test_download_track_re_download_of_a_lost_library_file_is_left_for_the_sweep(
    db_session, monkeypatch, tmp_path
):
    """v48: a ledger row whose library copy went missing is downloaded again into /downloads.
    The row must read not-in-library again, or the sweep (which reads only in_library=False)
    never files the new copy."""
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    db_session.add(
        DownloadedTrack(
            spotify_track_id="abc123",
            file_path="/library/gone/01 - Artist - Song A.mp3",
            format="mp3",
            bitrate="320k",
            in_library=True,
        )
    )
    db_session.commit()
    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())
    monkeypatch.setattr(downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, output_path))

    download_task.download_track(str(track.id))

    ledger_row = db_session.get(DownloadedTrack, "abc123")
    assert (ledger_row.file_path, ledger_row.in_library) == (str(output_path), False)


def test_download_track_success_marks_completed_and_upserts_ledger(db_session, monkeypatch, tmp_path):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    published = _capture_events(monkeypatch)

    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, output_path)
    )

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.COMPLETED
    assert updated.output_path == str(output_path)

    ledger_row = db_session.get(DownloadedTrack, "abc123")
    assert ledger_row is not None
    assert ledger_row.file_path == str(output_path)
    assert ledger_row.format == "opus"
    assert ledger_row.bitrate == "best"

    # "downloading" (progress=0, right before the attempt) then "completed" once durable.
    states = [args[3] for args, _ in published]
    assert states == ["downloading", "completed"]
    # v34.2: the attempt start says which attempt it is (the frontend's progress cache).
    assert published[0][1]["progress"] == 0
    assert published[0][1]["attempt_count"] == 0

    rows = _attempts(db_session, track)
    assert len(rows) == 1
    assert rows[0].outcome == TrackAttemptOutcome.COMPLETED
    assert rows[0].proxy_id is None
    assert rows[0].error_type is None
    assert rows[0].error_message is None
    assert rows[0].started_at <= rows[0].finished_at


def test_download_track_skips_tagging_for_unsupported_format(db_session, monkeypatch, tmp_path):
    """_patch_common's default (tagging.is_supported_format -> False) is itself a real
    download_track code path (v26's "skip cleanly for a format the tag library can't
    handle" -- e.g. wav), not just a test stub -- this pins that down explicitly."""
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    output_path = tmp_path / "song-a.wav"
    output_path.write_bytes(b"fake audio bytes")
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, output_path)
    )

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("verify_tags should not be called for an unsupported format")

    monkeypatch.setattr(tagging, "verify_tags", _fail_if_called)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.COMPLETED

    rows = _attempts(db_session, track)
    assert rows[-1].error_message is None


def test_download_track_success_with_no_missing_tags_skips_repair(db_session, monkeypatch, tmp_path):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, output_path)
    )
    monkeypatch.setattr(tagging, "is_supported_format", lambda path: True)
    monkeypatch.setattr(tagging, "verify_tags", lambda path: set())

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("repair_tags should not run when nothing is missing")

    monkeypatch.setattr(tagging, "repair_tags", _fail_if_called)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.COMPLETED

    rows = _attempts(db_session, track)
    assert rows[-1].error_message is None


def test_download_track_success_records_tag_repair_warning(db_session, monkeypatch, tmp_path):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, output_path)
    )
    monkeypatch.setattr(tagging, "is_supported_format", lambda path: True)
    monkeypatch.setattr(tagging, "verify_tags", lambda path: {"cover_art"})
    monkeypatch.setattr(
        tagging, "repair_tags", lambda path, song, missing: "cover art missing: fetch from Spotify failed"
    )

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    # A tag-repair warning is diagnostic, never a failure -- the track still completes.
    assert updated.state == TrackState.COMPLETED

    rows = _attempts(db_session, track)
    assert rows[-1].outcome == TrackAttemptOutcome.COMPLETED
    # v35 (d): a warning, not an error, on a completed attempt.
    assert rows[-1].warning_message == "tag warning: cover art missing: fetch from Spotify failed"
    assert rows[-1].error_message is None


def test_download_track_success_survives_unexpected_tagging_exception(db_session, monkeypatch, tmp_path):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, output_path)
    )
    monkeypatch.setattr(tagging, "is_supported_format", lambda path: True)

    def _boom(path):
        raise OSError("disk exploded")

    monkeypatch.setattr(tagging, "verify_tags", _boom)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    # The audio is already downloaded and correct -- a tagging bug must never turn a
    # successful download into a failed track.
    assert updated.state == TrackState.COMPLETED

    rows = _attempts(db_session, track)
    assert rows[-1].outcome == TrackAttemptOutcome.COMPLETED
    # v35 (d): a warning, not an error, on a completed attempt.
    assert rows[-1].warning_message == "tag warning: tag verification/repair failed unexpectedly"
    assert rows[-1].error_message is None


def test_download_track_other_error_reschedules_to_waiting(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    published = _capture_events(monkeypatch)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())

    def fake_download_one(song, downloader):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING
    assert updated.last_error == "provider exploded"
    assert updated.last_error_type == TrackErrorType.OTHER
    assert updated.attempt_count == 1
    assert updated.scheduled_at is not None
    assert db_session.get(DownloadedTrack, "abc123") is None

    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.consecutive_failures == 0

    _, final_kwargs = published[-1]
    assert final_kwargs["scheduled_at"] == updated.scheduled_at
    assert final_kwargs["error"] == "provider exploded"

    rows = _attempts(db_session, track)
    assert len(rows) == 1
    assert rows[0].outcome == TrackAttemptOutcome.FAILED
    assert rows[0].error_type == TrackErrorType.OTHER
    assert rows[0].error_message == "provider exploded"
    assert rows[0].proxy_id is None
    assert rows[0].attempt_number == 1
    assert (updated.attempts_made, updated.failure_count) == (1, 1)
    assert final_kwargs["attempts_made"] == 1
    assert final_kwargs["failure_count"] == 1


def test_download_track_audio_provider_error_feeds_breaker(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())

    def fake_download_one(song, downloader):
        raise AudioProviderError("rate limited")

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING
    assert updated.last_error_type == TrackErrorType.AUDIO_PROVIDER
    assert updated.attempt_count == 1

    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.consecutive_failures == 1


def test_download_track_no_output_path_feeds_breaker(db_session, monkeypatch):
    """v23: spotdl completing without raising but returning a `None` output path is the
    actual outage this version root-caused (docs/GOTCHAS.md's v23 entry) -- it must
    classify as its own type and feed the breaker exactly like a directly-raised
    AudioProviderError, not fall into the OTHER bucket that never trips it."""
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    published = _capture_events(monkeypatch)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())
    monkeypatch.setattr(downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, None))

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING
    assert updated.last_error == "spotdl returned no output file for this track"
    assert updated.last_error_type == TrackErrorType.NO_OUTPUT
    assert updated.attempt_count == 1
    assert db_session.get(DownloadedTrack, "abc123") is None

    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.consecutive_failures == 1

    # Metadata (v23) rides along on every event, including the failure one -- a track
    # that fails before ever being fetched via REST still renders with a real name.
    _, final_kwargs = published[-1]
    assert final_kwargs["title"] == "Song A"


def test_download_track_nonexistent_output_path_feeds_breaker(db_session, monkeypatch, tmp_path):
    """v31: found live by this version's own real-album verification -- search_and_download's
    returned path was trusted completely, with nothing checking it actually exists. A confirmed
    real cause: spotdl's own output-template renderer drops `{track-number} - ` entirely when a
    song has no track_number, so the reported path can point at a file that was never written
    under that name. Must classify and retry exactly like a `None` path, not silently succeed --
    and not depend on the broad tag-verification try/except (which used to swallow this) to even
    notice anything went wrong."""
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    published = _capture_events(monkeypatch)

    missing_path = tmp_path / "this-file-was-never-actually-written.mp3"

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())
    monkeypatch.setattr(downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, missing_path))

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING
    assert "no file exists there" in updated.last_error
    assert updated.last_error_type == TrackErrorType.NO_OUTPUT
    assert updated.attempt_count == 1
    assert db_session.get(DownloadedTrack, "abc123") is None

    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.consecutive_failures == 1


def test_download_track_age_gate_is_terminal_even_through_a_proxy(db_session, monkeypatch):
    """A search miss or age gate spotdl swallowed now reaches download_track as a
    LookupError (downloads.download_one) -- terminal on every rung, the proxy one included,
    and never fed to the breaker."""
    track = _make_track(db_session)
    track.attempt_count = 2  # v29: proxy is the third rung
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    db_session.add(Proxy(url="http://proxy-1", source=ProxySource.FILE, enabled=True))
    db_session.commit()
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())

    def fake_download_one(song, downloader):
        raise downloads.AgeRestrictedError("Age-restricted on YouTube (sign-in required): x")

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.LOOKUP_FAILED
    assert updated.last_error_type == TrackErrorType.LOOKUP
    assert updated.scheduled_at is None
    worker_state = db_session.get(WorkerState, 1)
    assert worker_state is None or worker_state.consecutive_failures == 0


def test_download_track_lookup_error_is_terminal(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    published = _capture_events(monkeypatch)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())

    def fake_download_one(song, downloader):
        raise LookupError("no result on any provider")

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.LOOKUP_FAILED
    assert updated.last_error_type == TrackErrorType.LOOKUP
    assert updated.scheduled_at is None

    args, final_kwargs = published[-1]
    assert args[3] == "lookup_failed"
    assert final_kwargs.get("scheduled_at") is None
    assert final_kwargs["error"] == "no result on any provider"


def test_download_track_success_resets_breaker_state(db_session, monkeypatch, tmp_path):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = 3
    worker_state.breaker_trip_count = 1
    db_session.commit()

    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, output_path)
    )

    download_task.download_track(str(track.id))

    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.consecutive_failures == 0
    assert worker_state.breaker_trip_count == 0


def test_download_track_skips_entirely_while_breaker_tripped(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    tripped_until = datetime.now(timezone.utc) + timedelta(hours=1)
    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_tripped_until = tripped_until
    db_session.commit()

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("dedup should not be checked while the breaker is tripped")

    monkeypatch.setattr(dedup, "is_already_downloaded", _fail_if_called)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING
    # SQLite round-trips this timestamptz column as naive (see v02/v03 gotchas); a no-op
    # against real Postgres/psycopg.
    assert updated.scheduled_at.replace(tzinfo=timezone.utc) == tripped_until

    rows = _attempts(db_session, track)
    assert len(rows) == 1
    assert rows[0].outcome == TrackAttemptOutcome.HELD
    assert rows[0].error_message is None
    assert "circuit breaker" in rows[0].warning_message
    assert rows[0].error_type is None
    assert rows[0].proxy_id is None


def test_breaker_hold_gets_its_own_attempt_number_and_keeps_attempt_one_direct(db_session, monkeypatch, tmp_path):
    """v35 designed away v24's documented collision (docs/GOTCHAS.md's v24 entry): the
    breaker-hold row used to share its attempt_number with the real attempt that followed
    it. It still never bumps attempt_count (that would break "attempt 1 is always direct"),
    but numbering is now a per-track row sequence, so the two rows are 1 and 2, the hold is
    `held` rather than `failed`, and only the real attempt counts as an attempt."""
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    tripped_until = datetime.now(timezone.utc) - timedelta(seconds=1)  # already cleared
    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.commit()

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    download_task.download_track(str(track.id))  # 1st invocation: breaker-requeue row

    # Clear the breaker, then run for real -- attempt_count is still 0, exactly like the
    # first invocation left it.
    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_tripped_until = tripped_until
    db_session.commit()
    captured = {}

    def fake_get_downloader(fmt, bitrate, output_dir, output_template, proxy=None, network_path=None):
        captured["network_path"] = network_path
        return _FakeDownloader()

    monkeypatch.setattr(downloads, "get_downloader", fake_get_downloader)
    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, output_path)
    )
    # What beat's dispatch_due_tracks does before it sends the message (v34.1: a message
    # finding its track still `waiting` is dropped as stray).
    track.state = TrackState.QUEUED
    db_session.commit()
    download_task.download_track(str(track.id))  # 2nd invocation: the real attempt

    rows = _attempts(db_session, track)
    assert len(rows) == 2
    assert rows[0].outcome == TrackAttemptOutcome.HELD
    assert rows[1].outcome == TrackAttemptOutcome.COMPLETED  # the real attempt
    assert [row.attempt_number for row in rows] == [1, 2]
    assert rows[0].started_at < rows[1].started_at
    assert captured["network_path"] == NetworkPath.DIRECT_IPV4
    updated = db_session.get(Track, track.id)
    assert (updated.attempts_made, updated.failure_count, updated.attempt_count) == (1, 0, 0)


def test_download_track_unknown_track_is_a_noop(db_session, monkeypatch):
    monkeypatch.setattr(download_task, "SessionLocal", lambda: _NonClosingSession(db_session))

    download_task.download_track(str(uuid.uuid4()))


def test_download_track_first_attempt_never_touches_proxy_pool(db_session, monkeypatch, tmp_path):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)

    def _fail_if_called(db):
        raise AssertionError("pick_proxy should not be called on the direct-first attempt")

    monkeypatch.setattr(proxies, "pick_proxy", _fail_if_called)

    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")
    captured = {}

    def fake_get_downloader(fmt, bitrate, output_dir, output_template, proxy=None, network_path=None):
        captured["proxy"] = proxy
        captured["network_path"] = network_path
        return _FakeDownloader()

    monkeypatch.setattr(downloads, "get_downloader", fake_get_downloader)
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, output_path)
    )

    download_task.download_track(str(track.id))

    assert captured["proxy"] is None
    assert captured["network_path"] == NetworkPath.DIRECT_IPV4
    updated = db_session.get(Track, track.id)
    assert updated.used_proxy_id is None

    rows = _attempts(db_session, track)
    assert rows[0].network_path == NetworkPath.DIRECT_IPV4


def test_download_track_second_attempt_forces_ipv6_never_touches_proxy_pool(db_session, monkeypatch, tmp_path):
    # v29 inserts the forced-other-family rung between direct-default and proxy -- attempt
    # 2 (attempt_count == 1) must not reach the proxy pool at all, unlike before this
    # version, when attempt_count >= 1 went straight to proxy.
    track = _make_track(db_session)
    track.attempt_count = 1
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)

    def _fail_if_called(db):
        raise AssertionError("pick_proxy should not be called on the forced-family attempt")

    monkeypatch.setattr(proxies, "pick_proxy", _fail_if_called)

    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")
    captured = {}

    def fake_get_downloader(fmt, bitrate, output_dir, output_template, proxy=None, network_path=None):
        captured["proxy"] = proxy
        captured["network_path"] = network_path
        return _FakeDownloader()

    monkeypatch.setattr(downloads, "get_downloader", fake_get_downloader)
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, output_path)
    )

    download_task.download_track(str(track.id))

    assert captured["proxy"] is None
    assert captured["network_path"] == NetworkPath.DIRECT_IPV6
    updated = db_session.get(Track, track.id)
    assert updated.used_proxy_id is None

    rows = _attempts(db_session, track)
    assert rows[0].network_path == NetworkPath.DIRECT_IPV6
    assert rows[0].attempt_number == 1


def test_download_track_retry_picks_proxy_and_records_success(db_session, monkeypatch, tmp_path):
    track = _make_track(db_session)
    track.attempt_count = 2  # v29: proxy is now the *third* rung (attempt_count >= 2)
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)

    proxy = Proxy(url="http://proxy-1", source=ProxySource.FILE, enabled=True)
    db_session.add(proxy)
    db_session.commit()

    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")
    captured = {}

    def fake_get_downloader(fmt, bitrate, output_dir, output_template, proxy=None, network_path=None):
        captured["proxy"] = proxy
        captured["network_path"] = network_path
        return _FakeDownloader()

    monkeypatch.setattr(downloads, "get_downloader", fake_get_downloader)
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, output_path)
    )

    download_task.download_track(str(track.id))

    assert captured["proxy"] == "http://proxy-1"
    assert captured["network_path"] == NetworkPath.PROXY
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.COMPLETED
    assert updated.used_proxy_id == proxy.id

    updated_proxy = db_session.get(Proxy, proxy.id)
    assert updated_proxy.last_success_at is not None
    assert updated_proxy.consecutive_failures == 0

    rows = _attempts(db_session, track)
    assert len(rows) == 1
    assert rows[0].outcome == TrackAttemptOutcome.COMPLETED
    assert rows[0].proxy_id == proxy.id
    # v35: a per-track row sequence, not tracks.attempt_count (which this test seeds to 2
    # with no history behind it).
    assert rows[0].attempt_number == 1
    assert rows[0].network_path == NetworkPath.PROXY


def test_download_track_retry_proxy_failure_sets_cooldown(db_session, monkeypatch):
    track = _make_track(db_session)
    track.attempt_count = 2  # v29: proxy is now the third rung
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)

    proxy = Proxy(url="http://proxy-1", source=ProxySource.FILE, enabled=True)
    db_session.add(proxy)
    db_session.commit()

    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())

    def fake_download_one(song, downloader):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING
    assert updated.used_proxy_id == proxy.id

    updated_proxy = db_session.get(Proxy, proxy.id)
    assert updated_proxy.consecutive_failures == 1
    assert updated_proxy.cooldown_until is not None

    rows = _attempts(db_session, track)
    assert len(rows) == 1
    assert rows[0].outcome == TrackAttemptOutcome.FAILED
    assert rows[0].proxy_id == proxy.id


def _proxy_rung_track(db_session, monkeypatch):
    track = _make_track(db_session)
    track.attempt_count = 2  # v29: proxy is the third rung
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    proxy = Proxy(url="http://proxy-1", source=ProxySource.FILE, enabled=True)
    db_session.add(proxy)
    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = retry.BREAKER_TRIP_THRESHOLD - 1
    db_session.commit()
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())
    return track, proxy


def _assert_proxy_transport_failure(db_session, track, proxy, before):
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING
    # Never reached YouTube: the track keeps its rung...
    assert updated.attempt_count == 2
    assert updated.last_error_type == TrackErrorType.OTHER
    assert _aware(updated.scheduled_at) - before >= retry.next_delay(0) - timedelta(seconds=1)
    # ...the breaker hears nothing (one more breaker-feeding failure would have tripped it)...
    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.consecutive_failures == retry.BREAKER_TRIP_THRESHOLD - 1
    assert worker_state.breaker_tripped_until is None
    # ...and the proxy is the one that cools down.
    updated_proxy = db_session.get(Proxy, proxy.id)
    assert updated_proxy.consecutive_failures == 1
    assert updated_proxy.cooldown_until is not None
    rows = _attempts(db_session, track)
    assert len(rows) == 1
    assert rows[0].outcome == TrackAttemptOutcome.FAILED
    assert rows[0].error_type == TrackErrorType.OTHER
    assert rows[0].network_path == NetworkPath.PROXY
    assert rows[0].proxy_id == proxy.id


def test_download_track_proxy_transport_failure_keeps_rung_and_spares_breaker(db_session, monkeypatch):
    """v40.1: the swallowed shape production hit -- download_one turns it into a
    ProxyTransportError."""
    track, proxy = _proxy_rung_track(db_session, monkeypatch)

    def fake_download_one(song, downloader):
        raise retry.ProxyTransportError("proxy unreachable, YouTube was never reached (ProxyError: ...)")

    monkeypatch.setattr(downloads, "download_one", fake_download_one)
    before = datetime.now(timezone.utc)

    download_task.download_track(str(track.id))

    _assert_proxy_transport_failure(db_session, track, proxy, before)


def test_download_track_directly_raised_proxy_error_is_a_transport_failure(db_session, monkeypatch):
    """The same failure raised outside spotdl's swallow, e.g. by force_proxy building its
    proxied YTMusic client on entry."""
    from requests.exceptions import ProxyError as RequestsProxyError

    track, proxy = _proxy_rung_track(db_session, monkeypatch)

    def fake_download_one(song, downloader):
        raise RequestsProxyError("Max retries exceeded (Caused by ProxyError('Unable to connect to proxy'))")

    monkeypatch.setattr(downloads, "download_one", fake_download_one)
    before = datetime.now(timezone.utc)

    download_task.download_track(str(track.id))

    _assert_proxy_transport_failure(db_session, track, proxy, before)


def _chained_no_output(cause):
    """download_one's real shape: a NoOutputFileError raised from what spotdl swallowed."""
    try:
        try:
            raise cause
        except Exception as inner:
            raise retry.NoOutputFileError(
                f"spotdl returned no output file for this track (ConnectionError: {cause})"
            ) from inner
    except retry.NoOutputFileError as exc:
        return exc


def test_download_track_dropped_connection_via_proxy_is_a_transport_failure(db_session, monkeypatch):
    """v40.1, found on the real stack: a proxy that accepts the TCP connection and drops it
    raised requests' plain ConnectionError ("Connection aborted."), which fed the breaker
    and tripped it."""
    from requests.exceptions import ConnectionError as RequestsConnectionError

    track, proxy = _proxy_rung_track(db_session, monkeypatch)
    exc = _chained_no_output(RequestsConnectionError("('Connection aborted.', ConnectionResetError(104))"))

    def fake_download_one(song, downloader):
        raise exc

    monkeypatch.setattr(downloads, "download_one", fake_download_one)
    before = datetime.now(timezone.utc)

    download_task.download_track(str(track.id))

    _assert_proxy_transport_failure(db_session, track, proxy, before)
    assert db_session.get(Track, track.id).last_error.startswith("proxy failed to carry the request: ")


def test_download_track_second_transport_failure_in_a_row_consumes_the_rung(db_session, monkeypatch):
    """Review finding: a read timeout or reset can also happen *after* YouTube was reached
    (mid-download), so a rung-free retry every 15m could go on forever while other tracks
    keep the proxies healthy. Only one in a row is free; the next one climbs the ladder --
    still `other`, so still no breaker."""
    from requests.exceptions import ConnectionError as RequestsConnectionError

    track, proxy = _proxy_rung_track(db_session, monkeypatch)
    second_proxy = Proxy(url="http://proxy-2", source=ProxySource.FILE, enabled=True)
    db_session.add(second_proxy)
    db_session.commit()

    def fake_download_one(song, downloader):
        raise _chained_no_output(RequestsConnectionError("Read timed out."))

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))
    assert db_session.get(Track, track.id).attempt_count == 2

    track = db_session.get(Track, track.id)
    track.state = TrackState.QUEUED
    db_session.commit()
    before = datetime.now(timezone.utc)
    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING
    assert updated.attempt_count == 3
    assert _aware(updated.scheduled_at) - before >= retry.next_delay(2) - timedelta(seconds=1)
    assert updated.last_error_type == TrackErrorType.OTHER
    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.consecutive_failures == retry.BREAKER_TRIP_THRESHOLD - 1
    rows = _attempts(db_session, track)
    assert [r.network_path for r in rows] == [NetworkPath.PROXY, NetworkPath.PROXY]
    assert all(r.error_message.startswith("proxy failed to carry the request: ") for r in rows)


def test_download_track_cancel_during_the_proxy_probe_is_not_overwritten(db_session, monkeypatch):
    """Review finding: pick_proxy's probes can take seconds; a cancel committed meanwhile
    must not be overwritten by the DOWNLOADING write."""
    track, _proxy = _proxy_rung_track(db_session, monkeypatch)

    def cancelling_pick_proxy(db):
        db_session.get(Track, track.id).state = TrackState.CANCELLED
        db_session.commit()
        return None

    monkeypatch.setattr(proxies, "pick_proxy", cancelling_pick_proxy)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("a track cancelled while picking a proxy must not download")

    monkeypatch.setattr(downloads, "get_downloader", _fail_if_called)

    download_task.download_track(str(track.id))

    assert db_session.get(Track, track.id).state == TrackState.CANCELLED
    rows = _attempts(db_session, track)
    assert [r.outcome for r in rows] == [TrackAttemptOutcome.CANCELLED]


def test_download_track_dropped_connection_on_a_direct_rung_still_feeds_the_breaker(db_session, monkeypatch):
    """The same error without a proxy is ambiguous, so it keeps its old classification."""
    from requests.exceptions import ConnectionError as RequestsConnectionError

    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())
    exc = _chained_no_output(RequestsConnectionError("('Connection aborted.', ConnectionResetError(104))"))

    def fake_download_one(song, downloader):
        raise exc

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.last_error_type == TrackErrorType.NO_OUTPUT
    assert updated.attempt_count == 1
    assert db_session.get(WorkerState, 1).consecutive_failures == 1


@pytest.mark.parametrize(
    "exc",
    [
        LookupError("No results found for song: Scooter - C.I.F.L. - Remastered"),
        downloads.AgeRestrictedError("Age-restricted on YouTube (sign-in required): ..."),
        downloads.UnavailableVideoError("Unavailable on YouTube: ..."),
        downloads.NotYetReleasedError("Not released yet on YouTube: ... Premieres in 102 days"),
    ],
)
def test_download_track_terminal_verdict_via_proxy_credits_the_proxy(db_session, monkeypatch, exc):
    """v40.1: a verdict about the video means the proxy carried the request to YouTube and
    back. Production cooled down the first proxy that ever worked for exactly that."""
    track, proxy = _proxy_rung_track(db_session, monkeypatch)

    def fake_download_one(song, downloader):
        raise exc

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.LOOKUP_FAILED
    updated_proxy = db_session.get(Proxy, proxy.id)
    assert updated_proxy.consecutive_failures == 0
    assert updated_proxy.cooldown_until is None
    assert updated_proxy.last_success_at is not None
    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.consecutive_failures == retry.BREAKER_TRIP_THRESHOLD - 1


def test_download_track_falls_back_to_direct_when_every_proxy_is_unreachable(db_session, monkeypatch):
    """v40.1: pick_proxy probes before use; a pool that refuses TCP connections cools down
    and the attempt goes out direct (the existing no-proxy-available fallback)."""
    track, proxy = _proxy_rung_track(db_session, monkeypatch)
    monkeypatch.setattr(proxies, "_probe_reachable", lambda url, timeout=2.0: False)
    captured = {}

    def fake_get_downloader(fmt, bitrate, output_dir, output_template, proxy=None, network_path=None):
        captured["proxy"] = proxy
        captured["network_path"] = network_path
        return _FakeDownloader()

    monkeypatch.setattr(downloads, "get_downloader", fake_get_downloader)

    def fake_download_one(song, downloader):
        raise downloads.AgeRestrictedError("Age-restricted on YouTube (sign-in required): ...")

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    assert captured == {"proxy": None, "network_path": NetworkPath.DIRECT_IPV4}
    assert db_session.get(Track, track.id).state == TrackState.LOOKUP_FAILED
    cooled = db_session.get(Proxy, proxy.id)
    assert cooled.consecutive_failures == 1
    assert cooled.cooldown_until is not None
    rows = _attempts(db_session, track)
    assert rows[0].network_path == NetworkPath.DIRECT_IPV4
    assert rows[0].proxy_id is None


def test_download_track_retry_failure_redacts_proxy_credentials_from_last_error(db_session, monkeypatch):
    track = _make_track(db_session)
    track.attempt_count = 2  # v29: proxy is now the third rung
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)

    proxy = Proxy(url="http://sneaky:hunter2@proxy-1:8080", source=ProxySource.FILE, enabled=True)
    db_session.add(proxy)
    db_session.commit()
    # v40.1: this URL has a port, so pick_proxy would really probe it (and fall back to
    # direct when `proxy-1` doesn't resolve) -- keep the attempt on the proxy it's about.
    monkeypatch.setattr(proxies, "_probe_reachable", lambda url, timeout=2.0: True)

    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())

    def fake_download_one(song, downloader):
        raise RuntimeError(f"Invalid proxy server: {proxy.url}")

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert "hunter2" not in updated.last_error
    assert "sneaky" not in updated.last_error
    assert "http://proxy-1:8080" in updated.last_error

    rows = _attempts(db_session, track)
    assert len(rows) == 1
    assert rows[0].error_message is not None
    assert "hunter2" not in rows[0].error_message
    assert "sneaky" not in rows[0].error_message
    assert "http://proxy-1:8080" in rows[0].error_message
    assert rows[0].network_path == NetworkPath.PROXY


def test_download_track_skips_entirely_when_already_cancelled(db_session, monkeypatch):
    track = _make_track(db_session)
    track.state = TrackState.CANCELLED
    db_session.commit()
    _patch_common(monkeypatch, db_session)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("nothing should run for an already-cancelled track")

    monkeypatch.setattr(dedup, "is_already_downloaded", _fail_if_called)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.CANCELLED

    rows = _attempts(db_session, track)
    assert len(rows) == 1
    assert rows[0].outcome == TrackAttemptOutcome.CANCELLED


def test_download_track_discards_success_when_cancelled_mid_download(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    published = _capture_events(monkeypatch)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())

    def fake_download_one(song, downloader):
        # A `DELETE /api/tracks/{id}` (separate request/session) landing while this
        # blocking, real download call was still running — search_and_download isn't
        # cleanly interruptible, so the cancel just commits the state change directly.
        db_session.query(Track).filter(Track.id == track.id).update(
            {"state": TrackState.CANCELLED, "scheduled_at": None}
        )
        db_session.commit()
        return downloads.DownloadResult(song, Path("/downloads/song-a.mp3"))

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.CANCELLED
    assert updated.output_path is None
    assert db_session.get(DownloadedTrack, "abc123") is None
    # "downloading", then a re-published "cancelled" -- never "completed". The
    # re-publish exists because the real (uninterruptible) download's progress
    # callback keeps firing "downloading" events after the DB row already flipped to
    # cancelled; without this, a live SSE client's last-known state for the track
    # would be a stray "downloading" event, not the true outcome (caught via real
    # end-to-end testing, not visible from a REST-only check).
    states = [args[3] for args, _ in published]
    assert states == ["downloading", "cancelled"]

    rows = _attempts(db_session, track)
    assert len(rows) == 1
    assert rows[0].outcome == TrackAttemptOutcome.CANCELLED


def test_download_track_discards_failure_when_cancelled_mid_download(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    published = _capture_events(monkeypatch)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader())

    def fake_download_one(song, downloader):
        db_session.query(Track).filter(Track.id == track.id).update(
            {"state": TrackState.CANCELLED, "scheduled_at": None}
        )
        db_session.commit()
        raise RuntimeError("provider exploded after cancel")

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.CANCELLED
    assert updated.last_error is None

    worker_state = db_session.get(WorkerState, 1)
    assert worker_state is None or worker_state.consecutive_failures == 0

    # "downloading", then a re-published "cancelled" -- same stray-progress-event race
    # as the success-path test above, just hitting the except branch instead.
    states = [args[3] for args, _ in published]
    assert states == ["downloading", "cancelled"]

    rows = _attempts(db_session, track)
    assert len(rows) == 1
    assert rows[0].outcome == TrackAttemptOutcome.CANCELLED
    assert rows[0].error_message is None


def test_spotdls_file_already_exists_skip_is_not_a_network_attempt(db_session, monkeypatch, tmp_path):
    """v55 (E8): spotdl found the output file already in place and returned it without
    downloading. Recorded like a dedup hit (`skipped_duplicate`, no network path), never as a
    `completed direct-ipv4` attempt: the counters don't move, no breaker or proxy verdict, and
    the ledger gains the row it was missing."""
    track = _make_track(db_session)
    track.attempt_count = 1
    track.attempts_made, track.failure_count = 1, 1
    track.last_error, track.last_error_type = "HTTP Error 429", TrackErrorType.AUDIO_PROVIDER
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    published = _capture_events(monkeypatch)
    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = 3
    db_session.commit()
    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"already here")
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda *args, **kwargs: _FakeDownloader())
    monkeypatch.setattr(
        downloads,
        "download_one",
        lambda song, downloader: downloads.DownloadResult(song, output_path, skipped_existing=True),
    )

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.SKIPPED_DUPLICATE
    assert updated.output_path == str(output_path)
    assert (updated.attempt_count, updated.attempts_made, updated.failure_count) == (1, 1, 1)
    assert (updated.last_error, updated.last_error_type) == (None, None)
    row = _attempts(db_session, track)[-1]
    assert (row.outcome, row.network_path, row.proxy_id) == (TrackAttemptOutcome.SKIPPED_DUPLICATE, None, None)
    assert db_session.get(DownloadedTrack, "abc123").file_path == str(output_path)
    assert db_session.get(WorkerState, 1).consecutive_failures == 3  # no success, no failure
    _, kwargs = published[-1]
    assert (kwargs["attempts_made"], kwargs["failure_count"]) == (1, 1)


@pytest.mark.parametrize("download_result", ["success", "failure"])
def test_a_mid_download_cancel_publishes_after_its_row_with_counters(db_session, monkeypatch, download_result):
    """v55 (E6): the `cancelled` event goes out once its attempt row is committed, and carries
    the counters that row moved (one attempt, no failure), so a live row isn't off by one
    until reload. It used to go out first, with no counters at all."""
    track = _make_track(db_session)
    track.attempt_count = 1  # one earlier failure: the event says which attempt this was
    track.attempts_made, track.failure_count = 1, 1
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    seen = []

    def publish(owner_id, track_id, job_id, state, **kwargs):
        rows = db_session.query(TrackAttempt).filter(TrackAttempt.track_id == track.id).count()
        seen.append((state, rows, kwargs))

    monkeypatch.setattr(events, "publish_track_event", publish)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda *args, **kwargs: _FakeDownloader())

    def fake_download_one(song, downloader):
        db_session.query(Track).filter(Track.id == track.id).update(
            {"state": TrackState.CANCELLED, "scheduled_at": None}
        )
        db_session.commit()
        if download_result == "failure":
            raise RuntimeError("provider exploded after cancel")
        return downloads.DownloadResult(song, Path("/downloads/song-a.mp3"))

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    state, rows_at_publish, kwargs = seen[-1]
    assert state == "cancelled"
    assert rows_at_publish == 1
    assert (kwargs["attempt_count"], kwargs["attempts_made"], kwargs["failure_count"]) == (1, 2, 1)


def test_download_track_retry_falls_back_to_direct_when_no_proxy_available(db_session, monkeypatch, tmp_path):
    track = _make_track(db_session)
    track.attempt_count = 2  # v29: proxy is now the third rung
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    # No Proxy rows at all -> pick_proxy returns None -> the attempt still has to happen
    # directly rather than stalling the track indefinitely on proxy availability.

    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")
    captured = {}

    def fake_get_downloader(fmt, bitrate, output_dir, output_template, proxy=None, network_path=None):
        captured["proxy"] = proxy
        captured["network_path"] = network_path
        return _FakeDownloader()

    monkeypatch.setattr(downloads, "get_downloader", fake_get_downloader)
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, output_path)
    )

    download_task.download_track(str(track.id))

    assert captured["proxy"] is None
    # The fallback must not be mislabeled as NetworkPath.PROXY -- no proxy was actually
    # used, so both get_downloader's forced family and the stored track_attempts row must
    # honestly reflect a direct (forced-ipv4) attempt instead.
    assert captured["network_path"] == NetworkPath.DIRECT_IPV4
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.COMPLETED
    assert updated.used_proxy_id is None

    rows = _attempts(db_session, track)
    assert rows[0].network_path == NetworkPath.DIRECT_IPV4


def test_pacing_delay_is_zero_when_unconfigured(monkeypatch):
    """The regression guard for the drift itself -- PACING_MAX_SEC=0 (the default) must
    mean the sleep path never runs, not time.sleep(0). Nothing ever asserted this before,
    which is exactly how the hook went unwired without anyone noticing."""

    def _fail_if_called(_seconds):
        raise AssertionError("time.sleep must not be called with pacing off")

    monkeypatch.setattr(download_task.time, "sleep", _fail_if_called)
    assert download_task.pacing_delay() == 0.0


def test_pacing_delay_samples_inside_the_configured_window(monkeypatch):
    settings = download_task.get_settings()
    monkeypatch.setattr(settings, "pacing_min_sec", 2, raising=False)
    monkeypatch.setattr(settings, "pacing_max_sec", 6, raising=False)

    samples = [download_task.pacing_delay() for _ in range(200)]
    assert all(2 <= s <= 6 for s in samples)
    # Randomized, not fixed -- a constant delay would make the whole worker fleet's
    # request timing trivially fingerprintable, which is the point of "randomized" in
    # the plan.
    assert len(set(samples)) > 1


def test_download_track_sleeps_before_the_attempt_when_pacing_configured(db_session, monkeypatch, tmp_path):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    settings = download_task.get_settings()
    monkeypatch.setattr(settings, "pacing_min_sec", 3, raising=False)
    monkeypatch.setattr(settings, "pacing_max_sec", 3, raising=False)

    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")

    calls = []
    monkeypatch.setattr(
        download_task.time, "sleep", lambda seconds: calls.append(("sleep", seconds))
    )
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(
        downloads,
        "get_downloader",
        lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: (
            calls.append(("download", None)) or _FakeDownloader()
        ),
    )
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, output_path)
    )

    download_task.download_track(str(track.id))

    # Ordering is the assertion that matters: a pacing delay applied *after* the download
    # would space nothing out on a --concurrency=1 worker's final track in a batch.
    assert calls == [("sleep", 3.0), ("download", None)]
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.COMPLETED


def test_download_track_does_not_pace_a_skipped_duplicate(db_session, monkeypatch):
    """The placement guard from the plan: a track that never touches the network must
    not burn wall-clock waiting to not touch it."""
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    settings = download_task.get_settings()
    monkeypatch.setattr(settings, "pacing_min_sec", 30, raising=False)
    monkeypatch.setattr(settings, "pacing_max_sec", 60, raising=False)

    def _fail_if_called(_seconds):
        raise AssertionError("a duplicate must not pay the pacing delay")

    monkeypatch.setattr(download_task.time, "sleep", _fail_if_called)
    monkeypatch.setattr(
        dedup, "is_already_downloaded", lambda track_id: Path("/downloads/existing.mp3")
    )

    download_task.download_track(str(track.id))

    assert db_session.get(Track, track.id).state == TrackState.SKIPPED_DUPLICATE


def test_download_track_cancelled_during_pacing_wait_skips_download(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    settings = download_task.get_settings()
    monkeypatch.setattr(settings, "pacing_min_sec", 30, raising=False)
    monkeypatch.setattr(settings, "pacing_max_sec", 60, raising=False)

    def _cancel_during_wait(_seconds):
        # Simulates a DELETE /api/tracks/{id} landing while download_track is asleep --
        # a separate request/session committing this change underneath the sleeping task.
        current = db_session.get(Track, track.id)
        current.state = TrackState.CANCELLED
        current.scheduled_at = None
        db_session.commit()

    monkeypatch.setattr(download_task.time, "sleep", _cancel_during_wait)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("a track cancelled during the pacing wait must not download")

    monkeypatch.setattr(downloads, "get_downloader", _fail_if_called)

    download_task.download_track(str(track.id))

    assert db_session.get(Track, track.id).state == TrackState.CANCELLED
    rows = _attempts(db_session, track)
    assert len(rows) == 1
    assert rows[0].outcome == TrackAttemptOutcome.CANCELLED


def test_a_stray_message_for_a_waiting_or_lookup_failed_track_is_dropped(db_session, monkeypatch):
    """v34.1: only `pending`/`queued` (or a crash-redelivered `downloading`) track is ever
    legitimately dispatched. A duplicate that lands after the first attempt already sent
    the track into the ladder must not run -- that would jump the ladder."""
    _patch_common(monkeypatch, db_session)
    calls = []
    monkeypatch.setattr(downloads, "download_one", lambda *a, **k: calls.append(a))
    published = []
    monkeypatch.setattr(events, "publish_track_event", lambda *a, **k: published.append(a))

    for state in (TrackState.WAITING, TrackState.LOOKUP_FAILED):
        track = _make_track(db_session)
        track.state = state
        track.attempt_count = 1
        db_session.commit()

        download_task.download_track(str(track.id))

        db_session.refresh(track)
        assert track.state == state
        assert track.attempt_count == 1
        assert _attempts(db_session, track) == []
    assert calls == []
    assert published == []


def test_a_retry_publishes_its_attempt_count_on_start_and_on_every_tick(db_session, monkeypatch, tmp_path):
    """v34.2: the frontend keys its cached progress on attempt_count, so a retry's events
    must say which attempt they are -- a first attempt (0) can't tell "wired" from
    "omitted, defaulted to 0", so this uses attempt 2."""
    track = _make_track(db_session)
    track.state = TrackState.QUEUED
    track.attempt_count = 2
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(proxies, "pick_proxy", lambda db: None)
    monkeypatch.setattr(
        downloads,
        "get_downloader",
        lambda fmt, bitrate, output_dir, output_template, proxy=None, network_path=None: _FakeDownloader(),
    )
    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")

    class _Tracker:
        progress = 50

    def download_one(song, downloader):
        downloader.progress_handler.update_callback(_Tracker(), "Downloading")
        return downloads.DownloadResult(song, output_path)

    monkeypatch.setattr(downloads, "download_one", download_one)
    published = []
    monkeypatch.setattr(events, "publish_track_event", lambda *a, **k: published.append((a, k)))

    download_task.download_track(str(track.id))

    ticks = [k for a, k in published if a[3] == "downloading"]
    assert [t["progress"] for t in ticks] == [0, 50]
    assert all(t["attempt_count"] == 2 for t in ticks)


# --- v35 (a): attempt counting/numbering, and the ladder input it must not move ---------


def _run_invocation(db_session, monkeypatch, track, *, outcome, captured=None, output_path=None):
    """One download_track invocation for `track`, shaped by `outcome`: "held" (breaker
    active), "failed" (a plain error, so the breaker isn't fed and the ladder is the only
    thing that moves) or "completed". Puts the track back to `queued` first, which is what
    beat's dispatch does before it sends the message."""
    track.state = TrackState.QUEUED
    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_tripped_until = (
        datetime.now(timezone.utc) + timedelta(hours=1) if outcome == "held" else None
    )
    db_session.commit()

    def fake_get_downloader(fmt, bitrate, output_dir, output_template, proxy=None, network_path=None):
        if captured is not None:
            captured.append(network_path)
        return _FakeDownloader()

    def fake_download_one(song, downloader):
        if outcome == "failed":
            raise RuntimeError("boom")
        return downloads.DownloadResult(song, output_path)

    monkeypatch.setattr(downloads, "get_downloader", fake_get_downloader)
    monkeypatch.setattr(downloads, "download_one", fake_download_one)
    download_task.download_track(str(track.id))
    return db_session.get(Track, track.id)


def test_a_success_after_a_failure_clears_last_error(db_session, monkeypatch, tmp_path):
    """v55 (E9): the track fails once, then succeeds. It used to keep the failure's
    last_error/last_error_type, shown as a red "last error" on a completed row."""
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    _capture_events(monkeypatch)
    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")

    failed = _run_invocation(db_session, monkeypatch, track, outcome="failed")
    assert (failed.last_error, failed.last_error_type) == ("boom", TrackErrorType.OTHER)
    updated = _run_invocation(db_session, monkeypatch, track, outcome="completed", output_path=output_path)

    assert updated.state == TrackState.COMPLETED
    assert (updated.last_error, updated.last_error_type) == (None, None)
    assert [row.outcome for row in _attempts(db_session, track)] == [
        TrackAttemptOutcome.FAILED,
        TrackAttemptOutcome.COMPLETED,
    ]


def test_first_try_success_counts_one_attempt_and_no_failures(db_session, monkeypatch, tmp_path):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    published = _capture_events(monkeypatch)
    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")

    updated = _run_invocation(
        db_session, monkeypatch, track, outcome="completed", output_path=output_path
    )

    assert updated.state == TrackState.COMPLETED
    assert (updated.attempts_made, updated.failure_count) == (1, 0)
    assert [row.attempt_number for row in _attempts(db_session, track)] == [1]
    _, final_kwargs = published[-1]
    assert (final_kwargs["attempts_made"], final_kwargs["failure_count"]) == (1, 0)


def test_two_failures_then_success_counts_three_attempts_and_two_failures(
    db_session, monkeypatch, tmp_path
):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")

    _run_invocation(db_session, monkeypatch, track, outcome="failed")
    _run_invocation(db_session, monkeypatch, track, outcome="held")
    _run_invocation(db_session, monkeypatch, track, outcome="failed")
    updated = _run_invocation(
        db_session, monkeypatch, track, outcome="completed", output_path=output_path
    )

    assert updated.state == TrackState.COMPLETED
    assert (updated.attempts_made, updated.failure_count) == (3, 2)
    rows = _attempts(db_session, track)
    assert [row.outcome for row in rows] == [
        TrackAttemptOutcome.FAILED,
        TrackAttemptOutcome.HELD,
        TrackAttemptOutcome.FAILED,
        TrackAttemptOutcome.COMPLETED,
    ]
    # Unique and strictly increasing across the breaker hold.
    assert [row.attempt_number for row in rows] == [1, 2, 3, 4]


def test_cancelled_rows_count_as_attempts_only_when_they_reached_the_network(db_session):
    from app.services import attempts

    track = _make_track(db_session)
    now = datetime.now(timezone.utc)
    attempts.record_attempt(db_session, track.id, now, now, TrackAttemptOutcome.CANCELLED)
    attempts.record_attempt(
        db_session,
        track.id,
        now,
        now,
        TrackAttemptOutcome.CANCELLED,
        network_path=NetworkPath.DIRECT_IPV4,
    )
    db_session.commit()

    updated = db_session.get(Track, track.id)
    assert (updated.attempts_made, updated.failure_count) == (1, 0)
    assert [row.attempt_number for row in _attempts(db_session, track)] == [1, 2]


# The ladder step and network-path rung each failure count produced before v35, written out
# as literals so a change to either can't hide behind a shared helper: the delay applied by
# the (n+1)-th failure, and the path the (n+1)-th real attempt takes.
_PINNED_LADDER = [900, 3600, 14400, 43200, 86400, 86400, 86400]
_PINNED_RUNG = [
    NetworkPath.DIRECT_IPV4,
    NetworkPath.DIRECT_IPV6,
    # No proxy is configured in these tests, so the proxy rung falls back to forced IPv4
    # (download.py's pick_proxy-returned-None branch) -- unchanged since v29.
    NetworkPath.DIRECT_IPV4,
    NetworkPath.DIRECT_IPV4,
    NetworkPath.DIRECT_IPV4,
    NetworkPath.DIRECT_IPV4,
    NetworkPath.DIRECT_IPV4,
]


def test_next_delay_is_pinned_for_every_failure_count(monkeypatch):
    monkeypatch.setattr(
        get_settings(), "ladder_seconds", [900, 3600, 14400, 43200, 86400], raising=False
    )
    for failures, seconds in enumerate(_PINNED_LADDER):
        assert retry.next_delay(failures) == timedelta(seconds=seconds)


@pytest.mark.parametrize("failures", range(7))
def test_ladder_step_ignores_held_and_cancelled_rows(db_session, monkeypatch, failures):
    """v35's ladder pin: `failures` real failures, each preceded by a breaker hold, plus a
    cancelled row from a mid-download cancel, then one more failure. The delay it gets and
    the rung its attempt used must be exactly what `failures` alone gave before v35 -- the
    extra held/cancelled rows (and the new display counters) must not move either."""
    from app.services import attempts

    monkeypatch.setattr(
        get_settings(), "ladder_seconds", [900, 3600, 14400, 43200, 86400], raising=False
    )
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)

    for _ in range(failures):
        _run_invocation(db_session, monkeypatch, track, outcome="held")
        _run_invocation(db_session, monkeypatch, track, outcome="failed")
    now = datetime.now(timezone.utc)
    attempts.record_attempt(
        db_session,
        track.id,
        now,
        now,
        TrackAttemptOutcome.CANCELLED,
        network_path=NetworkPath.DIRECT_IPV4,
    )
    db_session.commit()
    assert db_session.get(Track, track.id).attempt_count == failures

    rungs = []
    before = datetime.now(timezone.utc)
    updated = _run_invocation(db_session, monkeypatch, track, outcome="failed", captured=rungs)
    after = datetime.now(timezone.utc)

    assert rungs == [_PINNED_RUNG[failures]]
    assert updated.state == TrackState.WAITING
    assert updated.attempt_count == failures + 1
    scheduled = updated.scheduled_at.replace(tzinfo=timezone.utc)
    step = timedelta(seconds=_PINNED_LADDER[failures])
    assert before + step <= scheduled <= after + step
    # The display counters moved independently: holds aren't attempts, the
    # mid-download cancel is.
    assert updated.failure_count == failures + 1
    assert updated.attempts_made == failures + 2
    numbers = [row.attempt_number for row in _attempts(db_session, track)]
    assert numbers == list(range(1, 2 * failures + 3))


# --- v35 (c): redelivery must not rewrite a completed track -----------------------------

_LONG_AGO = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("state", [TrackState.COMPLETED, TrackState.SKIPPED_DUPLICATE])
def test_redelivered_message_for_a_finished_track_is_a_noop(db_session, monkeypatch, state):
    track = _make_track(db_session)
    track.state = state
    track.output_path = "/downloads/song-a.mp3"
    # An explicit past value (v51): inside db_session's one transaction, Postgres's now() is
    # the test's start, so an onupdate bump would write the value the row already holds.
    track.updated_at = _LONG_AGO
    db_session.add(
        DownloadedTrack(
            spotify_track_id="abc123", file_path="/downloads/song-a.mp3", format="mp3", bitrate="320k"
        )
    )
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    published = _capture_events(monkeypatch)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("a finished track must not reach dedup or the downloader")

    monkeypatch.setattr(dedup, "is_already_downloaded", _fail_if_called)
    monkeypatch.setattr(downloads, "get_downloader", _fail_if_called)
    before_updated_at = db_session.get(Track, track.id).updated_at
    assert before_updated_at == _LONG_AGO

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == state
    assert updated.output_path == "/downloads/song-a.mp3"
    assert updated.updated_at == before_updated_at
    assert (updated.attempts_made, updated.failure_count) == (0, 0)
    assert _attempts(db_session, track) == []
    assert published == []


def test_a_redelivery_before_the_first_deliverys_ack_is_a_noop_on_real_connections(
    committed_db, monkeypatch, tmp_path
):
    """v51, the test above on real connections: the first delivery commits COMPLETED and its
    ledger row, then stops before it returns, as a worker that crashes before its ack does
    (acks_late). The redelivered message runs on a session of its own, and the real dedup
    gate reads the ledger through its own connection. Guard: the v35 (c) finished-track check;
    without it the redelivery rewrote the track to skipped_duplicate."""
    with committed_db() as db:
        user = User(email="owner@example.com", is_admin=False)
        db.add(user)
        db.flush()
        job = Job(source_url="https://open.spotify.com/track/abc", source_type=JobSourceType.TRACK, user_id=user.id)
        db.add(job)
        db.flush()
        track = Track(
            job_id=job.id, spotify_track_id="abc123", song_json={"name": "Song A"}, state=TrackState.QUEUED
        )
        db.add(track)
        db.commit()
        track_id = track.id
    monkeypatch.setattr(download_task, "SessionLocal", committed_db)
    monkeypatch.setattr(dedup, "SessionLocal", committed_db)
    monkeypatch.setattr(download_task.Song, "from_dict", classmethod(lambda cls, data: data))
    monkeypatch.setattr(tagging, "is_supported_format", lambda path: False)
    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")
    monkeypatch.setattr(downloads, "get_downloader", lambda *args, **kwargs: _FakeDownloader())
    monkeypatch.setattr(downloads, "download_one", lambda song, downloader: downloads.DownloadResult(song, output_path))
    gate = Gate("first delivery: COMPLETED committed, not yet acked")
    published = []

    def publish(owner_id, track_id_, job_id, state, **kwargs):
        published.append((threading.current_thread().name, state))
        if state == "completed":
            gate()

    monkeypatch.setattr(events, "publish_track_event", publish)

    first = Thread(download_task.download_track, str(track_id), name="first delivery")
    gate.wait_reached()
    download_task.download_track(str(track_id))  # the redelivered message
    gate.open()
    first.join()

    with committed_db() as db:
        track = db.get(Track, track_id)
        assert (track.state, track.output_path) == (TrackState.COMPLETED, str(output_path))
        outcomes = [a.outcome for a in db.query(TrackAttempt).filter(TrackAttempt.track_id == track_id)]
        assert outcomes == [TrackAttemptOutcome.COMPLETED]
    assert published == [("first delivery", "downloading"), ("first delivery", "completed")]


def test_a_stray_message_for_a_cancelled_track_leaves_updated_at_alone(db_session, monkeypatch):
    """v35: record_attempt's counter UPDATE must not bump tracks.updated_at (the job's
    archive clock) when nothing about the track itself changed."""
    track = _make_track(db_session)
    track.state = TrackState.CANCELLED
    track.updated_at = _LONG_AGO  # see test_redelivered_message_for_a_finished_track_is_a_noop
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    before = db_session.get(Track, track.id).updated_at
    assert before == _LONG_AGO

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert [row.outcome for row in _attempts(db_session, track)] == [TrackAttemptOutcome.CANCELLED]
    assert updated.updated_at == before


# --- v55 (E11): consecutive holds collapse into one row -------------------------------------


def test_a_ten_tick_breaker_hold_over_three_tracks_writes_three_rows(db_session, monkeypatch):
    """Ten ticks of a tripped breaker, each re-sending the same three queued tracks' messages:
    one `held` row per track, its hold_count 10 and its span the first hold to the last,
    where it used to be 30 rows."""
    _patch_common(monkeypatch, db_session)
    _capture_events(monkeypatch)
    tracks = [_make_track(db_session) for _ in range(3)]
    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.commit()

    for _ in range(10):
        for track in tracks:
            track.state = TrackState.QUEUED
            db_session.commit()
            download_task.download_track(str(track.id))

    rows = db_session.query(TrackAttempt).filter(TrackAttempt.track_id.in_([t.id for t in tracks])).all()
    assert len(rows) == 3
    assert {row.track_id for row in rows} == {t.id for t in tracks}
    for row in rows:
        assert (row.outcome, row.hold_count, row.attempt_number) == (TrackAttemptOutcome.HELD, 10, 1)
        assert row.finished_at > row.started_at
    for track in tracks:
        updated = db_session.get(Track, track.id)
        assert (updated.state, updated.attempts_made, updated.failure_count) == (TrackState.WAITING, 0, 0)


def test_a_hold_after_an_attempt_or_another_reason_starts_a_new_row(db_session, monkeypatch):
    """Only *consecutive identical* holds collapse: a real attempt in between, or a hold for a
    different reason, keeps the order of events readable."""
    from app.services import attempts

    track = _make_track(db_session)
    now = datetime.now(timezone.utc)

    def hold(reason):
        attempts.record_attempt(
            db_session, track.id, now, now, TrackAttemptOutcome.HELD, warning_message=reason, collapse_hold=True
        )
        db_session.commit()

    hold("circuit breaker active")
    hold("circuit breaker active")
    attempts.record_attempt(db_session, track.id, now, now, TrackAttemptOutcome.FAILED, error_message="boom")
    db_session.commit()
    hold("circuit breaker active")
    hold("/library is missing or empty")

    rows = _attempts_by_number(db_session, track)
    assert [(row.outcome, row.hold_count) for row in rows] == [
        (TrackAttemptOutcome.HELD, 2),
        (TrackAttemptOutcome.FAILED, 1),
        (TrackAttemptOutcome.HELD, 1),
        (TrackAttemptOutcome.HELD, 1),
    ]
    assert [row.attempt_number for row in rows] == [1, 2, 3, 4]


def _attempts_by_number(db_session, track):
    return (
        db_session.query(TrackAttempt)
        .filter(TrackAttempt.track_id == track.id)
        .order_by(TrackAttempt.attempt_number)
        .all()
    )
