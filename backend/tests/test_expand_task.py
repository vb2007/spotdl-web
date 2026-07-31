import uuid

from app.models import Job, JobSourceType, JobState, Track, TrackState
from app.services import events, expansion
from app.tasks import expand as expand_task


def _capture_job_events(monkeypatch):
    captured = []
    monkeypatch.setattr(
        events, "publish_job_event", lambda *args, **kwargs: captured.append((args, kwargs))
    )
    return captured


class _FakeSong:
    def __init__(self, song_id, data):
        self.song_id = song_id
        self.json = data


class _NonClosingSession:
    """Wraps db_session so expand_job's db.close() doesn't detach objects the test
    still needs to assert against — the fixture handles real teardown instead."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


def _stub_download_track(monkeypatch):
    enqueued = []
    monkeypatch.setattr(expand_task.download_track, "delay", lambda track_id: enqueued.append(track_id))
    return enqueued


def test_expand_job_success_inserts_pending_tracks(db_session, monkeypatch):
    job = Job(source_url="https://open.spotify.com/track/abc", source_type=JobSourceType.TRACK)
    db_session.add(job)
    db_session.commit()

    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(
        expansion, "expand", lambda url: [_FakeSong("abc123", {"name": "Song A"})]
    )
    enqueued = _stub_download_track(monkeypatch)
    published = _capture_job_events(monkeypatch)

    expand_task.expand_job(str(job.id))

    updated = db_session.get(Job, job.id)
    assert updated.state == JobState.EXPANDED
    assert updated.error is None

    tracks = db_session.query(Track).filter(Track.job_id == job.id).all()
    assert len(tracks) == 1
    assert tracks[0].spotify_track_id == "abc123"
    assert tracks[0].song_json == {"name": "Song A"}
    assert tracks[0].state == TrackState.PENDING
    assert enqueued == [str(tracks[0].id)]

    states = [args[1] for args, _ in published]
    assert states == ["expanding", "expanded"]


def test_expand_job_failure_marks_job_failed_with_error(db_session, monkeypatch):
    job = Job(source_url="garbage", source_type=JobSourceType.SEARCH)
    db_session.add(job)
    db_session.commit()

    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))

    def fake_expand(url):
        raise ValueError("boom")

    monkeypatch.setattr(expansion, "expand", fake_expand)
    published = _capture_job_events(monkeypatch)

    expand_task.expand_job(str(job.id))

    updated = db_session.get(Job, job.id)
    assert updated.state == JobState.FAILED
    assert updated.error == "boom"
    assert db_session.query(Track).filter(Track.job_id == job.id).count() == 0

    states = [args[1] for args, _ in published]
    assert states == ["expanding", "failed"]
    assert published[-1][1]["error"] == "boom"


def test_expand_job_db_error_during_insert_marks_job_failed(db_session, monkeypatch):
    job = Job(source_url="https://open.spotify.com/track/abc", source_type=JobSourceType.TRACK)
    db_session.add(job)
    db_session.commit()

    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    # spotify_track_id is NOT NULL — a song missing it (e.g. a malformed list-expansion
    # entry) must fail the job cleanly instead of crashing the task at commit() time.
    monkeypatch.setattr(
        expansion, "expand", lambda url: [_FakeSong(None, {"name": "Bad Song"})]
    )

    expand_task.expand_job(str(job.id))

    updated = db_session.get(Job, job.id)
    assert updated.state == JobState.FAILED
    assert updated.error
    assert db_session.query(Track).filter(Track.job_id == job.id).count() == 0


def test_expand_job_unknown_job_is_a_noop(db_session, monkeypatch):
    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))

    expand_task.expand_job(str(uuid.uuid4()))
