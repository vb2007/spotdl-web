import pytest
from pydantic import ValidationError

from app.config import Settings

_REQUIRED = {
    "DATABASE_URL": "postgresql+psycopg://test:test@localhost/test",
    "REDIS_URL": "redis://localhost:6379/0",
    "SESSION_SECRET": "test-secret",
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
