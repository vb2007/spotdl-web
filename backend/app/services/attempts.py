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

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import NetworkPath, Track, TrackAttempt, TrackAttemptOutcome, TrackErrorType

# Outcomes that always mean this invocation went out to the network. A `cancelled` row
# only counts when it carries a network_path, i.e. the cancel landed mid-download rather
# than before dispatch or during the pacing wait (download.py).
_NETWORK_OUTCOMES = {TrackAttemptOutcome.COMPLETED, TrackAttemptOutcome.FAILED}


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
    proxy_id: uuid.UUID | None = None,
    network_path: NetworkPath | None = None,
) -> RecordedAttempt:
    """Adds one `track_attempts` row and returns its attempt_number together with the
    track's counters after it.

    The counter UPDATE runs first so it takes the track's row lock before the number is
    read: beat's stale-track reclaim (worker-meta) and download_track (worker-dl) can
    write rows for the same track concurrently, and the lock serializes them so `max + 1`
    is never computed twice. The unique constraint on (track_id, attempt_number) backs
    this up. `synchronize_session="fetch"` keeps an already-loaded Track in this session
    (download_track's) in step with the new counter values."""
    attempted = outcome in _NETWORK_OUTCOMES or network_path is not None
    failed = outcome == TrackAttemptOutcome.FAILED
    attempts_made, failure_count = db.execute(
        update(Track)
        .where(Track.id == track_id)
        .values(
            attempts_made=Track.attempts_made + (1 if attempted else 0),
            failure_count=Track.failure_count + (1 if failed else 0),
        )
        .returning(Track.attempts_made, Track.failure_count)
        .execution_options(synchronize_session="fetch")
    ).one()
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
            proxy_id=proxy_id,
            network_path=network_path,
        )
    )
    # Flushed here so a second record_attempt for the same track in this session (none
    # today, but cheap to rule out) sees this row in its max().
    db.flush()
    return RecordedAttempt(attempt_number, attempts_made, failure_count)
