"""v53: the rate limiter's Redis client (the limit behavior itself is in test_extension_jobs.py)."""

from app.services import rate_limit


def test_the_limiter_never_retries_a_dead_redis(monkeypatch):
    """Review round 3: redis-py retries with backoff by default, which turned 'fails open'
    into a several-second stall per request."""
    from app.services import rate_limit

    monkeypatch.setattr(rate_limit, "_client", None)
    client = rate_limit._redis()
    assert client.get_connection_kwargs()["retry"]._retries == 0
    monkeypatch.setattr(rate_limit, "_client", None)


def test_bucket_addresses():
    assert rate_limit._bucket_address("2001:db8:1:2::5") == "2001:db8:1:2::/64"
    assert rate_limit._bucket_address("2001:DB8:1:2:FFFF:FFFF:FFFF:FFFF") == "2001:db8:1:2::/64"
    assert rate_limit._bucket_address("::ffff:198.51.100.7") == "198.51.100.7"
    assert rate_limit._bucket_address("198.51.100.7") == "198.51.100.7"
    assert rate_limit._bucket_address("fe80::1%eth0") == "fe80::/64"
    assert rate_limit._bucket_address("not an address") == "not an address"
