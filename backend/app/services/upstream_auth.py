import logging
import re

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_VB_AUTH_RE = re.compile(r"VB-AUTH=([^;]+)")


async def login(email: str, password: str) -> tuple[bool, str | None]:
    """Check credentials against vb2007.hu-api, and best-effort fetch the username via
    `GET /user` in the same login response's session (v25). Never forwards or returns
    the upstream VB-AUTH cookie to the caller — the token is extracted and used only
    inside this function, for exactly one follow-up request.

    Returns (upstream_ok, username). username is None whenever it couldn't be fetched
    for any reason (upstream down, malformed response, no cookie) -- this must never
    fail an otherwise-successful login; the caller falls back to displaying email."""
    settings = get_settings()
    base = settings.upstream_auth_base_url

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{base}/auth/login", json={"email": email, "password": password}
            )
    except httpx.HTTPError:
        logger.warning("Upstream auth request failed", exc_info=True)
        return False, None

    if response.status_code != 200:
        return False, None

    return True, await _fetch_username(base, response)


async def _fetch_username(base_url: str, login_response: httpx.Response) -> str | None:
    """`isAuthenticated`'s `GET /user` reads the `VB-AUTH` cookie itself -- extracted
    directly from the login response's raw `Set-Cookie` header rather than relying on
    httpx's own client-side cookie jar, which enforces RFC 6265 domain-matching against
    the cookie's `Domain` attribute (`COOKIE_TARGET_DOMAIN`, e.g. `localhost` in local
    dev) and would silently refuse to forward it to a differently-named request host
    such as `host.docker.internal` -- confirmed against the local upstream instance's
    own `.env`. Manually forwarding the raw token sidesteps that policy entirely and
    works regardless of what COOKIE_TARGET_DOMAIN is set to in any environment."""
    token = None
    for header in login_response.headers.get_list("set-cookie"):
        match = _VB_AUTH_RE.search(header)
        if match:
            token = match.group(1).strip('"')
            break
    if token is None:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0, cookies={"VB-AUTH": token}) as client:
            user_response = await client.get(f"{base_url}/user")
    except httpx.HTTPError:
        logger.warning("Upstream GET /user request failed", exc_info=True)
        return None

    if user_response.status_code != 200:
        logger.warning("Upstream GET /user returned %s", user_response.status_code)
        return None
    try:
        body = user_response.json()
    except ValueError:
        logger.warning("Upstream GET /user returned non-JSON body", exc_info=True)
        return None
    # `body` can parse as valid JSON that isn't an object at all (`null`, `[]`, a bare
    # number/string) -- a transient upstream fluke (health-check page, unauthenticated-
    # shape response served with a 200) must degrade the same as a hard failure, not
    # raise AttributeError out of `.get(...)` and 500 an otherwise-successful login.
    # An empty-string username is treated the same as "none fetched" for the same reason
    # `get_or_create_user` only reconciles on a truthy value -- one flaky/odd response
    # must never blank a previously known-good name.
    username = body.get("username") if isinstance(body, dict) else None
    return username or None
