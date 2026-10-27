"""Shared fixtures for the alert suites (test_alerts, test_alert_outbox, test_alert_loss_paths):
Matrix configured with a fake token, a fake Redis, a fake homeserver that deduplicates on the
transaction id the way Synapse does, a movable clock for the outbox, and sessions on the
test's own db_session. `deliver`, `meta_killed` and `redis_down` are what the loss-path tests
drive the delivery machinery with: test_alert_loss_paths.py names no outbox function, so the
same file also runs against v36's Celery path, which loses every one of them (the PR shows that
run)."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import SecretStr

from app.config import get_settings
from app.services import alerts

# Deliberately low-entropy and obviously fake (secret scanners flag realistic-looking ones).
TOKEN = "test-matrix-token-not-a-secret"


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture()
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(alerts, "_redis", lambda: fake)
    return fake


@pytest.fixture()
def configured(monkeypatch):
    settings = get_settings().model_copy(
        update={
            "matrix_homeserver_url": "https://matrix.example.org/",
            "matrix_access_token": SecretStr(TOKEN),
            "matrix_room_id": "!room:example.org",
        }
    )
    monkeypatch.setattr(alerts, "get_settings", lambda: settings)
    return settings


class WorkerKilled(BaseException):
    """The sending process dying mid-send: not an Exception, so nothing in it catches it."""


class Homeserver:
    """Every PUT the code makes, answered from a script (`answer(...)`; 200 once it runs
    out). "killed" kills the sender before the request lands; "posted-then-killed" posts the
    message and then kills the sender before it reads the answer, the case a retry could
    double-post. The room keeps one message per
    transaction id, as Synapse does, so a retry under the same id lands once."""

    def __init__(self):
        self.requests: list[dict] = []
        self.room: dict[str, str] = {}
        self._script: list = []

    def answer(self, *outcomes) -> None:
        self._script.extend(outcomes)

    @property
    def messages(self) -> list[str]:
        return list(self.room.values())

    def put(self, url, json, headers, timeout):
        txn = url.rsplit("/", 1)[1]
        self.requests.append({"url": url, "txn": txn, "json": json, "headers": headers})
        outcome = self._script.pop(0) if self._script else 200
        if outcome == "unreachable":
            raise httpx.ConnectError("[Errno 111] Connection refused")
        if outcome == "killed":
            raise WorkerKilled()
        if outcome == "posted-then-killed":
            self.room.setdefault(txn, json["body"])
            raise WorkerKilled()
        if isinstance(outcome, tuple):
            status, payload = outcome
            return httpx.Response(status, json=payload)
        if outcome >= 400:
            return httpx.Response(outcome, json={"errcode": "M_UNKNOWN", "error": "simulated"})
        self.room.setdefault(txn, json["body"])
        return httpx.Response(200, json={"event_id": f"${txn}"})


@pytest.fixture()
def homeserver(monkeypatch):
    server = Homeserver()
    monkeypatch.setattr(alerts.httpx, "put", server.put)
    return server


class Clock:
    def __init__(self):
        # A second ahead: rows are stamped by the database's clock at insert, after this.
        self.now = datetime.now(timezone.utc) + timedelta(seconds=1)

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture()
def clock(monkeypatch):
    """The outbox's notion of now (due times, backoff, give-up). Rows are still stamped by
    the database's clock, which this starts ahead of."""
    fake = Clock()
    monkeypatch.setattr(alerts, "_utcnow", lambda: fake.now)
    return fake


class _Borrowed:
    """db_session, lent as a short-lived session: `with`, commit and close as the code does,
    each commit only a savepoint of the test's rollback."""

    def __init__(self, session):
        self._s = session

    def __getattr__(self, name):
        return getattr(self._s, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if exc[0] is not None:
            self._s.rollback()
        return False

    def close(self):
        pass


@pytest.fixture()
def sessions(db_session, monkeypatch):
    """A make_session for deliver_due/the watchdog, and app.db.SessionLocal (alerts.enqueue's,
    the Celery tasks') pointed at the same db_session."""
    import app.db
    from app.tasks import alerts as alert_tasks

    def make():
        return _Borrowed(db_session)

    monkeypatch.setattr(app.db, "SessionLocal", make)
    monkeypatch.setattr(alert_tasks, "SessionLocal", make)
    return make


@pytest.fixture()
def deliver(sessions):
    """One round of whatever delivers alerts: here, an outbox pass. A sender killed mid-send
    is the process dying: the pass just ends, and what it claimed stays leased in Postgres."""

    def run():
        try:
            alerts.deliver_due(sessions)
        except WorkerKilled:
            pass

    return run


@pytest.fixture()
def meta_killed():
    """worker-meta killed (kill -9) and started again. Nothing about an alert lives in its
    memory or in the broker any more, so there's nothing to lose."""
    return lambda: None


@pytest.fixture()
def redis_down(monkeypatch):
    """Redis (broker and cache) unreachable inside the `with`."""
    import redis

    @contextmanager
    def down():
        def refuse(*a, **k):
            raise redis.ConnectionError("Error 111 connecting to redis:6379. Connection refused.")

        class Down:
            get = set = delete = refuse

        with monkeypatch.context() as patch:
            patch.setattr(alerts, "_redis", lambda: Down())
            yield

    return down
