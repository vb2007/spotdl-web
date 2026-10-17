"""Per-track backoff ladder and global circuit breaker — see CLAUDE.md's "Retry engine
numbers" for the exact sequence this implements."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ProxyError as RequestsProxyError
from requests.exceptions import Timeout as RequestsTimeout
from spotdl.providers.audio.base import AudioProviderError
from urllib3.exceptions import ProtocolError as Urllib3ProtocolError
from urllib3.exceptions import ProxyError as Urllib3ProxyError
from urllib3.exceptions import TimeoutError as Urllib3TimeoutError
from yt_dlp.networking.exceptions import ProxyError as YtDlpProxyError
from yt_dlp.networking.exceptions import TransportError as YtDlpTransportError

from app.config import get_settings
from app.models import BreakerEvent, BreakerEventKind, Track, TrackErrorType, TrackState, WorkerState
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


# Errors that can only mean a proxy failed, wherever they're seen: requests'/urllib3's
# ProxyError, and yt-dlp's wording for the same (its errors are mostly text on a
# DownloadError).
_PROXY_ONLY_TYPES = (ProxyTransportError, RequestsProxyError, Urllib3ProxyError, YtDlpProxyError)
_PROXY_ONLY_MARKERS = (
    "unable to connect to proxy",
    "tunnel connection failed",
    "407 proxy authentication",
)

# Connection-level failures (aborted, reset, refused, timed out). On a direct attempt
# these are ambiguous, so they keep their old classification there. On a proxied attempt
# our only TCP peer is the proxy, so they're the proxy failing to carry the request:
# found on the real stack, a proxy that accepts and then drops the connection surfaces as
# requests' plain ConnectionError("Connection aborted."), not its ProxyError. YouTube's
# own rate limiting comes back as an HTTP answer (429, a bot-check page), which a working
# proxy relays as such -- none of these types or markers covers that.
_TRANSPORT_TYPES = (
    RequestsConnectionError,
    RequestsTimeout,
    ConnectionError,
    TimeoutError,
    Urllib3ProtocolError,
    Urllib3TimeoutError,
    YtDlpTransportError,
)
_TRANSPORT_MARKERS = (
    "connection aborted",
    "connection reset by peer",
    "remote end closed connection",
    "connection refused",
    "timed out",
    "transporterror",
)


def _exception_chain(exc: BaseException) -> list[BaseException]:
    """`exc` and everything it was raised from. Also follows yt-dlp's DownloadError, which
    keeps the original error in `.exc_info` instead of chaining it."""
    chain: list[BaseException] = []
    cur: BaseException | None = exc
    while cur is not None and cur not in chain:
        chain.append(cur)
        nxt = cur.__cause__ or cur.__context__
        if nxt is None:
            exc_info = getattr(cur, "exc_info", None)
            if isinstance(exc_info, tuple) and len(exc_info) > 1 and isinstance(exc_info[1], BaseException):
                nxt = exc_info[1]
        cur = nxt
    return chain


def is_proxy_transport_error(exc: BaseException, *, via_proxy: bool = False) -> bool:
    """True if `exc` (or anything it was raised from) shows the request never got through
    its proxy. Without `via_proxy` only proxy-specific errors count; with it (the attempt
    went through a proxy) any connection-level failure does too."""
    types = _PROXY_ONLY_TYPES + (_TRANSPORT_TYPES if via_proxy else ())
    markers = _PROXY_ONLY_MARKERS + (_TRANSPORT_MARKERS if via_proxy else ())
    for link in _exception_chain(exc):
        if isinstance(link, types):
            return True
        text = str(link).lower()
        if any(marker in text for marker in markers):
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


def breaker_tripped(worker_state: WorkerState, now: datetime) -> bool:
    tripped_until = worker_state.breaker_tripped_until
    # SQLite (used for fast in-process tests, see v02/v03 gotchas) returns a naive
    # datetime even for this timestamptz column; a no-op against real Postgres/psycopg.
    if tripped_until is not None and tripped_until.tzinfo is None:
        tripped_until = tripped_until.replace(tzinfo=timezone.utc)
    return tripped_until is not None and tripped_until > now


def breaker_active(worker_state: WorkerState, now: datetime) -> bool:
    return bool(worker_state.paused) or breaker_tripped(worker_state, now)


def maybe_trip_breaker(db: Session, error_type: TrackErrorType | None = None) -> None:
    worker_state = get_worker_state(db)
    if worker_state.consecutive_failures >= BREAKER_TRIP_THRESHOLD:
        now = datetime.now(timezone.utc)
        # v44 (review round 2): a pause that ran out before any tick, release or success
        # recorded it is about to be overwritten; record its release first, so the history
        # never has a trip without its end.
        if worker_state.breaker_tripped_until is not None and not breaker_tripped(worker_state, now):
            record_breaker_release(db, now, end_running=False)
        worker_state.breaker_trip_count += 1
        delay = BREAKER_TRIP_DELAYS[min(worker_state.breaker_trip_count - 1, len(BREAKER_TRIP_DELAYS) - 1)]
        worker_state.breaker_tripped_until = now + delay
        tripped_on = worker_state.consecutive_failures
        # v44: the stats page's breaker history, in the same transaction as the trip itself
        # (and the alert below), so a rolled-back trip leaves no row either.
        db.add(
            BreakerEvent(
                kind=(
                    BreakerEventKind.TRIPPED
                    if worker_state.breaker_trip_count == 1
                    else BreakerEventKind.ESCALATED
                ),
                occurred_at=now,
                step_seconds=int(delay.total_seconds()),
                trip_count=worker_state.breaker_trip_count,
                paused_until=worker_state.breaker_tripped_until,
            )
        )
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
    picks another one or, with every proxy cooling, falls back to direct. download_track
    grants this only once in a row: a second consecutive transport failure goes through
    record_failure and consumes the rung, so a track whose proxied attempts keep dying
    (possibly after reaching YouTube, e.g. a reset mid-download) still follows the ladder's
    pace instead of retrying every 15m forever."""
    track.last_error = message
    track.last_error_type = TrackErrorType.OTHER
    track.state = TrackState.WAITING
    track.scheduled_at = datetime.now(timezone.utc) + next_delay(0)


def record_breaker_release(db: Session, now: datetime, *, end_running: bool, manual: bool = False) -> bool:
    """Ends the current trip's pause and records its `released` breaker event (v44), at
    most once per trip. Returns whether it recorded one.

    A pause that has already run out is released as of its own end time, whoever notices
    it first: beat's dispatch tick, a manual release, or a success. One still running ends
    only when `end_running` (a manual release, or a success, which clears the breaker), as
    of `now`; `manual` marks the admin's release. Clearing `breaker_tripped_until` is what
    makes this once-only: an expired value and NULL mean the same thing to every reader
    (breaker_active, alerts.breaker_released, the UI's `> now` checks). The row is locked
    so two of those callers can't both record it."""
    worker_state = get_worker_state(db)
    # Anything this session changed on the row goes to the database before the refresh
    # below reloads it.
    db.flush()
    db.refresh(worker_state, with_for_update=True)
    tripped_until = worker_state.breaker_tripped_until
    if tripped_until is None:
        return False
    # SQLite (fast in-process tests) returns a naive datetime; see breaker_tripped.
    if tripped_until.tzinfo is None:
        tripped_until = tripped_until.replace(tzinfo=timezone.utc)
    expired = tripped_until <= now
    if not expired and not end_running:
        return False
    worker_state.breaker_tripped_until = None
    db.add(
        BreakerEvent(
            kind=BreakerEventKind.RELEASED,
            occurred_at=tripped_until if expired else now,
            manual=manual and not expired,
        )
    )
    return True


def record_success(db: Session, track: Track) -> None:
    # v44: a success can be the first thing to notice an expired pause (a message that was
    # already queued runs before beat's next tick); record that release before it's cleared.
    record_breaker_release(db, datetime.now(timezone.utc), end_running=True)
    worker_state = get_worker_state(db)
    worker_state.consecutive_failures = 0
    worker_state.breaker_tripped_until = None
    worker_state.breaker_trip_count = 0
