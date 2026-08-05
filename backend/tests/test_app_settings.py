from app.models import AppSettings
from app.services import app_settings


class _FakeSettings:
    default_format = "mp3"
    default_bitrate = "320k"


def test_get_output_settings_creates_row_seeded_from_env(db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())

    row = app_settings.get_output_settings(db_session)
    db_session.commit()

    assert row.default_format == "mp3"
    assert row.default_bitrate == "320k"
    assert row.output_template == app_settings.DEFAULT_OUTPUT_TEMPLATE


def test_get_output_settings_returns_existing_row_without_reseeding(db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())
    existing = AppSettings(
        id=1,
        default_format="flac",
        default_bitrate="disable",
        output_template="{title}.{output-ext}",
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
    assert row.default_bitrate == "320k"


def test_update_output_settings_creates_row_if_missing(db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "get_settings", lambda: _FakeSettings())

    row = app_settings.update_output_settings(db_session, default_bitrate="256k")
    db_session.commit()

    assert row.default_bitrate == "256k"
    assert row.default_format == "mp3"
