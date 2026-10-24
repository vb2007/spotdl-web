"""Shared v53 test helpers: an in-memory stand-in for the rate limiter's Redis, and the
`api_keys` table, which conftest's per-table SQLite schema doesn't create."""

import time

import pytest

from app.models import ApiKey
from app.services import rate_limit


class FakeRedis:
    """The few commands services/rate_limit.py uses, with real expiry."""

    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expires: dict[str, float] = {}

    def _expire_due(self, key: str) -> None:
        if key in self.expires and self.expires[key] <= time.monotonic():
            self.values.pop(key, None)
            self.expires.pop(key, None)

    def get(self, key):
        self._expire_due(key)
        value = self.values.get(key)
        return None if value is None else str(value).encode()

    def ttl(self, key):
        self._expire_due(key)
        if key not in self.values:
            return -2
        if key not in self.expires:
            return -1
        return max(0, int(round(self.expires[key] - time.monotonic())))

    def incr(self, key):
        self._expire_due(key)
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key, seconds, nx=False):
        self._expire_due(key)
        if key not in self.values or (nx and key in self.expires):
            return False
        self.expires[key] = time.monotonic() + seconds
        return True

    def delete(self, key):
        self._expire_due(key)
        existed = key in self.values
        self.values.pop(key, None)
        self.expires.pop(key, None)
        return int(existed)

    def pipeline(self):
        return _Pipeline(self)


class _Pipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.calls: list = []

    def __getattr__(self, name):
        def queue(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self

        return queue

    def execute(self):
        return [getattr(self.redis, name)(*args, **kwargs) for name, args, kwargs in self.calls]


@pytest.fixture()
def fake_redis(monkeypatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(rate_limit, "_redis", lambda: fake)
    return fake


@pytest.fixture()
def api_keys_table(db_session):
    ApiKey.__table__.create(db_session.get_bind(), checkfirst=True)


def bearer(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}
