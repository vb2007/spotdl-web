from datetime import datetime, timedelta, timezone

from app.models import Job, JobSourceType, JobState, Track, TrackState


def test_worker_status_defaults(authenticated_client, db_session):
    """Deliberately not admin-gated (v17) -- any authenticated user can see why a queue
    looks stalled."""
    response = authenticated_client.get("/api/worker/status")

    assert response.status_code == 200
    assert response.json() == {
        "paused": False,
        "breaker_active": False,
        "breaker_remaining_seconds": None,
        "breaker_tripped_until": None,
        "breaker_trip_count": 0,
        "consecutive_failures": 0,
        "busy": False,
    }


def test_worker_status_reports_a_running_breaker_from_the_servers_clock(authenticated_client, db_session):
    """v56 (A7): the client gets "active, N seconds left" decided on the server's clock,
    so a browser whose clock is off still counts down the real remaining time (#63)."""
    from app.services import retry

    retry.get_worker_state(db_session).breaker_tripped_until = datetime.now(timezone.utc) + timedelta(minutes=30)
    db_session.commit()

    body = authenticated_client.get("/api/worker/status").json()

    assert body["breaker_active"] is True
    assert 30 * 60 - 5 < body["breaker_remaining_seconds"] <= 30 * 60


def test_worker_status_reports_an_expired_trip_as_inactive(authenticated_client, db_session):
    """beat records an expired trip's release on its next tick (v44); until then the
    timestamp is still set, but the pause is over."""
    from app.services import retry

    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_tripped_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    worker_state.paused = True
    db_session.commit()

    body = authenticated_client.get("/api/worker/status").json()

    assert (body["breaker_active"], body["breaker_remaining_seconds"], body["paused"]) == (False, None, True)
    assert body["breaker_tripped_until"] is not None


def test_worker_busy_reflects_any_users_downloading_track(
    client, db_session, make_user, session_cookie
):
    """`busy` is global (any user's track), not scoped to the caller -- and carries no
    id/title, only the boolean (v20's "worker busy elsewhere" indicator)."""
    make_user("owner@example.com")
    other = make_user("other@example.com")
    job = Job(
        source_url="https://open.spotify.com/track/abc",
        source_type=JobSourceType.TRACK,
        state=JobState.EXPANDED,
        user_id=other.id,
    )
    db_session.add(job)
    db_session.flush()
    track = Track(
        job_id=job.id,
        spotify_track_id="abc",
        song_json={"name": "Song"},
        state=TrackState.DOWNLOADING,
    )
    db_session.add(track)
    db_session.commit()

    client.cookies.update(session_cookie("owner@example.com"))
    response = client.get("/api/worker/status")
    assert response.json()["busy"] is True

    track.state = TrackState.COMPLETED
    db_session.commit()
    assert client.get("/api/worker/status").json()["busy"] is False


def test_non_admin_cannot_pause_resume_or_release_breaker(authenticated_client, db_session):
    assert authenticated_client.post("/api/worker/pause").status_code == 403
    assert authenticated_client.post("/api/worker/resume").status_code == 403
    assert authenticated_client.post("/api/worker/breaker/release").status_code == 403


def test_admin_pause_and_resume_worker(admin_client, db_session):
    paused = admin_client.post("/api/worker/pause")
    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    assert admin_client.get("/api/worker/status").json()["paused"] is True

    resumed = admin_client.post("/api/worker/resume")
    assert resumed.status_code == 200
    assert resumed.json()["paused"] is False
    assert admin_client.get("/api/worker/status").json()["paused"] is False


def test_admin_breaker_release_starts_a_fresh_streak_but_keeps_escalation(admin_client, db_session):
    """v40.1: a release used to keep the streak, so the first failure after it re-tripped
    straight away. It now resets the streak like a trip does, and keeps trip_count so a
    new full streak still escalates."""
    from datetime import datetime, timedelta, timezone

    from app.services import retry

    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = 10
    worker_state.breaker_trip_count = 6
    worker_state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(hours=6)
    db_session.commit()

    response = admin_client.post("/api/worker/breaker/release")
    assert response.status_code == 200
    body = response.json()
    assert body["consecutive_failures"] == 0
    assert body["breaker_trip_count"] == 6

    db_session.expire_all()
    worker_state = retry.get_worker_state(db_session)
    assert worker_state.consecutive_failures == 0
    assert worker_state.breaker_trip_count == 6
    assert worker_state.breaker_tripped_until is None


def test_admin_breaker_release_records_a_manual_release_event(admin_client, db_session):
    """v44: the admin's button ends a running pause and records it as a manual release."""
    from datetime import datetime, timedelta, timezone

    from app.models import BreakerEvent, BreakerEventKind
    from app.services import retry

    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_trip_count = 1
    worker_state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(minutes=30)
    db_session.commit()

    assert admin_client.post("/api/worker/breaker/release").status_code == 200
    # Nothing left to release: a second click records nothing.
    assert admin_client.post("/api/worker/breaker/release").status_code == 200

    db_session.expire_all()
    events = db_session.query(BreakerEvent).all()
    assert [(e.kind, e.manual) for e in events] == [(BreakerEventKind.RELEASED, True)]


def test_admin_breaker_release_of_an_expired_pause_records_it_as_ended_on_its_own(
    admin_client, db_session
):
    from datetime import datetime, timedelta, timezone

    from app.models import BreakerEvent, BreakerEventKind
    from app.services import retry

    ended = datetime.now(timezone.utc) - timedelta(minutes=1)
    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_tripped_until = ended
    db_session.commit()

    assert admin_client.post("/api/worker/breaker/release").status_code == 200

    db_session.expire_all()
    events = db_session.query(BreakerEvent).all()
    assert [(e.kind, e.manual) for e in events] == [(BreakerEventKind.RELEASED, False)]
    assert events[0].occurred_at.replace(tzinfo=timezone.utc) == ended


def test_non_admin_release_writes_no_breaker_event(authenticated_client, db_session):
    from datetime import datetime, timedelta, timezone

    from app.models import BreakerEvent
    from app.services import retry

    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(minutes=30)
    db_session.commit()

    assert authenticated_client.post("/api/worker/breaker/release").status_code == 403
    assert db_session.query(BreakerEvent).count() == 0
