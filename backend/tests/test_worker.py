from app.models import Job, JobSourceType, JobState, Track, TrackState


def test_worker_status_defaults(authenticated_client, db_session):
    """Deliberately not admin-gated (v17) -- any authenticated user can see why a queue
    looks stalled."""
    response = authenticated_client.get("/api/worker/status")

    assert response.status_code == 200
    assert response.json() == {
        "paused": False,
        "breaker_tripped_until": None,
        "breaker_trip_count": 0,
        "consecutive_failures": 0,
        "busy": False,
    }


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
