import socket

import pytest

from app.models import NetworkPath
from app.services import network_path


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
