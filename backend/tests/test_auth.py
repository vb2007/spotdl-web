import httpx

from app.routers import auth


def _mock_upstream_login(monkeypatch, *, ok: bool, username: str | None = None) -> None:
    async def fake_login(email: str, password: str) -> tuple[bool, str | None]:
        return ok, username

    monkeypatch.setattr(auth.upstream_auth, "login", fake_login)


def test_login_success_sets_cookie_and_me_returns_email(client, monkeypatch):
    _mock_upstream_login(monkeypatch, ok=True)

    response = client.post(
        "/api/auth/login", json={"email": "allowed@example.com", "password": "correct"}
    )

    assert response.status_code == 200
    assert response.json() == {"email": "allowed@example.com", "username": None, "is_admin": False}
    assert "SPOTDL_SESSION" in response.cookies

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json() == {"email": "allowed@example.com", "username": None, "is_admin": False}


def test_login_stores_and_returns_username_from_upstream(client, monkeypatch):
    _mock_upstream_login(monkeypatch, ok=True, username="cooluser")

    response = client.post(
        "/api/auth/login", json={"email": "allowed@example.com", "password": "correct"}
    )

    assert response.status_code == 200
    assert response.json()["username"] == "cooluser"

    me_response = client.get("/api/auth/me")
    assert me_response.json()["username"] == "cooluser"


def test_login_with_failed_username_fetch_falls_back_to_email_and_still_succeeds(client, monkeypatch):
    """upstream_auth.login degrades gracefully (username=None) when GET /user fails --
    the login itself must still succeed and the frontend falls back to displaying
    email."""
    _mock_upstream_login(monkeypatch, ok=True, username=None)

    response = client.post(
        "/api/auth/login", json={"email": "allowed@example.com", "password": "correct"}
    )

    assert response.status_code == 200
    assert response.json()["username"] is None
    assert response.json()["email"] == "allowed@example.com"


def test_second_login_with_new_username_overwrites_stale_one(client, monkeypatch):
    """A username changed upstream must propagate on the next login (same reconciliation
    pattern as is_admin)."""
    _mock_upstream_login(monkeypatch, ok=True, username="oldname")
    client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "correct"})

    _mock_upstream_login(monkeypatch, ok=True, username="newname")
    response = client.post(
        "/api/auth/login", json={"email": "allowed@example.com", "password": "correct"}
    )

    assert response.json()["username"] == "newname"

    # A subsequent login whose username fetch fails keeps the last known-good value,
    # rather than nulling it out.
    _mock_upstream_login(monkeypatch, ok=True, username=None)
    response = client.post(
        "/api/auth/login", json={"email": "allowed@example.com", "password": "correct"}
    )
    assert response.json()["username"] == "newname"


def test_login_end_to_end_through_real_cookie_extraction_path_never_leaks_vb_auth(client, monkeypatch):
    """Unlike every other test in this file, this does NOT mock `upstream_auth.login` --
    it patches the underlying `httpx.AsyncClient` (via `httpx.MockTransport`) so the real
    `_fetch_username`/cookie-extraction code actually runs, then asserts on the real
    `/api/auth/login` FastAPI response. Closes the gap where every other test only proves
    VB-AUTH doesn't leak when the extraction code never executes at all."""
    real_client_cls = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/login":
            return httpx.Response(
                200, headers=[("set-cookie", "VB-AUTH=realtok456; Domain=localhost; HttpOnly")]
            )
        assert request.headers.get("cookie") == "VB-AUTH=realtok456"
        return httpx.Response(200, json={"username": "realuser", "email": "allowed@example.com"})

    def _client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client_with_mock_transport)

    response = client.post(
        "/api/auth/login", json={"email": "allowed@example.com", "password": "correct"}
    )

    assert response.status_code == 200
    assert response.json()["username"] == "realuser"
    assert "VB-AUTH" not in response.headers.get("set-cookie", "")
    assert "realtok456" not in response.text
    assert "VB-AUTH" not in response.text


def test_wrong_password_and_disallowed_email_return_identical_response(client, monkeypatch):
    _mock_upstream_login(monkeypatch, ok=False)
    wrong_password = client.post(
        "/api/auth/login", json={"email": "allowed@example.com", "password": "wrong"}
    )

    _mock_upstream_login(monkeypatch, ok=True)
    not_allowed = client.post(
        "/api/auth/login", json={"email": "someone-else@example.com", "password": "correct"}
    )

    assert wrong_password.status_code == not_allowed.status_code == 401
    assert wrong_password.json() == not_allowed.json()
    assert "SPOTDL_SESSION" not in wrong_password.cookies
    assert "SPOTDL_SESSION" not in not_allowed.cookies


def test_vb_auth_cookie_never_reaches_the_browser(client, monkeypatch):
    _mock_upstream_login(monkeypatch, ok=True)

    response = client.post(
        "/api/auth/login", json={"email": "allowed@example.com", "password": "correct"}
    )

    assert "VB-AUTH" not in response.headers.get("set-cookie", "")
    assert "VB-AUTH" not in response.text


def test_protected_route_without_session_returns_401(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_logout_clears_session(client, monkeypatch):
    _mock_upstream_login(monkeypatch, ok=True)
    client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "correct"})

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 401
