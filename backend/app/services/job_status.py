"""v62 (F1): a job's rollup status, published when it moves.

The dashboard's state chips (`counts_by_status`) are read once with a page and then moved
locally. A job's status moves without any `job.state` event (a track settling is what turns
`active` into `settled:complete`), so before this the browser could move a chip only for a
job on its loaded page: there it knew the old status from the row. This publishes the move
itself, old -> new, for every job.

The previous status lives in Redis (`spotdl:job-status:<job id>`), swapped by `SET ... GET`.
The read of the status and that swap happen under the job's row lock (`SELECT ... FOR
UPDATE`), so two publishers for one job (the worker finishing a track, an API cancel) run one
after the other: the second reads after the first has swapped, and with every change already
committed. The events therefore form one chain, each `prev_status` the previous event's
`status`, and the last one is the job's status now (review round 1: a stale reading could
otherwise land last). The lock also keeps a cancel (which takes it) from committing between
the read of the job's state and of its tracks. A key that's missing (a job from before v62,
an expired key, a flushed Redis) gives an event with no `prev_status` at all, and the browser
re-reads its counts rather than guess.

Best effort, like every publish: a database or Redis failure loses these status events, never
the change that caused them.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.job import Job
from app.services import events
from app.services.rollup import derive_rollup
from app.services.serializers import track_counts_by_job

logger = logging.getLogger(__name__)

KEY_PREFIX = "spotdl:job-status:"
# Refreshed on every change. A job quiet for this long reports its next move with no
# `prev_status`, and the browser re-reads its counts once.
KEY_TTL_SECONDS = 90 * 24 * 3600


def _key(job_id: Any) -> str:
    return f"{KEY_PREFIX}{job_id}"


def publish_change(db: Session, user_id: uuid.UUID | str, job_id: Any, *, created: bool = False) -> None:
    """Publishes `job.status` to the job's owner if the job's rollup status differs from the
    last one published. `created` is the job's first status, from `create_job`
    (`prev_status: null`). See `publish_changes`."""
    publish_changes(db, {job_id: user_id}, created=created)


def publish_changes(db: Session, owners: dict[Any, uuid.UUID | str], *, created: bool = False) -> None:
    """`publish_change` for many jobs at once (`{job id: owner id}`): one locking read of the
    jobs, one grouped count of their tracks, one Redis round trip. Call it after the commit
    that changed a track's or a job's state (the read must see it), once per job: beat's
    dispatch and reclaim pass every job they touched.

    Reads with the caller's session (a test's rollback covers it) and ends that transaction,
    releasing the locks, so a caller that goes on to wait (a download, a pacing sleep) never
    holds one open (v31's idle-in-transaction lesson). Never called with unflushed changes.

    Never raises: a completion's call sits inside the download's own `try`, where any
    exception reads as the download failing."""
    if not owners:
        return
    if db.new or db.dirty or db.deleted:
        logger.warning("job_status.publish_changes: called with pending changes; skipped")
        return
    try:
        _publish_changes(db, owners, created)
    except Exception:
        logger.warning("job_status.publish_changes: failed for %d job(s)", len(owners), exc_info=True)
    finally:
        # Ends the read (and its locks) whatever happened; nothing was written to roll back.
        try:
            db.rollback()
        except Exception:
            logger.warning("job_status.publish_changes: couldn't end the read", exc_info=True)


def _publish_changes(db: Session, owners: dict[Any, uuid.UUID | str], created: bool) -> None:
    ids = [uuid.UUID(str(job_id)) for job_id in owners]
    # In id order, so two publishers locking overlapping sets never wait on each other in a
    # cycle. Only job rows are locked here, never a track.
    rows = db.execute(
        select(Job.id, Job.state, Job.archived_at)
        .where(Job.id.in_(ids))
        .order_by(Job.id)
        .with_for_update()
    ).all()
    if not rows:
        return
    counts = track_counts_by_job(db, [row.id for row in rows])
    statuses = {row.id: derive_rollup(row.state, counts.get(row.id, {})).key for row in rows}
    owner_by_id = {uuid.UUID(str(job_id)): user_id for job_id, user_id in owners.items()}

    pipe = events._get_client().pipeline(transaction=False)
    for row in rows:
        pipe.set(_key(row.id), statuses[row.id], ex=KEY_TTL_SECONDS, get=True)
    previous = pipe.execute()

    for row, before in zip(rows, previous, strict=True):
        status = statuses[row.id]
        prev = before.decode() if isinstance(before, bytes) else before
        if prev == status:
            continue
        if prev is not None:
            prev_status: Any = prev
        elif created:
            prev_status = None
        else:
            prev_status = events.PREV_STATUS_UNKNOWN
        events.publish_job_status_event(
            owner_by_id[row.id], row.id, status, archived=row.archived_at is not None, prev_status=prev_status
        )
