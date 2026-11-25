"""Redis-backed fixed-window rate limits (v53): failed logins per email and client address,
job creates per user and per API key, (v65) short link resolves per user, and (v71) the login's
second step per challenge and client address.

A window starts at a bucket's first counted event and lasts its `window` seconds (INCR, then
EXPIRE NX), so `Retry-After` is the bucket's remaining TTL. Limits are best effort: a Redis
outage lets the request through (logged), since locking every user out of login because
Redis is down would be worse than an unthrottled minute.

The limits are settings (`app/config.py`, all optional): LOGIN_RATE_LIMIT_FAILURES per
LOGIN_RATE_LIMIT_WINDOW_SECONDS, and JOB_CREATE_RATE_LIMIT per
JOB_CREATE_RATE_LIMIT_WINDOW_SECONDS. A limit of 0 turns that limiter off.
"""

import hashlib
import ipaddress
import logging
import uuid

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from fastapi import Request

from app.config import get_settings
from app.errors import ApiError
from app.services.upstream_auth import CHALLENGE_TTL_SECONDS

logger = logging.getLogger(__name__)

KEY_PREFIX = "spotdl:ratelimit:"

_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        # Short timeouts: a limiter that waits on a dead Redis would stall the login it guards.
        # No retries either: redis-py's default retries a dead connection with backoff for
        # several seconds before the error that lets the request through.
        _client = redis.Redis.from_url(
            get_settings().redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
            retry=Retry(NoBackoff(), 0),
        )
    return _client


def rate_limited(retry_after: int, reason: str | None = None) -> ApiError:
    """The 429 every limit answers. v71: also the upstream's own 429s on login and MFA, with its
    `reason` (`resendCooldown`, `mfaEmailLimit`) when it gave one."""
    retry_after = max(1, retry_after)
    params: dict = {"retry_after": retry_after}
    if reason:
        params["reason"] = reason
    return ApiError(
        429,
        "rate_limited",
        "Too many requests; try again later",
        params,
        headers={"Retry-After": str(retry_after)},
    )


def _count(bucket: str, window: int) -> int:
    """Counts one event; returns the bucket's count including it."""
    pipe = _redis().pipeline()
    pipe.incr(bucket)
    pipe.expire(bucket, window, nx=True)
    count, _ = pipe.execute()
    return int(count)


def _bucket_address(address: str) -> str:
    """The address a login bucket keys on: an IPv6 address by its /64 (one host usually holds
    a whole /64 and could rotate through it), anything else as it is."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


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


# The per-address bucket's limit, as a multiple of LOGIN_RATE_LIMIT_FAILURES: looser than the
# email-and-address one (a household shares an address), but it stops one address spraying
# guesses across many emails, each of which the upstream would otherwise be asked about.
ADDRESS_LIMIT_FACTOR = 5


def _login_bucket(email: str, address: str) -> str:
    # Hashed, so the Redis keyspace never holds an email address. `surrogatepass`: a lone
    # surrogate can't be UTF-8 encoded, and the caller refuses such an email anyway.
    text = f"{email.strip().lower()}\n{_bucket_address(address)}"
    digest = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
    return f"{KEY_PREFIX}login:{digest}"


def _address_bucket(address: str, kind: str = "login") -> str:
    digest = hashlib.sha256(_bucket_address(address).encode("utf-8", "surrogatepass")).hexdigest()
    return f"{KEY_PREFIX}{kind}-address:{digest}"


def hit_login(email: str, address: str) -> None:
    """Counts this login attempt for its email and client address before the upstream is
    asked, and raises 429 `rate_limited` once the window holds more than
    LOGIN_RATE_LIMIT_FAILURES of them, so a right password is refused too until it ends.
    Counted first, not after a failure: a burst of parallel guesses would otherwise all read
    the same count and every one would reach the upstream. A success clears the email's bucket
    (`clear_login_failures`), so what accumulates there is failures plus attempts in flight.
    The address's own bucket (ADDRESS_LIMIT_FACTOR times looser) counts every attempt from it,
    for any email, and isn't cleared by a success."""
    settings = get_settings()
    limit = settings.login_rate_limit_failures
    if limit <= 0:
        return
    _hit(
        ((_login_bucket(email, address), limit), (_address_bucket(address), limit * ADDRESS_LIMIT_FACTOR)),
        settings.login_rate_limit_window_seconds,
        "login attempt",
    )


def _hit(buckets, window: int, what: str) -> None:
    """Counts one event in every (bucket, limit) and raises 429 when any is over its limit, with
    the longest wait. A Redis error lets the event through (fail open, logged)."""
    retry_after = None
    try:
        for bucket, bucket_limit in buckets:
            if _count(bucket, window) > bucket_limit:
                ttl = _redis().ttl(bucket)
                retry_after = max(retry_after or 0, ttl if ttl > 0 else 1)
    except redis.RedisError:
        logger.warning("rate_limit: %s not counted, Redis unavailable", what)
        return
    if retry_after is not None:
        raise rate_limited(retry_after)


def hit_mfa(challenge_id: str, address: str) -> None:
    """v71: counts one second-step request (`/api/auth/mfa/verify` or `/email`) against its
    challenge and its client address, by the login limit and window: the challenge's bucket at
    LOGIN_RATE_LIMIT_FAILURES (upstream allows only 5 tries anyway; this caps the resends and the
    requests sent after the tries ran out), the address's ADDRESS_LIMIT_FACTOR times looser."""
    settings = get_settings()
    limit = settings.login_rate_limit_failures
    if limit <= 0:
        return
    challenge = hashlib.sha256(challenge_id.encode("utf-8", "surrogatepass")).hexdigest()
    _hit(
        (
            (f"{KEY_PREFIX}mfa:{challenge}", limit),
            (_address_bucket(address, "mfa"), limit * ADDRESS_LIMIT_FACTOR),
        ),
        # Never a wait longer than the challenge lives: after it, only a new sign-in helps.
        min(settings.login_rate_limit_window_seconds, CHALLENGE_TTL_SECONDS),
        "MFA request",
    )


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
    refused create counts as well (its window still ends when it would have). With one limit for
    both, the key's bucket only ever trips first when the user's window has just rolled over:
    it's there so a key keeps its own count if the limits ever differ."""
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
        raise rate_limited(retry_after)


def hit_link_resolve(user_id: uuid.UUID) -> None:
    """v65: counts one short link resolve (`/api/links/resolve`) against the user, by the job
    create limit and window but in a bucket of its own, so a share's resolve and its create
    don't share one count. Raises 429 `rate_limited` over it."""
    settings = get_settings()
    limit = settings.job_create_rate_limit
    if limit <= 0:
        return
    bucket = f"{KEY_PREFIX}resolve:user:{user_id}"
    try:
        if _count(bucket, settings.job_create_rate_limit_window_seconds) <= limit:
            return
        ttl = _redis().ttl(bucket)
    except redis.RedisError:
        logger.warning("rate_limit: link resolve not counted, Redis unavailable")
        return
    raise rate_limited(ttl if ttl > 0 else 1)
