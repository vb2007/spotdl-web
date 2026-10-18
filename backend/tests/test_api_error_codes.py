"""v46: every user-facing API error carries a stable `code` beside its English `detail`, so
the frontend translates by code and never by matching the sentence. One case per code, each
reached through the real endpoint the UI calls."""

import uuid
from datetime import datetime, timezone

import pytest

from app.models import Job, JobSourceType, Proxy, ProxySource, Track, TrackState
from app.routers import library as library_router
from app.routers import settings as settings_router
from app.services import alerts, app_settings


def _error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code
    # `detail` stays the English sentence every pre-v46 client reads.
    assert isinstance(body["detail"], str) and body["detail"]
    return body


def _make_track(db_session, owner, *, state=TrackState.WAITING, archived=False):
    job = Job(
        source_url="https://open.spotify.com/track/abc",
        source_type=JobSourceType.TRACK,
        user_id=owner.id,
        archived_at=datetime.now(timezone.utc) if archived else None,
    )
    db_session.add(job)
    db_session.commit()
    track = Track(job_id=job.id, spotify_track_id=f"{job.id}-t", song_json={"name": "Song"}, state=state)
    db_session.add(track)
    db_session.commit()
    return track


class _FakeOutputSettings:
    default_format = "mp3"
    default_bitrate = "320k"
    download_output_dir = "/downloads"


def test_auth_errors_carry_codes(client, monkeypatch):
    from app.routers import auth

    async def rejected(email: str, password: str):
        return False, None

    monkeypatch.setattr(auth.upstream_auth, "login", rejected)
    _error(client.post("/api/auth/login", json={"email": "a@example.com", "password": "x"}), 401, "invalid_credentials")
    _error(client.get("/api/auth/me"), 401, "not_authenticated")
    client.cookies.set("SPOTDL_SESSION", "not-a-real-token")
    _error(client.get("/api/jobs"), 401, "not_authenticated")


def test_admin_required_carries_a_code(authenticated_client):
    _error(authenticated_client.get("/api/settings/output"), 403, "admin_required")


def test_hidden_admin_404s_stay_codeless(authenticated_client):
    """A non-admin's 404 on an admin-only route must read exactly like an unknown route's."""
    for response in (
        authenticated_client.get("/api/admin/stats"),
        authenticated_client.post("/api/settings/alerts/test"),
        authenticated_client.get("/api/no-such-route"),
    ):
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}


def test_job_errors_carry_codes(authenticated_client, owner, db_session):
    _error(authenticated_client.get(f"/api/jobs/{uuid.uuid4()}"), 404, "job_not_found")
    _error(authenticated_client.post("/api/jobs/archive", json={}), 400, "archive_nothing_selected")
    body = _error(authenticated_client.get("/api/jobs?sort=nope"), 400, "invalid_list_params")
    # The server's own diagnostic travels as a param, for the translation to quote.
    assert body["params"] == {"reason": body["detail"]} and "nope" in body["detail"]
    _error(authenticated_client.get("/api/jobs?cursor=garbage"), 400, "invalid_list_params")
    _error(authenticated_client.get("/api/tracks?state=nope"), 400, "invalid_list_params")
    track = _make_track(db_session, owner)
    _error(
        authenticated_client.get(f"/api/jobs/{track.job_id}/tracks?sort=nope"), 400, "invalid_list_params"
    )


def test_track_errors_carry_codes(authenticated_client, owner, db_session):
    _error(authenticated_client.post(f"/api/tracks/{uuid.uuid4()}/retry"), 404, "track_not_found")

    downloading = _make_track(db_session, owner, state=TrackState.DOWNLOADING)
    body = _error(
        authenticated_client.post(f"/api/tracks/{downloading.id}/retry"), 409, "track_not_retryable"
    )
    assert body["params"] == {"state": "downloading"}

    archived = _make_track(db_session, owner, state=TrackState.LOOKUP_FAILED, archived=True)
    _error(authenticated_client.post(f"/api/tracks/{archived.id}/retry"), 409, "job_archived")

    never_downloaded = _make_track(db_session, owner, state=TrackState.WAITING)
    _error(authenticated_client.get(f"/api/tracks/{never_downloaded.id}/file"), 404, "file_not_found")


def test_library_sort_running_carries_a_code(admin_client, db_session, monkeypatch):
    monkeypatch.setattr(library_router.sort_library, "delay", lambda admin_id: None)
    assert admin_client.post("/api/library/sort").status_code == 202
    _error(admin_client.post("/api/library/sort"), 409, "library_sort_running")


def test_settings_errors_carry_codes_and_params(admin_client, db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeOutputSettings())
    body = _error(admin_client.patch("/api/settings/output", json={"default_format": "wma"}), 400, "unsupported_format")
    assert body["params"] == {"value": "wma"}
    body = _error(
        admin_client.patch("/api/settings/output", json={"default_bitrate": "999k"}), 400, "unsupported_bitrate"
    )
    assert body["params"] == {"value": "999k"}

    body = _error(admin_client.patch("/api/settings/library", json={"library_target_dir": "  "}), 400, "setting_blank")
    assert body["params"] == {"field": "library_target_dir"}

    body = _error(
        admin_client.patch("/api/settings/alerts", json={"alert_spike_threshold": 1}), 400, "setting_out_of_range"
    )
    assert body["params"] == {"field": "alert_spike_threshold", "min": 2, "max": 1000}

    _error(admin_client.patch("/api/settings/retention", json={"retention_days": 0}), 400, "retention_days_invalid")


@pytest.mark.parametrize(
    ("raised", "status", "code"),
    [
        (alerts.AlertsNotConfigured(), 409, "alerts_not_configured"),
        (alerts.AlertSendError("HTTP 403: forbidden"), 502, "alert_send_failed"),
    ],
)
def test_test_alert_errors_carry_codes(admin_client, monkeypatch, raised, status, code):
    def fail(_message):
        raise raised

    monkeypatch.setattr(settings_router.alerts, "send_now", fail)
    body = _error(admin_client.post("/api/settings/alerts/test"), status, code)
    if code == "alert_send_failed":
        assert body["params"] == {"reason": "HTTP 403: forbidden"}


def test_proxy_errors_carry_codes_and_params(admin_client, db_session):
    _error(admin_client.patch(f"/api/proxies/{uuid.uuid4()}", json={"enabled": True}), 404, "proxy_not_found")
    _error(admin_client.post("/api/proxies", json={"url": "  "}), 400, "proxy_url_required")
    _error(admin_client.post("/api/proxies", json={"url": "socks5://nope"}), 400, "proxy_url_invalid")

    db_session.add(Proxy(url="http://user:secretpw@203.0.113.5:8080", source=ProxySource.FILE, enabled=True))
    db_session.commit()
    _error(admin_client.post("/api/proxies", json={"url": "http://user:secretpw@203.0.113.5:8080"}), 409, "proxy_url_exists")
    body = _error(admin_client.post("/api/proxies", json={"url": "http://203.0.113.5:8080"}), 409, "proxy_target_exists")
    assert body["params"] == {"target": "203.0.113.5:8080", "source": "file"}
    # The params name the target only, never a credential.
    assert "secretpw" not in str(body)
