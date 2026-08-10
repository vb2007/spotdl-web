from app.services import app_settings


class _FakeSettings:
    default_format = "mp3"
    default_bitrate = "320k"
    download_output_dir = "/downloads"


def test_get_output_settings_seeds_from_env_defaults(admin_client, db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())

    response = admin_client.get("/api/settings/output")

    assert response.status_code == 200
    assert response.json() == {
        "default_format": "mp3",
        "default_bitrate": "320k",
        "output_dir": "/downloads",
        "output_template": app_settings.DEFAULT_OUTPUT_TEMPLATE,
    }


def test_get_output_options_reflects_the_real_installed_spotdl(admin_client, db_session):
    # Not mocked -- this is the whole point: the endpoint introspects the real installed
    # spotdl's argparse choices rather than a hardcoded guess.
    response = admin_client.get("/api/settings/output/options")

    assert response.status_code == 200
    body = response.json()
    assert "mp3" in body["formats"]
    assert "flac" in body["formats"]
    assert "320k" in body["bitrates"]
    assert "disable" in body["bitrates"]


def test_update_output_settings_persists_and_returns_partial_update(admin_client, db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())

    updated = admin_client.patch("/api/settings/output", json={"default_format": "flac", "default_bitrate": "256k"})

    assert updated.status_code == 200
    body = updated.json()
    assert body["default_format"] == "flac"
    assert body["default_bitrate"] == "256k"
    assert body["output_dir"] == "/downloads"

    refetched = admin_client.get("/api/settings/output")
    assert refetched.json()["default_format"] == "flac"


def test_update_output_settings_ignores_unset_fields(admin_client, db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())
    admin_client.patch("/api/settings/output", json={"default_bitrate": "192k"})

    response = admin_client.patch("/api/settings/output", json={"default_format": "flac"})

    body = response.json()
    assert body["default_bitrate"] == "192k"
    assert body["default_format"] == "flac"


def test_update_output_settings_rejects_unsupported_format(admin_client, db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())

    response = admin_client.patch("/api/settings/output", json={"default_format": "wma"})

    assert response.status_code == 400


def test_update_output_settings_rejects_unsupported_bitrate(admin_client, db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())

    response = admin_client.patch("/api/settings/output", json={"default_bitrate": "999k"})

    assert response.status_code == 400


def test_update_output_settings_ignores_output_dir_if_sent(admin_client, db_session, monkeypatch):
    # output_dir isn't a field on the request model at all -- pydantic silently drops
    # unknown extra keys, so sending it must have zero effect rather than erroring or
    # being stored.
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())

    response = admin_client.patch("/api/settings/output", json={"output_dir": "/somewhere-else"})

    assert response.status_code == 200
    assert response.json()["output_dir"] == "/downloads"


def test_settings_endpoints_require_session(client):
    assert client.get("/api/settings/output").status_code == 401
    assert client.get("/api/settings/output/options").status_code == 401
    assert client.patch("/api/settings/output", json={}).status_code == 401


def test_settings_endpoints_reject_non_admin(authenticated_client):
    assert authenticated_client.get("/api/settings/output").status_code == 403
    assert authenticated_client.get("/api/settings/output/options").status_code == 403
    assert authenticated_client.patch("/api/settings/output", json={}).status_code == 403
