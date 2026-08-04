from app.models import Proxy, ProxySource
from app.routers import auth


def _login(client, monkeypatch):
    async def fake_login(email, password):
        return True

    monkeypatch.setattr(auth.upstream_auth, "login", fake_login)
    client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "x"})


def test_list_proxies_redacts_credentials_for_both_sources(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    db_session.add_all(
        [
            Proxy(url="http://user:pass@203.0.113.5:8080", source=ProxySource.FILE, enabled=True),
            Proxy(url="http://198.51.100.9:9090", source=ProxySource.MANUAL, enabled=False),
        ]
    )
    db_session.commit()

    response = client.get("/api/proxies")

    assert response.status_code == 200
    rows = {row["source"]: row for row in response.json()}
    assert rows["file"]["url"] == "http://203.0.113.5:8080"
    assert "user" not in rows["file"]["url"]
    assert "pass" not in rows["file"]["url"]
    assert rows["manual"]["url"] == "http://198.51.100.9:9090"
    assert rows["manual"]["enabled"] is False


def test_create_proxy_defaults_to_manual_source_and_enabled(client, db_session, monkeypatch):
    _login(client, monkeypatch)

    response = client.post("/api/proxies", json={"url": "http://203.0.113.5:8080"})

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "manual"
    assert body["enabled"] is True

    row = db_session.query(Proxy).one()
    assert row.url == "http://203.0.113.5:8080"
    assert row.source == ProxySource.MANUAL


def test_create_proxy_rejects_duplicate_url(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    db_session.add(Proxy(url="http://203.0.113.5:8080", source=ProxySource.FILE, enabled=True))
    db_session.commit()

    response = client.post("/api/proxies", json={"url": "http://203.0.113.5:8080"})

    assert response.status_code == 409


def test_create_proxy_rejects_blank_url(client, db_session, monkeypatch):
    _login(client, monkeypatch)

    response = client.post("/api/proxies", json={"url": "   "})

    assert response.status_code == 400


def test_update_proxy_toggles_enabled(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    proxy = Proxy(url="http://203.0.113.5:8080", source=ProxySource.MANUAL, enabled=True)
    db_session.add(proxy)
    db_session.commit()

    response = client.patch(f"/api/proxies/{proxy.id}", json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert db_session.get(Proxy, proxy.id).enabled is False


def test_update_unknown_proxy_is_404(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    import uuid

    response = client.patch(f"/api/proxies/{uuid.uuid4()}", json={"enabled": False})

    assert response.status_code == 404


def test_delete_proxy_soft_disables_without_dropping_row(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    proxy = Proxy(
        url="http://203.0.113.5:8080",
        source=ProxySource.MANUAL,
        enabled=True,
        consecutive_failures=4,
    )
    db_session.add(proxy)
    db_session.commit()

    response = client.delete(f"/api/proxies/{proxy.id}")

    assert response.status_code == 200
    assert response.json()["enabled"] is False

    row = db_session.get(Proxy, proxy.id)
    assert row is not None
    assert row.enabled is False
    assert row.consecutive_failures == 4


def test_proxies_endpoints_require_session(client):
    assert client.get("/api/proxies").status_code == 401
    assert client.post("/api/proxies", json={"url": "http://x:1"}).status_code == 401
