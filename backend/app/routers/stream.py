import logging
import time

import json
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.config import get_settings
from app.db import get_db
from app.models import User, UserSession
from app.routers.auth import COOKIE_NAME, require_session_for_streaming
from app.services import allowlist
from app.services.events import ADMIN_CHANNEL_PATTERN, CONTROL_REVOKED, channel_for, control_channel_for
from app.services.sessions import SESSION_IDLE_TIMEOUT
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
# v69: the last thing a removed user's stream sends before it ends. A data event (the page's
# `onmessage` hands it to the queue store, whose revoke block runs the logout path).
REVOKED = 'data: {"type": "session.revoked"}\n\n'
# v69: how often an open stream re-checks its session and its owner's allowlist entry: the
# safety net for a lost control publish (pub/sub is fire-and-forget). The heartbeat's cadence.
SESSION_RECHECK_SEC = HEARTBEAT_INTERVAL_SEC


def _session_status(request: Request, token: str | None, user_id) -> str:
    """`ok`, `revoked` (the owner's address is off the allowlist) or `ended` (the session is
    gone or idle past its timeout: a sign-out, an expiry). Read-only, on a short-lived database
    session that is closed before this returns, never one held for the stream's life (v31's
    idle-in-transaction bug, docs/GOTCHAS.md v23/v31), resolved as require_session_for_streaming
    resolves it so a test's override applies. Doesn't touch `last_seen_at`: an open tab isn't a
    request, and a write every 15s for every open stream would cost more than it tells."""
    db_factory = request.app.dependency_overrides.get(get_db, get_db)
    db_gen = db_factory()
    db = next(db_gen)
    try:
        # The owner first: a removal deletes the session too, and the page should still learn
        # that it was the access, not the session, that ended.
        email = db.execute(select(User.email).where(User.id == user_id)).scalar_one_or_none()
        last_seen_at = None
        if token is not None and "\x00" not in token:
            last_seen_at = db.execute(
                select(UserSession.last_seen_at).where(
                    UserSession.token == token, UserSession.user_id == user_id
                )
            ).scalar_one_or_none()
        if email is None or not allowlist.is_allowed(db, email):
            status = "revoked"
        elif last_seen_at is None:
            status = "ended"
        else:
            if last_seen_at.tzinfo is None:
                last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
            status = "ended" if datetime.now(timezone.utc) - last_seen_at > SESSION_IDLE_TIMEOUT else "ok"
        # Ends the read's transaction before the session closes (nothing was written).
        db.commit()
        return status
    finally:
        next(db_gen, None)


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
    # v69: the caller's own control channel, by exact name in every view (never the admin's
    # pattern, which can't match it): `revoked` ends this stream.
    control_channel = control_channel_for(user.id)
    token = request.cookies.get(COOKIE_NAME)
    if use_pattern:
        await pubsub.psubscribe(ADMIN_CHANNEL_PATTERN)
    else:
        await pubsub.subscribe(own_channel)
    await pubsub.subscribe(control_channel)
    last_sent = last_checked = time.monotonic()
    try:
        # v69: a first chunk at once. A proxy that holds the response headers until the first
        # byte (Vite's dev proxy does) would otherwise open the page's EventSource only with the
        # first heartbeat, 15s in. Before v69 the subscribe confirmation's empty read sent one by
        # accident; the loop below now waits out the interval on such a read. Inside the `try`,
        # so a client gone at this first yield still unsubscribes and closes its connections.
        yield HEARTBEAT
        while True:
            if await request.is_disconnected():
                break

            # v69: the safety net, on its own clock so a busy stream (no heartbeat due) still
            # re-checks: a removal whose control publish was lost ends the stream here.
            now = time.monotonic()
            if now - last_checked >= SESSION_RECHECK_SEC:
                last_checked = now
                try:
                    status = await run_in_threadpool(_session_status, request, token, user.id)
                except Exception:
                    # Postgres unreachable says nothing about the session: keep streaming, and
                    # ask again next time.
                    logger.warning("stream: the session re-check failed", exc_info=True)
                    status = "ok"
                if status == "revoked":
                    yield REVOKED
                    break
                if status == "ended":
                    break

            # get_message's own timeout doubles as the heartbeat interval — no message
            # within that window means it's time to emit one rather than a real event.
            # Filters (p)subscribe confirmations the same way for both subscribe modes.
            # v62 (F4): the time left until the next one is due, not a fresh interval, so
            # dropped messages (`others`) can't stretch the silence past it.
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=max(
                    0.0,
                    min(HEARTBEAT_INTERVAL_SEC - (now - last_sent), SESSION_RECHECK_SEC - (now - last_checked)),
                ),
            )
            if message is None:
                if time.monotonic() - last_sent >= HEARTBEAT_INTERVAL_SEC:
                    last_sent = time.monotonic()
                    yield HEARTBEAT
                continue

            channel = message.get("channel")
            if isinstance(channel, bytes):
                channel = channel.decode()
            if channel == control_channel:
                data = message["data"]
                try:
                    kind = json.loads(data).get("type") if data else None
                except (ValueError, AttributeError):
                    kind = None
                if kind == CONTROL_REVOKED:
                    yield REVOKED
                    break
                continue

            if skip_channel is not None:
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
        await pubsub.unsubscribe(control_channel)
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
