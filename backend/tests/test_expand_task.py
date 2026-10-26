import uuid

from concurrency import Gate, Thread, blocked_or_done
from sqlalchemy import event, text

from app.models import Job, JobSourceType, JobState, Track, TrackState, User
from app.routers import jobs as jobs_router
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


# --- v51: the v34.1 cancel race, on two real connections -------------------------------
# The tests above simulate the cancel inside expand_job's own session. These run the real
# cancel_job and the real expand_job on sessions of their own (conftest's committed_db), in
# both orders the race allows.


def _committed_expanding_job(committed_db) -> tuple[uuid.UUID, uuid.UUID]:
    with committed_db() as db:
        user = User(email="owner@example.com", is_admin=False)
        db.add(user)
        db.flush()
        job = Job(
            source_url="https://open.spotify.com/album/abc",
            source_type=JobSourceType.ALBUM,
            user_id=user.id,
        )
        db.add(job)
        db.commit()
        return job.id, user.id


def _real_sessions(committed_db, monkeypatch) -> list[str]:
    monkeypatch.setattr(expand_task, "SessionLocal", committed_db)
    monkeypatch.setattr(events, "publish_job_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(events, "publish_track_event", lambda *args, **kwargs: None)
    return _stub_download_track(monkeypatch)


def _cancel(committed_db, job_id, user_id) -> None:
    with committed_db() as db:
        jobs_router.cancel_job(job_id, db=db, user=db.get(User, user_id))


def _assert_cancelled_with_its_tracks(committed_db, job_id) -> None:
    with committed_db() as db:
        assert db.get(Job, job_id).state == JobState.CANCELLED
        states = [t.state for t in db.query(Track).filter(Track.job_id == job_id).all()]
        assert states == [TrackState.CANCELLED, TrackState.CANCELLED]


def test_a_cancel_committed_mid_expansion_stays_cancelled_on_real_connections(committed_db, monkeypatch):
    """The cancel lands while expansion's Spotify round trip runs. Guard: expand_job's
    conditional UPDATE (WHERE state = expanding), which then matches no row."""
    job_id, user_id = _committed_expanding_job(committed_db)
    enqueued = _real_sessions(committed_db, monkeypatch)
    gate = Gate("expansion's Spotify round trip")
    songs = [_FakeSong("abc123", {"name": "Song A"}), _FakeSong("def456", {"name": "Song B"})]
    monkeypatch.setattr(expansion, "expand", gate.wrap(lambda url: songs))

    expander = Thread(expand_task.expand_job, str(job_id), name="expand_job")
    gate.wait_reached()
    _cancel(committed_db, job_id, user_id)
    gate.open()
    expander.join()

    _assert_cancelled_with_its_tracks(committed_db, job_id)
    assert enqueued == []


def test_an_expanded_commit_during_a_cancel_waits_for_it_on_real_connections(committed_db, monkeypatch):
    """expand_job's EXPANDED commit lands between cancel_job's track query and its commit.
    Guard: cancel_job's row lock, which holds the commit off until the cancel has committed."""
    job_id, user_id = _committed_expanding_job(committed_db)
    enqueued = _real_sessions(committed_db, monkeypatch)
    songs = [_FakeSong("abc123", {"name": "Song A"}), _FakeSong("def456", {"name": "Song B"})]
    monkeypatch.setattr(expansion, "expand", lambda url: songs)
    gate = Gate("cancel_job, tracks read, before its commit")

    def cancel():
        with committed_db() as db:
            event.listen(db, "before_commit", gate, once=True)
            jobs_router.cancel_job(job_id, db=db, user=db.get(User, user_id))

    canceller = Thread(cancel, name="cancel_job")
    gate.wait_reached()
    expander = Thread(expand_task.expand_job, str(job_id), name="expand_job")
    held_off = blocked_or_done(expander)
    gate.open()
    canceller.join()
    expander.join()

    _assert_cancelled_with_its_tracks(committed_db, job_id)
    assert enqueued == []
    assert held_off == "blocked"


# --- v56 (E1): the outbox marker. A broker error mid-enqueue no longer strands tracks ------


class _BrokerDown(Exception):
    """Stands in for kombu's OperationalError: the broker refused a send."""


class _Broker:
    """One stub for `download_track.delay`, which expand_job and beat share (one task
    object): records who sent each track, and can fail or die on expand_job's n-th send."""

    def __init__(self, monkeypatch, *, fail_at: int | None = None, error: BaseException | None = None):
        self.sender = "expand_job"
        self.sent: list[tuple[str, str]] = []
        self._fail_at, self._error = fail_at, error
        self.during_expand = None
        monkeypatch.setattr(expand_task.download_track, "delay", self.delay)

    def delay(self, track_id: str) -> None:
        if self.sender == "expand_job" and self._fail_at is not None and len(self.sent) == self._fail_at:
            raise self._error
        self.sent.append((self.sender, track_id))
        if self.sender == "expand_job" and self.during_expand is not None:
            self.during_expand(len(self.sent))

    def by(self, sender: str) -> list[str]:
        return [track_id for who, track_id in self.sent if who == sender]


def _beat(committed_db, monkeypatch, broker: _Broker):
    from app.tasks import beat as beat_task

    monkeypatch.setattr(beat_task, "SessionLocal", committed_db)
    monkeypatch.setattr(beat_task.alerts, "record_beat_heartbeat", lambda: None)

    def tick() -> None:
        previous, broker.sender = broker.sender, "beat"
        try:
            beat_task.dispatch_due_tracks()
        finally:
            broker.sender = previous

    return tick


def _songs(n: int) -> list[_FakeSong]:
    return [_FakeSong(f"song{i}", {"name": f"Song {i}"}) for i in range(n)]


def _track_ids_in_order(committed_db, job_id) -> list[str]:
    with committed_db() as db:
        tracks = db.query(Track).filter(Track.job_id == job_id).all()
        by_song = {t.spotify_track_id: str(t.id) for t in tracks}
        return [by_song[f"song{i}"] for i in range(len(tracks))]


def test_expand_job_sends_each_track_once_and_beat_mid_send_sends_none(committed_db, monkeypatch):
    """The happy path, with a beat tick landing while expand_job is still sending: the
    run's claim (the marker leased ahead) keeps beat off every one of its tracks, so each
    is sent exactly once, in album order, and none is left due afterwards."""
    job_id, _ = _committed_expanding_job(committed_db)
    _real_sessions(committed_db, monkeypatch)
    broker = _Broker(monkeypatch)
    tick = _beat(committed_db, monkeypatch, broker)
    monkeypatch.setattr(expansion, "expand", lambda url: _songs(5))
    broker.during_expand = lambda n: tick() if n == 2 else None  # a tick between two sends

    expand_task.expand_job(str(job_id))
    tick()  # and one after

    assert broker.by("expand_job") == _track_ids_in_order(committed_db, job_id)
    assert broker.by("beat") == []
    with committed_db() as db:
        rows = db.query(Track.state, Track.scheduled_at).filter(Track.job_id == job_id).all()
        assert rows == [(TrackState.PENDING, None)] * 5


def test_a_broker_error_mid_enqueue_leaves_the_rest_to_beats_next_tick(committed_db, monkeypatch):
    """The v34.1 gap (E1): the broker fails on the 3rd of 5 sends. Before v56 the task
    failed, was acked, and tracks 3-5 stayed `pending` forever. Now beat's next tick sends
    exactly those three, so every track is sent once and none twice."""
    job_id, _ = _committed_expanding_job(committed_db)
    _real_sessions(committed_db, monkeypatch)
    broker = _Broker(monkeypatch, fail_at=2, error=_BrokerDown("Error 111 connecting to redis:6379."))
    tick = _beat(committed_db, monkeypatch, broker)
    monkeypatch.setattr(expansion, "expand", lambda url: _songs(5))

    expand_task.expand_job(str(job_id))  # doesn't raise: the rest is beat's
    ordered = _track_ids_in_order(committed_db, job_id)
    assert broker.by("expand_job") == ordered[:2]
    with committed_db() as db:  # beat's order must come from the marker, not the heap
        db.execute(text("UPDATE tracks SET song_json = song_json WHERE spotify_track_id IN ('song2', 'song3')"))
        db.commit()
        due = (
            db.query(Track.spotify_track_id)
            .filter(Track.job_id == job_id, Track.scheduled_at.is_not(None))
            .order_by(Track.scheduled_at)
            .all()
        )
        assert [song for (song,) in due] == ["song2", "song3", "song4"]

    tick()
    tick()

    assert broker.by("beat") == ordered[2:]  # in album order, and only once
    assert sorted(track_id for _, track_id in broker.sent) == sorted(ordered)
    with committed_db() as db:
        assert db.get(Job, job_id).state == JobState.EXPANDED
        states = sorted(t.state.value for t in db.query(Track).filter(Track.job_id == job_id))
        assert states == ["pending", "pending", "queued", "queued", "queued"]


def test_a_run_that_dies_after_its_claim_leaves_the_tracks_to_beat_once_its_lease_runs_out(
    committed_db, monkeypatch
):
    """The worker is killed between the claim and the sends (nothing in the task can
    catch that): the tracks stay leased, beat leaves them alone until the lease runs out,
    then sends them."""
    from datetime import timedelta

    job_id, _ = _committed_expanding_job(committed_db)
    _real_sessions(committed_db, monkeypatch)
    broker = _Broker(monkeypatch, fail_at=0, error=SystemExit("worker killed"))
    tick = _beat(committed_db, monkeypatch, broker)
    monkeypatch.setattr(expansion, "expand", lambda url: _songs(2))

    try:
        expand_task.expand_job(str(job_id))
    except SystemExit:
        pass
    tick()
    assert broker.sent == []

    with committed_db() as db:  # the lease runs out
        for track in db.query(Track).filter(Track.job_id == job_id):
            track.scheduled_at -= expand_task.DISPATCH_LEASE + timedelta(seconds=1)
        db.commit()
    tick()

    assert broker.by("beat") == _track_ids_in_order(committed_db, job_id)
