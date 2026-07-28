from app.routers import auth


def _mock_upstream_login(monkeypatch, *, ok: bool) -> None:
    async def fake_login(email: str, password: str) -> bool:
        return ok

    monkeypatch.setattr(auth.upstream_auth, "login", fake_login)


def test_login_success_sets_cookie_and_me_returns_email(client, monkeypatch):
    _mock_upstream_login(monkeypatch, ok=True)

    response = client.post(
        "/api/auth/login", json={"email": "allowed@example.com", "password": "correct"}
    )

    assert response.status_code == 200
    assert response.json() == {"email": "allowed@example.com"}
    assert "SPOTDL_SESSION" in response.cookies

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json() == {"email": "allowed@example.com"}


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
