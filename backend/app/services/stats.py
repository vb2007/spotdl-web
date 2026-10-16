"""The admin stats page's aggregates (v44): how downloads are actually going, from v24's
track_attempts (v29/v35's network_path and error_type), v44's breaker_events and the live
tracks table.

Global by design: every user's rows are counted together, which is why only the admin
may read it. Nothing here returns an identity, a job or track title, or a proxy URL --
only counts, timestamps, error-type names and `proxies.redact()` labels.

Every metric is one SQL aggregate over its window (GROUP BY, never a per-proxy, per-path
or per-bucket query loop, per CLAUDE.md's bulk invariant). Buckets are UTC-aligned: hourly
for 24h, daily (UTC days) for 7d/30d, the last one being the current, partial bucket.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import BigInteger, case, func, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import FunctionElement

from app.models import (
    BreakerEvent,
    BreakerEventKind,
    NetworkPath,
    Proxy,
    Track,
    TrackAttempt,
    TrackAttemptOutcome,
    TrackErrorType,
    TrackState,
)
from app.services.serializers import _proxy_label

# window -> (bucket length, bucket count)
WINDOWS: dict[str, tuple[timedelta, int]] = {
    "24h": (timedelta(hours=1), 24),
    "7d": (timedelta(days=1), 7),
    "30d": (timedelta(days=1), 30),
}

# Only these touched the network (v35): holds, dedup skips and cancels are not attempts.
_NETWORK_OUTCOMES = (TrackAttemptOutcome.COMPLETED, TrackAttemptOutcome.FAILED)
# A path recorded as NULL on a real attempt: v24-era rows from before v29 recorded the
# path, and beat's stale-track reclaim (whose stuck invocation never said).
UNKNOWN = "unknown"
QUEUE_STATES = (TrackState.PENDING, TrackState.QUEUED, TrackState.DOWNLOADING, TrackState.WAITING)


class epoch_bucket(FunctionElement):
    """`floor(epoch seconds of <timestamp> / <seconds>)`: the index of the UTC-aligned
    bucket a timestamp falls in. Rendered per dialect; the bucket length is our own
    integer and is inlined, so the SELECT and GROUP BY expressions compile identically
    (two bound parameters would make Postgres reject the GROUP BY). The SQLite rendering
    for the in-process tests lives in tests/conftest.py, next to the JSONB shim."""

    type = BigInteger()
    inherit_cache = True
    name = "epoch_bucket"

    def __init__(self, column, seconds: int):
        self.seconds = int(seconds)
        super().__init__(column)


@compiles(epoch_bucket, "postgresql")
def _epoch_bucket_postgresql(element, compiler, **kw):
    return (
        f"CAST(FLOOR(EXTRACT(EPOCH FROM {compiler.process(element.clauses, **kw)}) "
        f"/ {element.seconds}) AS BIGINT)"
    )


def _aware(value: datetime | None) -> datetime | None:
    # SQLite (fast in-process tests) round-trips timestamptz as naive UTC.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value: datetime | None) -> str | None:
    value = _aware(value)
    return value.isoformat() if value is not None else None


def _rate(completed: int, attempts: int) -> float | None:
    return completed / attempts if attempts else None


def window_bounds(window: str, now: datetime) -> tuple[datetime, int, int]:
    """(window start, bucket seconds, first bucket index): the window covers whole
    UTC-aligned buckets, ending with the one `now` is in."""
    bucket, count = WINDOWS[window]
    seconds = int(bucket.total_seconds())
    current = int(now.timestamp()) // seconds
    first = current - count + 1
    return datetime.fromtimestamp(first * seconds, tz=timezone.utc), seconds, first


def _outcome_counts():
    """completed / failed (anything but "not found") / not_found, as SQL aggregates."""
    completed = func.sum(case((TrackAttempt.outcome == TrackAttemptOutcome.COMPLETED, 1), else_=0))
    not_found = func.sum(
        case(
            (
                (TrackAttempt.outcome == TrackAttemptOutcome.FAILED)
                & (TrackAttempt.error_type == TrackErrorType.LOOKUP),
                1,
            ),
            else_=0,
        )
    )
    return func.count().label("attempts"), completed.label("completed"), not_found.label("not_found")


def _counts_dict(attempts: int, completed: int | None, not_found: int | None) -> dict:
    completed = int(completed or 0)
    not_found = int(not_found or 0)
    return {
        "attempts": attempts,
        "completed": completed,
        "failed": attempts - completed - not_found,
        "not_found": not_found,
        "success_rate": _rate(completed, attempts),
    }


def admin_stats(db: Session, window: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    start, bucket_seconds, first_bucket = window_bounds(window, now)
    bucket_count = WINDOWS[window][1]
    in_window = (TrackAttempt.finished_at >= start) & TrackAttempt.outcome.in_(_NETWORK_OUTCOMES)

    # --- per network path -----------------------------------------------------------
    attempts, completed, not_found = _outcome_counts()
    path_rows = db.execute(
        select(TrackAttempt.network_path, attempts, completed, not_found)
        .where(in_window)
        .group_by(TrackAttempt.network_path)
    ).all()
    by_path = {
        (row.network_path.value if row.network_path is not None else UNKNOWN): _counts_dict(
            row.attempts, row.completed, row.not_found
        )
        for row in path_rows
    }
    # The three real paths always appear, so "IPv6 never used" reads as a zero, not a gap.
    network_paths = [
        {"path": path.value, **by_path.pop(path.value, _counts_dict(0, 0, 0))} for path in NetworkPath
    ]
    if UNKNOWN in by_path:
        network_paths.append({"path": UNKNOWN, **by_path[UNKNOWN]})

    # --- per proxy ------------------------------------------------------------------
    # Every configured proxy, with its window's attempts (zero if unused); the URL never
    # leaves this function, only its redacted label.
    attempts, completed, not_found = _outcome_counts()
    per_proxy = (
        select(TrackAttempt.proxy_id, attempts, completed, not_found)
        .where(in_window, TrackAttempt.proxy_id.is_not(None))
        .group_by(TrackAttempt.proxy_id)
        .subquery()
    )
    proxy_rows = db.execute(
        select(
            Proxy.url,
            Proxy.enabled,
            Proxy.last_success_at,
            Proxy.cooldown_until,
            func.coalesce(per_proxy.c.attempts, 0).label("attempts"),
            per_proxy.c.completed,
            per_proxy.c.not_found,
        )
        .outerjoin(per_proxy, per_proxy.c.proxy_id == Proxy.id)
        .order_by(func.coalesce(per_proxy.c.attempts, 0).desc(), Proxy.url)
    ).all()
    proxies = []
    for row in proxy_rows:
        cooldown_until = _aware(row.cooldown_until)
        proxies.append(
            {
                "label": _proxy_label(row.url),
                "enabled": row.enabled,
                **_counts_dict(row.attempts, row.completed, row.not_found),
                "last_success_at": _iso(row.last_success_at),
                # Only a cooldown still running is "current".
                "cooldown_until": (
                    cooldown_until.isoformat()
                    if cooldown_until is not None and cooldown_until > now
                    else None
                ),
            }
        )

    # --- failures by error_type over time --------------------------------------------
    bucket = epoch_bucket(TrackAttempt.finished_at, bucket_seconds).label("bucket")
    error_type = TrackAttempt.error_type
    failure_rows = db.execute(
        select(bucket, error_type, func.count().label("failures"))
        .where(TrackAttempt.finished_at >= start, TrackAttempt.outcome == TrackAttemptOutcome.FAILED)
        .group_by(bucket, error_type)
    ).all()
    series: dict[str, list[int]] = {}
    for row in failure_rows:
        index = row.bucket - first_bucket
        if not 0 <= index < bucket_count:
            continue  # a clock-skewed row stamped after `now`
        key = row.error_type.value if row.error_type is not None else UNKNOWN
        series.setdefault(key, [0] * bucket_count)[index] += row.failures
    order = [t.value for t in TrackErrorType] + [UNKNOWN]
    failures = {
        "buckets": [
            datetime.fromtimestamp((first_bucket + i) * bucket_seconds, tz=timezone.utc).isoformat()
            for i in range(bucket_count)
        ],
        "series": [
            {"error_type": key, "counts": series[key], "total": sum(series[key])}
            for key in order
            if key in series
        ],
    }

    # --- breaker history -------------------------------------------------------------
    # The window's events, plus a trip from before it whose pause reaches into it, so a
    # pause running across the window's start still draws.
    trip_kinds = (BreakerEventKind.TRIPPED, BreakerEventKind.ESCALATED)
    event_rows = db.execute(
        select(BreakerEvent)
        .where(
            (BreakerEvent.occurred_at >= start)
            | (BreakerEvent.kind.in_(trip_kinds) & (BreakerEvent.paused_until > start))
        )
        .order_by(BreakerEvent.occurred_at)
    ).scalars().all()
    breaker = {
        "events": [
            {
                "kind": event.kind.value,
                "occurred_at": _iso(event.occurred_at),
                "step_seconds": event.step_seconds,
                "trip_count": event.trip_count,
                "paused_until": _iso(event.paused_until),
                "manual": event.manual,
            }
            for event in event_rows
        ],
        "trips": sum(
            1 for event in event_rows if event.kind in trip_kinds and _aware(event.occurred_at) >= start
        ),
    }

    # --- the queue right now ---------------------------------------------------------
    state_rows = db.execute(
        select(Track.state, func.count().label("tracks"))
        .where(Track.state.in_(QUEUE_STATES))
        .group_by(Track.state)
    ).all()
    counts = {state.value: 0 for state in QUEUE_STATES}
    counts.update({row.state.value: row.tracks for row in state_rows})
    oldest_waiting = _aware(
        db.execute(select(func.min(Track.created_at)).where(Track.state == TrackState.WAITING)).scalar()
    )

    return {
        "window": window,
        "generated_at": now.isoformat(),
        "window_start": start.isoformat(),
        "bucket_seconds": bucket_seconds,
        "network_paths": network_paths,
        "proxies": proxies,
        "failures": failures,
        "breaker": breaker,
        "queue": {
            "counts": counts,
            "oldest_waiting_since": _iso(oldest_waiting),
            "oldest_waiting_age_seconds": (
                max(0, int((now - oldest_waiting).total_seconds())) if oldest_waiting else None
            ),
        },
    }
