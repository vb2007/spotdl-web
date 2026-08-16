"""Per-attempt download history (v24) -- see app/models/track_attempt.py's docstring.

A thin wrapper rather than duplicated `TrackAttempt(...)` construction at every
`download_track` exit point, matching this codebase's other single-purpose service
modules (retry.py, dedup.py). Callers are responsible for redacting `error_message`
before calling this -- see `TrackAttempt.error_message`'s own docstring."""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import TrackAttempt, TrackAttemptOutcome, TrackErrorType


def record_attempt(
    db: Session,
    track_id: uuid.UUID,
    attempt_number: int,
    started_at: datetime,
    finished_at: datetime,
    outcome: TrackAttemptOutcome,
    *,
    error_type: TrackErrorType | None = None,
    error_message: str | None = None,
    proxy_id: uuid.UUID | None = None,
) -> None:
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
        )
    )
