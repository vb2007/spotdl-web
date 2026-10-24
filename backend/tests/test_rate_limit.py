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
