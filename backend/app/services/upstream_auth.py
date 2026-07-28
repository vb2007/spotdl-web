import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


async def login(email: str, password: str) -> bool:
    """Check credentials against vb2007.hu-api. Never forwards or returns the upstream
    VB-AUTH cookie — the caller only ever learns whether the status was 200."""
    settings = get_settings()
    url = f"{settings.upstream_auth_base_url}/auth/login"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"email": email, "password": password})
    except httpx.HTTPError:
        logger.warning("Upstream auth request failed", exc_info=True)
        return False

    return response.status_code == 200
