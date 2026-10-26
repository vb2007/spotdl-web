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
        json={"library_target_dir": "/mnt/raid1/media/music/sorted", "library_quarantine_enabled": False},
    )

    assert updated.status_code == 200
    body = updated.json()
    assert body["library_target_dir"] == "/mnt/raid1/media/music/sorted"
    assert body["library_quarantine_enabled"] is False
    # Untouched fields survive the partial update.
    assert body["library_folder_template"] == app_settings.DEFAULT_LIBRARY_FOLDER_TEMPLATE

    refetched = admin_client.get("/api/settings/library")
    assert refetched.json()["library_target_dir"] == "/mnt/raid1/media/music/sorted"


def test_update_library_settings_rejects_blank_path_fields(admin_client, db_session):
    response = admin_client.patch("/api/settings/library", json={"library_target_dir": "   "})

    assert response.status_code == 400


def test_library_settings_endpoints_require_session(client):
    assert client.get("/api/settings/library").status_code == 401
    assert client.patch("/api/settings/library", json={}).status_code == 401


def test_library_settings_endpoints_reject_non_admin(authenticated_client):
    assert authenticated_client.get("/api/settings/library").status_code == 403
    assert authenticated_client.patch("/api/settings/library", json={}).status_code == 403


# v57 (L2): the library, quarantine and downloads dirs may not overlap in a way that lets a sweep
# act on its own output. The downloads dir is the env's (`/downloads` in the suite); the
# defaults are library `/mnt/raid1/media/music` and quarantine `/downloads/quarantine`.
@pytest.mark.parametrize(
    ("patch", "field", "other", "relation"),
    [
        ({"library_target_dir": "/downloads"}, "library_target_dir", "download_output_dir", "equal"),
        ({"library_target_dir": "/downloads/sorted"}, "library_target_dir", "download_output_dir", "inside"),
        ({"library_target_dir": "/"}, "library_target_dir", "download_output_dir", "contains"),
        ({"library_target_dir": "/downloads/../downloads/"}, "library_target_dir", "download_output_dir", "equal"),
        ({"library_quarantine_dir": "/mnt/raid1/media/music"}, "library_quarantine_dir", "library_target_dir", "equal"),
        (
            {"library_quarantine_dir": "/mnt/raid1/media/music/quarantine"},
            "library_quarantine_dir",
            "library_target_dir",
            "inside",
        ),
        ({"library_quarantine_dir": "/mnt/raid1"}, "library_quarantine_dir", "library_target_dir", "contains"),
        ({"library_quarantine_dir": "/downloads"}, "library_quarantine_dir", "download_output_dir", "equal"),
        ({"library_quarantine_dir": "/srv"}, None, None, None),
        (
            {"library_target_dir": "/mnt/raid1/media/music/sorted", "library_quarantine_dir": "/mnt/raid1/media"},
            "library_quarantine_dir",
            "library_target_dir",
            "contains",
        ),
    ],
)
def test_update_library_settings_refuses_overlapping_directories(
    admin_client, db_session, patch, field, other, relation
):
    before = admin_client.get("/api/settings/library").json()

    response = admin_client.patch("/api/settings/library", json=patch)

    if field is None:
        assert response.status_code == 200
        return
    assert response.status_code == 422
    assert response.json()["code"] == "library_paths_overlap"
    assert response.json()["params"] == {"field": field, "other": other, "relation": relation}
    assert admin_client.get("/api/settings/library").json() == before


def test_update_library_settings_refuses_a_quarantine_containing_the_downloads_dir(admin_client, db_session):
    response = admin_client.patch("/api/settings/library", json={"library_quarantine_dir": "/"})

    assert response.status_code == 422
    # The library is inside "/" too; the first conflict found is the one reported.
    assert response.json()["params"]["field"] == "library_quarantine_dir"
    assert response.json()["params"]["relation"] == "contains"


def test_update_library_settings_allows_a_quarantine_inside_the_downloads_dir(admin_client, db_session):
    """Owner decision (2026-10-26): `/downloads/quarantine` is the shipped default and stays valid."""
    response = admin_client.patch("/api/settings/library", json={"library_quarantine_dir": "/downloads/q2"})

    assert response.status_code == 200
    assert response.json()["library_quarantine_dir"] == "/downloads/q2"


def test_update_library_settings_keeps_the_root_it_leaves(admin_client, db_session):
    """v57 (L6): a moved library_target_dir keeps the old one as a known root."""
    from app.services import app_settings

    admin_client.patch(
        "/api/settings/library", json={"library_target_dir": "/mnt/raid1/media/music/new"}
    ).raise_for_status()

    row = app_settings.get_library_settings(db_session)
    db_session.refresh(row)
    assert row.library_known_roots == ["/mnt/raid1/media/music", "/mnt/raid1/media/music/new"]


@pytest.mark.parametrize("patch", [{"library_target_dir": "music"}, {"library_quarantine_dir": "./quarantine"}])
def test_update_library_settings_refuses_a_relative_directory(admin_client, db_session, patch):
    """v57 (review round 2): a relative path resolves against each container's own working
    directory, so the overlap check can't judge it."""
    response = admin_client.patch("/api/settings/library", json=patch)

    assert response.status_code == 422
    assert response.json()["code"] == "library_path_not_absolute"
    assert response.json()["params"] == {"field": next(iter(patch))}


@pytest.mark.parametrize("library_dir", ["/mnt/raid1/media", "/mnt/newlib", "/srv/music", "/mnt/raid1/media/musicx"])
def test_update_library_settings_refuses_a_library_dir_outside_the_mount(admin_client, db_session, library_dir):
    """Owner decision (2026-10-26): the library is mounted at /mnt/raid1/media/music in every
    container (and nginx serves only that); anywhere else is a container's own writable layer."""
    response = admin_client.patch("/api/settings/library", json={"library_target_dir": library_dir})

    assert response.status_code == 422
    assert response.json()["code"] == "library_dir_outside_mount"
    assert response.json()["params"] == {"field": "library_target_dir", "mount": "/mnt/raid1/media/music"}


def test_update_library_settings_allows_a_folder_inside_the_mount(admin_client, db_session):
    response = admin_client.patch("/api/settings/library", json={"library_target_dir": "/mnt/raid1/media/music/sorted"})

    assert response.status_code == 200


def test_update_library_settings_checks_the_quarantine_dir_even_while_quarantine_is_off(admin_client, db_session):
    """L2 as written (review round 5): the quarantine dir is checked on every save, used or not."""
    off = admin_client.patch(
        "/api/settings/library", json={"library_quarantine_enabled": False, "library_quarantine_dir": "/downloads"}
    )
    assert off.status_code == 422
    assert off.json()["params"]["field"] == "library_quarantine_dir"


@pytest.mark.parametrize("field", ["library_target_dir", "library_quarantine_dir"])
def test_update_library_settings_refuses_a_nul_in_a_path(admin_client, db_session, field):
    """Live review: it was a 500 (every filesystem call raised on it)."""
    response = admin_client.patch("/api/settings/library", json={field: "/mnt/raid1/media/music/a\u0000b"})

    assert response.status_code == 422
    assert response.json()["code"] == "library_path_invalid"
    assert response.json()["params"] == {"field": field}
