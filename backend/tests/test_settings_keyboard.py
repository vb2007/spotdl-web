"""v45: the per-user keyboard-shortcut off switch (WCAG 2.1.4)."""


def test_keyboard_shortcuts_default_to_on(authenticated_client, db_session):
    response = authenticated_client.get("/api/settings/keyboard")

    assert response.status_code == 200
    assert response.json() == {"keyboard_shortcuts": True}


def test_update_keyboard_shortcuts_persists_and_reaches_me(authenticated_client, db_session):
    updated = authenticated_client.patch("/api/settings/keyboard", json={"keyboard_shortcuts": False})

    assert updated.status_code == 200
    assert updated.json() == {"keyboard_shortcuts": False}
    assert authenticated_client.get("/api/settings/keyboard").json() == {"keyboard_shortcuts": False}
    # The app shell reads it from /me on every route load.
    assert authenticated_client.get("/api/auth/me").json()["keyboard_shortcuts"] is False

    authenticated_client.patch("/api/settings/keyboard", json={"keyboard_shortcuts": True})
    assert authenticated_client.get("/api/auth/me").json()["keyboard_shortcuts"] is True


def test_me_reports_the_default_without_creating_a_settings_row(authenticated_client, db_session):
    from app.models import UserSettings

    assert authenticated_client.get("/api/auth/me").json()["keyboard_shortcuts"] is True
    assert db_session.query(UserSettings).count() == 0


def test_update_keyboard_shortcuts_rejects_a_non_boolean(authenticated_client, db_session):
    assert authenticated_client.patch("/api/settings/keyboard", json={"keyboard_shortcuts": "off"}).status_code == 422
    assert authenticated_client.patch("/api/settings/keyboard", json={}).status_code == 422


def test_keyboard_setting_leaves_retention_alone(authenticated_client, db_session):
    authenticated_client.patch("/api/settings/retention", json={"retention_days": 9})
    authenticated_client.patch("/api/settings/keyboard", json={"keyboard_shortcuts": False})

    assert authenticated_client.get("/api/settings/retention").json() == {"retention_days": 9}


def test_keyboard_settings_endpoints_require_session(client):
    assert client.get("/api/settings/keyboard").status_code == 401
    assert client.patch("/api/settings/keyboard", json={"keyboard_shortcuts": False}).status_code == 401
