import socket

import pytest

from app.models import NetworkPath
from app.services import network_path

# Taken at import, before conftest's autouse fixture pins network_path.ipv6_routable.
_real_probe = network_path.ipv6_routable


def test_force_family_none_is_a_noop():
    real = socket.getaddrinfo
    with network_path.force_family(None):
        assert socket.getaddrinfo is real
    assert socket.getaddrinfo is real


def test_force_family_proxy_is_a_noop():
    # A proxy's destination is a literal IPv4 host (proxies.PROXY_URL_RE) -- forcing a
    # family for it would be meaningless.
    real = socket.getaddrinfo
    with network_path.force_family(NetworkPath.PROXY):
        assert socket.getaddrinfo is real
    assert socket.getaddrinfo is real


def test_force_family_ipv4_forces_af_inet(monkeypatch):
    seen = []
    real = socket.getaddrinfo

    def _fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        seen.append(family)
        return []

    monkeypatch.setattr(network_path, "_real_getaddrinfo", _fake_getaddrinfo)

    with network_path.force_family(NetworkPath.DIRECT_IPV4):
        socket.getaddrinfo("example.com", 443, family=0)

    assert seen == [socket.AF_INET]
    assert socket.getaddrinfo is real


def test_force_family_ipv6_forces_af_inet6(monkeypatch):
    seen = []

    def _fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        seen.append(family)
        return []

    monkeypatch.setattr(network_path, "_real_getaddrinfo", _fake_getaddrinfo)

    with network_path.force_family(NetworkPath.DIRECT_IPV6):
        socket.getaddrinfo("example.com", 443, family=socket.AF_INET)  # caller's ask is ignored

    assert seen == [socket.AF_INET6]


def test_force_family_restores_getaddrinfo_after_exception(monkeypatch):
    real = socket.getaddrinfo
    monkeypatch.setattr(network_path, "_real_getaddrinfo", lambda *a, **k: [])

    with pytest.raises(ValueError):
        with network_path.force_family(NetworkPath.DIRECT_IPV4):
            raise ValueError("boom mid-download")

    assert socket.getaddrinfo is real


def test_force_family_rejects_reentry():
    with network_path.force_family(NetworkPath.DIRECT_IPV4):
        with pytest.raises(RuntimeError):
            with network_path.force_family(NetworkPath.DIRECT_IPV6):
                pass


# --- v55 (E12): the IPv6 routability probe ---------------------------------------------------


class _ProbeSocket:
    """Stands in for socket.socket in the probe: records what it was asked, and fails the
    connect() with `error` when one is given, as a host without an IPv6 route does."""

    made: list = []

    def __init__(self, family, type_, error=None):
        self.family, self.type, self.error = family, type_, error
        self.connected = None
        _ProbeSocket.made.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def connect(self, address):
        self.connected = address
        if self.error is not None:
            raise self.error


@pytest.fixture()
def probe_socket(monkeypatch):
    _ProbeSocket.made = []
    monkeypatch.setattr(network_path, "_ipv6_probe", None)
    errors = []
    monkeypatch.setattr(
        network_path.socket, "socket", lambda family, type_: _ProbeSocket(family, type_, errors[0] if errors else None)
    )
    return errors


def test_the_ipv6_probe_is_a_udp_connect_that_sends_nothing(probe_socket):
    assert _real_probe() is True
    [made] = _ProbeSocket.made
    assert (made.family, made.type) == (socket.AF_INET6, socket.SOCK_DGRAM)
    assert made.connected == network_path._IPV6_PROBE_ADDRESS


@pytest.mark.parametrize(
    "error", [OSError(101, "Network is unreachable"), OSError(99, "Cannot assign requested address")]
)
def test_the_ipv6_probe_reports_no_route(probe_socket, error):
    probe_socket.append(error)
    assert _real_probe() is False


def test_the_ipv6_probe_is_cached_for_its_ttl(probe_socket, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(network_path.time, "monotonic", lambda: clock[0])
    assert _real_probe() is True
    probe_socket.append(OSError(101, "Network is unreachable"))
    clock[0] += network_path.IPV6_PROBE_TTL_SECONDS - 1
    assert _real_probe() is True  # still the cached answer
    assert len(_ProbeSocket.made) == 1
    clock[0] += 1
    assert _real_probe() is False  # re-probed once the TTL ran out
    assert len(_ProbeSocket.made) == 2


def test_the_ipv6_probe_on_this_machine_answers_without_raising():
    """The real kernel, no stub: whatever this machine's routing says, the probe answers."""
    network_path._ipv6_probe = None
    try:
        assert _real_probe() in (True, False)
    finally:
        network_path._ipv6_probe = None
