"""Per-attempt download history (v24) -- see app/models/track_attempt.py's docstring.

A thin wrapper rather than duplicated `TrackAttempt(...)` construction at every
`download_track` exit point, matching this codebase's other single-purpose service
modules (retry.py, dedup.py). Callers are responsible for redacting `error_message`
before calling this -- see `TrackAttempt.error_message`'s own docstring.

v35: this is also the only writer of `track_attempts.attempt_number` and of the
`tracks.attempts_made`/`failure_count` display counters. Every row must go through
`record_attempt`, or the counters stop matching the history."""

import uuid
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import Exists, func, select, update
from sqlalchemy.orm import Session

from app.models import NetworkPath, Track, TrackAttempt, TrackAttemptOutcome, TrackErrorType

# Outcomes that always mean this invocation went out to the network. A `cancelled` row
# only counts when it carries a network_path, i.e. the cancel landed mid-download rather
# than before dispatch or during the pacing wait (download.py).
_NETWORK_OUTCOMES = {TrackAttemptOutcome.COMPLETED, TrackAttemptOutcome.FAILED}


# v40.1: every proxy transport failure's error message starts with this, so the next
# attempt (download_track) and the failure-spike alert (alerts.failure_spike) can tell one
# apart in track_attempts without a new error_type. Here rather than in retry.py because
# alerts.py must not import spotdl (see its module docstring).
TRANSPORT_FAILURE_PREFIX = "proxy failed to carry the request: "

# v55 (E3): every `failed` row beat's stale reclaim writes for a track stuck `downloading`
# starts with this. If that invocation was still alive, its real outcome later supersedes the
# row (record_attempt's `supersede_reclaim_after`), so one network attempt is counted once.
RECLAIM_PREFIX = "reclaimed: "


def latest_attempt_number(db: Session, track_id: uuid.UUID) -> int:
    """The track's newest attempt_number (0 with no rows). v55 (E4/E5): download_track reads
    it on entry as its ownership token. Every other writer that takes a track away from a
    running invocation (beat's reclaim) records a row, so a newer number means this
    invocation no longer owns the track."""
    return db.execute(
        select(func.coalesce(func.max(TrackAttempt.attempt_number), 0)).where(
            TrackAttempt.track_id == track_id
        )
    ).scalar_one()


def recorded_since(track_id: uuid.UUID, attempt_number: int) -> Exists:
    """`EXISTS` a row newer than `attempt_number` (see latest_attempt_number)."""
    return (
        select(TrackAttempt.id)
        .where(TrackAttempt.track_id == track_id, TrackAttempt.attempt_number > attempt_number)
        .exists()
    )


def previous_was_transport_failure(db: Session, track_id: uuid.UUID) -> bool:
    """Whether this track's latest real attempt was itself a proxy transport failure. Holds
    never touched the network, so they're skipped. Call before recording the current
    attempt."""
    previous = db.execute(
        select(TrackAttempt.outcome, TrackAttempt.error_message)
        .where(TrackAttempt.track_id == track_id, TrackAttempt.outcome != TrackAttemptOutcome.HELD)
        .order_by(TrackAttempt.attempt_number.desc())
        .limit(1)
    ).first()
    return (
        previous is not None
        and previous.outcome == TrackAttemptOutcome.FAILED
        and (previous.error_message or "").startswith(TRANSPORT_FAILURE_PREFIX)
    )


class RecordedAttempt(NamedTuple):
    attempt_number: int
    attempts_made: int
    failure_count: int


def record_attempt(
    db: Session,
    track_id: uuid.UUID,
    started_at: datetime,
    finished_at: datetime,
    outcome: TrackAttemptOutcome,
    *,
    error_type: TrackErrorType | None = None,
    error_message: str | None = None,
    warning_message: str | None = None,
    proxy_id: uuid.UUID | None = None,
    network_path: NetworkPath | None = None,
    supersede_reclaim_after: int | None = None,
) -> RecordedAttempt:
    """Adds one `track_attempts` row and returns its attempt_number together with the
    track's counters after it.

    The track's row lock is taken first, before anything is read: beat's stale-track
    reclaim (worker-meta) and download_track (worker-dl) can write rows for the same track
    concurrently, and the lock serializes them so `max + 1` is never computed twice. The
    unique constraint on (track_id, attempt_number) backs this up. `synchronize_session=
    "fetch"` keeps an already-loaded Track in this session (download_track's) in step with
    the new counter values.

    v55 (E3) `supersede_reclaim_after`: the caller's entry token (latest_attempt_number).
    If beat reclaimed the track while this invocation was still running, the `failed` row
    the reclaim wrote on its behalf is rewritten into this real outcome instead of a second
    row being added, and the counters move by the difference: one network attempt, counted
    once. A reclaim of an invocation that really died keeps its row, the only record of it."""
    # Derived from the row alone (outcome + network_path), so the counters can always be
    # recomputed from track_attempts -- the migration's backfill uses the same rule.
    attempted = outcome in _NETWORK_OUTCOMES or network_path is not None
    failed = outcome == TrackAttemptOutcome.FAILED
    db.execute(select(Track.id).where(Track.id == track_id).with_for_update())
    reclaim_row: TrackAttempt | None = None
    if supersede_reclaim_after is not None:
        reclaim_row = db.execute(
            select(TrackAttempt)
            .where(
                TrackAttempt.track_id == track_id,
                TrackAttempt.attempt_number > supersede_reclaim_after,
                TrackAttempt.outcome == TrackAttemptOutcome.FAILED,
                TrackAttempt.network_path.is_(None),
                TrackAttempt.error_message.startswith(RECLAIM_PREFIX),
            )
            .order_by(TrackAttempt.attempt_number)
            .limit(1)
        ).scalar_one_or_none()
    # The reclaim row was counted as a failed network attempt.
    superseded = int(reclaim_row is not None)
    attempts_made, failure_count = db.execute(
        update(Track)
        .where(Track.id == track_id)
        .values(
            attempts_made=Track.attempts_made + int(attempted) - superseded,
            failure_count=Track.failure_count + int(failed) - superseded,
            # Not a change to the track itself: without this the column's onupdate would
            # bump it, and a stray message's row on an already-cancelled track would
            # restart its job's archive clock. Paths that do change the track flush that
            # change (and its updated_at) on their own.
            updated_at=Track.updated_at,
        )
        .returning(Track.attempts_made, Track.failure_count)
        .execution_options(synchronize_session="fetch")
    ).one()
    if reclaim_row is not None:
        reclaim_row.started_at = started_at
        reclaim_row.finished_at = finished_at
        reclaim_row.outcome = outcome
        reclaim_row.error_type = error_type
        reclaim_row.error_message = error_message
        reclaim_row.warning_message = warning_message
        reclaim_row.proxy_id = proxy_id
        reclaim_row.network_path = network_path
        db.flush()
        return RecordedAttempt(reclaim_row.attempt_number, attempts_made, failure_count)
    attempt_number = db.execute(
        select(func.coalesce(func.max(TrackAttempt.attempt_number), 0) + 1).where(
            TrackAttempt.track_id == track_id
        )
    ).scalar_one()
    db.add(
        TrackAttempt(
            track_id=track_id,
            attempt_number=attempt_number,
            started_at=started_at,
            finished_at=finished_at,
            outcome=outcome,
            error_type=error_type,
            error_message=error_message,
            warning_message=warning_message,
            proxy_id=proxy_id,
            network_path=network_path,
        )
    )
    # Flushed here so a second record_attempt for the same track in this session (none
    # today, but cheap to rule out) sees this row in its max().
    db.flush()
    return RecordedAttempt(attempt_number, attempts_made, failure_count)
