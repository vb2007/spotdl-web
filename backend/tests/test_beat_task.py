from datetime import datetime, timedelta, timezone

from app.models import Job, JobSourceType, JobState, Track, TrackState, User, UserSettings
from app.services import events, retry
from app.tasks import beat as beat_task


def _owner(db_session) -> User:
    user = db_session.query(User).filter(User.email == "owner@example.com").one_or_none()
    if user is None:
        user = User(email="owner@example.com", is_admin=False)
        db_session.add(user)
        db_session.flush()
    return user


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
        user_id=_owner(db_session).id,
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
    assert published == [(_owner(db_session).id, due.id, due.job_id, "queued")]


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


def _make_job(db_session, owner, *, job_state=JobState.EXPANDED, track_states=()) -> Job:
    job = Job(
        source_url="https://open.spotify.com/album/x",
        source_type=JobSourceType.ALBUM,
        state=job_state,
        user_id=owner.id,
    )
    db_session.add(job)
    db_session.commit()
    for index, state in enumerate(track_states):
        db_session.add(
            Track(
                job_id=job.id,
                spotify_track_id=f"{job.id}-{index}",
                song_json={"name": "Song"},
                state=state,
            )
        )
    db_session.commit()
    return job


def _set_retention(db_session, user, days) -> None:
    db_session.add(UserSettings(user_id=user.id, retention_days=days))
    db_session.commit()


def test_archive_due_jobs_archives_settled_jobs_past_the_users_retention_threshold(
    db_session, monkeypatch
):
    _patch_session(monkeypatch, db_session)
    owner = _owner(db_session)
    _set_retention(db_session, owner, 1)
    job = _make_job(db_session, owner, track_states=(TrackState.COMPLETED,))
    stale = datetime.now(timezone.utc) - timedelta(days=10)
    for track in db_session.query(Track).filter(Track.job_id == job.id):
        track.updated_at = stale
    db_session.commit()

    published = []
    monkeypatch.setattr(events, "publish_job_event", lambda *a, **kw: published.append((a, kw)))

    beat_task.archive_due_jobs()

    assert db_session.get(Job, job.id).archived_at is not None
    assert published == [((owner.id, job.id, "expanded"), {"archived": True})]


def test_archive_due_jobs_never_archives_a_waiting_job_even_when_old(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    owner = _owner(db_session)
    _set_retention(db_session, owner, 1)
    job = _make_job(db_session, owner, track_states=(TrackState.WAITING,))
    long_ago = datetime.now(timezone.utc) - timedelta(days=365)
    job.created_at = long_ago
    for track in db_session.query(Track).filter(Track.job_id == job.id):
        track.updated_at = long_ago
    db_session.commit()
    monkeypatch.setattr(events, "publish_job_event", lambda *a, **kw: None)

    beat_task.archive_due_jobs()

    assert db_session.get(Job, job.id).archived_at is None


def test_archive_due_jobs_skips_users_with_null_retention(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    owner = _owner(db_session)
    # No UserSettings row at all -- the default, unset state -- must be treated the same
    # as an explicit retention_days=None: never touched by the sweep.
    job = _make_job(db_session, owner, track_states=(TrackState.COMPLETED,))
    for track in db_session.query(Track).filter(Track.job_id == job.id):
        track.updated_at = datetime.now(timezone.utc) - timedelta(days=365)
    db_session.commit()
    monkeypatch.setattr(events, "publish_job_event", lambda *a, **kw: None)

    beat_task.archive_due_jobs()

    assert db_session.get(Job, job.id).archived_at is None


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


def test_dispatch_due_tracks_reclaims_stale_downloading_track(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    stuck = _make_track(db_session, state=TrackState.DOWNLOADING)
    stuck.updated_at = datetime.now(timezone.utc) - beat_task.stale_track_after() - timedelta(minutes=1)
    db_session.commit()

    dispatched_ids = []
    monkeypatch.setattr(beat_task.download_track, "delay", lambda track_id: dispatched_ids.append(track_id))
    published = []
    monkeypatch.setattr(events, "publish_track_event", lambda *args, **kwargs: published.append((args, kwargs)))

    beat_task.dispatch_due_tracks()

    # Reclaimed to WAITING with scheduled_at=now, which this same tick's due-tracks query
    # then picks straight back up (its scheduled_at is already <= "now" computed just after)
    # -- no reason to force an extra 30s wait once the decision to retry has been made.
    refreshed = db_session.get(Track, stuck.id)
    assert refreshed.state == TrackState.QUEUED
    assert dispatched_ids == [str(stuck.id)]
    published_states = [args[3] for args, kwargs in published]
    assert published_states == ["waiting", "queued"]


def test_dispatch_due_tracks_leaves_recent_downloading_track_alone(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    fresh = _make_track(db_session, state=TrackState.DOWNLOADING)
    # updated_at defaults to "now" via server_default -- well within the stale window.

    monkeypatch.setattr(beat_task.download_track, "delay", lambda track_id: None)
    monkeypatch.setattr(events, "publish_track_event", lambda *args, **kwargs: None)

    beat_task.dispatch_due_tracks()

    assert db_session.get(Track, fresh.id).state == TrackState.DOWNLOADING


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
