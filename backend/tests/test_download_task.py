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
    User,
    WorkerState,
)
from app.services import dedup, downloads, events, proxies, retry
from app.tasks import download as download_task


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
    to bind its progress_handler.update_callback hook (see v08's events.py wiring)."""

    def __init__(self):
        self.progress_handler = _FakeProgressHandler()


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


def _patch_common(monkeypatch, db_session):
    monkeypatch.setattr(download_task, "SessionLocal", lambda: _NonClosingSession(db_session))
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
    published = _capture_events(monkeypatch)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None: _FakeDownloader())
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

    # "downloading" (progress=0, right before the attempt) then "completed" once durable.
    states = [args[3] for args, _ in published]
    assert states == ["downloading", "completed"]


def test_download_track_other_error_reschedules_to_waiting(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    published = _capture_events(monkeypatch)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None: _FakeDownloader())

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


def test_download_track_audio_provider_error_feeds_breaker(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None: _FakeDownloader())

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
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None: _FakeDownloader())
    monkeypatch.setattr(downloads, "download_one", lambda song, downloader: (song, None))

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


def test_download_track_lookup_error_is_terminal(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    published = _capture_events(monkeypatch)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None: _FakeDownloader())

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


def test_download_track_success_resets_breaker_state(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)

    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = 3
    worker_state.breaker_trip_count = 1
    db_session.commit()

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None: _FakeDownloader())
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

    def fake_get_downloader(fmt, bitrate, output_dir, output_template, proxy=None):
        captured["proxy"] = proxy
        return _FakeDownloader()

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

    def fake_get_downloader(fmt, bitrate, output_dir, output_template, proxy=None):
        captured["proxy"] = proxy
        return _FakeDownloader()

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

    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None: _FakeDownloader())

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


def test_download_track_retry_failure_redacts_proxy_credentials_from_last_error(db_session, monkeypatch):
    track = _make_track(db_session)
    track.attempt_count = 1
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)

    proxy = Proxy(url="http://sneaky:hunter2@proxy-1:8080", source=ProxySource.FILE, enabled=True)
    db_session.add(proxy)
    db_session.commit()

    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None: _FakeDownloader())

    def fake_download_one(song, downloader):
        raise RuntimeError(f"Invalid proxy server: {proxy.url}")

    monkeypatch.setattr(downloads, "download_one", fake_download_one)

    download_task.download_track(str(track.id))

    updated = db_session.get(Track, track.id)
    assert "hunter2" not in updated.last_error
    assert "sneaky" not in updated.last_error
    assert "http://proxy-1:8080" in updated.last_error


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


def test_download_track_discards_success_when_cancelled_mid_download(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    published = _capture_events(monkeypatch)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None: _FakeDownloader())

    def fake_download_one(song, downloader):
        # A `DELETE /api/tracks/{id}` (separate request/session) landing while this
        # blocking, real download call was still running — search_and_download isn't
        # cleanly interruptible, so the cancel just commits the state change directly.
        db_session.query(Track).filter(Track.id == track.id).update(
            {"state": TrackState.CANCELLED, "scheduled_at": None}
        )
        db_session.commit()
        return song, Path("/downloads/song-a.mp3")

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


def test_download_track_discards_failure_when_cancelled_mid_download(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    published = _capture_events(monkeypatch)

    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(downloads, "get_downloader", lambda fmt, bitrate, output_dir, output_template, proxy=None: _FakeDownloader())

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


def test_download_track_retry_falls_back_to_direct_when_no_proxy_available(db_session, monkeypatch):
    track = _make_track(db_session)
    track.attempt_count = 1
    db_session.commit()
    _patch_common(monkeypatch, db_session)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    # No Proxy rows at all -> pick_proxy returns None -> the attempt still has to happen
    # directly rather than stalling the track indefinitely on proxy availability.

    captured = {}

    def fake_get_downloader(fmt, bitrate, output_dir, output_template, proxy=None):
        captured["proxy"] = proxy
        return _FakeDownloader()

    monkeypatch.setattr(downloads, "get_downloader", fake_get_downloader)
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: (song, Path("/downloads/song-a.mp3"))
    )

    download_task.download_track(str(track.id))

    assert captured["proxy"] is None
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.COMPLETED
    assert updated.used_proxy_id is None


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


def test_download_track_sleeps_before_the_attempt_when_pacing_configured(db_session, monkeypatch):
    track = _make_track(db_session)
    _patch_common(monkeypatch, db_session)
    settings = download_task.get_settings()
    monkeypatch.setattr(settings, "pacing_min_sec", 3, raising=False)
    monkeypatch.setattr(settings, "pacing_max_sec", 3, raising=False)

    calls = []
    monkeypatch.setattr(
        download_task.time, "sleep", lambda seconds: calls.append(("sleep", seconds))
    )
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda track_id: None)
    monkeypatch.setattr(
        downloads,
        "get_downloader",
        lambda fmt, bitrate, output_dir, output_template, proxy=None: (
            calls.append(("download", None)) or _FakeDownloader()
        ),
    )
    monkeypatch.setattr(
        downloads, "download_one", lambda song, downloader: (song, Path("/downloads/song-a.mp3"))
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
