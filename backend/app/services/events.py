"""Redis pub/sub event bus for live progress.

Publishers (Celery tasks) are plain sync code, so this module uses the sync `redis`
client. The SSE endpoint (app/routers/stream.py) subscribes with `redis.asyncio`
separately — the two sides never share a client. Event payloads are a flat,
provider-agnostic schema (`{type, ..., ts}`) precisely so a later WebSocket swap only
touches the transport, never this shape (per the v08 plan).

v17: channels are per-user, not global. Every publishing function takes the owning
user's id as its first, required, positional argument -- never optional, never
keyword-with-a-default -- so a future call site that forgets it fails loudly
(TypeError) instead of silently broadcasting to nobody's channel. Before v17 this
module published everything to one global channel that every connected client
subscribed to, which meant every logged-in user already received every other user's
track ids, job ids, titles and error strings live on the wire.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import redis

from app.config import get_settings

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "spotdl:events:"
# Matches every per-user channel -- only ever passed to PSUBSCRIBE, and only by
# routers/stream.py when the session is admin *and* the all-users toggle is on.
ADMIN_CHANNEL_PATTERN = f"{CHANNEL_PREFIX}*"

_client: redis.Redis | None = None


def channel_for(user_id: Any) -> str:
    return f"{CHANNEL_PREFIX}{user_id}"


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(get_settings().redis_url)
    return _client


def publish(user_id: uuid.UUID | str, event: dict[str, Any]) -> None:
    """Best-effort — a Redis hiccup must never fail the download/expand task calling
    this, only lose that one live-progress update."""
    payload = {"ts": datetime.now(timezone.utc).isoformat(), **event}
    try:
        _get_client().publish(channel_for(user_id), json.dumps(payload))
    except redis.RedisError:
        logger.warning("events.publish: failed to publish %s event", event.get("type"), exc_info=True)


def publish_track_event(
    user_id: uuid.UUID | str,
    track_id: Any,
    job_id: Any,
    state: str,
    *,
    progress: int | None = None,
    scheduled_at: datetime | None = None,
    error: str | None = None,
    attempt_count: int | None = None,
    title: str | None = None,
    artists: list[str] | None = None,
    album: str | None = None,
) -> None:
    # v23: title/artists/album, straight from the same `song_json` the caller already
    # has loaded -- zero extra cost. Before this, the frontend could only seed a live
    # track's metadata from a prior REST fetch (queue.ts's findCachedTrackMeta), so a
    # track that started and failed before ever being fetched rendered as
    # unknown-artist/unknown-song (see docs/GOTCHAS.md's v23 entry). Optional (not
    # required like `user_id`) since plenty of call sites -- job-level events, tests --
    # have no song metadata to offer; findCachedTrackMeta stays as the frontend fallback
    # for those and for events published before this field existed.
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
    if attempt_count is not None:
        event["attempt_count"] = attempt_count
    if title is not None:
        event["title"] = title
    if artists is not None:
        event["artists"] = artists
    if album is not None:
        event["album"] = album
    publish(user_id, event)


def publish_job_event(
    user_id: uuid.UUID | str,
    job_id: Any,
    state: str,
    *,
    error: str | None = None,
    archived: bool | None = None,
) -> None:
    event: dict[str, Any] = {"type": "job.state", "job_id": str(job_id), "state": state}
    if error is not None:
        event["error"] = error
    if archived is not None:
        event["archived"] = archived
    publish(user_id, event)


def publish_library_progress(
    user_id: uuid.UUID | str,
    *,
    processed: int,
    total: int,
    moved: int,
    skipped_present: int,
    quarantined: int,
    current_file: str | None = None,
    done: bool = False,
) -> None:
    """v28: library sort & move progress, published only to the admin who triggered the
    sweep (their own per-user channel) -- there is exactly one sweep at a time and it's
    admin-only, so this needs no broader audience the way track/job events do."""
    event: dict[str, Any] = {
        "type": "library.progress",
        "processed": processed,
        "total": total,
        "moved": moved,
        "skipped_present": skipped_present,
        "quarantined": quarantined,
        "done": done,
    }
    if current_file is not None:
        event["current_file"] = current_file
    publish(user_id, event)


def make_progress_callback(
    user_id: uuid.UUID | str,
    track_id: Any,
    job_id: Any,
    *,
    title: str | None = None,
    artists: list[str] | None = None,
    album: str | None = None,
) -> Callable[[Any, str], None]:
    """Returns a callback for spotdl's `ProgressHandler.update_callback` hook — every
    `SongTracker.notify_*` call (searching/getting-meta/downloading/converting/complete)
    ends by invoking this with the tracker itself (`.progress` is 0-100) and a status
    message. Verified against the installed spotdl 4.5.2 source
    (spotdl/download/progress_handler.py): `update_callback` is a plain settable
    attribute on `ProgressHandler`, not a DownloaderOptions key — there is no other way
    to reach it than setting it directly on the constructed instance.

    title/artists/album (v23) are captured in this closure rather than read from
    `tracker` each call -- the caller already has `song_json` loaded once per track, and
    every one of these callback invocations describes the same track.
    """

    def _callback(tracker: Any, message: str) -> None:
        publish_track_event(
            user_id,
            track_id,
            job_id,
            "downloading",
            progress=int(tracker.progress),
            title=title,
            artists=artists,
            album=album,
        )

    return _callback
