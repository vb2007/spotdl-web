"""Redis pub/sub event bus for live progress.

Publishers (Celery tasks) are plain sync code, so this module uses the sync `redis`
client. The SSE endpoint (app/routers/stream.py) subscribes with `redis.asyncio`
separately — the two sides never share a client. Event payloads are a flat,
provider-agnostic schema (`{type, ..., ts}`) precisely so a later WebSocket swap only
touches the transport, never this shape (per the v08 plan).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

import redis

from app.config import get_settings

logger = logging.getLogger(__name__)

CHANNEL = "spotdl:events"

_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(get_settings().redis_url)
    return _client


def publish(event: dict[str, Any]) -> None:
    """Best-effort — a Redis hiccup must never fail the download/expand task calling
    this, only lose that one live-progress update."""
    payload = {"ts": datetime.now(timezone.utc).isoformat(), **event}
    try:
        _get_client().publish(CHANNEL, json.dumps(payload))
    except redis.RedisError:
        logger.warning("events.publish: failed to publish %s event", event.get("type"), exc_info=True)


def publish_track_event(
    track_id: Any,
    job_id: Any,
    state: str,
    *,
    progress: int | None = None,
    scheduled_at: datetime | None = None,
    error: str | None = None,
) -> None:
    event: dict[str, Any] = {
        "type": "track.state",
        "track_id": str(track_id),
        "job_id": str(job_id),
        "state": state,
    }
    if progress is not None:
        event["progress"] = progress
    if scheduled_at is not None:
        event["scheduled_at"] = scheduled_at.isoformat()
    if error is not None:
        event["error"] = error
    publish(event)


def publish_job_event(job_id: Any, state: str, *, error: str | None = None) -> None:
    event: dict[str, Any] = {"type": "job.state", "job_id": str(job_id), "state": state}
    if error is not None:
        event["error"] = error
    publish(event)


def make_progress_callback(track_id: Any, job_id: Any) -> Callable[[Any, str], None]:
    """Returns a callback for spotdl's `ProgressHandler.update_callback` hook — every
    `SongTracker.notify_*` call (searching/getting-meta/downloading/converting/complete)
    ends by invoking this with the tracker itself (`.progress` is 0-100) and a status
    message. Verified against the installed spotdl 4.5.2 source
    (spotdl/download/progress_handler.py): `update_callback` is a plain settable
    attribute on `ProgressHandler`, not a DownloaderOptions key — there is no other way
    to reach it than setting it directly on the constructed instance.
    """

    def _callback(tracker: Any, message: str) -> None:
        publish_track_event(track_id, job_id, "downloading", progress=int(tracker.progress))

    return _callback
