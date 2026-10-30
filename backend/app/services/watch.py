"""v63: watched jobs and re-expansion.

A watched playlist or artist job is re-expanded every `jobs.watch_interval_hours`: beat's
tick (`tasks/beat.py`) picks the due ones (`next_expand_at <= now`) and `expand_job` runs in
re-expand mode, adding only the tracks new to the job. "Check now" (`POST
/api/jobs/{id}/reexpand`) runs the same thing on any expanded job, at once.

Postgres holds the schedule (`next_expand_at`), never a Celery ETA. What lives in Redis is
only the "one at a time per job" marker: set when a re-expansion is handed to the broker,
cleared when it ends, and expiring on its own if the worker dies. Not being a lock the work
relies on, the re-expansion itself stays safe to run twice (it inserts under the job's row
lock, and only ids the job doesn't have yet).
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Job, JobSourceType, Track

logger = logging.getLogger(__name__)

# Albums are immutable enough not to be offered (the plan); a track or a search has no list.
WATCHABLE_SOURCE_TYPES = frozenset({JobSourceType.PLAYLIST, JobSourceType.ARTIST})
# The UI offers daily, weekly and monthly; the API takes any whole number of hours between.
MIN_WATCH_INTERVAL_HOURS = 24
MAX_WATCH_INTERVAL_HOURS = 24 * 365

CAP_WINDOW = timedelta(hours=1)
# Beat's selection and the cap's count run under this transaction-level advisory lock, so two
# overlapping ticks can't both spend the same hour's budget.
_CAP_LOCK_KEY = 0x7370_6463_7665_6170  # "spdcveap"

KEY_PREFIX = "spotdl:reexpand:"
# Covers a backed-up expand queue (a library sweep shares it). Past it, a second run may start;
# that costs a redundant Spotify read, never a duplicate track.
RUN_MARKER_TTL_SECONDS = 3600

_client: redis.Redis | None = None


class MarkerUnavailable(Exception):
    """Redis didn't answer: the broker is the same Redis, so nothing could be queued anyway."""


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        # Short timeouts and no retries (rate_limit.py's reasons): a request waits seconds at
        # most on a dead Redis.
        _client = redis.Redis.from_url(
            get_settings().redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
            retry=Retry(NoBackoff(), 0),
        )
    return _client


def claim_run(job_id: uuid.UUID) -> bool:
    """Marks a re-expansion of `job_id` as queued or running; False if one already is."""
    try:
        return bool(_redis().set(f"{KEY_PREFIX}{job_id}", "1", nx=True, ex=RUN_MARKER_TTL_SECONDS))
    except redis.RedisError as exc:
        raise MarkerUnavailable(str(exc)) from exc


def release_run(job_id: uuid.UUID | str) -> None:
    """Best effort: a marker left behind expires by itself."""
    try:
        _redis().delete(f"{KEY_PREFIX}{job_id}")
    except redis.RedisError as exc:
        logger.warning("watch: couldn't clear the re-expansion marker of job %s: %s", job_id, exc)


def is_watchable(job: Job) -> bool:
    return job.source_type in WATCHABLE_SOURCE_TYPES


def lock_cap(db: Session) -> None:
    db.execute(select(func.pg_advisory_xact_lock(_CAP_LOCK_KEY)))


def started_this_hour(db: Session, now: datetime) -> int:
    """Re-expansions started in the last hour, every job's: the global cap's count."""
    return db.execute(
        select(func.count()).select_from(Job).where(Job.last_expanded_at > now - CAP_WINDOW)
    ).scalar_one()


def mark_started(job: Job, now: datetime) -> None:
    """A re-expansion of `job` starts now. A watched job's next one is due an interval later,
    set here rather than when the run ends, so a run lost with its worker is retried on
    schedule and never stops the watch."""
    job.last_expanded_at = now
    if job.watch_interval_hours is not None:
        job.next_expand_at = now + timedelta(hours=job.watch_interval_hours)


def new_track_counts(db: Session, job_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Per job, the tracks re-expansions added: every track inserted after the first
    expansion's. That expansion inserts all its tracks in one transaction, so they share one
    `created_at` (Postgres's `now()` is the transaction's start), and a re-expansion stamps
    its own with the statement's clock, later. One grouped query for the whole page, like serializers.track_counts_by_job; a job
    with none is absent."""
    if not job_ids:
        return {}
    first = (
        select(Track.job_id, func.min(Track.created_at).label("first_at"))
        .where(Track.job_id.in_(job_ids))
        .group_by(Track.job_id)
        .subquery()
    )
    rows = db.execute(
        select(Track.job_id, func.count())
        .join(first, and_(first.c.job_id == Track.job_id, Track.created_at > first.c.first_at))
        .group_by(Track.job_id)
    ).all()
    return {job_id: count for job_id, count in rows}


def new_tracks(db: Session, job_id: uuid.UUID) -> int:
    return new_track_counts(db, [job_id]).get(job_id, 0)
