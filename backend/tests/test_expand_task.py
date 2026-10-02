import uuid

from app.models import Job, JobSourceType, JobState, Track, TrackState, User
from app.services import events, expansion
from app.tasks import expand as expand_task


def _owner(db_session) -> User:
    user = db_session.query(User).filter(User.email == "owner@example.com").one_or_none()
    if user is None:
        user = User(email="owner@example.com", is_admin=False)
        db_session.add(user)
        db_session.flush()
    return user


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
    job = Job(
        source_url="https://open.spotify.com/track/abc",
        source_type=JobSourceType.TRACK,
        user_id=_owner(db_session).id,
    )
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

    states = [args[2] for args, _ in published]
    assert states == ["expanding", "expanded"]


def test_expand_job_failure_marks_job_failed_with_error(db_session, monkeypatch):
    job = Job(source_url="garbage", source_type=JobSourceType.SEARCH, user_id=_owner(db_session).id)
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

    states = [args[2] for args, _ in published]
    assert states == ["expanding", "failed"]
    assert published[-1][1]["error"] == "boom"


def test_expand_job_db_error_during_insert_marks_job_failed(db_session, monkeypatch):
    job = Job(
        source_url="https://open.spotify.com/track/abc",
        source_type=JobSourceType.TRACK,
        user_id=_owner(db_session).id,
    )
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


def test_expand_job_never_dispatches_when_cancelled_mid_expansion(db_session, monkeypatch):
    job = Job(
        source_url="https://open.spotify.com/track/abc",
        source_type=JobSourceType.TRACK,
        user_id=_owner(db_session).id,
    )
    db_session.add(job)
    db_session.commit()

    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    enqueued = _stub_download_track(monkeypatch)
    published_tracks = []
    monkeypatch.setattr(
        events, "publish_track_event", lambda *args, **kwargs: published_tracks.append(args)
    )

    def fake_expand(url):
        # A `DELETE /api/jobs/{id}` landing on a separate request/session while this
        # (multi-second, real) Spotify round trip was still running.
        db_session.query(Job).filter(Job.id == job.id).update({"state": JobState.CANCELLED})
        db_session.commit()
        return [_FakeSong("abc123", {"name": "Song A"})]

    monkeypatch.setattr(expansion, "expand", fake_expand)

    expand_task.expand_job(str(job.id))

    updated = db_session.get(Job, job.id)
    assert updated.state == JobState.CANCELLED

    tracks = db_session.query(Track).filter(Track.job_id == job.id).all()
    assert len(tracks) == 1
    assert tracks[0].state == TrackState.CANCELLED

    assert enqueued == []
    assert published_tracks == [(_owner(db_session).id, tracks[0].id, tracks[0].job_id, "cancelled")]


def test_expand_job_unknown_job_is_a_noop(db_session, monkeypatch):
    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))

    expand_task.expand_job(str(uuid.uuid4()))


def test_expand_job_failure_after_a_mid_expansion_cancel_stays_cancelled(db_session, monkeypatch):
    job = Job(
        source_url="https://open.spotify.com/artist/abc",
        source_type=JobSourceType.ARTIST,
        user_id=_owner(db_session).id,
    )
    db_session.add(job)
    db_session.commit()

    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    published = _capture_job_events(monkeypatch)

    def fake_expand(url):
        db_session.query(Job).filter(Job.id == job.id).update({"state": JobState.CANCELLED})
        db_session.commit()
        raise KeyError("discography")

    monkeypatch.setattr(expansion, "expand", fake_expand)

    expand_task.expand_job(str(job.id))

    updated = db_session.get(Job, job.id)
    assert updated.state == JobState.CANCELLED
    assert updated.error is None
    # Only the task's own opening `expanding` echo -- never a `failed` one.
    assert [args[2] for args, _ in published] == ["expanding"]


def test_expand_job_skips_a_job_cancelled_before_the_task_ran(db_session, monkeypatch):
    job = Job(
        source_url="https://open.spotify.com/artist/abc",
        source_type=JobSourceType.ARTIST,
        user_id=_owner(db_session).id,
        state=JobState.CANCELLED,
    )
    db_session.add(job)
    db_session.commit()

    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    published = _capture_job_events(monkeypatch)
    calls = []
    monkeypatch.setattr(expansion, "expand", lambda url: calls.append(url) or [])

    expand_task.expand_job(str(job.id))

    assert calls == []
    assert published == []
    assert db_session.get(Job, job.id).state == JobState.CANCELLED


def test_long_running_tasks_route_to_the_expand_queue_not_meta():
    from app.tasks.celery_app import celery_app

    def queue_for(name):
        return celery_app.amqp.router.route({}, name)["queue"].name

    assert queue_for("app.tasks.expand.expand_job") == "expand"
    assert queue_for("app.tasks.library.sort_library") == "expand"
    assert queue_for("app.tasks.beat.dispatch_due_tracks") == "meta"
    assert queue_for("app.tasks.beat.archive_due_jobs") == "meta"
    assert queue_for("app.tasks.download.download_track") == "downloads"


def test_expand_job_redelivered_after_expanded_enqueues_only_pending_tracks(db_session, monkeypatch):
    """A run that committed EXPANDED then died mid-enqueue is redelivered (acks_late): it
    must not re-expand (duplicate tracks) nor skip (pending tracks stranded forever)."""
    job = Job(
        source_url="https://open.spotify.com/album/abc",
        source_type=JobSourceType.ALBUM,
        user_id=_owner(db_session).id,
        state=JobState.EXPANDED,
    )
    db_session.add(job)
    db_session.flush()
    stranded = Track(job_id=job.id, spotify_track_id="a", song_json={"name": "A"})
    done = Track(job_id=job.id, spotify_track_id="b", song_json={"name": "B"}, state=TrackState.COMPLETED)
    db_session.add_all([stranded, done])
    db_session.commit()

    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    calls = []
    monkeypatch.setattr(expansion, "expand", lambda url: calls.append(url) or [])
    enqueued = _stub_download_track(monkeypatch)
    published = _capture_job_events(monkeypatch)

    expand_task.expand_job(str(job.id))

    assert calls == []
    assert enqueued == [str(stranded.id)]
    assert published == []
    assert db_session.query(Track).filter(Track.job_id == job.id).count() == 2


def test_expand_job_discards_its_tracks_when_another_run_already_expanded_the_job(db_session, monkeypatch):
    job = Job(
        source_url="https://open.spotify.com/album/abc",
        source_type=JobSourceType.ALBUM,
        user_id=_owner(db_session).id,
    )
    db_session.add(job)
    db_session.commit()
    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    enqueued = _stub_download_track(monkeypatch)
    published = _capture_job_events(monkeypatch)

    def fake_expand(url):
        # An overlapping run of the same job (a redelivery) finished first.
        db_session.query(Job).filter(Job.id == job.id).update({"state": JobState.EXPANDED})
        db_session.commit()
        return [_FakeSong("abc123", {"name": "Song A"})]

    monkeypatch.setattr(expansion, "expand", fake_expand)

    expand_task.expand_job(str(job.id))

    assert db_session.query(Track).filter(Track.job_id == job.id).count() == 0
    assert enqueued == []
    assert [args[2] for args, _ in published] == ["expanding"]


def test_expand_job_failure_after_the_expanded_commit_still_enqueues_the_tracks(db_session, monkeypatch):
    job = Job(
        source_url="https://open.spotify.com/album/abc",
        source_type=JobSourceType.ALBUM,
        user_id=_owner(db_session).id,
    )
    db_session.add(job)
    db_session.commit()
    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(expansion, "expand", lambda url: [_FakeSong("abc123", {"name": "Song A"})])
    enqueued = _stub_download_track(monkeypatch)

    def publish(user_id, job_id, state, **kwargs):
        if state == "expanded":
            raise RuntimeError("something after the commit broke")

    monkeypatch.setattr(events, "publish_job_event", publish)

    expand_task.expand_job(str(job.id))

    assert db_session.get(Job, job.id).state == JobState.EXPANDED
    tracks = db_session.query(Track).filter(Track.job_id == job.id).all()
    assert enqueued == [str(t.id) for t in tracks] and len(tracks) == 1


def test_expand_job_overlapping_run_after_expand_then_cancel_adds_no_second_track_set(db_session, monkeypatch):
    job = Job(
        source_url="https://open.spotify.com/album/abc",
        source_type=JobSourceType.ALBUM,
        user_id=_owner(db_session).id,
    )
    db_session.add(job)
    db_session.commit()
    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    enqueued = _stub_download_track(monkeypatch)
    monkeypatch.setattr(events, "publish_track_event", lambda *a, **k: None)
    _capture_job_events(monkeypatch)

    def fake_expand(url):
        # Run A finished first (EXPANDED + its track), then the user cancelled.
        db_session.add(
            Track(job_id=job.id, spotify_track_id="abc123", song_json={"name": "A"}, state=TrackState.CANCELLED)
        )
        db_session.query(Job).filter(Job.id == job.id).update({"state": JobState.CANCELLED})
        db_session.commit()
        return [_FakeSong("abc123", {"name": "Song A"})]

    monkeypatch.setattr(expansion, "expand", fake_expand)

    expand_task.expand_job(str(job.id))

    assert db_session.query(Track).filter(Track.job_id == job.id).count() == 1
    assert enqueued == []
