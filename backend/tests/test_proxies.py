import uuid
from datetime import datetime, timedelta, timezone

import pytest
from spotdl.providers.audio.ytmusic import YouTubeMusic

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


def test_redact_text_strips_a_credentialed_url_embedded_in_other_text():
    """v31: the exact-substring guard this replaces only caught a leak when the message
    contained the literal, already-known proxy_url string byte-for-byte -- this must
    catch it purely from shape, with no proxy_url to compare against at all."""
    message = (
        "ProxyError: Unable to connect via proxy http://scraper9:hunter2@203.0.113.5:8080 "
        "to music.youtube.com"
    )
    redacted = proxies.redact_text(message)
    assert "hunter2" not in redacted
    assert "scraper9" not in redacted
    assert "http://203.0.113.5:8080" in redacted


def test_redact_text_handles_a_url_with_no_port_or_no_credentials():
    assert "user:" not in proxies.redact_text("via http://user:pass@198.51.100.9")
    assert proxies.redact_text("via http://198.51.100.9:1234") == "via http://198.51.100.9:1234"


def test_redact_text_is_a_no_op_on_a_message_with_nothing_embedded():
    message = "AudioProviderError: YT-DLP download error - https://music.youtube.com/watch?v=x"
    assert proxies.redact_text(message) == message


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


def test_pick_proxy_selects_across_manual_and_file_sources_by_lru(db_session):
    """v13 shipped MANUAL-source (UI-added) proxies alongside FILE-source ones, both meant
    to be drawn from equally by pick_proxy -- but every existing test here only ever
    builds FILE rows, so the service layer had never actually exercised a MANUAL one
    (v14's audit, routed to v15). pick_proxy filters purely on enabled/cooldown and never
    branches on source, so this should just work; the point is proving it, not changing
    behavior."""
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Proxy(
                url="http://file-proxy",
                source=ProxySource.FILE,
                enabled=True,
                last_used_at=now,
            ),
            Proxy(url="http://manual-proxy", source=ProxySource.MANUAL, enabled=True),
        ]
    )
    db_session.commit()

    chosen = proxies.pick_proxy(db_session)

    assert chosen is not None
    assert chosen.url == "http://manual-proxy"
    assert chosen.source == ProxySource.MANUAL


def test_record_proxy_result_updates_a_manual_source_proxy(db_session):
    proxy = Proxy(url="http://manual-proxy", source=ProxySource.MANUAL, enabled=True)
    db_session.add(proxy)
    db_session.commit()

    proxies.record_proxy_result(db_session, proxy.id, success=True)
    db_session.commit()
    updated = db_session.get(Proxy, proxy.id)
    assert updated.consecutive_failures == 0
    assert updated.last_success_at is not None

    proxies.record_proxy_result(db_session, proxy.id, success=False)
    db_session.commit()
    updated = db_session.get(Proxy, proxy.id)
    assert updated.consecutive_failures == 1
    assert updated.cooldown_until is not None


def test_pick_proxy_skips_and_cools_down_a_proxy_that_refuses_tcp(db_session, monkeypatch):
    """v40.1: production's whole pool was dead, and every proxy-rung attempt was spent on
    one. An unreachable proxy is now cooled down at pick time and the next one is tried."""
    db_session.add_all(
        [
            Proxy(url="http://198.51.100.1:3128", source=ProxySource.FILE, enabled=True),
            Proxy(
                url="http://198.51.100.2:3128",
                source=ProxySource.FILE,
                enabled=True,
                last_used_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
        ]
    )
    db_session.commit()
    monkeypatch.setattr(
        proxies, "_probe_reachable", lambda url, timeout=2.0: url.endswith(".2:3128")
    )

    chosen = proxies.pick_proxy(db_session)
    db_session.commit()

    assert chosen.url == "http://198.51.100.2:3128"
    dead = db_session.query(Proxy).filter(Proxy.url == "http://198.51.100.1:3128").one()
    assert dead.consecutive_failures == 1
    assert dead.cooldown_until is not None
    assert chosen.consecutive_failures == 0
    assert chosen.cooldown_until is None


def test_pick_proxy_returns_none_when_every_proxy_refuses_tcp(db_session, monkeypatch):
    db_session.add_all(
        [
            Proxy(url="http://198.51.100.1:3128", source=ProxySource.FILE, enabled=True),
            Proxy(url="http://198.51.100.2:3128", source=ProxySource.MANUAL, enabled=True),
        ]
    )
    db_session.commit()
    monkeypatch.setattr(proxies, "_probe_reachable", lambda url, timeout=2.0: False)

    assert proxies.pick_proxy(db_session) is None
    db_session.commit()

    rows = db_session.query(Proxy).all()
    assert all(row.consecutive_failures == 1 and row.cooldown_until is not None for row in rows)
    # A second pick finds both cooling down, so it doesn't probe them again.
    monkeypatch.setattr(
        proxies, "_probe_reachable", lambda url, timeout=2.0: pytest.fail("probed a cooling proxy")
    )
    assert proxies.pick_proxy(db_session) is None


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


def test_connection_target_ignores_scheme_credentials_and_default_ports():
    target = proxies.connection_target
    assert target("http://u:p@203.0.113.5:8080") == "203.0.113.5:8080"
    assert target("https://203.0.113.5:8080") == "203.0.113.5:8080"
    assert target("http://203.0.113.5") == target("http://203.0.113.5:80") == "203.0.113.5:80"
    assert target("https://203.0.113.5") == "203.0.113.5:443"
    # Unparseable: its own target, never the raw line (a credential could be logged).
    secret = "secretpw"
    bad = target(f"http://user:{secret}@203.0.113.5:99999")
    assert bad.startswith("unparseable:") and secret not in bad
    assert bad == target(f"http://user:{secret}@203.0.113.5:99999")
    assert bad != target("http://other:pw@203.0.113.5:99999")
    assert secret not in target(f"user:{secret}@203.0.113.5:8080")


def test_sync_from_file_keeps_one_proxy_per_target(db_session, monkeypatch, tmp_path):
    """v44: the first line for a host:port wins; a later one is skipped, and a row it
    already had is disabled like a removed line. A manual proxy holds its target too."""
    monkeypatch.setattr(proxies, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(proxies, "_probe_reachable", lambda url, timeout=2.0: True)
    db_session.add_all(
        [
            Proxy(url="http://b:2@203.0.113.5:8080", source=ProxySource.FILE, enabled=True),
            Proxy(url="http://198.51.100.9:3128", source=ProxySource.MANUAL, enabled=False),
        ]
    )
    db_session.commit()

    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text(
        "http://a:1@203.0.113.5:8080\nhttp://b:2@203.0.113.5:8080\n"
        "http://c:3@198.51.100.9:3128\nhttp://192.0.2.7:8080\nhttp://192.0.2.7:8080\n"
    )
    monkeypatch.setattr(proxies, "get_settings", lambda: _FakeSettings(proxy_file))

    proxies.sync_from_file()

    rows = {p.url: p for p in db_session.query(Proxy).all()}
    assert set(rows) == {
        "http://a:1@203.0.113.5:8080",
        "http://b:2@203.0.113.5:8080",
        "http://198.51.100.9:3128",
        "http://192.0.2.7:8080",
    }
    assert rows["http://a:1@203.0.113.5:8080"].enabled is True
    assert rows["http://b:2@203.0.113.5:8080"].enabled is False
    assert rows["http://198.51.100.9:3128"].source == ProxySource.MANUAL
    assert rows["http://192.0.2.7:8080"].enabled is True


def test_sync_from_file_rotates_a_credential_in_place(db_session, monkeypatch, tmp_path):
    """A new credential for a target whose old line left the file is the same proxy:
    one row, its history kept, never a second row for the target."""
    monkeypatch.setattr(proxies, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(proxies, "_probe_reachable", lambda url, timeout=2.0: True)
    old = Proxy(
        url="http://old:pw@203.0.113.5:8080",
        source=ProxySource.FILE,
        enabled=False,
        consecutive_failures=4,
        last_success_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    db_session.add(old)
    db_session.commit()

    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("http://new:pw@203.0.113.5:8080\n")
    monkeypatch.setattr(proxies, "get_settings", lambda: _FakeSettings(proxy_file))

    proxies.sync_from_file()

    rows = db_session.query(Proxy).all()
    assert [row.id for row in rows] == [old.id]
    assert rows[0].url == "http://new:pw@203.0.113.5:8080"
    assert rows[0].enabled is True
    # The new credential starts clean; when the proxy last worked is kept.
    assert rows[0].consecutive_failures == 0
    assert rows[0].cooldown_until is None
    assert rows[0].last_success_at is not None


def test_sync_from_file_rotation_keeps_the_live_row_of_two_old_duplicates(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(proxies, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(proxies, "_probe_reachable", lambda url, timeout=2.0: True)
    parked = Proxy(url="http://a:1@203.0.113.5:8080", source=ProxySource.FILE, enabled=False)
    live = Proxy(
        url="http://b:2@203.0.113.5:8080",
        source=ProxySource.FILE,
        enabled=True,
        last_success_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    db_session.add_all([parked, live])
    db_session.commit()

    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("http://c:3@203.0.113.5:8080\n")
    monkeypatch.setattr(proxies, "get_settings", lambda: _FakeSettings(proxy_file))

    proxies.sync_from_file()

    assert db_session.get(Proxy, live.id).url == "http://c:3@203.0.113.5:8080"
    assert db_session.get(Proxy, live.id).enabled is True
    assert db_session.get(Proxy, parked.id).enabled is False


def test_sync_from_file_never_logs_a_skipped_lines_credential(db_session, monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(proxies, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(proxies, "_probe_reachable", lambda url, timeout=2.0: True)
    proxy_file = tmp_path / "proxies.txt"
    # Generated, so no credential-shaped literal reaches a commit (a secret scanner flags
    # even fake ones).
    secrets = [uuid.uuid4().hex[:10] for _ in range(4)]
    proxy_file.write_text(
        f"http://{secrets[0]}:{secrets[1]}@203.0.113.5:8080\n"
        f"http://{secrets[2]}:{secrets[3]}@203.0.113.5:8080\n"
    )
    monkeypatch.setattr(proxies, "get_settings", lambda: _FakeSettings(proxy_file))

    with caplog.at_level("INFO", logger=proxies.logger.name):
        proxies.sync_from_file()

    assert "203.0.113.5:8080" in caplog.text
    assert "1 skipped" in caplog.text
    for secret in secrets:
        assert secret not in caplog.text


class _FakeDownloaderForProxy:
    """Stands in for spotdl's Downloader -- force_proxy only ever touches
    .audio_providers, so that's all this needs."""

    def __init__(self, audio_providers):
        self.audio_providers = audio_providers


def _fake_youtube_music_provider(client):
    # A real YouTubeMusic instance built without calling __init__ (which would try a real
    # network call via _create_client) -- isinstance(provider, YouTubeMusic) is exactly
    # what force_proxy checks, so this has to be the real class, not a stand-in.
    provider = YouTubeMusic.__new__(YouTubeMusic)
    provider.client = client
    return provider


def test_force_proxy_none_is_a_noop():
    original = YouTubeMusic._create_client
    provider = _fake_youtube_music_provider(client="original-client")
    downloader = _FakeDownloaderForProxy(audio_providers=[provider])

    with proxies.force_proxy(None, downloader):
        assert YouTubeMusic._create_client is original
        assert provider.client == "original-client"

    assert YouTubeMusic._create_client is original
    assert provider.client == "original-client"


def test_force_proxy_patches_create_client_with_the_given_proxy(monkeypatch):
    seen = []

    def _fake_ytmusic(*, language, proxies=None):
        seen.append((language, proxies))
        return "fake-client"

    monkeypatch.setattr(proxies, "YTMusic", _fake_ytmusic)
    original = YouTubeMusic._create_client
    downloader = _FakeDownloaderForProxy(audio_providers=[])

    with proxies.force_proxy("http://user:pass@203.0.113.5:8080", downloader):
        client = YouTubeMusic._create_client()

    assert client == "fake-client"
    assert seen == [
        (
            "de",
            {
                "http": "http://user:pass@203.0.113.5:8080",
                "https": "http://user:pass@203.0.113.5:8080",
            },
        )
    ]
    assert YouTubeMusic._create_client is original


def test_force_proxy_leaves_create_client_callable_as_an_instance_method_after_exit(monkeypatch):
    """v31: a real end-to-end run caught this, no unit test did -- every existing test here
    calls `YouTubeMusic._create_client()` off the *class*, which stays a callable either way.
    The actual bug only shows up calling it the way spotdl's own retry-rebuild path does:
    `self._create_client()` off a real *instance*, with no arguments. The old restore
    (`YouTubeMusic._create_client = previous_create_client`, capturing the plain function a
    staticmethod unwraps to when read off the class) left a bare function sitting on the
    class -- itself a descriptor, so the next instance call implicitly binds `self` as an
    unwanted first argument. Confirmed live: every download in the process failed with
    `_create_client() takes 0 positional arguments but 1 was given` immediately after the
    first real proxied attempt succeeded anywhere in that worker."""

    def _fake_ytmusic(*, language, proxies=None):
        return "fake-client"

    monkeypatch.setattr(proxies, "YTMusic", _fake_ytmusic)
    downloader = _FakeDownloaderForProxy(audio_providers=[])

    with proxies.force_proxy("http://203.0.113.5:8080", downloader):
        pass

    provider = _fake_youtube_music_provider(client="whatever")
    assert provider._create_client() is not None


def test_force_proxy_swaps_an_already_constructed_providers_client(monkeypatch):
    # The real bug this version's end-to-end proof caught: get_downloader caches
    # Downloaders (and their providers) across attempts, and YouTubeMusic.__init__ builds
    # self.client exactly once, at construction time -- before this context is ever
    # entered. Patching only the classmethod left that already-built, unproxied client on
    # the provider for the whole attempt, since a search that succeeds on its first try
    # never calls _create_client() again. force_proxy must swap the *existing* client too.
    monkeypatch.setattr(proxies, "YTMusic", lambda **kwargs: kwargs)
    provider = _fake_youtube_music_provider(client="original-unproxied-client")
    downloader = _FakeDownloaderForProxy(audio_providers=[provider])

    with proxies.force_proxy("http://203.0.113.5:8080", downloader):
        assert provider.client == {
            "language": "de",
            "proxies": {"http": "http://203.0.113.5:8080", "https": "http://203.0.113.5:8080"},
        }

    assert provider.client == "original-unproxied-client"


def test_force_proxy_only_swaps_youtube_music_providers(monkeypatch):
    monkeypatch.setattr(proxies, "YTMusic", lambda **kwargs: "proxied-client")
    provider = _fake_youtube_music_provider(client="original-client")
    non_ytmusic_provider = object()
    downloader = _FakeDownloaderForProxy(audio_providers=[provider, non_ytmusic_provider])

    with proxies.force_proxy("http://203.0.113.5:8080", downloader):
        assert provider.client == "proxied-client"
        # Untouched -- not a YouTubeMusic instance, nothing to swap.
        assert not hasattr(non_ytmusic_provider, "client")

    assert provider.client == "original-client"


def test_force_proxy_restores_create_client_after_exception(monkeypatch):
    monkeypatch.setattr(proxies, "YTMusic", lambda **kwargs: "fake-client")
    original = YouTubeMusic._create_client
    downloader = _FakeDownloaderForProxy(audio_providers=[])

    with pytest.raises(ValueError):
        with proxies.force_proxy("http://203.0.113.5:8080", downloader):
            raise ValueError("boom mid-search")

    assert YouTubeMusic._create_client is original


def test_force_proxy_restores_client_after_exception(monkeypatch):
    monkeypatch.setattr(proxies, "YTMusic", lambda **kwargs: "proxied-client")
    provider = _fake_youtube_music_provider(client="original-client")
    downloader = _FakeDownloaderForProxy(audio_providers=[provider])

    with pytest.raises(ValueError):
        with proxies.force_proxy("http://203.0.113.5:8080", downloader):
            assert provider.client == "proxied-client"
            raise ValueError("boom mid-search")

    assert provider.client == "original-client"


def test_force_proxy_rejects_reentry():
    downloader = _FakeDownloaderForProxy(audio_providers=[])
    with proxies.force_proxy("http://203.0.113.5:8080", downloader):
        with pytest.raises(RuntimeError):
            with proxies.force_proxy("http://203.0.113.6:8080", downloader):
                pass


def test_force_proxy_releases_the_reentry_guard_even_if_the_downloader_has_no_audio_providers():
    # Regression: a real Downloader always has .audio_providers, but the first version of
    # this fix only wrapped `yield` in try/finally -- an AttributeError walking
    # downloader.audio_providers (as a bare object without that attribute raises) escaped
    # before the cleanup ran, leaving _force_proxy_active stuck True forever and
    # deadlocking every subsequent attempt in the process via the reentry guard above.
    downloader_without_providers = object()

    with pytest.raises(AttributeError):
        with proxies.force_proxy("http://203.0.113.5:8080", downloader_without_providers):
            pass

    # Must not be stuck active -- a following attempt (even a no-op direct one) must work.
    with proxies.force_proxy(None, downloader_without_providers):
        pass
