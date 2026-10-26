import pytest

from app.services import app_settings


class _FakeSettings:
    default_format = "m4a"
    default_bitrate = "128k"
    download_output_dir = "/downloads"


def test_get_output_settings_seeds_from_env_defaults(admin_client, db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())

    response = admin_client.get("/api/settings/output")

    assert response.status_code == 200
    assert response.json() == {
        "default_format": "m4a",
        "default_bitrate": "128k",
        "output_dir": "/downloads",
        "output_template": app_settings.DEFAULT_OUTPUT_TEMPLATE,
    }


def test_get_output_options_offers_only_what_the_source_can_back(admin_client, db_session):
    """v54.2: not spotdl's whole range. Nothing above YouTube's ~130-160k source, no
    lossless containers for a lossy source, no spotdl-internal auto/disable/VBR values."""
    response = admin_client.get("/api/settings/output/options")

    assert response.status_code == 200
    assert response.json() == {
        "formats": ["opus", "m4a", "mp3"],
        "bitrates": ["best", "160k", "128k", "96k", "64k"],
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("default_bitrate", "320k"),
        ("default_bitrate", "192k"),
        ("default_bitrate", "0"),
        ("default_bitrate", "auto"),
        ("default_bitrate", "disable"),
        ("default_format", "flac"),
        ("default_format", "wav"),
        ("default_format", "ogg"),
    ],
)
def test_update_output_settings_rejects_what_the_source_cannot_back(admin_client, db_session, monkeypatch, field, value):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())

    response = admin_client.patch("/api/settings/output", json={field: value})

    assert response.status_code == 400
    assert response.json()["code"] == ("unsupported_bitrate" if field == "default_bitrate" else "unsupported_format")


def test_update_output_settings_persists_and_returns_partial_update(admin_client, db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())

    updated = admin_client.patch("/api/settings/output", json={"default_format": "opus", "default_bitrate": "best"})

    assert updated.status_code == 200
    body = updated.json()
    assert body["default_format"] == "opus"
    assert body["default_bitrate"] == "best"
    assert body["output_dir"] == "/downloads"

    refetched = admin_client.get("/api/settings/output")
    assert refetched.json()["default_format"] == "opus"


def test_update_output_settings_ignores_unset_fields(admin_client, db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())
    admin_client.patch("/api/settings/output", json={"default_bitrate": "96k"})

    response = admin_client.patch("/api/settings/output", json={"default_format": "mp3"})

    body = response.json()
    assert body["default_bitrate"] == "96k"
    assert body["default_format"] == "mp3"


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


def test_get_library_settings_seeds_from_defaults(admin_client, db_session):
    response = admin_client.get("/api/settings/library")

    assert response.status_code == 200
    assert response.json() == {
        "library_target_dir": app_settings.DEFAULT_LIBRARY_TARGET_DIR,
        "library_folder_template": app_settings.DEFAULT_LIBRARY_FOLDER_TEMPLATE,
        "library_quarantine_enabled": True,
        "library_quarantine_dir": app_settings.DEFAULT_LIBRARY_QUARANTINE_DIR,
    }


def test_update_library_settings_persists_partial_update(admin_client, db_session):
    updated = admin_client.patch(
        "/api/settings/library",
        json={"library_target_dir": "/mnt/library", "library_quarantine_enabled": False},
    )

    assert updated.status_code == 200
    body = updated.json()
    assert body["library_target_dir"] == "/mnt/library"
    assert body["library_quarantine_enabled"] is False
    # Untouched fields survive the partial update.
    assert body["library_folder_template"] == app_settings.DEFAULT_LIBRARY_FOLDER_TEMPLATE

    refetched = admin_client.get("/api/settings/library")
    assert refetched.json()["library_target_dir"] == "/mnt/library"


def test_update_library_settings_rejects_blank_path_fields(admin_client, db_session):
    response = admin_client.patch("/api/settings/library", json={"library_target_dir": "   "})

    assert response.status_code == 400


def test_library_settings_endpoints_require_session(client):
    assert client.get("/api/settings/library").status_code == 401
    assert client.patch("/api/settings/library", json={}).status_code == 401


def test_library_settings_endpoints_reject_non_admin(authenticated_client):
    assert authenticated_client.get("/api/settings/library").status_code == 403
    assert authenticated_client.patch("/api/settings/library", json={}).status_code == 403
