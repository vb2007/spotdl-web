import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spotdl.providers.audio.base import AudioProviderError

from app.models import (
    DownloadedTrack,
    Job,
    JobSourceType,
    Proxy,
    ProxySource,
    Track,
    TrackErrorType,
    TrackState,
    WorkerState,
)
from app.services import dedup, downloads, proxies, retry
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
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, proxy=None: "fake-downloader")
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


def test_download_track_other_error_reschedules_to_waiting(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, proxy=None: "fake-downloader")

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


def test_download_track_audio_provider_error_feeds_breaker(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, proxy=None: "fake-downloader")

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


def test_download_track_lookup_error_is_terminal(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, proxy=None: "fake-downloader")

    def fake_download_one(song, downloader):
        raise LookupError("no result on any provider")

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.LOOKUP_FAILED
    assert updated.last_error_type == TrackErrorType.LOOKUP
    assert updated.scheduled_at is None


def test_download_track_success_resets_breaker_state(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = 3
    worker_state.breaker_trip_count = 1
    db_session.commit()

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, proxy=None: "fake-downloader")
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: (song, Path("/downloads/song-a.mp3"))
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


def test_download_track_unknown_track_is_a_noop(db_session, monkeypatch):
    monkeypatch.setattr(download_task, "SessionLocal", lambda: _NonClosingSession(db_session))

    download_task.download_track(str(uuid.uuid4()))


def test_download_track_first_attempt_never_touches_proxy_pool(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)

    def _fail_if_called(db):
        raise AssertionError("pick_proxy should not be called on the direct-first attempt")

    monkeypatch.setattr(proxies, "pick_proxy", _fail_if_called)

    captured = {}

    def fake_get_downloader(fmt, bitrate, proxy=None):
        captured["proxy"] = proxy
        return "fake-downloader"

    monkeypatch.setattr(downloads, "get_downloader", fake_get_downloader)
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: (song, Path("/downloads/song-a.mp3"))
    )

    download_task.download_track(str(track.id))

    assert captured["proxy"] is None
    updated = db_session.get(Track, track.id)
    assert updated.used_proxy_id is None


def test_download_track_retry_picks_proxy_and_records_success(db_session, monkeypatch):
    track = _make_track(db_session)
    track.attempt_count = 1
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)

    proxy = Proxy(url="http://proxy-1", source=ProxySource.FILE, enabled=True)
    db_session.add(proxy)
    db_session.commit()

    captured = {}

    def fake_get_downloader(fmt, bitrate, proxy=None):
        captured["proxy"] = proxy
        return "fake-downloader"

    monkeypatch.setattr(downloads, "get_downloader", fake_get_downloader)
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: (song, Path("/downloads/song-a.mp3"))
    )

    download_task.download_track(str(track.id))

    assert captured["proxy"] == "http://proxy-1"
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.COMPLETED
    assert updated.used_proxy_id == proxy.id

    updated_proxy = db_session.get(Proxy, proxy.id)
    assert updated_proxy.last_success_at is not None
    assert updated_proxy.consecutive_failures == 0


def test_download_track_retry_proxy_failure_sets_cooldown(db_session, monkeypatch):
    track = _make_track(db_session)
    track.attempt_count = 1
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)

    proxy = Proxy(url="http://proxy-1", source=ProxySource.FILE, enabled=True)
    db_session.add(proxy)
    db_session.commit()

    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, proxy=None: "fake-downloader")

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


def test_download_track_retry_falls_back_to_direct_when_no_proxy_available(db_session, monkeypatch):
    track = _make_track(db_session)
    track.attempt_count = 1
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    # No Proxy rows at all -> pick_proxy returns None -> the attempt still has to happen
    # directly rather than stalling the track indefinitely on proxy availability.

    captured = {}

    def fake_get_downloader(fmt, bitrate, proxy=None):
        captured["proxy"] = proxy
        return "fake-downloader"

    monkeypatch.setattr(downloads, "get_downloader", fake_get_downloader)
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: (song, Path("/downloads/song-a.mp3"))
    )

    download_task.download_track(str(track.id))

    assert captured["proxy"] is None
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.COMPLETED
    assert updated.used_proxy_id is None
