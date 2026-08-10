import asyncio
import uuid

import redis.asyncio as aioredis

from app.models import User
from app.routers import stream as stream_router
from app.services.events import ADMIN_CHANNEL_PATTERN, channel_for


async def _fake_event_stream(request, user, all_users):
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
    async def is_disconnected(self) -> bool:
        # Ends the loop after the (p)subscribe call, before any get_message wait --
        # these tests are about which channel gets subscribed to, not the forward loop.
        return True


class _FakePubSub:
    def __init__(self):
        self.subscribed: list[str] = []
        self.psubscribed: list[str] = []

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def psubscribe(self, pattern: str) -> None:
        self.psubscribed.append(pattern)

    async def unsubscribe(self, channel: str) -> None:
        pass

    async def punsubscribe(self, pattern: str) -> None:
        pass

    async def get_message(self, **kwargs) -> None:
        return None

    async def aclose(self) -> None:
        pass


class _FakeRedisClient:
    def __init__(self):
        self._pubsub = _FakePubSub()

    def pubsub(self) -> _FakePubSub:
        return self._pubsub

    async def aclose(self) -> None:
        pass


def _drive(monkeypatch, user: User, all_users: bool) -> _FakePubSub:
    fake_client = _FakeRedisClient()
    monkeypatch.setattr(aioredis.Redis, "from_url", lambda url: fake_client)

    async def _run():
        async for _ in stream_router._event_stream(_FakeRequest(), user, all_users):
            pass

    asyncio.run(_run())
    return fake_client._pubsub


def test_event_stream_subscribes_to_the_users_own_channel(monkeypatch):
    user = User(id=uuid.uuid4(), email="a@example.com", is_admin=False)

    pubsub = _drive(monkeypatch, user, all_users=False)

    assert pubsub.subscribed == [channel_for(user.id)]
    assert pubsub.psubscribed == []


def test_event_stream_admin_all_users_psubscribes_to_the_admin_pattern(monkeypatch):
    admin = User(id=uuid.uuid4(), email="admin@example.com", is_admin=True)

    pubsub = _drive(monkeypatch, admin, all_users=True)

    assert pubsub.psubscribed == [ADMIN_CHANNEL_PATTERN]
    assert pubsub.subscribed == []


def test_event_stream_non_admin_all_users_flag_is_ignored(monkeypatch):
    """v17's threat model: a client-supplied scope flag is never trusted -- a non-admin
    passing all_users=true still only ever gets their own channel."""
    user = User(id=uuid.uuid4(), email="a@example.com", is_admin=False)

    pubsub = _drive(monkeypatch, user, all_users=True)

    assert pubsub.subscribed == [channel_for(user.id)]
    assert pubsub.psubscribed == []
