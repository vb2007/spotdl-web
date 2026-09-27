"""Forces yt-dlp's and ytmusicapi's separate HTTP stacks onto one IP family (v29).

Two independent mechanisms cover the two stacks, because only one of them exposes a
family-forcing knob:

- yt-dlp's own requests: `Downloader`'s `yt_dlp_args` is baked in at *construction* time
  (see downloads.get_downloader), so a Downloader built for one family must never be
  reused for the other -- that's why `family` is part of get_downloader's cache key.
- ytmusicapi's search calls: spotdl hardcodes `YTMusic(language="de")` with no session/
  family override (verified against the installed source), so there is no per-call knob
  to pass. `force_family` instead monkeypatches `socket.getaddrinfo` for the duration of
  the call, restricting every DNS resolution -- ytmusicapi's and yt-dlp's alike -- to the
  forced family. This is only safe because worker-dl runs `--concurrency=1`
  (CLAUDE.md invariant): the patch is process-global, so two attempts wanting different
  families must never run concurrently in the same process. `_active_lock` turns a
  violation of that invariant into a loud `RuntimeError` instead of one attempt silently
  leaking its forced family into another's.
"""

import contextlib
import socket
import threading
from typing import Iterator

from app.models import NetworkPath

_FAMILY_BY_PATH = {
    NetworkPath.DIRECT_IPV4: socket.AF_INET,
    NetworkPath.DIRECT_IPV6: socket.AF_INET6,
}

_real_getaddrinfo = socket.getaddrinfo
_active_lock = threading.Lock()
_active = False


@contextlib.contextmanager
def force_family(network_path: NetworkPath | None) -> Iterator[None]:
    """No-op for PROXY (a literal-IPv4 destination, see NetworkPath's own docstring) and
    for None. Only DIRECT_IPV4/DIRECT_IPV6 patch anything."""
    forced_family = _FAMILY_BY_PATH.get(network_path) if network_path is not None else None
    if forced_family is None:
        yield
        return

    global _active
    with _active_lock:
        if _active:
            raise RuntimeError(
                "network_path.force_family: already active in this process -- "
                "worker-dl must run --concurrency=1 for this to be safe"
            )
        _active = True

    def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
        # Ignores whatever family the caller asked for (yt-dlp/requests/ytmusicapi all
        # pass 0/AF_UNSPEC) and forces the OS resolver to only return the desired
        # family's addresses -- an empty AAAA/A record set surfaces as a real
        # socket.gaierror, the correct signal that this path genuinely has no route.
        return _real_getaddrinfo(host, port, forced_family, type, proto, flags)

    # Captured locally rather than restored from the module-level `_real_getaddrinfo` --
    # that name is deliberately mutable (tests monkeypatch it to avoid touching real DNS),
    # and restoring from it instead of this snapshot would leak whatever it was rebound to
    # into `socket.getaddrinfo` process-wide once this context manager exits.
    previous_getaddrinfo = socket.getaddrinfo
    socket.getaddrinfo = _patched_getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = previous_getaddrinfo
        with _active_lock:
            _active = False
