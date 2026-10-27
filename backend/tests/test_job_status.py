"""v62 (F1): `job.status` events, a job's rollup status old -> new, published when it moves."""

from datetime import datetime, timezone

import pytest
import redis

from app.models import Job, JobSourceType, JobState, Track, TrackState
from app.services import events, job_status
from app.tasks import beat


class _NonClosingSession:
    """beat's db.close() would otherwise detach objects the test still asserts against."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


class _FakeRedis:
    """`SET key value EX ttl GET`, the one command job_status sends."""

    def __init__(self):
        self.values: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key, value, ex=None, get=False):
        previous = self.values.get(key)
        self.values[key] = str(value).encode()
        self.ttls[key] = ex
        return previous if get else True


@pytest.fixture()
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(events, "_get_client", lambda: fake)
    return fake


@pytest.fixture()
def published(monkeypatch):
    """Every `job.status` event, as (user_id, payload); the other events are dropped."""
    captured = []

    def publish(user_id, event):
        if event["type"] == "job.status":
            captured.append((user_id, event))

    monkeypatch.setattr(events, "publish", publish)
    return captured


def _job(db_session, owner, states, *, job_state=JobState.EXPANDED):
    job = Job(
        source_url="https://open.spotify.com/album/x",
        source_type=JobSourceType.ALBUM,
        state=job_state,
        user_id=owner.id,
    )
    db_session.add(job)
    db_session.commit()
    for index, state in enumerate(states):
        db_session.add(
            Track(job_id=job.id, spotify_track_id=f"{job.id}-{index}", song_json={"name": "Song"}, state=state)
        )
    db_session.commit()
    return job


def _set_track_states(db_session, job, *states):
    tracks = db_session.query(Track).filter(Track.job_id == job.id).order_by(Track.spotify_track_id).all()
    for track, state in zip(tracks, states, strict=True):
        track.state = state
    db_session.commit()


def test_a_created_job_says_it_was_counted_nowhere_before(db_session, make_user, fake_redis, published):
    owner = make_user("owner@example.com")
    job = _job(db_session, owner, (), job_state=JobState.EXPANDING)

    job_status.publish_change(db_session, owner.id, job.id, created=True)

    assert published == [
        (owner.id, {"type": "job.status", "job_id": str(job.id), "status": "expanding", "archived": False, "prev_status": None})
    ]
    assert fake_redis.ttls[f"spotdl:job-status:{job.id}"] == job_status.KEY_TTL_SECONDS


def test_each_move_names_the_status_it_left(db_session, make_user, fake_redis, published):
    """The chain: each event's prev_status is the previous one's status."""
    owner = make_user("owner@example.com")
    job = _job(db_session, owner, (), job_state=JobState.EXPANDING)
    job_status.publish_change(db_session, owner.id, job.id, created=True)
    db_session.add(Track(job_id=job.id, spotify_track_id="t1", song_json={}, state=TrackState.PENDING))
    db_session.add(Track(job_id=job.id, spotify_track_id="t2", song_json={}, state=TrackState.PENDING))
    job.state = JobState.EXPANDED
    db_session.commit()
    job_status.publish_change(db_session, owner.id, job.id)
    _set_track_states(db_session, job, TrackState.COMPLETED, TrackState.WAITING)
    job_status.publish_change(db_session, owner.id, job.id)
    _set_track_states(db_session, job, TrackState.COMPLETED, TrackState.LOOKUP_FAILED)
    job_status.publish_change(db_session, owner.id, job.id)

    assert [(e["prev_status"], e["status"]) for _, e in published] == [
        (None, "expanding"),
        ("expanding", "active"),
        ("active", "waiting"),
        ("waiting", "settled:partial"),
    ]


def test_nothing_is_published_while_the_status_stays(db_session, make_user, fake_redis, published):
    owner = make_user("owner@example.com")
    job = _job(db_session, owner, (TrackState.QUEUED, TrackState.PENDING))
    job_status.publish_change(db_session, owner.id, job.id)
    published.clear()

    _set_track_states(db_session, job, TrackState.COMPLETED, TrackState.DOWNLOADING)
    job_status.publish_change(db_session, owner.id, job.id)

    assert published == []


def test_a_job_with_no_recorded_status_moves_with_no_prev_status(db_session, make_user, fake_redis, published):
    """A job from before v62 (or an expired key): the browser can't know what it left, so
    the key is absent, not null (null means a new job)."""
    owner = make_user("owner@example.com")
    job = _job(db_session, owner, (TrackState.COMPLETED,))

    job_status.publish_change(db_session, owner.id, job.id)

    assert published == [
        (owner.id, {"type": "job.status", "job_id": str(job.id), "status": "settled:complete", "archived": False})
    ]


def test_the_event_says_whether_the_job_is_archived(db_session, make_user, fake_redis, published):
    owner = make_user("owner@example.com")
    job = _job(db_session, owner, (TrackState.WAITING,))
    job.archived_at = datetime.now(timezone.utc)
    db_session.commit()

    job_status.publish_change(db_session, owner.id, job.id)

    assert published[0][1]["archived"] is True


def test_it_ends_the_read_transaction(db_session, make_user, fake_redis, published):
    """A caller that goes on to wait (a download) must not hold an open transaction."""
    owner = make_user("owner@example.com")
    job = _job(db_session, owner, (TrackState.PENDING,))
    db_session.expire_all()

    job_status.publish_change(db_session, owner.id, job.id)

    assert not db_session.in_transaction()


def test_pending_changes_are_never_committed_by_it(db_session, make_user, fake_redis, published):
    owner = make_user("owner@example.com")
    job = _job(db_session, owner, (TrackState.PENDING,))
    job.priority = 5

    job_status.publish_change(db_session, owner.id, job.id)

    assert published == []
    assert job in db_session.dirty


def test_a_redis_failure_loses_only_the_event(db_session, make_user, published, monkeypatch):
    class _Down:
        def set(self, *args, **kwargs):
            raise redis.ConnectionError("down")

    monkeypatch.setattr(events, "_get_client", lambda: _Down())
    owner = make_user("owner@example.com")
    job = _job(db_session, owner, (TrackState.PENDING,))

    job_status.publish_change(db_session, owner.id, job.id)

    assert published == []


def test_it_never_raises(db_session, make_user, fake_redis, published, monkeypatch):
    """A completion's call sits inside the download's own try: a raise would read as the
    download failing."""
    owner = make_user("owner@example.com")
    job = _job(db_session, owner, (TrackState.PENDING,))
    monkeypatch.setattr(job_status, "derive_rollup", lambda *a: 1 / 0)

    job_status.publish_change(db_session, owner.id, job.id)

    assert published == []


def test_a_cancel_publishes_the_move_to_the_owner(authenticated_client, db_session, owner, fake_redis, published):
    job = _job(db_session, owner, (TrackState.WAITING, TrackState.COMPLETED))
    job_status.publish_change(db_session, owner.id, job.id)
    published.clear()

    assert authenticated_client.delete(f"/api/jobs/{job.id}").status_code == 200

    assert [(user_id, e["prev_status"], e["status"]) for user_id, e in published] == [
        (owner.id, "waiting", "cancelled")
    ]


def test_create_publishes_the_new_jobs_first_status(authenticated_client, db_session, owner, fake_redis, published, monkeypatch):
    from app.routers import jobs as jobs_router

    monkeypatch.setattr(jobs_router.expand_job, "delay", lambda *a: None)

    response = authenticated_client.post("/api/jobs", json={"url": "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"})

    assert response.status_code == 201
    assert published == [
        (
            owner.id,
            {"type": "job.status", "job_id": response.json()["id"], "status": "expanding", "archived": False, "prev_status": None},
        )
    ]


def test_retry_now_of_a_not_found_track_reopens_its_job(authenticated_client, db_session, owner, fake_redis, published):
    job = _job(db_session, owner, (TrackState.LOOKUP_FAILED, TrackState.COMPLETED))
    job_status.publish_change(db_session, owner.id, job.id)
    published.clear()
    track = db_session.query(Track).filter(Track.job_id == job.id, Track.state == TrackState.LOOKUP_FAILED).one()

    assert authenticated_client.post(f"/api/tracks/{track.id}/retry").status_code == 200

    assert [(e["prev_status"], e["status"]) for _, e in published] == [("settled:partial", "waiting")]


def test_beat_checks_each_dispatched_job_once(db_session, make_user, fake_redis, published, monkeypatch):
    """Two due tracks of one job: one status check, one event (waiting -> active)."""
    owner = make_user("owner@example.com")
    job = _job(db_session, owner, (TrackState.WAITING, TrackState.WAITING))
    for track in db_session.query(Track).filter(Track.job_id == job.id):
        track.scheduled_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db_session.commit()
    job_status.publish_change(db_session, owner.id, job.id)
    published.clear()
    checks = []
    real = job_status.publish_change
    monkeypatch.setattr(job_status, "publish_change", lambda *a, **k: (checks.append(a[2]), real(*a, **k)))
    monkeypatch.setattr(beat, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(beat.download_track, "delay", lambda *a: None)
    monkeypatch.setattr(beat.alerts, "record_beat_heartbeat", lambda: None)

    beat.dispatch_due_tracks()

    assert checks == [job.id]
    assert [(e["prev_status"], e["status"]) for _, e in published] == [("waiting", "active")]
