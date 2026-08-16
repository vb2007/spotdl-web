"""v25: `upstream_auth.login` now also best-effort fetches the username via `GET /user`,
in the same login flow, using the VB-AUTH token extracted from the login response's raw
`Set-Cookie` header rather than httpx's own cookie jar (see the module docstring for
why -- COOKIE_TARGET_DOMAIN domain-matching). `httpx.MockTransport` stands in for the
real network so these exercise the actual request/response handling, not a mock of
`login` itself."""

import httpx
import pytest

from app.services import upstream_auth


def _install_transport(monkeypatch, handler) -> None:
    real_client_cls = httpx.AsyncClient

    def _client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client_with_mock_transport)


@pytest.mark.asyncio
async def test_login_success_fetches_username_using_extracted_cookie(monkeypatch):
    seen_cookie = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/login":
            return httpx.Response(
                200,
                headers=[("set-cookie", "VB-AUTH=tok123; Domain=localhost; Path=/; HttpOnly")],
            )
        assert request.url.path == "/user"
        seen_cookie["value"] = request.headers.get("cookie")
        return httpx.Response(200, json={"username": "cooluser", "email": "a@b.com"})

    _install_transport(monkeypatch, handler)

    ok, username = await upstream_auth.login("a@b.com", "pw")

    assert ok is True
    assert username == "cooluser"
    assert seen_cookie["value"] == "VB-AUTH=tok123"


@pytest.mark.asyncio
async def test_login_failure_never_calls_get_user(monkeypatch):
    called = {"user_endpoint_hit": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user":
            called["user_endpoint_hit"] = True
        return httpx.Response(403)

    _install_transport(monkeypatch, handler)

    ok, username = await upstream_auth.login("a@b.com", "wrong")

    assert ok is False
    assert username is None
    assert called["user_endpoint_hit"] is False


@pytest.mark.asyncio
async def test_get_user_failure_degrades_to_none_without_failing_login(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/login":
            return httpx.Response(200, headers=[("set-cookie", "VB-AUTH=tok123; Domain=localhost")])
        return httpx.Response(500)

    _install_transport(monkeypatch, handler)

    ok, username = await upstream_auth.login("a@b.com", "pw")

    assert ok is True
    assert username is None


@pytest.mark.asyncio
async def test_login_success_with_no_set_cookie_header_degrades_to_none(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/login"
        return httpx.Response(200)

    _install_transport(monkeypatch, handler)

    ok, username = await upstream_auth.login("a@b.com", "pw")

    assert ok is True
    assert username is None


@pytest.mark.asyncio
async def test_upstream_connection_error_returns_false_and_none(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _install_transport(monkeypatch, handler)

    ok, username = await upstream_auth.login("a@b.com", "pw")

    assert ok is False
    assert username is None
