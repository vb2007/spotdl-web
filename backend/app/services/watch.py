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
from sqlalchemy import and_, func, select, update
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
# A claimed run's next check is this close until its task starts (schedule_next), like the
# tracks' outbox lease (tasks/expand.py's DISPATCH_LEASE): a run lost between its claim and its
# start (beat killed after its commit, a broker that took the message and lost it) is claimed
# again a quarter-hour later, never an interval later.
CLAIM_LEASE = timedelta(minutes=15)
# Beat's selection and the cap's count run under this transaction-level advisory lock, so two
# overlapping ticks can't both spend the same hour's budget.
_CAP_LOCK_KEY = 0x7370_6463_7665_6170  # "spdcveap"

KEY_PREFIX = "spotdl:reexpand:"
# As long as the claim's lease (review round 6): a run lost before its task started is
# claimed again once the lease is due, not an hour later. A run still queued behind a
# backed-up expand queue (a library sweep shares it) past it may get a second claim; that
# costs a redundant Spotify read, never a duplicate track.
RUN_MARKER_TTL_SECONDS = int(CLAIM_LEASE.total_seconds())
# Once its task starts, a run holds its marker this long (start_run): a discography's read can
# approach an hour (celery_app.py's visibility timeout note), and "one at a time per job" must
# hold for all of it. A worker killed mid-run leaves it to expire.
RUNNING_MARKER_TTL_SECONDS = 2 * 3600

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


def claim_run(job_id: uuid.UUID) -> str | None:
    """Marks a re-expansion of `job_id` as queued or running: the claim's token, or None if
    one already is. The run hands the token back to release_run."""
    token = uuid.uuid4().hex
    try:
        claimed = _redis().set(f"{KEY_PREFIX}{job_id}", token, nx=True, ex=RUN_MARKER_TTL_SECONDS)
    except redis.RedisError as exc:
        raise MarkerUnavailable(str(exc)) from exc
    return token if claimed else None


def start_run(job_id: uuid.UUID | str, token: str | None) -> bool:
    """The run claimed with `token` has started: it keeps its marker for the whole run
    (RUNNING_MARKER_TTL_SECONDS), taking it back if it expired while the message waited in a
    backed-up queue. False when another claim holds it: this run was superseded (beat claimed
    the job again once the lease ran out), and the newer message does the work, so this one
    skips its Spotify read. `None` (a message sent without a token) always runs. Best effort on
    a Redis error: the run goes ahead, as it would have before markers."""
    if token is None:
        return True
    key = f"{KEY_PREFIX}{job_id}"
    try:
        client = _redis()
        held = client.get(key)
        if held is None:
            return bool(client.set(key, token, nx=True, ex=RUNNING_MARKER_TTL_SECONDS))
        if (held.decode() if isinstance(held, bytes) else held) != token:
            return False
        client.expire(key, RUNNING_MARKER_TTL_SECONDS)
        return True
    except redis.RedisError as exc:
        logger.warning("watch: couldn't read the re-expansion marker of job %s: %s", job_id, exc)
        return True


def release_run(job_id: uuid.UUID | str, token: str | None) -> None:
    """Clears the claim `token` made, never a later one: a run whose marker expired behind a
    backed-up queue mustn't free the claim of the run that replaced it. `None` (a message
    sent without one) clears whatever is there. Best effort: a marker left behind expires by
    itself."""
    key = f"{KEY_PREFIX}{job_id}"
    try:
        client = _redis()
        if token is not None:
            held = client.get(key)
            if held is None or (held.decode() if isinstance(held, bytes) else held) != token:
                return
        client.delete(key)
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
    """A re-expansion of `job` is claimed now (the hourly cap counts it). A watched job's next
    check is the claim's lease until the task starts and schedules the next one
    (schedule_next)."""
    job.last_expanded_at = now
    if job.watch_interval_hours is not None:
        job.next_expand_at = now + CLAIM_LEASE


def schedule_next(db: Session, job_id: uuid.UUID) -> None:
    """The run has started: a watched job's next check is an interval after its claim, set
    before the Spotify read, so a failed read waits for it like a run that found nothing. Only
    while the next check is still this claim's lease: a watch set or changed since keeps its
    own (the caller commits)."""
    db.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.watch_interval_hours.is_not(None),
            Job.next_expand_at == Job.last_expanded_at + CLAIM_LEASE,
        )
        .values(next_expand_at=Job.last_expanded_at + func.make_interval(0, 0, 0, 0, Job.watch_interval_hours))
        .execution_options(synchronize_session=False)
    )


def new_track_counts(db: Session, job_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Per job, the tracks re-expansions added: every track inserted after the first
    expansion's. That expansion inserts all its tracks in one transaction, so they share one
    `created_at` (Postgres's `now()` is the transaction's start), and a re-expansion stamps
    its batch with one later reading of the clock. One grouped query for the whole page, like serializers.track_counts_by_job; a job
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
        # Only a job that has been re-expanded: a job from before v63 never was, whatever its
        # tracks' timestamps say.
        .join(Job, and_(Job.id == Track.job_id, Job.last_expanded_at.is_not(None)))
        .group_by(Track.job_id)
    ).all()
    return {job_id: count for job_id, count in rows}


def new_tracks(db: Session, job_id: uuid.UUID) -> int:
    return new_track_counts(db, [job_id]).get(job_id, 0)
