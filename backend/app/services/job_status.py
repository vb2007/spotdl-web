"""v62 (F1): a job's rollup status, published when it moves.

The dashboard's state chips (`counts_by_status`) are read once with a page and then moved
locally. A job's status moves without any `job.state` event (a track settling is what turns
`active` into `settled:complete`), so before this the browser could move a chip only for a
job on its loaded page: there it knew the old status from the row. This publishes the move
itself, old -> new, for every job.

The previous status lives in Redis (`spotdl:job-status:<job id>`), swapped atomically by
`SET ... GET`. Two writers finishing at once (the worker and an API cancel) therefore can't
both report the same old status: the events form one chain, each `prev_status` the previous
event's `status`, whatever order the commits landed in. A key that's missing (a job from
before v62, an expired key, a flushed Redis) gives an event with no `prev_status` at all,
and the browser re-reads its counts rather than guess.

Best effort, like every publish: a database or Redis failure loses this one status event,
never the change that caused it.
"""

import logging
import uuid
from typing import Any

import redis
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.job import Job
from app.services import events
from app.services.rollup import derive_rollup
from app.services.serializers import track_counts

logger = logging.getLogger(__name__)

KEY_PREFIX = "spotdl:job-status:"
# Refreshed on every change. A job quiet for this long reports its next move with no
# `prev_status`, and the browser re-reads its counts once.
KEY_TTL_SECONDS = 90 * 24 * 3600


def _key(job_id: Any) -> str:
    return f"{KEY_PREFIX}{job_id}"


def publish_change(db: Session, user_id: uuid.UUID | str, job_id: Any, *, created: bool = False) -> None:
    """Publishes `job.status` to the job's owner if the job's rollup status differs from the
    last one published. Call it after the commit that changed a track's or the job's state
    (the read here must see it), once per job: a bulk change of many tracks of one job needs
    one call. `created` is the job's first status, from `create_job` (`prev_status: null`).

    Reads with the caller's session (a test's rollback covers it), then ends that read's
    transaction, so a caller that goes on to wait (a download, a pacing sleep) never holds
    one open (v31's idle-in-transaction lesson). Never called with unflushed changes.

    Never raises: a completion's call sits inside the download's own `try`, where any
    exception reads as the download failing."""
    try:
        _publish_change(db, user_id, job_id, created)
    except Exception:
        logger.warning("job_status.publish_change: failed for job %s", job_id, exc_info=True)


def _publish_change(db: Session, user_id: uuid.UUID | str, job_id: Any, created: bool) -> None:
    if db.new or db.dirty or db.deleted:
        logger.warning("job_status.publish_change: called with pending changes for job %s; skipped", job_id)
        return
    try:
        row = db.execute(select(Job.state, Job.archived_at).where(Job.id == job_id)).one_or_none()
        status = derive_rollup(row.state, track_counts(db, job_id)).key if row is not None else None
        db.commit()
    except SQLAlchemyError:
        logger.warning("job_status.publish_change: couldn't read job %s", job_id, exc_info=True)
        db.rollback()
        return
    if row is None:
        return
    try:
        previous = events._get_client().set(_key(job_id), status, ex=KEY_TTL_SECONDS, get=True)
    except redis.RedisError:
        logger.warning("job_status.publish_change: Redis unavailable for job %s", job_id, exc_info=True)
        return
    prev = previous.decode() if isinstance(previous, bytes) else previous
    if prev == status:
        return
    if prev is not None:
        prev_status: Any = prev
    elif created:
        prev_status = None
    else:
        prev_status = events.PREV_STATUS_UNKNOWN
    events.publish_job_status_event(
        user_id, job_id, status, archived=row.archived_at is not None, prev_status=prev_status
    )
