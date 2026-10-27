import logging
import time

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.models import User
from app.routers.auth import require_session_for_streaming
from app.services.events import ADMIN_CHANNEL_PATTERN, channel_for
from app.services.view_scope import View, resolve_view

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["stream"])

# Cloudflare Tunnel closes an idle connection — this must stay comfortably under whatever
# idle timeout it enforces (see CLAUDE.md's SSE notes).
HEARTBEAT_INTERVAL_SEC = 15.0
# v62 (F4): a named event, not only an SSE comment: page JavaScript never sees a comment, so a
# quiet stream and one the network dropped under it (a laptop's sleep) looked the same. The
# page times this (`addEventListener('heartbeat')`; `onmessage` ignores a named event) and
# restarts a stream silent for longer than the interval. Its data is never read, but an
# event with no data isn't dispatched at all.
HEARTBEAT = "event: heartbeat\ndata: {}\n\n"


async def _event_stream(request: Request, user: User, view: View):
    settings = get_settings()
    client = aioredis.Redis.from_url(settings.redis_url)
    pubsub = client.pubsub()
    # Decided from the session, never trusted from the client (v17's threat model): a
    # non-admin asking for `all` or `others` is silently treated as `mine`. The router has
    # already normalized it; this re-checks so the generator is safe on its own.
    if not user.is_admin:
        view = "mine"
    use_pattern = view != "mine"
    # `others` (v54) pattern-subscribes like `all` and drops the admin's own channel. The
    # payloads carry no owner (v17), so the channel is the only thing to filter on.
    own_channel = channel_for(user.id)
    skip_channel = own_channel if view == "others" else None
    if use_pattern:
        await pubsub.psubscribe(ADMIN_CHANNEL_PATTERN)
    else:
        await pubsub.subscribe(own_channel)
    last_sent = time.monotonic()
    try:
        while True:
            if await request.is_disconnected():
                break

            # get_message's own timeout doubles as the heartbeat interval — no message
            # within that window means it's time to emit one rather than a real event.
            # Filters (p)subscribe confirmations the same way for both subscribe modes.
            # v62 (F4): the time left until the next one is due, not a fresh interval, so
            # dropped messages (`others`) can't stretch the silence past it.
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=max(0.0, HEARTBEAT_INTERVAL_SEC - (time.monotonic() - last_sent)),
            )
            if message is None:
                last_sent = time.monotonic()
                yield HEARTBEAT
                continue

            if skip_channel is not None:
                channel = message.get("channel")
                if isinstance(channel, bytes):
                    channel = channel.decode()
                if channel == skip_channel:
                    # A steady run of dropped own-channel messages would otherwise keep the
                    # wire silent past the tunnel's idle timeout: heartbeat on schedule.
                    if time.monotonic() - last_sent >= HEARTBEAT_INTERVAL_SEC:
                        last_sent = time.monotonic()
                        yield HEARTBEAT
                    continue

            data = message["data"]
            if isinstance(data, bytes):
                data = data.decode()
            last_sent = time.monotonic()
            yield f"data: {data}\n\n"
    finally:
        if use_pattern:
            await pubsub.punsubscribe(ADMIN_CHANNEL_PATTERN)
        else:
            await pubsub.unsubscribe(own_channel)
        await pubsub.aclose()
        await client.aclose()


@router.get("/stream")
async def stream(
    request: Request,
    view: View | None = None,
    all_users: bool | None = None,
    user: User = Depends(require_session_for_streaming),
) -> StreamingResponse:
    view = resolve_view(view, all_users, is_admin=user.is_admin)
    return StreamingResponse(
        _event_stream(request, user, view),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
