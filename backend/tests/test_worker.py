from datetime import datetime, timedelta, timezone

from app.routers import auth
from app.services import retry


def _login(client, monkeypatch):
    async def fake_login(email, password):
        return True

    monkeypatch.setattr(auth.upstream_auth, "login", fake_login)
    client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "x"})


def test_worker_status_defaults(client, db_session, monkeypatch):
    _login(client, monkeypatch)

    response = client.get("/api/worker/status")

    assert response.status_code == 200
    assert response.json() == {
        "paused": False,
        "breaker_tripped_until": None,
        "breaker_trip_count": 0,
        "consecutive_failures": 0,
    }


def test_pause_and_resume_worker(client, db_session, monkeypatch):
    _login(client, monkeypatch)

    paused = client.post("/api/worker/pause")
    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    assert client.get("/api/worker/status").json()["paused"] is True

    resumed = client.post("/api/worker/resume")
    assert resumed.status_code == 200
    assert resumed.json()["paused"] is False
    assert client.get("/api/worker/status").json()["paused"] is False


def test_release_breaker_clears_countdown_without_resetting_trip_count(client, db_session, monkeypatch):
    _login(client, monkeypatch)

    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(hours=2)
    worker_state.breaker_trip_count = 2
    worker_state.consecutive_failures = 5
    db_session.commit()

    response = client.post("/api/worker/breaker/release")

    assert response.status_code == 200
    body = response.json()
    assert body["breaker_tripped_until"] is None
    # A manual release is not an earned recovery -- these stay as they were, so the next
    # failure re-trips at the *next* escalation step rather than back at 30m.
    assert body["breaker_trip_count"] == 2
    assert body["consecutive_failures"] == 5


def test_worker_endpoints_require_session(client):
    assert client.get("/api/worker/status").status_code == 401
    assert client.post("/api/worker/pause").status_code == 401
    assert client.post("/api/worker/resume").status_code == 401
    assert client.post("/api/worker/breaker/release").status_code == 401
