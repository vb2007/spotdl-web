from datetime import datetime, timedelta, timezone

from app.models import Proxy, ProxySource
from app.services import proxies


class _NonClosingSession:
    """Wraps db_session so sync_from_file's db.close() doesn't detach objects the test
    still needs to assert against — the fixture handles real teardown instead."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


def _aware(dt: datetime) -> datetime:
    # SQLite (used for these in-process tests, see v02/v03 gotchas) round-trips a
    # timestamptz column as a naive datetime; a no-op against real Postgres/psycopg.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class _FakeSettings:
    def __init__(self, proxy_file):
        self.proxy_file = str(proxy_file)


def test_redact_strips_credentials():
    assert proxies.redact("http://user:pass@203.0.113.5:8080") == "http://203.0.113.5:8080"
    assert proxies.redact("http://203.0.113.5:8080") == "http://203.0.113.5:8080"


def test_next_cooldown_follows_ladder_and_caps_at_final_step():
    assert proxies.next_cooldown(0) == timedelta(minutes=15)
    assert proxies.next_cooldown(1) == timedelta(hours=1)
    assert proxies.next_cooldown(2) == timedelta(hours=4)
    assert proxies.next_cooldown(10) == timedelta(hours=4)


def test_pick_proxy_returns_none_when_pool_is_empty(db_session):
    assert proxies.pick_proxy(db_session) is None


def test_pick_proxy_skips_disabled_and_cooled_down(db_session):
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Proxy(url="http://disabled", source=ProxySource.FILE, enabled=False),
            Proxy(
                url="http://cooling",
                source=ProxySource.FILE,
                enabled=True,
                cooldown_until=now + timedelta(hours=1),
            ),
            Proxy(url="http://healthy", source=ProxySource.FILE, enabled=True),
        ]
    )
    db_session.commit()

    chosen = proxies.pick_proxy(db_session)

    assert chosen is not None
    assert chosen.url == "http://healthy"


def test_pick_proxy_prefers_never_used_then_oldest_last_used_at(db_session):
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Proxy(url="http://recent", source=ProxySource.FILE, enabled=True, last_used_at=now),
            Proxy(
                url="http://stale",
                source=ProxySource.FILE,
                enabled=True,
                last_used_at=now - timedelta(hours=1),
            ),
            Proxy(url="http://never-used", source=ProxySource.FILE, enabled=True),
        ]
    )
    db_session.commit()

    chosen = proxies.pick_proxy(db_session)
    assert chosen.url == "http://never-used"


def test_pick_proxy_stamps_last_used_at_on_selection(db_session):
    before = datetime.now(timezone.utc)
    proxy = Proxy(url="http://healthy", source=ProxySource.FILE, enabled=True)
    db_session.add(proxy)
    db_session.commit()

    chosen = proxies.pick_proxy(db_session)
    db_session.commit()

    assert chosen is not None
    assert _aware(chosen.last_used_at) >= before


def test_record_proxy_result_success_resets_failure_count(db_session):
    proxy = Proxy(
        url="http://flaky",
        source=ProxySource.FILE,
        enabled=True,
        consecutive_failures=2,
    )
    db_session.add(proxy)
    db_session.commit()

    proxies.record_proxy_result(db_session, proxy.id, success=True)
    db_session.commit()

    updated = db_session.get(Proxy, proxy.id)
    assert updated.consecutive_failures == 0
    assert updated.last_success_at is not None


def test_record_proxy_result_failure_sets_cooldown_and_increments(db_session):
    proxy = Proxy(url="http://flaky", source=ProxySource.FILE, enabled=True)
    db_session.add(proxy)
    db_session.commit()
    before = datetime.now(timezone.utc)

    proxies.record_proxy_result(db_session, proxy.id, success=False)
    db_session.commit()

    updated = db_session.get(Proxy, proxy.id)
    assert updated.consecutive_failures == 1
    assert updated.cooldown_until is not None
    assert _aware(updated.cooldown_until) - before >= timedelta(minutes=14)


def test_record_proxy_result_failure_reads_ladder_before_incrementing(db_session):
    # Mirrors retry.py's "computed before incrementing" ordering gotcha: the second
    # failure should use the ladder's second rung (1h), not skip straight past it.
    proxy = Proxy(url="http://flaky", source=ProxySource.FILE, enabled=True, consecutive_failures=1)
    db_session.add(proxy)
    db_session.commit()
    before = datetime.now(timezone.utc)

    proxies.record_proxy_result(db_session, proxy.id, success=False)
    db_session.commit()

    updated = db_session.get(Proxy, proxy.id)
    assert updated.consecutive_failures == 2
    assert _aware(updated.cooldown_until) - before >= timedelta(minutes=59)


def test_record_proxy_result_unknown_proxy_is_a_noop(db_session):
    import uuid

    proxies.record_proxy_result(db_session, uuid.uuid4(), success=True)
    db_session.commit()


def test_sync_from_file_adds_new_and_disables_removed(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(proxies, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(proxies, "_probe_reachable", lambda url, timeout=2.0: True)

    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("# comment\nhttp://one\n\nhttp://two\n")
    monkeypatch.setattr(proxies, "get_settings", lambda: _FakeSettings(proxy_file))

    proxies.sync_from_file()

    rows = {p.url: p for p in db_session.query(Proxy).all()}
    assert set(rows) == {"http://one", "http://two"}
    assert all(row.enabled for row in rows.values())
    assert all(row.source == ProxySource.FILE for row in rows.values())

    # Editing the file to drop "http://two" and add "http://three" should disable the
    # removed one (soft delete) without resetting its historical stats, and enable the
    # new one.
    rows["http://two"].consecutive_failures = 7
    db_session.commit()

    proxy_file.write_text("http://one\nhttp://three\n")
    proxies.sync_from_file()

    rows = {p.url: p for p in db_session.query(Proxy).all()}
    assert rows["http://one"].enabled is True
    assert rows["http://two"].enabled is False
    assert rows["http://two"].consecutive_failures == 7
    assert rows["http://three"].enabled is True


def test_sync_from_file_re_enables_without_resetting_stats(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(proxies, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(proxies, "_probe_reachable", lambda url, timeout=2.0: True)

    existing = Proxy(
        url="http://one",
        source=ProxySource.FILE,
        enabled=False,
        consecutive_failures=3,
    )
    db_session.add(existing)
    db_session.commit()

    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("http://one\n")
    monkeypatch.setattr(proxies, "get_settings", lambda: _FakeSettings(proxy_file))

    proxies.sync_from_file()

    updated = db_session.get(Proxy, existing.id)
    assert updated.enabled is True
    assert updated.consecutive_failures == 3


def test_sync_from_file_missing_file_is_a_noop(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(proxies, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(proxies, "get_settings", lambda: _FakeSettings(tmp_path / "does-not-exist.txt"))

    proxies.sync_from_file()

    assert db_session.query(Proxy).count() == 0


def test_sync_from_file_marks_unreachable_new_proxy_with_cooldown(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(proxies, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(proxies, "_probe_reachable", lambda url, timeout=2.0: False)

    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("http://dead\n")
    monkeypatch.setattr(proxies, "get_settings", lambda: _FakeSettings(proxy_file))

    proxies.sync_from_file()

    row = db_session.query(Proxy).filter(Proxy.url == "http://dead").one()
    assert row.enabled is True
    assert row.cooldown_until is not None
