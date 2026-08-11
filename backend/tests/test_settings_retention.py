def test_get_retention_settings_defaults_to_null(authenticated_client, db_session):
    response = authenticated_client.get("/api/settings/retention")

    assert response.status_code == 200
    assert response.json() == {"retention_days": None}


def test_update_retention_settings_persists(authenticated_client, db_session):
    updated = authenticated_client.patch("/api/settings/retention", json={"retention_days": 30})

    assert updated.status_code == 200
    assert updated.json() == {"retention_days": 30}

    refetched = authenticated_client.get("/api/settings/retention")
    assert refetched.json() == {"retention_days": 30}


def test_update_retention_settings_can_disable_with_null(authenticated_client, db_session):
    authenticated_client.patch("/api/settings/retention", json={"retention_days": 30})

    response = authenticated_client.patch("/api/settings/retention", json={"retention_days": None})

    assert response.status_code == 200
    assert response.json() == {"retention_days": None}


def test_update_retention_settings_rejects_non_positive_value(authenticated_client, db_session):
    assert authenticated_client.patch("/api/settings/retention", json={"retention_days": 0}).status_code == 400
    assert authenticated_client.patch("/api/settings/retention", json={"retention_days": -1}).status_code == 400


def test_retention_settings_are_isolated_per_user(authenticated_client, db_session, session_cookie):
    authenticated_client.patch("/api/settings/retention", json={"retention_days": 7})

    # A second identity on the same client via session_cookie, not a second login (which
    # would just overwrite the shared cookie jar -- see conftest.py's session_cookie doc).
    other_cookies = session_cookie("other@example.com")
    other_response = authenticated_client.get("/api/settings/retention", cookies=other_cookies)

    assert other_response.json() == {"retention_days": None}


def test_non_admin_can_read_and_write_their_own_retention_setting(authenticated_client, db_session):
    # Unlike /api/settings/output, retention is deliberately open to every user, not
    # admin-gated -- a plain authenticated_client succeeding here is the point.
    response = authenticated_client.patch("/api/settings/retention", json={"retention_days": 14})
    assert response.status_code == 200


def test_retention_settings_endpoints_require_session(client):
    assert client.get("/api/settings/retention").status_code == 401
    assert client.patch("/api/settings/retention", json={"retention_days": 1}).status_code == 401
