"""Proxy pool: file sync (`proxies.txt`), LRU selection, and per-proxy cooldown.

Mirrors app/services/retry.py's ladder shape but on a shorter cap — a bad proxy is usually
just swapped for another rather than nursed back with the full 24h track ladder.
"""

import logging
import socket
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import Proxy, ProxySource

logger = logging.getLogger(__name__)

PROXY_COOLDOWN_LADDER = [timedelta(minutes=15), timedelta(hours=1), timedelta(hours=4)]


def next_cooldown(consecutive_failures_before: int) -> timedelta:
    """Same "failures before this one, computed before incrementing" convention as
    retry.next_delay — see CLAUDE.md's v06 ordering gotcha."""
    return PROXY_COOLDOWN_LADDER[min(consecutive_failures_before, len(PROXY_COOLDOWN_LADDER) - 1)]


def redact(url: str) -> str:
    """scheme://host:port for logging — never print a proxy URL's user:pass in plaintext."""
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"


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
