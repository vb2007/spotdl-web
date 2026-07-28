import uuid

from app.models import Job, JobSourceType, JobState, Track, TrackState
from app.services import expansion
from app.tasks import expand as expand_task


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


def test_expand_job_success_inserts_pending_tracks(db_session, monkeypatch):
    job = Job(source_url="https://open.spotify.com/track/abc", source_type=JobSourceType.TRACK)
    db_session.add(job)
    db_session.commit()

    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(
        expansion, "expand", lambda url: [_FakeSong("abc123", {"name": "Song A"})]
    )

    expand_task.expand_job(str(job.id))

    updated = db_session.get(Job, job.id)
    assert updated.state == JobState.EXPANDED
    assert updated.error is None

    tracks = db_session.query(Track).filter(Track.job_id == job.id).all()
    assert len(tracks) == 1
    assert tracks[0].spotify_track_id == "abc123"
    assert tracks[0].song_json == {"name": "Song A"}
    assert tracks[0].state == TrackState.PENDING


def test_expand_job_failure_marks_job_failed_with_error(db_session, monkeypatch):
    job = Job(source_url="garbage", source_type=JobSourceType.SEARCH)
    db_session.add(job)
    db_session.commit()

    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))

    def fake_expand(url):
        raise ValueError("boom")

    monkeypatch.setattr(expansion, "expand", fake_expand)

    expand_task.expand_job(str(job.id))

    updated = db_session.get(Job, job.id)
    assert updated.state == JobState.FAILED
    assert updated.error == "boom"
    assert db_session.query(Track).filter(Track.job_id == job.id).count() == 0


def test_expand_job_unknown_job_is_a_noop(db_session, monkeypatch):
    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))

    expand_task.expand_job(str(uuid.uuid4()))
