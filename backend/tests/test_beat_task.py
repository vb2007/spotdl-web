from datetime import datetime, timedelta, timezone

from app.models import Job, JobSourceType, Track, TrackState
from app.services import events, retry
from app.tasks import beat as beat_task


class _NonClosingSession:
    """See test_download_task.py — download_track's db.close() would otherwise detach
    objects the test still needs to assert against."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


def _make_track(db_session, *, state, scheduled_at=None, spotify_track_id="abc123", job_priority=0):
    job = Job(
        source_url="https://open.spotify.com/track/abc",
        source_type=JobSourceType.TRACK,
        priority=job_priority,
    )
    db_session.add(job)
    db_session.commit()

    track = Track(
        job_id=job.id,
        spotify_track_id=spotify_track_id,
        song_json={"name": "Song A"},
        state=state,
        scheduled_at=scheduled_at,
    )
    db_session.add(track)
    db_session.commit()
    return track


def _patch_session(monkeypatch, db_session):
    monkeypatch.setattr(beat_task, "SessionLocal", lambda: _NonClosingSession(db_session))


def test_dispatch_due_tracks_dispatches_and_flips_state(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    due = _make_track(
        db_session, state=TrackState.WAITING, scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    not_due = _make_track(
        db_session,
        state=TrackState.WAITING,
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        spotify_track_id="def456",
    )

    dispatched_ids = []
    monkeypatch.setattr(beat_task.download_track, "delay", lambda track_id: dispatched_ids.append(track_id))

    published = []
    monkeypatch.setattr(
        events, "publish_track_event", lambda *args, **kwargs: published.append(args)
    )

    beat_task.dispatch_due_tracks()

    assert dispatched_ids == [str(due.id)]
    assert db_session.get(Track, due.id).state == TrackState.QUEUED
    assert db_session.get(Track, not_due.id).state == TrackState.WAITING
    assert published == [(due.id, due.job_id, "queued")]


def test_dispatch_due_tracks_skips_entirely_while_breaker_tripped(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    due = _make_track(
        db_session, state=TrackState.WAITING, scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1)
    )

    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.commit()

    def _fail_if_called(track_id):
        raise AssertionError("download_track should not be dispatched while the breaker is tripped")

    monkeypatch.setattr(beat_task.download_track, "delay", _fail_if_called)

    beat_task.dispatch_due_tracks()

    assert db_session.get(Track, due.id).state == TrackState.WAITING


def test_dispatch_due_tracks_orders_by_job_priority_over_scheduled_at(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    now = datetime.now(timezone.utc)
    # low-priority job's track became due first (earlier scheduled_at) -- priority must
    # still win, dispatching the high-priority job's track first among everything due.
    low = _make_track(
        db_session,
        state=TrackState.WAITING,
        scheduled_at=now - timedelta(minutes=10),
        spotify_track_id="low",
        job_priority=0,
    )
    high = _make_track(
        db_session,
        state=TrackState.WAITING,
        scheduled_at=now - timedelta(minutes=1),
        spotify_track_id="high",
        job_priority=5,
    )

    dispatched_ids = []
    monkeypatch.setattr(beat_task.download_track, "delay", lambda track_id: dispatched_ids.append(track_id))
    monkeypatch.setattr(events, "publish_track_event", lambda *args, **kwargs: None)

    beat_task.dispatch_due_tracks()

    assert dispatched_ids == [str(high.id), str(low.id)]


def test_dispatch_due_tracks_priority_never_pulls_forward_a_not_yet_due_track(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    now = datetime.now(timezone.utc)
    # High-priority job's track is still waiting out its ladder delay -- priority only
    # reorders among tracks already due, it cannot make this one jump ahead.
    due_low = _make_track(
        db_session,
        state=TrackState.WAITING,
        scheduled_at=now - timedelta(minutes=1),
        spotify_track_id="low",
        job_priority=0,
    )
    not_due_high = _make_track(
        db_session,
        state=TrackState.WAITING,
        scheduled_at=now + timedelta(hours=1),
        spotify_track_id="high",
        job_priority=5,
    )

    dispatched_ids = []
    monkeypatch.setattr(beat_task.download_track, "delay", lambda track_id: dispatched_ids.append(track_id))
    monkeypatch.setattr(events, "publish_track_event", lambda *args, **kwargs: None)

    beat_task.dispatch_due_tracks()

    assert dispatched_ids == [str(due_low.id)]
    assert db_session.get(Track, not_due_high.id).state == TrackState.WAITING


def test_dispatch_due_tracks_skips_entirely_while_paused(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    due = _make_track(
        db_session, state=TrackState.WAITING, scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1)
    )

    worker_state = retry.get_worker_state(db_session)
    worker_state.paused = True
    db_session.commit()

    def _fail_if_called(track_id):
        raise AssertionError("download_track should not be dispatched while paused")

    monkeypatch.setattr(beat_task.download_track, "delay", _fail_if_called)

    beat_task.dispatch_due_tracks()

    assert db_session.get(Track, due.id).state == TrackState.WAITING
