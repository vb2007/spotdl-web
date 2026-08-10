import pytest
from pydantic import ValidationError

from app.config import Settings

_REQUIRED = {
    "DATABASE_URL": "postgresql+psycopg://test:test@localhost/test",
    "REDIS_URL": "redis://localhost:6379/0",
    "SESSION_SECRET": "test-secret",
    "ALLOWED_EMAILS": "allowed@example.com,admin@example.com",
    "ADMIN_EMAIL": "admin@example.com",
}


def test_pacing_window_defaults_are_valid():
    settings = Settings(**_REQUIRED)
    assert settings.pacing_min_sec == 0
    assert settings.pacing_max_sec == 0


def test_pacing_min_greater_than_max_is_rejected():
    """random.uniform tolerates reversed bounds and silently samples them anyway --
    MIN=5/MAX=0 would otherwise read as "pace by up to 5s" while meaning "off". v15
    fails this at startup instead of letting it misbehave quietly."""
    with pytest.raises(ValidationError):
        Settings(**_REQUIRED, PACING_MIN_SEC=5, PACING_MAX_SEC=0)


@pytest.mark.parametrize("key", ["PACING_MIN_SEC", "PACING_MAX_SEC"])
def test_pacing_negative_values_are_rejected(key):
    with pytest.raises(ValidationError):
        Settings(**_REQUIRED, **{key: -1})


def test_pacing_min_equal_to_max_is_allowed():
    settings = Settings(**_REQUIRED, PACING_MIN_SEC=5, PACING_MAX_SEC=5)
    assert settings.pacing_min_sec == settings.pacing_max_sec == 5


def test_admin_email_missing_is_rejected(monkeypatch):
    # conftest.py sets ADMIN_EMAIL in os.environ for every other test in the suite --
    # Settings (a pydantic-settings BaseSettings) falls back to reading it from there
    # for any field omitted from the constructor kwargs, so it must be unset here too
    # for "missing" to actually mean missing.
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    required = {k: v for k, v in _REQUIRED.items() if k != "ADMIN_EMAIL"}
    with pytest.raises(ValidationError):
        Settings(**required)


def test_admin_email_not_in_allowed_emails_is_rejected():
    """An admin who isn't allowlisted could never log in -- a deployment nobody can
    administer, which must crash-loop at boot rather than surface only once someone
    notices settings/proxies/worker are unreachable."""
    with pytest.raises(ValidationError):
        Settings(**{**_REQUIRED, "ADMIN_EMAIL": "not-allowed@example.com"})


def test_admin_email_matching_is_allowed():
    settings = Settings(**_REQUIRED)
    assert settings.admin_email == "admin@example.com"
