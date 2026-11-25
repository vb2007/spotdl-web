"""The server-side login proxy to `vb2007.hu-api` (v03, v25; v71 for upstream v3's MFA).

spotdl never forwards an upstream cookie to the browser. The upstream session (`__Host-VB-AUTH`)
and the MFA challenge (`__Host-VB-MFA`) are read from the raw `Set-Cookie` header and replayed by
hand, never through httpx's cookie jar (v25: its RFC 6265 domain matching silently dropped the
token). Neither token is ever logged, returned or stored in Postgres: the session lives only for
the identity fetch and its logout, the challenge only in Redis (`store_challenge`), keyed by a
random id the browser holds in `SPOTDL_MFA`.

Interim until v73 replaces this proxy with "Sign in with vb2007.hu". Upstream keeps one session
per account, so a spotdl login still logs the user out of vb2007.hu (docs/GOTCHAS.md v71).
"""

import hashlib
import json
import logging
import re
import secrets
from dataclasses import dataclass, field

import httpx
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.config import get_settings

logger = logging.getLogger(__name__)

SESSION_COOKIE = "__Host-VB-AUTH"
MFA_COOKIE = "__Host-VB-MFA"
# Anchored on the cookie's name: `X__Host-VB-AUTH=` or a value mentioning it never matches.
_SESSION_RE = re.compile(r"^\s*__Host-VB-AUTH=([^;]*)")
_MFA_RE = re.compile(r"^\s*__Host-VB-MFA=([^;]*)")
# `Responses.Authentication.accountSuspended`, by its stable start (tests/fixtures pins the
# whole sentence as upstream v3.4.0 words it).
SUSPENDED_PREFIX = "This account is suspended"
# The second steps a server-side proxy can answer, in upstream's order. `passkey` can't be proxied
# (its origin is vb2007.hu) and arrives with v73.
PROXIED_METHODS = ("email", "totp", "recovery")
# Upstream's MFA_CHALLENGE_MINUTES.
CHALLENGE_TTL_SECONDS = 10 * 60
_TIMEOUT = 10.0


@dataclass(frozen=True)
class Ok:
    """The password (or second step) passed. `session` is the upstream session token, used only
    by `finish`/`logout` (repr hidden, so a logged result never carries it). None: the 200 had
    no `__Host-VB-AUTH` cookie, which still signs in (logged: v2.6's rename hid like that)."""

    session: str | None = field(repr=False)


@dataclass(frozen=True)
class MfaRequired:
    methods: tuple[str, ...]
    challenge: str = field(repr=False)


@dataclass(frozen=True)
class Invalid:
    pass


@dataclass(frozen=True)
class Suspended:
    pass


@dataclass(frozen=True)
class RateLimited:
    retry_after: int
    reason: str | None = None


@dataclass(frozen=True)
class Unavailable:
    pass


LoginResult = Ok | MfaRequired | Invalid | Suspended | RateLimited | Unavailable


@dataclass(frozen=True)
class CodeRejected:
    """`POST /auth/mfa/verify`'s 400: a wrong code (with the tries left), or a malformed one."""

    attempts_left: int | None


@dataclass(frozen=True)
class ChallengeEnded:
    """Upstream's 403 on an `/auth/mfa` route: `noChallenge`, `triesUsedUp`, `expired` or `ended`."""

    reason: str


@dataclass(frozen=True)
class Sent:
    pass


@dataclass(frozen=True)
class MethodOff:
    pass


@dataclass(frozen=True)
class MailUnavailable:
    pass


@dataclass(frozen=True)
class Identity:
    """What `GET /user` told a login (v72). Each field is None when the read failed or the value
    was odd: the username stays as known, and `is_superuser` None never changes `is_admin`."""

    username: str | None = None
    is_superuser: bool | None = None


def _cookie(response: httpx.Response, pattern: re.Pattern[str]) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        match = pattern.match(header)
        if match and match.group(1).strip('"'):
            return match.group(1).strip('"')
    return None


def _session(response: httpx.Response) -> str | None:
    token = _cookie(response, _SESSION_RE)
    if token is None:
        logger.warning("Upstream %s answered 200 without a %s cookie", response.request.url.path, SESSION_COOKIE)
    return token


def _body(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _retry_after(response: httpx.Response, body: dict) -> int:
    for value in (body.get("retryAfter"), response.headers.get("retry-after")):
        try:
            seconds = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            return seconds
    return 60


def _common(response: httpx.Response) -> RateLimited | Unavailable | None:
    """The answers every proxied call shares: a 429 and an upstream that isn't answering."""
    if response.status_code == 429:
        body = _body(response)
        reason = body.get("reason")
        return RateLimited(_retry_after(response, body), reason if isinstance(reason, str) else None)
    if response.status_code >= 500:
        logger.warning("Upstream auth answered %s", response.status_code)
        return Unavailable()
    return None


async def _post(path: str, *, json_body: dict | None = None, cookie: str | None = None) -> httpx.Response | None:
    headers = {"Cookie": cookie} if cookie else None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            return await client.post(f"{get_settings().upstream_auth_base_url}{path}", json=json_body, headers=headers)
    except httpx.HTTPError as exc:
        # The exception's type only: its text could carry the request (and so a cookie).
        logger.warning("Upstream auth request to %s failed: %s", path, type(exc).__name__)
        return None


async def login(email: str, password: str) -> LoginResult:
    """`POST /auth/login`. The caller reads the allowlist before acting on anything but
    `Invalid`/`Unavailable`/`RateLimited`, and ends an `Ok` with `finish` (or `logout`)."""
    response = await _post("/auth/login", json_body={"email": email, "password": password})
    if response is None:
        return Unavailable()
    common = _common(response)
    if common is not None:
        return common
    if response.status_code == 200:
        return Ok(_session(response))
    if response.status_code == 202:
        challenge = _cookie(response, _MFA_RE)
        methods = _body(response).get("methods")
        if challenge is None or not isinstance(methods, list):
            logger.warning("Upstream login answered 202 without a challenge or methods")
            return Unavailable()
        return MfaRequired(tuple(m for m in methods if isinstance(m, str)), challenge)
    if response.status_code == 403:
        error = _body(response).get("error")
        if isinstance(error, str) and error.startswith(SUSPENDED_PREFIX):
            return Suspended()
    # Any other 403, a 400 (a field upstream refuses) or anything unexpected.
    return Invalid()


def proxied_methods(methods: tuple[str, ...]) -> list[str]:
    """The challenge's methods this proxy can answer, in upstream's order: `passkey` dropped
    (`recovery` kept even if it's all that's left). Empty: only a passkey (`mfa_unsupported`)."""
    return [m for m in methods if m in PROXIED_METHODS]


async def verify(challenge: str, method: str, code: str) -> LoginResult | CodeRejected | ChallengeEnded:
    """`POST /auth/mfa/verify` with the stored challenge. 200: `Ok(session)`."""
    response = await _post(
        "/auth/mfa/verify", json_body={"method": method, "code": code}, cookie=f"{MFA_COOKIE}={challenge}"
    )
    if response is None:
        return Unavailable()
    common = _common(response)
    if common is not None:
        return common
    body = _body(response)
    if response.status_code == 200:
        return Ok(_session(response))
    if response.status_code == 400:
        left = body.get("attemptsLeft")
        return CodeRejected(left if isinstance(left, int) and not isinstance(left, bool) else None)
    if response.status_code == 403:
        return ChallengeEnded(_reason(body))
    logger.warning("Upstream MFA verify answered %s", response.status_code)
    return Unavailable()


async def send_email_code(
    challenge: str,
) -> Sent | MethodOff | MailUnavailable | ChallengeEnded | RateLimited | Unavailable:
    """`POST /auth/mfa/email`: mails a fresh code for the challenge."""
    response = await _post("/auth/mfa/email", cookie=f"{MFA_COOKIE}={challenge}")
    if response is None:
        return Unavailable()
    if response.status_code == 503:
        return MailUnavailable()
    common = _common(response)
    if common is not None:
        return common
    if response.status_code == 202:
        return Sent()
    if response.status_code == 400:
        return MethodOff()
    if response.status_code == 403:
        return ChallengeEnded(_reason(_body(response)))
    logger.warning("Upstream MFA email answered %s", response.status_code)
    return Unavailable()


_REASONS = ("noChallenge", "triesUsedUp", "expired", "ended")


def _reason(body: dict) -> str:
    reason = body.get("reason")
    return reason if reason in _REASONS else "ended"


async def finish(session: str | None) -> Identity:
    """For an allowed address's `Ok`: the username and superuser flag (`GET /user`), then the
    upstream session is logged out, so spotdl leaves none behind. Both best effort: never fails
    the login."""
    if session is None:
        return Identity()
    identity = await _fetch_identity(session)
    await logout(session)
    return identity


async def logout(session: str | None) -> None:
    """`POST /auth/logout` with the session, best effort."""
    if session is None:
        return
    response = await _post("/auth/logout", cookie=f"{SESSION_COOKIE}={session}")
    if response is not None and response.status_code != 200:
        logger.warning("Upstream logout answered %s", response.status_code)


async def _fetch_identity(session: str) -> Identity:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                f"{get_settings().upstream_auth_base_url}/user", headers={"Cookie": f"{SESSION_COOKIE}={session}"}
            )
    except httpx.HTTPError as exc:
        logger.warning("Upstream GET /user failed: %s", type(exc).__name__)
        return Identity()
    if response.status_code != 200:
        logger.warning("Upstream GET /user returned %s", response.status_code)
        return Identity()
    # A body that parses but isn't an object, an empty name or a non-boolean flag degrades like a
    # failure: one odd answer must never 500 a login, blank a known-good name or touch `is_admin`.
    body = _body(response)
    username = body.get("username")
    is_superuser = body.get("isSuperuser")
    return Identity(
        username=username if isinstance(username, str) and username else None,
        is_superuser=is_superuser if isinstance(is_superuser, bool) else None,
    )


# --- The MFA challenge store -------------------------------------------------------------------

CHALLENGE_PREFIX = "spotdl:mfa-challenge:"


class ChallengeStoreError(Exception):
    """Redis refused. Unlike the rate limits this fails closed: no stored challenge, no second step."""


_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1, retry=Retry(NoBackoff(), 0)
        )
    return _client


def _challenge_key(challenge_id: str) -> str:
    # Hashed: the Redis keyspace never holds the id the browser's cookie carries.
    return CHALLENGE_PREFIX + hashlib.sha256(challenge_id.encode("utf-8", "surrogatepass")).hexdigest()


def store_challenge(upstream_challenge: str, email: str) -> str:
    """Keeps `{upstream challenge, email}` for upstream's 10 minutes; returns the new id."""
    challenge_id = secrets.token_urlsafe(32)
    value = json.dumps({"upstream_mfa_token": upstream_challenge, "email": email})
    try:
        _redis().set(_challenge_key(challenge_id), value, ex=CHALLENGE_TTL_SECONDS)
    except redis.RedisError as exc:
        raise ChallengeStoreError from exc
    return challenge_id


def load_challenge(challenge_id: str) -> tuple[str, str] | None:
    """(upstream challenge, email), or None when it expired or never existed."""
    try:
        raw = _redis().get(_challenge_key(challenge_id))
    except redis.RedisError as exc:
        raise ChallengeStoreError from exc
    if raw is None:
        return None
    data = json.loads(raw)
    return data["upstream_mfa_token"], data["email"]


def drop_challenge(challenge_id: str) -> None:
    try:
        _redis().delete(_challenge_key(challenge_id))
    except redis.RedisError:
        # It expires on its own within 10 minutes, and upstream has already ended it.
        logger.warning("MFA challenge not deleted, Redis unavailable")
