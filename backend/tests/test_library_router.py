from app.models import LibrarySortState
from app.routers import library as library_router


def _stub_sort_library(monkeypatch):
    enqueued = []
    monkeypatch.setattr(
        library_router.sort_library, "delay", lambda admin_id: enqueued.append(admin_id)
    )
    return enqueued


def test_sort_status_seeds_an_idle_run(admin_client, db_session):
    response = admin_client.get("/api/library/sort/status")

    assert response.status_code == 200
    assert response.json() == {
        "state": "idle",
        "started_at": None,
        "finished_at": None,
        "total": 0,
        "processed": 0,
        "moved": 0,
        "skipped_present": 0,
        "quarantined": 0,
        "errors": [],
    }


def test_start_sort_enqueues_the_task_and_marks_running(admin_client, db_session, admin_user, monkeypatch):
    enqueued = _stub_sort_library(monkeypatch)

    response = admin_client.post("/api/library/sort")

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "running"
    assert body["started_at"] is not None
    assert enqueued == [str(admin_user.id)]

    status = admin_client.get("/api/library/sort/status")
    assert status.json()["state"] == "running"


def test_start_sort_rejects_a_second_concurrent_sweep(admin_client, db_session, monkeypatch):
    _stub_sort_library(monkeypatch)
    first = admin_client.post("/api/library/sort")
    assert first.status_code == 202

    second = admin_client.post("/api/library/sort")

    assert second.status_code == 409


def test_start_sort_allowed_again_once_previous_run_is_idle(admin_client, db_session, monkeypatch):
    enqueued = _stub_sort_library(monkeypatch)
    admin_client.post("/api/library/sort").raise_for_status()

    from app.models import LibrarySortRun

    run = db_session.get(LibrarySortRun, 1)
    run.state = LibrarySortState.IDLE
    db_session.commit()

    response = admin_client.post("/api/library/sort")

    assert response.status_code == 202
    assert len(enqueued) == 2


def test_library_endpoints_require_session(client):
    assert client.get("/api/library/sort/status").status_code == 401
    assert client.post("/api/library/sort").status_code == 401


def test_library_endpoints_reject_non_admin(authenticated_client):
    assert authenticated_client.get("/api/library/sort/status").status_code == 403
    assert authenticated_client.post("/api/library/sort").status_code == 403
