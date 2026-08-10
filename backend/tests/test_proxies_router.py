import uuid

from app.models import Proxy, ProxySource


def test_list_proxies_redacts_credentials_for_both_sources(admin_client, db_session):
    db_session.add_all(
        [
            Proxy(url="http://user:pass@203.0.113.5:8080", source=ProxySource.FILE, enabled=True),
            Proxy(url="http://198.51.100.9:9090", source=ProxySource.MANUAL, enabled=False),
        ]
    )
    db_session.commit()

    response = admin_client.get("/api/proxies")

    assert response.status_code == 200
    rows = {row["source"]: row for row in response.json()}
    assert rows["file"]["url"] == "http://203.0.113.5:8080"
    assert "user" not in rows["file"]["url"]
    assert "pass" not in rows["file"]["url"]
    assert rows["manual"]["url"] == "http://198.51.100.9:9090"
    assert rows["manual"]["enabled"] is False


def test_create_proxy_defaults_to_manual_source_and_enabled(admin_client, db_session):
    response = admin_client.post("/api/proxies", json={"url": "http://203.0.113.5:8080"})

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "manual"
    assert body["enabled"] is True

    row = db_session.query(Proxy).one()
    assert row.url == "http://203.0.113.5:8080"
    assert row.source == ProxySource.MANUAL


def test_create_proxy_rejects_duplicate_url(admin_client, db_session):
    db_session.add(Proxy(url="http://203.0.113.5:8080", source=ProxySource.FILE, enabled=True))
    db_session.commit()

    response = admin_client.post("/api/proxies", json={"url": "http://203.0.113.5:8080"})

    assert response.status_code == 409


def test_create_proxy_rejects_blank_url(admin_client, db_session):
    response = admin_client.post("/api/proxies", json={"url": "   "})

    assert response.status_code == 400


def test_create_proxy_rejects_malformed_url(admin_client, db_session):
    # A hostname (not a literal IPv4) and a socks5:// scheme are both real formats
    # spotdl's own Downloader rejects (see proxies.PROXY_URL_RE's docstring) -- these
    # must never reach the DB as an entry that will only fail once actually tried.
    for bad_url in ["http://proxy.example.com:8080", "socks5://203.0.113.5:1080"]:
        response = admin_client.post("/api/proxies", json={"url": bad_url})
        assert response.status_code == 400, bad_url

    assert db_session.query(Proxy).count() == 0


def test_create_proxy_accepts_well_formed_url(admin_client, db_session):
    response = admin_client.post("/api/proxies", json={"url": "http://user:pass@203.0.113.5:8080"})

    assert response.status_code == 201


def test_update_proxy_toggles_enabled(admin_client, db_session):
    proxy = Proxy(url="http://203.0.113.5:8080", source=ProxySource.MANUAL, enabled=True)
    db_session.add(proxy)
    db_session.commit()

    response = admin_client.patch(f"/api/proxies/{proxy.id}", json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert db_session.get(Proxy, proxy.id).enabled is False


def test_update_unknown_proxy_is_404(admin_client, db_session):
    response = admin_client.patch(f"/api/proxies/{uuid.uuid4()}", json={"enabled": False})

    assert response.status_code == 404


def test_delete_manual_proxy_hard_deletes_the_row(admin_client, db_session):
    # Original v13 behavior (soft-disable for every source) left a manual proxy
    # permanently disabled with no way to actually remove it -- a real UX dead end
    # caught in manual testing, since nothing (no proxies.txt entry) would ever bring it
    # back. A manual proxy's "remove" must really remove it.
    proxy = Proxy(
        url="http://203.0.113.5:8080",
        source=ProxySource.MANUAL,
        enabled=True,
        consecutive_failures=4,
    )
    db_session.add(proxy)
    db_session.commit()

    response = admin_client.delete(f"/api/proxies/{proxy.id}")

    assert response.status_code == 204
    assert db_session.get(Proxy, proxy.id) is None


def test_delete_file_proxy_soft_disables_without_dropping_row(admin_client, db_session):
    # A source=file row keeps the original soft-delete: the file is still the real
    # source of truth for it, and sync_from_file() re-enables it (preserving stats) as
    # long as it's still listed in proxies.txt -- matches v07's never-hard-delete stance.
    proxy = Proxy(
        url="http://203.0.113.5:8080",
        source=ProxySource.FILE,
        enabled=True,
        consecutive_failures=4,
    )
    db_session.add(proxy)
    db_session.commit()

    response = admin_client.delete(f"/api/proxies/{proxy.id}")

    assert response.status_code == 200
    assert response.json()["enabled"] is False

    row = db_session.get(Proxy, proxy.id)
    assert row is not None
    assert row.enabled is False
    assert row.consecutive_failures == 4


def test_proxies_endpoints_require_session(client):
    assert client.get("/api/proxies").status_code == 401
    assert client.post("/api/proxies", json={"url": "http://x:1"}).status_code == 401


def test_proxies_endpoints_reject_non_admin(authenticated_client):
    assert authenticated_client.get("/api/proxies").status_code == 403
    assert authenticated_client.post("/api/proxies", json={"url": "http://x:1"}).status_code == 403
