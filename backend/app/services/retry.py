"""Per-track backoff ladder and global circuit breaker — see CLAUDE.md's "Retry engine
numbers" for the exact sequence this implements."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from spotdl.providers.audio.base import AudioProviderError

from app.config import get_settings
from app.models import Track, TrackErrorType, TrackState, WorkerState

BREAKER_TRIP_THRESHOLD = 5
BREAKER_TRIP_DELAYS = [timedelta(minutes=30), timedelta(hours=2), timedelta(hours=6)]


class NoOutputFileError(Exception):
    """spotdl's search_and_download completed without raising but returned no output
    path. Root-caused in v23 (docs/GOTCHAS.md): YouTube's PO-token bot-check raises a
    real AudioProviderError deep inside spotdl, which spotdl itself catches and swallows,
    returning `None` instead of propagating it. A bare RuntimeError here used to classify
    as OTHER, which shares the retry ladder but never feeds the circuit breaker -- so a
    100% failure rate across every track in the queue never tripped it."""


def classify_error(exc: Exception) -> TrackErrorType:
    if isinstance(exc, AudioProviderError):
        return TrackErrorType.AUDIO_PROVIDER
    if isinstance(exc, LookupError):
        return TrackErrorType.LOOKUP
    if isinstance(exc, NoOutputFileError):
        return TrackErrorType.NO_OUTPUT
    return TrackErrorType.OTHER


def next_delay(attempt_count: int) -> timedelta:
    ladder = [timedelta(seconds=s) for s in get_settings().ladder_seconds]
    return ladder[min(attempt_count, len(ladder) - 1)]


def get_worker_state(db: Session) -> WorkerState:
    worker_state = db.get(WorkerState, 1)
    if worker_state is None:
        worker_state = WorkerState(id=1)
        db.add(worker_state)
        db.flush()
    return worker_state


def breaker_active(worker_state: WorkerState, now: datetime) -> bool:
    tripped_until = worker_state.breaker_tripped_until
    # SQLite (used for fast in-process tests, see v02/v03 gotchas) returns a naive
    # datetime even for this timestamptz column; a no-op against real Postgres/psycopg.
    if tripped_until is not None and tripped_until.tzinfo is None:
        tripped_until = tripped_until.replace(tzinfo=timezone.utc)
    return bool(worker_state.paused) or (tripped_until is not None and tripped_until > now)


def maybe_trip_breaker(db: Session) -> None:
    worker_state = get_worker_state(db)
    if worker_state.consecutive_failures >= BREAKER_TRIP_THRESHOLD:
        worker_state.breaker_trip_count += 1
        delay = BREAKER_TRIP_DELAYS[min(worker_state.breaker_trip_count - 1, len(BREAKER_TRIP_DELAYS) - 1)]
        worker_state.breaker_tripped_until = datetime.now(timezone.utc) + delay


def record_failure(db: Session, track: Track, error_type: TrackErrorType, message: str) -> None:
    track.last_error = message
    track.last_error_type = error_type

    if error_type == TrackErrorType.LOOKUP:
        # Terminal — never touch scheduled_at, never retried.
        track.state = TrackState.LOOKUP_FAILED
        return

    # next_delay reads attempt_count as "failures before this one" (0 on the very first
    # failure), computed before incrementing, so the ladder lines up with CLAUDE.md's
    # documented 15m -> 1h -> 4h -> 12h -> 24h sequence rather than skipping its first rung.
    delay = next_delay(track.attempt_count)
    track.attempt_count += 1
    track.state = TrackState.WAITING
    track.scheduled_at = datetime.now(timezone.utc) + delay

    # AUDIO_PROVIDER and NO_OUTPUT both feed the breaker -- both are real YT-Music-side
    # rate-limit/bot-check signals (v23: NO_OUTPUT is the same AudioProviderError, just
    # swallowed internally by spotdl before it ever reaches this function's caller, see
    # NoOutputFileError's docstring). Plain OTHER errors share the ladder but shouldn't
    # trip a pause meant for that specific signal.
    if error_type in (TrackErrorType.AUDIO_PROVIDER, TrackErrorType.NO_OUTPUT):
        worker_state = get_worker_state(db)
        worker_state.consecutive_failures += 1
        maybe_trip_breaker(db)


def record_success(db: Session, track: Track) -> None:
    worker_state = get_worker_state(db)
    worker_state.consecutive_failures = 0
    worker_state.breaker_tripped_until = None
    worker_state.breaker_trip_count = 0
