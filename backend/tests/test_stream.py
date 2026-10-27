import asyncio
import types
import uuid

import pytest
import redis.asyncio as aioredis

from app.models import User
from app.routers import stream as stream_router
from app.services.events import ADMIN_CHANNEL_PATTERN, channel_for


async def _fake_event_stream(request, user, view):
    yield 'data: {"type": "track.state", "state": "downloading"}\n\n'


def test_stream_requires_session(client):
    response = client.get("/api/stream")
    assert response.status_code == 401


def test_stream_returns_sse_headers_and_forwarded_events(authenticated_client, monkeypatch):
    # Swaps out the real Redis-subscribing generator for a finite one — the actual
    # subscribe/forward/heartbeat loop against a real Redis instance is covered by this
    # version's real-stack curl verification (see CLAUDE.md's v08 notes), not here; a real
    # generator never terminates on its own; and a plain (non-streaming) TestClient.get()
    # can't safely give up waiting for a real Redis message.
    monkeypatch.setattr(stream_router, "_event_stream", _fake_event_stream)

    response = authenticated_client.get("/api/stream")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "track.state" in response.text


class _FakeRequest:
    """Disconnects once `polls` loop turns have run: 0 ends the loop after the (p)subscribe
    call, before any get_message wait, for the tests about which channel gets subscribed."""

    def __init__(self, polls: int = 0):
        self.polls = polls

    async def is_disconnected(self) -> bool:
        if self.polls <= 0:
            return True
        self.polls -= 1
        return False


class _FakePubSub:
    """`messages` are replayed in order, shaped as redis-py delivers them: `channel` as
    bytes, a `pmessage` while pattern-subscribed and a `message` otherwise."""

    def __init__(self, messages: list[tuple[str, str]] | None = None):
        self.subscribed: list[str] = []
        self.psubscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.punsubscribed: list[str] = []
        self.timeouts: list[float] = []
        self._messages = list(messages or [])

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def psubscribe(self, pattern: str) -> None:
        self.psubscribed.append(pattern)

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed.append(channel)

    async def punsubscribe(self, pattern: str) -> None:
        self.punsubscribed.append(pattern)

    async def get_message(self, **kwargs) -> dict | None:
        self.timeouts.append(kwargs["timeout"])
        if not self._messages:
            return None
        channel, data = self._messages.pop(0)
        if self.psubscribed:
            return {"type": "pmessage", "pattern": self.psubscribed[0].encode(), "channel": channel.encode(), "data": data.encode()}
        return {"type": "message", "pattern": None, "channel": channel.encode(), "data": data.encode()}

    async def aclose(self) -> None:
        pass


class _FakeRedisClient:
    def __init__(self, messages=None):
        self._pubsub = _FakePubSub(messages)

    def pubsub(self) -> _FakePubSub:
        return self._pubsub

    async def aclose(self) -> None:
        pass


def _drive(monkeypatch, user: User, view: str, messages=None) -> tuple[_FakePubSub, list[str]]:
    fake_client = _FakeRedisClient(messages)
    monkeypatch.setattr(aioredis.Redis, "from_url", lambda url: fake_client)
    sent: list[str] = []

    async def _run():
        request = _FakeRequest(polls=len(messages or []))
        async for chunk in stream_router._event_stream(request, user, view):
            sent.append(chunk)

    asyncio.run(_run())
    return fake_client._pubsub, sent


def test_event_stream_subscribes_to_the_users_own_channel(monkeypatch):
    user = User(id=uuid.uuid4(), email="a@example.com", is_admin=False)

    pubsub, _ = _drive(monkeypatch, user, "mine")

    assert pubsub.subscribed == [channel_for(user.id)]
    assert pubsub.psubscribed == []
    assert pubsub.unsubscribed == [channel_for(user.id)]


def test_event_stream_admin_all_users_psubscribes_to_the_admin_pattern(monkeypatch):
    admin = User(id=uuid.uuid4(), email="admin@example.com", is_admin=True)

    pubsub, _ = _drive(monkeypatch, admin, "all")

    assert pubsub.psubscribed == [ADMIN_CHANNEL_PATTERN]
    assert pubsub.subscribed == []
    assert pubsub.punsubscribed == [ADMIN_CHANNEL_PATTERN]


def test_event_stream_admin_others_psubscribes_and_unsubscribes_like_all(monkeypatch):
    admin = User(id=uuid.uuid4(), email="admin@example.com", is_admin=True)

    pubsub, _ = _drive(monkeypatch, admin, "others")

    assert pubsub.psubscribed == [ADMIN_CHANNEL_PATTERN]
    assert pubsub.subscribed == []
    assert pubsub.punsubscribed == [ADMIN_CHANNEL_PATTERN]
    assert pubsub.unsubscribed == []


@pytest.mark.parametrize("view", ["all", "others"])
def test_event_stream_non_admin_all_users_flag_is_ignored(monkeypatch, view):
    """v17's threat model: a client-supplied scope flag is never trusted -- a non-admin
    passing all_users=true (v54: or view=all/others) still only ever gets their own channel."""
    user = User(id=uuid.uuid4(), email="a@example.com", is_admin=False)

    pubsub, _ = _drive(monkeypatch, user, view)

    assert pubsub.subscribed == [channel_for(user.id)]
    assert pubsub.psubscribed == []


def test_event_stream_others_drops_the_admins_own_channel_and_keeps_the_rest(monkeypatch):
    admin = User(id=uuid.uuid4(), email="admin@example.com", is_admin=True)
    other = uuid.uuid4()
    messages = [
        (channel_for(other), '{"n": 1}'),
        (channel_for(admin.id), '{"n": 2}'),
        (channel_for(other), '{"n": 3}'),
    ]

    _, others_sent = _drive(monkeypatch, admin, "others", messages)
    _, all_sent = _drive(monkeypatch, admin, "all", messages)

    assert others_sent == ['data: {"n": 1}\n\n', 'data: {"n": 3}\n\n']
    assert all_sent == ['data: {"n": 1}\n\n', 'data: {"n": 2}\n\n', 'data: {"n": 3}\n\n']


def test_event_stream_others_heartbeats_through_a_run_of_dropped_messages(monkeypatch):
    """A steady run of the admin's own events, all dropped, must not keep the wire silent
    past the heartbeat interval (the tunnel closes an idle connection)."""
    admin = User(id=uuid.uuid4(), email="admin@example.com", is_admin=True)
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(stream_router.time, "monotonic", lambda: next(clock))
    messages = [(channel_for(admin.id), "{}")] * 4

    _, sent = _drive(monkeypatch, admin, "others", messages)

    assert sent and all(chunk == stream_router.HEARTBEAT for chunk in sent)


def test_the_heartbeat_is_an_event_page_javascript_receives():
    """v62 (F4): an SSE comment never reaches the page, so a quiet stream looked like a dead
    one. A named event with data is dispatched (to `addEventListener('heartbeat')` only);
    one with no data line isn't dispatched at all."""
    lines = stream_router.HEARTBEAT.split("\n")

    assert lines[0] == "event: heartbeat"
    assert lines[1].startswith("data: ") and lines[1] != "data: "
    assert stream_router.HEARTBEAT.endswith("\n\n")


def test_dropped_messages_never_stretch_the_wait_past_the_heartbeat(monkeypatch):
    """v62 (F4): the page restarts a stream silent for longer than the interval, so each wait
    is only the time left until the next heartbeat is due, not a fresh interval."""
    admin = User(id=uuid.uuid4(), email="admin@example.com", is_admin=True)
    # The module stream.py reads, not time.monotonic itself (asyncio's loop reads that too):
    # sent at 0, a dropped message at 4 and another at 9.
    clock = iter([0.0, 4.0, 4.0, 9.0, 9.0])
    monkeypatch.setattr(stream_router, "time", types.SimpleNamespace(monotonic=lambda: next(clock)))
    messages = [(channel_for(admin.id), "{}")] * 2

    pubsub, sent = _drive(monkeypatch, admin, "others", messages)

    assert pubsub.timeouts == [stream_router.HEARTBEAT_INTERVAL_SEC - 4.0, stream_router.HEARTBEAT_INTERVAL_SEC - 9.0]
    assert sent == []
