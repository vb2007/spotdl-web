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

v55 (E12): `ipv6_routable` tells download_track whether the forced-IPv6 rung can work at all
here. Where it can't, that rung cost a whole ladder wait for a guaranteed failure.
"""

import contextlib
import socket
import threading
import time
from typing import Iterator

from app.models import NetworkPath

_FAMILY_BY_PATH = {
    NetworkPath.DIRECT_IPV4: socket.AF_INET,
    NetworkPath.DIRECT_IPV6: socket.AF_INET6,
}

# Google Public DNS. Never actually contacted: a UDP connect() only asks the kernel for a
# route and sends nothing.
_IPV6_PROBE_ADDRESS = ("2001:4860:4860::8888", 53)
IPV6_PROBE_TTL_SECONDS = 300
_ipv6_probe: tuple[float, bool] | None = None

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


def ipv6_routable() -> bool:
    """Whether this process has a route to the IPv6 internet, cached for
    IPV6_PROBE_TTL_SECONDS. A container without IPv6, or with it disabled, fails the connect()
    with ENETUNREACH/EADDRNOTAVAIL (or can't make the socket). A route doesn't promise a working
    path, only that the rung isn't certain to fail; a real attempt still decides that."""
    global _ipv6_probe
    now = time.monotonic()
    if _ipv6_probe is not None and now - _ipv6_probe[0] < IPV6_PROBE_TTL_SECONDS:
        return _ipv6_probe[1]
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as probe:
            probe.connect(_IPV6_PROBE_ADDRESS)
        routable = True
    except OSError:
        routable = False
    _ipv6_probe = (now, routable)
    return routable
