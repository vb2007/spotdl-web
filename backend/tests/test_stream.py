from app.routers import auth
from app.routers import stream as stream_router


def _login(client, monkeypatch):
    async def fake_login(email, password):
        return True

    monkeypatch.setattr(auth.upstream_auth, "login", fake_login)
    client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "x"})


async def _fake_event_stream(request):
    yield 'data: {"type": "track.state", "state": "downloading"}\n\n'


def test_stream_requires_session(client):
    response = client.get("/api/stream")
    assert response.status_code == 401


def test_stream_returns_sse_headers_and_forwarded_events(client, monkeypatch):
    _login(client, monkeypatch)
    # Swaps out the real Redis-subscribing generator for a finite one — the actual
    # subscribe/forward/heartbeat loop against a real Redis instance is covered by this
    # version's real-stack curl verification (see CLAUDE.md's v08 notes), not here; a real
    # generator never terminates on its own; and a plain (non-streaming) TestClient.get()
    # can't safely give up waiting for a real Redis message.
    monkeypatch.setattr(stream_router, "_event_stream", _fake_event_stream)

    response = client.get("/api/stream")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "track.state" in response.text
