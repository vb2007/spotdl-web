"""v55: download_track's races against cancel and beat's stale reclaim, on real connections.

Each test runs the real download_track in a thread on a session of its own (conftest's
`committed_db`), stops it at a chosen point with a Gate, commits the competing write from the
test's own session, then lets it go on. Only the network call (spotdl) is faked."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from concurrency import Gate, Thread

from app.models import (
    Job,
    JobSourceType,
    JobState,
    Track,
    TrackAttempt,
    TrackAttemptOutcome,
    TrackState,
    User,
)
from app.services import app_settings, dedup, downloads, events, tagging
from app.tasks import beat as beat_task
from app.tasks import download as download_task

_LONG_AGO = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeProgressHandler:
    update_callback = None


class _FakeDownloader:
    def __init__(self):
        self.progress_handler = _FakeProgressHandler()
        self.audio_providers = []


def _committed_track(committed_db, *, state=TrackState.QUEUED, attempt_count=0) -> uuid.UUID:
    with committed_db() as db:
        user = User(email="owner@example.com", is_admin=False)
        db.add(user)
        db.flush()
        job = Job(
            source_url="https://open.spotify.com/track/abc",
            source_type=JobSourceType.TRACK,
            user_id=user.id,
            state=JobState.EXPANDED,
        )
        db.add(job)
        db.flush()
        # Stuck past the staleness threshold, so a reclaim run by the test picks it up.
        track = Track(
            job_id=job.id,
            spotify_track_id="abc123",
            song_json={"name": "Song A"},
            state=state,
            attempt_count=attempt_count,
            updated_at=_LONG_AGO,
        )
        db.add(track)
        db.commit()
        return track.id


@pytest.fixture()
def real_task(committed_db, monkeypatch, tmp_path):
    """download_track on real sessions with every network call faked. `downloaded` lists each
    call that reached spotdl, `published` each event."""
    monkeypatch.setattr(download_task, "SessionLocal", committed_db)
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda spotify_track_id: None)
    monkeypatch.setattr(download_task.Song, "from_dict", classmethod(lambda cls, data: data))
    monkeypatch.setattr(tagging, "is_supported_format", lambda path: False)
    monkeypatch.setattr(downloads, "get_downloader", lambda *args, **kwargs: _FakeDownloader())
    output_path = tmp_path / "song-a.mp3"
    output_path.write_bytes(b"fake audio bytes")
    state = SimpleNamespace(downloaded=[], published=[], output_path=output_path)

    def download_one(song, downloader):
        state.downloaded.append(song)
        return song, output_path

    monkeypatch.setattr(downloads, "download_one", download_one)
    monkeypatch.setattr(
        events, "publish_track_event", lambda owner_id, track_id, job_id, s, **kwargs: state.published.append((s, kwargs))
    )
    return state


def _cancel(committed_db, track_id):
    """What cancel_job/DELETE /api/tracks/{id} commit for the track."""
    with committed_db() as db:
        track = db.get(Track, track_id)
        track.state = TrackState.CANCELLED
        track.scheduled_at = None
        db.commit()


def _reclaim_and_redispatch(committed_db, track_id):
    """Beat's stale reclaim takes the track (waiting + its row), and the same tick's dispatch
    queues it again with a message of its own: the track reads `queued` once more."""
    with committed_db() as db:
        beat_task._reclaim_stale_tracks(db)
    with committed_db() as db:
        track = db.get(Track, track_id)
        assert track.state == TrackState.WAITING
        track.state = TrackState.QUEUED
        db.commit()


def _rows(committed_db, track_id):
    with committed_db() as db:
        return [
            (row.outcome, row.network_path)
            for row in db.query(TrackAttempt)
            .filter(TrackAttempt.track_id == track_id)
            .order_by(TrackAttempt.attempt_number)
        ]


# --- E5: the `downloading` write is a conditional transition ------------------------------


@pytest.mark.parametrize("competitor", ["cancel", "reclaim"])
def test_a_cancel_or_reclaim_just_before_the_downloading_write_wins(
    committed_db, monkeypatch, real_task, competitor
):
    """The task has passed every gate and read its output settings; the competing write commits
    before its `downloading` write. A plain assignment overwrote it: the cancelled track was
    downloaded and completed, the reclaimed one downloaded here and again by beat's new
    message. The guarded transition matches no row, so the task exits without downloading."""
    track_id = _committed_track(committed_db)
    gate = Gate("download_track: output settings read, before the downloading write")
    monkeypatch.setattr(app_settings, "get_output_settings", gate.wrap(app_settings.get_output_settings))

    task = Thread(download_task.download_track, str(track_id), name="download_track")
    gate.wait_reached()
    if competitor == "cancel":
        _cancel(committed_db, track_id)
    else:
        _reclaim_and_redispatch(committed_db, track_id)
    gate.open()
    task.join()

    assert real_task.downloaded == []
    with committed_db() as db:
        track = db.get(Track, track_id)
        if competitor == "cancel":
            assert track.state == TrackState.CANCELLED
            assert _rows(committed_db, track_id) == [(TrackAttemptOutcome.CANCELLED, None)]
        else:
            # Beat's message owns it now; this invocation wrote nothing beside the reclaim's row.
            assert track.state == TrackState.QUEUED
            assert _rows(committed_db, track_id) == [(TrackAttemptOutcome.HELD, None)]
        assert (track.attempts_made, track.failure_count) == (0, 0)
    # The reclaim publishes its own `waiting`; the task publishes nothing.
    assert [s for s, _ in real_task.published] == ([] if competitor == "cancel" else ["waiting"])
