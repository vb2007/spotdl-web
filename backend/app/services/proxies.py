"""Proxy pool: file sync (`proxies.txt`), LRU selection, and per-proxy cooldown.

Mirrors app/services/retry.py's ladder shape but on a shorter cap — a bad proxy is usually
just swapped for another rather than nursed back with the full 24h track ladder.
"""

import contextlib
import logging
import re
import socket
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterator
from urllib.parse import urlsplit

from spotdl.providers.audio.ytmusic import YouTubeMusic
from sqlalchemy.orm import Session
from ytmusicapi import YTMusic

from app.config import get_settings
from app.db import SessionLocal
from app.models import Proxy, ProxySource
# v31's redact_text, moved to the dependency-free redaction module in v36 (the alert
# watchdog's own process uses it without importing spotdl); re-exported so every
# `proxies.redact_text` call site is unchanged.
from app.services.redaction import redact_text  # noqa: F401

if TYPE_CHECKING:
    from spotdl.download.downloader import Downloader

logger = logging.getLogger(__name__)

PROXY_COOLDOWN_LADDER = [timedelta(minutes=15), timedelta(hours=1), timedelta(hours=4)]

# spotdl 4.5.2's own accepted-proxy pattern, verified directly against the installed
# source (spotdl.download.downloader.Downloader.__init__) rather than assumed --
# literal IPv4 host required, hostnames and socks5:// are rejected. sync_from_file()
# deliberately does NOT enforce this (a malformed proxies.txt line is instead caught,
# and cooled down, the first time it's actually tried -- see that function's own
# docstring) since this could drift from spotdl's regex without anyone noticing in an
# unattended background sync. The manual-add UI form is a different context: a human
# typing into a live form benefits from immediate feedback, so *this* one entry point
# validates against it -- worst case a future spotdl loosening this regex means a
# technically-valid proxy is rejected here until this constant is refreshed, which is a
# far better failure mode than silently accepting anything.
PROXY_URL_RE = re.compile(
    r"^(http|https)://(?:(\w+)(?::(\w+))?@)?(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?$"
)


def next_cooldown(consecutive_failures_before: int) -> timedelta:
    """Same "failures before this one, computed before incrementing" convention as
    retry.next_delay — see CLAUDE.md's v06 ordering gotcha."""
    return PROXY_COOLDOWN_LADDER[min(consecutive_failures_before, len(PROXY_COOLDOWN_LADDER) - 1)]


def redact(url: str) -> str:
    """scheme://host:port for logging — never print a proxy URL's user:pass in plaintext."""
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"


_force_proxy_lock = threading.Lock()
_force_proxy_active = False


@contextlib.contextmanager
def force_proxy(proxy_url: str | None, downloader: "Downloader") -> Iterator[None]:
    """Makes ytmusicapi's search calls actually route through the configured proxy (v30).

    spotdl's own proxy wiring (Downloader.__init__ -> GlobalConfig.set_parameter) never
    reaches youtube-music, the only audio provider this app configures -- verified against
    the installed spotdl source, see v30's plan doc. YouTubeMusic._create_client is a bare
    staticmethod hardcoding `YTMusic(language="de")` with no proxies= argument.

    Patches two things, both required -- proven necessary by a real end-to-end run that
    caught this the classmethod-only version missed: get_downloader caches Downloader
    instances (and therefore their already-constructed YouTubeMusic providers) across
    attempts, and YouTubeMusic.__init__ builds `self.client` exactly once, at Downloader
    construction time -- which happens in download.py *before* this context is entered.
    Patching only the classmethod leaves that already-built client (real, unproxied)
    sitting on `downloader.audio_providers[N].client` for the entire attempt; a search
    that succeeds on its first try (the common case) never calls `_create_client()` again
    and so never picks up the patch at all.
    - The classmethod patch covers `YouTubeMusic.get_results`' own retry-on-empty-search
      path, which calls `self._create_client()` again for a fresh client mid-attempt.
    - The explicit `.client` swap below covers the already-built client for *this*
      specific attempt, restored to the original object on exit so a later attempt on
      this cached Downloader (direct, or via a different proxy) isn't left pointing at a
      stale proxied client.

    No-op for None, symmetric with network_path.force_family. Same non-reentrancy
    discipline and the same justification: process-global (the classmethod patch is),
    so two attempts wanting different proxies must never run concurrently in the same
    process (worker-dl's --concurrency=1 invariant makes this safe in practice) -- a
    separate lock from force_family's own, so the two compose regardless of whether
    today's ladder ever actually needs both active at once.
    """
    if proxy_url is None:
        yield
        return

    global _force_proxy_active
    with _force_proxy_lock:
        if _force_proxy_active:
            raise RuntimeError(
                "proxies.force_proxy: already active in this process -- "
                "worker-dl must run --concurrency=1 for this to be safe"
            )
        _force_proxy_active = True

    # Everything from here on must be inside this try/finally, not just the yield --
    # anything that can raise (patching the classmethod, walking audio_providers, building
    # a patched client) must not be able to leave _force_proxy_active stuck True forever,
    # which would permanently deadlock every subsequent attempt in this worker process via
    # the reentry guard above. Caught by a real unit test whose fake Downloader has no
    # audio_providers attribute at all -- the AttributeError used to escape before the
    # cleanup below ever ran.
    #
    # v31: accessed off the *class* like this, a staticmethod descriptor already unwraps
    # to the plain underlying function -- captured that way, not as a staticmethod object.
    # A real end-to-end run caught what every unit test missed: restoring it by assigning
    # that plain function straight back (`YouTubeMusic._create_client = previous_create_client`)
    # leaves a bare function sitting on the class, which is *itself* a descriptor -- the
    # next `self._create_client()` anywhere in the process implicitly binds `self` as a
    # first argument to a function defined to take none, permanently breaking every
    # download for the rest of the worker process's life after the first proxied
    # attempt succeeds, not just this one. Re-wrapped in `staticmethod(...)` below fixes it.
    previous_create_client = staticmethod(YouTubeMusic._create_client)
    patched_clients: list[tuple[YouTubeMusic, object]] = []
    try:
        def _patched_create_client() -> YTMusic:
            return YTMusic(language="de", proxies={"http": proxy_url, "https": proxy_url})

        YouTubeMusic._create_client = staticmethod(_patched_create_client)

        for provider in downloader.audio_providers:
            if isinstance(provider, YouTubeMusic):
                patched_clients.append((provider, provider.client))
                provider.client = _patched_create_client()

        yield
    finally:
        for provider, previous_client in patched_clients:
            provider.client = previous_client
        YouTubeMusic._create_client = previous_create_client
        with _force_proxy_lock:
            _force_proxy_active = False


def _probe_reachable(url: str, timeout: float = 2.0) -> bool:
    """Best-effort TCP connect so an obviously dead new entry doesn't get picked first —
    never raises, and an unparseable host/port is treated as reachable (don't block it)."""
    parsed = urlsplit(url)
    if not parsed.hostname or not parsed.port:
        return True
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=timeout):
            return True
    except OSError:
        return False


def sync_from_file() -> None:
    """Run once on worker-meta boot (see celery_app.py). Upserts proxies.txt's URLs as
    source=file rows and soft-disables (never deletes) source=file rows whose URL fell out
    of the file, preserving health history for a later re-add."""
    settings = get_settings()
    path = Path(settings.proxy_file)

    urls_in_file: set[str] = set()
    if path.is_file():
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            urls_in_file.add(stripped)
    else:
        # is_file() (rather than exists()) also covers a bind-mount source that doesn't
        # exist on the host yet — Docker silently creates an empty directory in that case
        # rather than erroring, which would otherwise crash read_text() with
        # IsADirectoryError.
        logger.warning("sync_from_file: %s is not a file, skipping proxy sync", path)
        return

    db = SessionLocal()
    try:
        existing = {p.url: p for p in db.query(Proxy).filter(Proxy.source == ProxySource.FILE).all()}

        added = 0
        re_enabled = 0
        for url in urls_in_file:
            row = existing.get(url)
            if row is None:
                proxy = Proxy(url=url, source=ProxySource.FILE, enabled=True)
                if not _probe_reachable(url):
                    proxy.cooldown_until = datetime.now(timezone.utc) + PROXY_COOLDOWN_LADDER[0]
                db.add(proxy)
                added += 1
            elif not row.enabled:
                row.enabled = True
                re_enabled += 1

        disabled = 0
        for url, row in existing.items():
            if url not in urls_in_file and row.enabled:
                row.enabled = False
                disabled += 1

        db.commit()
        logger.info(
            "sync_from_file: %d in file, %d added, %d re-enabled, %d disabled",
            len(urls_in_file),
            added,
            re_enabled,
            disabled,
        )
    finally:
        db.close()


def pick_proxy(db: Session) -> Proxy | None:
    """Least-recently-used selection among enabled, out-of-cooldown proxies — simple LRU,
    no scoring needed for a personal tool's handful of proxies. Comparisons happen in
    Python rather than a SQL filter, matching retry.py's naive/aware-datetime convention
    for SQLite test compatibility (a no-op against real Postgres/psycopg)."""
    now = datetime.now(timezone.utc)

    def _cooldown_over(proxy: Proxy) -> bool:
        cooldown_until = proxy.cooldown_until
        if cooldown_until is None:
            return True
        if cooldown_until.tzinfo is None:
            cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)
        return cooldown_until <= now

    candidates = [p for p in db.query(Proxy).filter(Proxy.enabled.is_(True)).all() if _cooldown_over(p)]
    if not candidates:
        return None

    def _sort_key(proxy: Proxy):
        last_used_at = proxy.last_used_at
        if last_used_at is not None and last_used_at.tzinfo is None:
            last_used_at = last_used_at.replace(tzinfo=timezone.utc)
        return (last_used_at is not None, last_used_at or datetime.min.replace(tzinfo=timezone.utc))

    candidates.sort(key=_sort_key)
    chosen = candidates[0]
    chosen.last_used_at = now
    return chosen


def record_proxy_result(db: Session, proxy_id: uuid.UUID, success: bool) -> None:
    proxy = db.get(Proxy, proxy_id)
    if proxy is None:
        return

    if success:
        proxy.consecutive_failures = 0
        proxy.last_success_at = datetime.now(timezone.utc)
        return

    delay = next_cooldown(proxy.consecutive_failures)
    proxy.consecutive_failures += 1
    proxy.cooldown_until = datetime.now(timezone.utc) + delay
