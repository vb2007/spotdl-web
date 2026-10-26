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
        "cancel_requested": False,
        "cancelled": False,
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
    assert client.post("/api/library/sort/cancel").status_code == 401


def test_library_endpoints_reject_non_admin(authenticated_client):
    assert authenticated_client.get("/api/library/sort/status").status_code == 403
    assert authenticated_client.post("/api/library/sort").status_code == 403
    assert authenticated_client.post("/api/library/sort/cancel").status_code == 403


def test_cancel_sort_flags_the_running_sweep(admin_client, db_session, monkeypatch):
    """v57 (L1): the flag only; the sweep stops at its next file boundary."""
    _stub_sort_library(monkeypatch)
    admin_client.post("/api/library/sort").raise_for_status()

    response = admin_client.post("/api/library/sort/cancel")

    assert response.status_code == 202
    assert response.json()["cancel_requested"] is True
    assert response.json()["state"] == "running"
    assert response.json()["cancelled"] is False


def test_cancel_sort_is_a_409_when_nothing_runs(admin_client, db_session):
    response = admin_client.post("/api/library/sort/cancel")

    assert response.status_code == 409
    assert response.json()["code"] == "library_sort_not_running"


def test_start_sort_clears_the_previous_sweeps_cancel(admin_client, db_session, monkeypatch):
    _stub_sort_library(monkeypatch)
    from app.models import LibrarySortRun

    db_session.add(LibrarySortRun(id=1, state=LibrarySortState.IDLE, errors=[], cancel_requested=True, cancelled=True))
    db_session.commit()

    body = admin_client.post("/api/library/sort").json()

    assert (body["cancel_requested"], body["cancelled"]) == (False, False)


def test_start_sort_refuses_overlapping_directories(admin_client, db_session, monkeypatch):
    """v57 (L2): a library saved before v57 inside the downloads dir is refused at the start,
    not only on save; nothing is enqueued and the run stays idle."""
    enqueued = _stub_sort_library(monkeypatch)
    from app.services import app_settings

    app_settings.get_library_settings(db_session).library_target_dir = "/downloads/library"
    db_session.commit()

    response = admin_client.post("/api/library/sort")

    assert response.status_code == 422
    assert response.json()["code"] == "library_paths_overlap"
    assert response.json()["params"] == {
        "field": "library_target_dir",
        "other": "download_output_dir",
        "relation": "inside",
    }
    assert enqueued == []
    assert admin_client.get("/api/library/sort/status").json()["state"] == "idle"
