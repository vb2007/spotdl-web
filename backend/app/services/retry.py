"""Per-track backoff ladder and global circuit breaker — see CLAUDE.md's "Retry engine
numbers" for the exact sequence this implements."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from requests.exceptions import ProxyError as RequestsProxyError
from spotdl.providers.audio.base import AudioProviderError
from urllib3.exceptions import ProxyError as Urllib3ProxyError

from app.config import get_settings
from app.models import Track, TrackErrorType, TrackState, WorkerState
from app.services import alerts

BREAKER_TRIP_THRESHOLD = 5
BREAKER_TRIP_DELAYS = [timedelta(minutes=30), timedelta(hours=2), timedelta(hours=6)]


class NoOutputFileError(Exception):
    """spotdl's search_and_download completed without raising but returned no output
    path. Root-caused in v23 (docs/GOTCHAS.md): YouTube's PO-token bot-check raises a
    real AudioProviderError deep inside spotdl, which spotdl itself catches and swallows,
    returning `None` instead of propagating it. A bare RuntimeError here used to classify
    as OTHER, which shares the retry ladder but never feeds the circuit breaker -- so a
    100% failure rate across every track in the queue never tripped it."""


class ProxyTransportError(Exception):
    """The attempt never got past its proxy (connect timeout, refused, a failed CONNECT
    tunnel, proxy auth): nothing reached YouTube, so it says nothing about rate limiting
    and nothing about the track. v40.1: on production every enabled proxy was dead, and
    this used to surface as a breaker-feeding `no_output`, which re-tripped the breaker on
    every release and kept every proxy-rung track from ever reaching a verdict."""


# yt-dlp's own wording for the same failure (its proxy errors aren't requests'/urllib3's
# exception classes, only text on a DownloadError).
_PROXY_TRANSPORT_MARKERS = (
    "unable to connect to proxy",
    "tunnel connection failed",
    "407 proxy authentication",
)


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    cur: BaseException | None = exc
    while cur is not None and cur not in chain:
        chain.append(cur)
        cur = cur.__cause__ or cur.__context__
    return chain


def is_proxy_transport_error(exc: BaseException) -> bool:
    """True if anything on `exc`'s cause/context chain is a proxy-level transport failure:
    requests'/urllib3's ProxyError, or yt-dlp's text for the same thing."""
    for link in _exception_chain(exc):
        if isinstance(link, (ProxyTransportError, RequestsProxyError, Urllib3ProxyError)):
            return True
        text = str(link).lower()
        if any(marker in text for marker in _PROXY_TRANSPORT_MARKERS):
            return True
    return False


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


def maybe_trip_breaker(db: Session, error_type: TrackErrorType | None = None) -> None:
    worker_state = get_worker_state(db)
    if worker_state.consecutive_failures >= BREAKER_TRIP_THRESHOLD:
        worker_state.breaker_trip_count += 1
        delay = BREAKER_TRIP_DELAYS[min(worker_state.breaker_trip_count - 1, len(BREAKER_TRIP_DELAYS) - 1)]
        worker_state.breaker_tripped_until = datetime.now(timezone.utc) + delay
        tripped_on = worker_state.consecutive_failures
        # v40.1: every trip starts a fresh streak, so re-tripping after a release takes
        # another BREAKER_TRIP_THRESHOLD consecutive failures, not one. Before this the
        # counter only reset on a success: once the queue held nothing but tracks that
        # can't succeed, one failure per release re-tripped it at 6h, forever, for every
        # user. Escalation still holds until a success (breaker_trip_count isn't reset).
        worker_state.consecutive_failures = 0
        # v36: queued on this session, sent only if the caller's commit lands (never in
        # the download's own path -- see alerts.enqueue_after_commit).
        step = alerts.format_duration(delay)
        verb = "tripped" if worker_state.breaker_trip_count == 1 else "escalated"
        last_error = error_type.value if error_type is not None else "unknown"
        alerts.enqueue_after_commit(
            db,
            alerts.CATEGORY_BREAKER,
            # One fingerprint per trip (its own end time): a later, separate trip is news
            # even inside the cooldown, so the room never ends on a stale "released".
            f"trip:{step}:{worker_state.breaker_tripped_until:%Y%m%dT%H%M%S}",
            f"Circuit breaker {verb}: downloads paused for {step} "
            f"(trip #{worker_state.breaker_trip_count}, after "
            f"{tripped_on} consecutive failures; last error "
            f"{last_error}). Paused until "
            f"{worker_state.breaker_tripped_until:%Y-%m-%d %H:%M} UTC.",
        )


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
        maybe_trip_breaker(db, error_type)


def record_transport_failure(db: Session, track: Track, message: str) -> None:
    """A proxy-rung attempt that never got past its proxy (ProxyTransportError). The track
    wasn't evaluated, so it doesn't climb the ladder (attempt_count unchanged: the next
    try is still this rung) and nothing feeds the breaker. It comes back after the
    ladder's first step, by which time this proxy is cooling down and the dispatch either
    picks another one or, with every proxy cooling, falls back to direct."""
    track.last_error = message
    track.last_error_type = TrackErrorType.OTHER
    track.state = TrackState.WAITING
    track.scheduled_at = datetime.now(timezone.utc) + next_delay(0)


def record_success(db: Session, track: Track) -> None:
    worker_state = get_worker_state(db)
    worker_state.consecutive_failures = 0
    worker_state.breaker_tripped_until = None
    worker_state.breaker_trip_count = 0
