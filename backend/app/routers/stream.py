import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.models import UserSession
from app.routers.auth import require_session
from app.services.events import CHANNEL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["stream"])

# Cloudflare Tunnel closes an idle connection — this must stay comfortably under whatever
# idle timeout it enforces (see CLAUDE.md's SSE notes).
HEARTBEAT_INTERVAL_SEC = 15.0


async def _event_stream(request: Request):
    settings = get_settings()
    client = aioredis.Redis.from_url(settings.redis_url)
    pubsub = client.pubsub()
    await pubsub.subscribe(CHANNEL)
    try:
        while True:
            if await request.is_disconnected():
                break

            # get_message's own timeout doubles as the heartbeat interval — no message
            # within that window means it's time to emit one rather than a real event.
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
        await pubsub.unsubscribe(CHANNEL)
        await pubsub.aclose()
        await client.aclose()


@router.get("/stream")
async def stream(request: Request, _: UserSession = Depends(require_session)) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
