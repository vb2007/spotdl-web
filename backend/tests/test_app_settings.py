from app.models import AppSettings
from app.services import app_settings


class _FakeSettings:
    default_format = "m4a"
    default_bitrate = "128k"


class _LegacySettings:
    """A pre-v54.2 `.env`: values the app no longer offers."""

    default_format = "mp3"
    default_bitrate = "320k"


def test_get_output_settings_creates_row_seeded_from_env(db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())

    row = app_settings.get_output_settings(db_session)
    db_session.commit()

    assert row.default_format == "m4a"
    assert row.default_bitrate == "128k"
    assert row.output_template == app_settings.DEFAULT_OUTPUT_TEMPLATE


def test_a_seed_the_app_no_longer_offers_falls_back_to_opus_best(db_session, monkeypatch):
    """v54.2: the env only seeds a fresh row, so a stale mp3/320k there seeds the defaults
    rather than a value the settings UI can't show (or a boot crash over it)."""
    monkeypatch.setattr(app_settings, "get_settings", lambda: _LegacySettings())

    row = app_settings.get_output_settings(db_session)
    db_session.commit()

    assert (row.default_format, row.default_bitrate) == ("opus", "best")


def test_get_output_settings_returns_existing_row_without_reseeding(db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())
    existing = AppSettings(
        id=1,
        default_format="flac",
        default_bitrate="disable",
        output_template="{title}.{output-ext}",
        library_target_dir="/mnt/library",
        library_folder_template="{artist}",
        library_quarantine_enabled=True,
        library_quarantine_dir="/downloads/quarantine",
    )
    db_session.add(existing)
    db_session.commit()

    def _fail_if_called():
        raise AssertionError("env Settings should not be read once a row already exists")

    monkeypatch.setattr(app_settings, "get_settings", _fail_if_called)

    row = app_settings.get_output_settings(db_session)

    assert row.default_format == "flac"
    assert row.output_template == "{title}.{output-ext}"


def test_update_output_settings_only_touches_given_fields(db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())
    app_settings.get_output_settings(db_session)
    db_session.commit()

    row = app_settings.update_output_settings(db_session, default_format="flac")
    db_session.commit()

    assert row.default_format == "flac"
    assert row.default_bitrate == "128k"


def test_update_output_settings_creates_row_if_missing(db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())

    row = app_settings.update_output_settings(db_session, default_bitrate="256k")
    db_session.commit()

    assert row.default_bitrate == "256k"
    assert row.default_format == "m4a"


def test_get_library_settings_creates_row_seeded_with_defaults(db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())

    row = app_settings.get_library_settings(db_session)
    db_session.commit()

    assert row.library_target_dir == app_settings.DEFAULT_LIBRARY_TARGET_DIR
    assert row.library_folder_template == app_settings.DEFAULT_LIBRARY_FOLDER_TEMPLATE
    assert row.library_quarantine_enabled is True
    assert row.library_quarantine_dir == app_settings.DEFAULT_LIBRARY_QUARANTINE_DIR


def test_get_library_settings_and_output_settings_share_one_row(db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())

    app_settings.update_output_settings(db_session, default_format="flac")
    db_session.commit()

    row = app_settings.get_library_settings(db_session)

    assert row.default_format == "flac"  # same singleton row, not a second table


def test_update_library_settings_only_touches_given_fields(db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())
    app_settings.get_library_settings(db_session)
    db_session.commit()

    row = app_settings.update_library_settings(db_session, library_quarantine_enabled=False)
    db_session.commit()

    assert row.library_quarantine_enabled is False
    assert row.library_target_dir == app_settings.DEFAULT_LIBRARY_TARGET_DIR
