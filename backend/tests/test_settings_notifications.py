"""v66: the per-user job-notifications switch, stored server-side like the other preferences."""


def test_job_notifications_default_off(authenticated_client, db_session):
    assert authenticated_client.get("/api/settings/notifications").json() == {"job_notifications": False}
    assert authenticated_client.get("/api/auth/me").json()["job_notifications"] is False


def test_update_job_notifications_persists_and_reaches_me(authenticated_client, db_session):
    assert authenticated_client.patch(
        "/api/settings/notifications", json={"job_notifications": True}
    ).json() == {"job_notifications": True}
    assert authenticated_client.get("/api/auth/me").json()["job_notifications"] is True
    assert authenticated_client.get("/api/settings/notifications").json() == {"job_notifications": True}
    assert authenticated_client.patch(
        "/api/settings/notifications", json={"job_notifications": False}
    ).json() == {"job_notifications": False}
    assert authenticated_client.get("/api/auth/me").json()["job_notifications"] is False


def test_update_job_notifications_rejects_non_booleans_and_an_empty_body(authenticated_client, db_session):
    for bad in ("true", 1, None, "on"):
        assert authenticated_client.patch(
            "/api/settings/notifications", json={"job_notifications": bad}
        ).status_code == 422, bad
    assert authenticated_client.patch("/api/settings/notifications", json={}).status_code == 422
    assert authenticated_client.get("/api/settings/notifications").json() == {"job_notifications": False}


def test_job_notifications_leave_the_other_preferences_alone(authenticated_client, db_session):
    authenticated_client.patch("/api/settings/clock", json={"clock": "24h"})
    authenticated_client.patch("/api/settings/keyboard", json={"keyboard_shortcuts": False})
    authenticated_client.patch("/api/settings/notifications", json={"job_notifications": True})
    me = authenticated_client.get("/api/auth/me").json()
    assert (me["clock"], me["keyboard_shortcuts"], me["job_notifications"]) == ("24h", False, True)


def test_job_notifications_endpoints_require_session(client):
    assert client.get("/api/settings/notifications").status_code == 401
    assert client.patch("/api/settings/notifications", json={"job_notifications": True}).status_code == 401
