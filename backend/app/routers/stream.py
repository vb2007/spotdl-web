import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.models import User
from app.routers.auth import require_session
from app.services.events import ADMIN_CHANNEL_PATTERN, channel_for

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["stream"])

# Cloudflare Tunnel closes an idle connection — this must stay comfortably under whatever
# idle timeout it enforces (see CLAUDE.md's SSE notes).
HEARTBEAT_INTERVAL_SEC = 15.0


async def _event_stream(request: Request, user: User, all_users: bool):
    settings = get_settings()
    client = aioredis.Redis.from_url(settings.redis_url)
    pubsub = client.pubsub()
    # Decided from the session, never trusted from the client (v17's threat model): a
    # non-admin passing all_users=true is silently treated the same as not passing it.
    use_pattern = all_users and user.is_admin
    if use_pattern:
        await pubsub.psubscribe(ADMIN_CHANNEL_PATTERN)
    else:
        await pubsub.subscribe(channel_for(user.id))
    try:
        while True:
            if await request.is_disconnected():
                break

            # get_message's own timeout doubles as the heartbeat interval — no message
            # within that window means it's time to emit one rather than a real event.
            # Filters (p)subscribe confirmations the same way for both subscribe modes.
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=HEARTBEAT_INTERVAL_SEC
            )
            if message is None:
                yield ": heartbeat\n\n"
                continue

            data = message["data"]
            if isinstance(data, bytes):
                data = data.decode()
            yield f"data: {data}\n\n"
    finally:
        if use_pattern:
            await pubsub.punsubscribe(ADMIN_CHANNEL_PATTERN)
        else:
            await pubsub.unsubscribe(channel_for(user.id))
        await pubsub.aclose()
        await client.aclose()


@router.get("/stream")
async def stream(
    request: Request,
    all_users: bool = False,
    user: User = Depends(require_session),
) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(request, user, all_users),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
