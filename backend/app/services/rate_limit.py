"""Redis-backed fixed-window rate limits (v53): failed logins per email and client address,
and job creates per user and per API key.

A window starts at a bucket's first counted event and lasts its `window` seconds (INCR, then
EXPIRE NX), so `Retry-After` is the bucket's remaining TTL. Limits are best effort: a Redis
outage lets the request through (logged), since locking every user out of login because
Redis is down would be worse than an unthrottled minute.

The limits are settings (`app/config.py`, all optional): LOGIN_RATE_LIMIT_FAILURES per
LOGIN_RATE_LIMIT_WINDOW_SECONDS, and JOB_CREATE_RATE_LIMIT per
JOB_CREATE_RATE_LIMIT_WINDOW_SECONDS. A limit of 0 turns that limiter off.
"""

import hashlib
import logging
import uuid

import redis
from fastapi import Request

from app.config import get_settings
from app.errors import ApiError

logger = logging.getLogger(__name__)

KEY_PREFIX = "spotdl:ratelimit:"

_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        # Short timeouts: a limiter that waits on a dead Redis would stall the login it guards.
        _client = redis.Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
        )
    return _client


def _rate_limited(retry_after: int) -> ApiError:
    retry_after = max(1, retry_after)
    return ApiError(
        429,
        "rate_limited",
        "Too many requests; try again later",
        {"retry_after": retry_after},
        headers={"Retry-After": str(retry_after)},
    )


def _over(bucket: str, limit: int) -> int | None:
    """The bucket's remaining seconds when it already holds `limit` events, else None."""
    client = _redis()
    count = client.get(bucket)
    if count is None or int(count) < limit:
        return None
    ttl = client.ttl(bucket)
    return ttl if ttl > 0 else 1


def _count(bucket: str, window: int) -> int:
    """Counts one event; returns the bucket's count including it."""
    pipe = _redis().pipeline()
    pipe.incr(bucket)
    pipe.expire(bucket, window, nx=True)
    count, _ = pipe.execute()
    return int(count)


def client_address(request: Request) -> str:
    """The caller's address. Production reaches the API through Cloudflare's tunnel and the
    `web` container's nginx, so the peer is nginx: Cloudflare's `CF-Connecting-IP` names the
    real client (Cloudflare sets it on every request; the tunnel is the only way in), then
    nginx's `X-Real-IP`, then the peer itself (local dev without either)."""
    for header in ("cf-connecting-ip", "x-real-ip"):
        value = request.headers.get(header, "").strip()
        if value:
            return value
    return request.client.host if request.client else "unknown"


def _login_bucket(email: str, address: str) -> str:
    # Hashed, so the Redis keyspace never holds an email address.
    digest = hashlib.sha256(f"{email.strip().lower()}\n{address}".encode()).hexdigest()
    return f"{KEY_PREFIX}login:{digest}"


def check_login(email: str, address: str) -> None:
    """Raises 429 `rate_limited` once this email has failed LOGIN_RATE_LIMIT_FAILURES times
    from this address inside the window -- before the upstream is asked, so a right password
    is refused too until the window ends."""
    settings = get_settings()
    if settings.login_rate_limit_failures <= 0:
        return
    try:
        retry_after = _over(_login_bucket(email, address), settings.login_rate_limit_failures)
    except redis.RedisError:
        logger.warning("rate_limit: login check skipped, Redis unavailable")
        return
    if retry_after is not None:
        raise _rate_limited(retry_after)


def record_login_failure(email: str, address: str) -> None:
    settings = get_settings()
    if settings.login_rate_limit_failures <= 0:
        return
    try:
        _count(_login_bucket(email, address), settings.login_rate_limit_window_seconds)
    except redis.RedisError:
        logger.warning("rate_limit: login failure not counted, Redis unavailable")


def clear_login_failures(email: str, address: str) -> None:
    """A successful login starts this email and address over."""
    if get_settings().login_rate_limit_failures <= 0:
        return
    try:
        _redis().delete(_login_bucket(email, address))
    except redis.RedisError:
        logger.warning("rate_limit: login failures not cleared, Redis unavailable")


def hit_job_create(user_id: uuid.UUID, api_key_id: uuid.UUID | None) -> None:
    """Counts one job create against the user and, for a key-authenticated request, the key
    too; raises 429 `rate_limited` when either is over JOB_CREATE_RATE_LIMIT in its window. A
    refused create counts as well (its window still ends when it would have)."""
    settings = get_settings()
    limit = settings.job_create_rate_limit
    if limit <= 0:
        return
    window = settings.job_create_rate_limit_window_seconds
    buckets = [f"{KEY_PREFIX}create:user:{user_id}"]
    if api_key_id is not None:
        buckets.append(f"{KEY_PREFIX}create:key:{api_key_id}")
    try:
        retry_after = None
        for bucket in buckets:
            if _count(bucket, window) > limit:
                ttl = _redis().ttl(bucket)
                retry_after = max(retry_after or 0, ttl if ttl > 0 else 1)
    except redis.RedisError:
        logger.warning("rate_limit: job create not counted, Redis unavailable")
        return
    if retry_after is not None:
        raise _rate_limited(retry_after)
