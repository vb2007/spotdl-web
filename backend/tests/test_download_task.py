import uuid
from pathlib import Path

from app.models import DownloadedTrack, Job, JobSourceType, Track, TrackState
from app.services import dedup, downloads
from app.tasks import download as download_task


class _NonClosingSession:
    """Wraps db_session so download_track's db.close() doesn't detach objects the test
    still needs to assert against — the fixture handles real teardown instead."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


class _FakeSettings:
    default_format = "mp3"
    default_bitrate = "320k"


def _make_track(db_session):
    job = Job(source_url="https://open.spotify.com/track/abc", source_type=JobSourceType.TRACK)
    db_session.add(job)
    db_session.commit()

    track = Track(job_id=job.id, spotify_track_id="abc123", song_json={"name": "Song A"})
    db_session.add(track)
    db_session.commit()
    return track


def _patch_common(monkeypatch, db_session):
    monkeypatch.setattr(download_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(download_task, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(download_task.Song, "from_dict", classmethod(lambda cls, data: data))


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


def test_download_track_success_marks_completed_and_upserts_ledger(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate: "fake-downloader")
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: (song, Path("/downloads/song-a.mp3"))
    )

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.COMPLETED
    assert updated.output_path == "/downloads/song-a.mp3"

    ledger_row = db_session.get(DownloadedTrack, "abc123")
    assert ledger_row is not None
    assert ledger_row.file_path == "/downloads/song-a.mp3"
    assert ledger_row.format == "mp3"
    assert ledger_row.bitrate == "320k"


def test_download_track_failure_marks_failed_with_error(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate: "fake-downloader")

    def fake_download_one(song, downloader):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.FAILED
    assert updated.last_error == "provider exploded"
    assert db_session.get(DownloadedTrack, "abc123") is None


def test_download_track_unknown_track_is_a_noop(db_session, monkeypatch):
    monkeypatch.setattr(download_task, "SessionLocal", lambda: _NonClosingSession(db_session))

    download_task.download_track(str(uuid.uuid4()))
