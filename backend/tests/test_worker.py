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
    }


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
