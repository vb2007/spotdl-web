import uuid
from datetime import datetime, timedelta, timezone

from app.models import Job, JobSourceType, Track, TrackState
from app.routers import auth
from app.services import retry


def _aware(dt: datetime) -> datetime:
    # SQLite (used for these in-process tests, see v02/v03 gotchas) round-trips a
    # timestamptz column as a naive datetime; a no-op against real Postgres/psycopg.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _login(client, monkeypatch):
    async def fake_login(email, password):
        return True

    monkeypatch.setattr(auth.upstream_auth, "login", fake_login)
    client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "x"})


def _make_track(db_session, *, state, scheduled_at=None, attempt_count=0):
    job = Job(source_url="https://open.spotify.com/track/abc", source_type=JobSourceType.TRACK)
    db_session.add(job)
    db_session.commit()

    track = Track(
        job_id=job.id,
        spotify_track_id="abc123",
        song_json={"name": "Song A"},
        state=state,
        scheduled_at=scheduled_at,
        attempt_count=attempt_count,
    )
    db_session.add(track)
    db_session.commit()
    return track


def test_cancel_track_marks_cancelled_and_clears_schedule(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    track = _make_track(
        db_session, state=TrackState.WAITING, scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )

    response = client.delete(f"/api/tracks/{track.id}")

    assert response.status_code == 200
    assert response.json()["state"] == "cancelled"
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.CANCELLED
    assert updated.scheduled_at is None


def test_cancel_track_is_a_noop_on_terminal_states(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    track = _make_track(db_session, state=TrackState.COMPLETED)

    response = client.delete(f"/api/tracks/{track.id}")

    assert response.status_code == 200
    assert response.json()["state"] == "completed"
    assert db_session.get(Track, track.id).state == TrackState.COMPLETED


def test_cancel_unknown_track_returns_404(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    assert client.delete(f"/api/tracks/{uuid.uuid4()}").status_code == 404


def test_retry_track_resets_schedule_and_dispatches_when_breaker_clear(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    track = _make_track(
        db_session,
        state=TrackState.WAITING,
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=12),
        attempt_count=2,
    )

    response = client.post(f"/api/tracks/{track.id}/retry")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "waiting"
    assert body["breaker_held"] is False
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING
    assert _aware(updated.scheduled_at) <= datetime.now(timezone.utc) + timedelta(seconds=5)


def test_retry_track_flips_lookup_failed_back_to_waiting(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    track = _make_track(db_session, state=TrackState.LOOKUP_FAILED, scheduled_at=None)

    response = client.post(f"/api/tracks/{track.id}/retry")

    assert response.status_code == 200
    assert response.json()["state"] == "waiting"
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING
    assert updated.scheduled_at is not None


def test_retry_track_held_while_breaker_tripped(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    track = _make_track(db_session, state=TrackState.WAITING)

    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.commit()

    response = client.post(f"/api/tracks/{track.id}/retry")

    assert response.status_code == 200
    body = response.json()
    assert body["breaker_held"] is True
    # scheduled_at is still reset to now -- the breaker gate lives in dispatch_due_tracks,
    # not here -- so a retry immediately becomes eligible the instant the breaker clears.
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING


def test_retry_track_rejects_non_retryable_states(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    track = _make_track(db_session, state=TrackState.DOWNLOADING)

    response = client.post(f"/api/tracks/{track.id}/retry")

    assert response.status_code == 409


def test_retry_unknown_track_returns_404(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    assert client.post(f"/api/tracks/{uuid.uuid4()}/retry").status_code == 404


def test_tracks_endpoints_require_session(client):
    assert client.delete(f"/api/tracks/{uuid.uuid4()}").status_code == 401
    assert client.post(f"/api/tracks/{uuid.uuid4()}/retry").status_code == 401
    assert client.get("/api/tracks").status_code == 401


def test_list_tracks_returns_every_track_across_every_job_in_one_call(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    a = _make_track(db_session, state=TrackState.WAITING)
    b = _make_track(db_session, state=TrackState.COMPLETED)

    response = client.get("/api/tracks")

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert ids == {str(a.id), str(b.id)}
