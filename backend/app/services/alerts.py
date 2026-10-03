"""Matrix alerts (v36) -- conditions that need a human, pushed into the same Matrix room
v33's deploy pipeline posts to (one bot, one room, see docs/DEPLOYMENT.md).

Categories (plan/master-v4/v36-alerting.md):

- `breaker`: the circuit breaker tripped, escalated, or released. Trip/escalation is
  queued at the trip point itself (retry.maybe_trip_breaker) and only leaves the process
  once that transaction commits; release is noticed by the watchdog below.
- `spike`: the last N real attempts (any track) all failed with the same error_type, the
  early warning that YouTube changed something (v31.1's YOUTUBE_PLAYER_CLIENTS).
- `beat_stale`: beat's heartbeat (written by every dispatch_due_tracks tick) is too old.
- `library`: a library sweep finished or crashed (tasks/library.py).
- `test`: the admin settings page's "send test alert" button.

Never in the hot path: a download or request only ever *enqueues* (`enqueue`, fire and
forget, on worker-meta's `meta` queue) and the send happens in `tasks/alerts.send_alert`.
The watchdog's own checks already run inside worker-meta and send directly. A failed
send is logged once and dropped: no retry, and nothing upstream ever sees it.

Unconfigured (any of MATRIX_HOMESERVER_URL / MATRIX_ACCESS_TOKEN / MATRIX_ROOM_ID unset)
means alerts are off: nothing is enqueued, the watchdog doesn't check, and worker-meta's
startup log says so once. The token is read here and nowhere else, and only ever goes into
the Authorization header -- never a log line, an exception message or an API response.

Dedupe/cooldown: a Redis key per (category, fingerprint), claimed with SET NX EX before
sending, so two workers can't both send the same alert and a worker-meta restart doesn't
re-fire one inside its window. The window is `app_settings.alert_cooldown_minutes`
(default 60). Fingerprints are chosen so that only a *repeat* of the same condition is
suppressed: the breaker step (`trip:30m`, `trip:2h`, ...), the spiking error_type, one
fixed key for a stale beat, and a per-run key for library sweeps (never suppressed).

Every message body goes through redact_text() first -- spotdl's errors echo proxy
credentials (CLAUDE.md invariant) -- both before it's enqueued (task args reach the broker
and Celery's own task log lines) and again right before it's sent.
"""

import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import NamedTuple
from urllib.parse import quote

import httpx
import redis
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.config import DEV_ENV_MARKER, get_settings
from app.services.redaction import redact_text

logger = logging.getLogger(__name__)

CATEGORY_BREAKER = "breaker"
CATEGORY_SPIKE = "spike"
CATEGORY_BEAT_STALE = "beat_stale"
CATEGORY_LIBRARY = "library"
CATEGORY_TEST = "test"

# Category -> its app_settings on/off column. `test` has none: the button always sends.
TOGGLE_FIELDS = {
    CATEGORY_BREAKER: "alerts_breaker_enabled",
    CATEGORY_SPIKE: "alerts_spike_enabled",
    CATEGORY_BEAT_STALE: "alerts_beat_stale_enabled",
    CATEGORY_LIBRARY: "alerts_library_enabled",
}

COOLDOWN_KEY_PREFIX = "spotdl:alerts:cooldown:"
# Holds the fingerprint of the last trip/escalation alert actually sent, cleared when the
# watchdog reports its release -- so "released" is only ever sent for a trip the room heard
# about, and each release is keyed to its own trip.
BREAKER_OPEN_KEY = "spotdl:alerts:breaker_open"
# Per error_type: finished_at of the newest attempt in the last spike alert sent, so the
# same rows aren't re-announced once the cooldown lapses with no new attempt since.
SPIKE_NEWEST_KEY_PREFIX = "spotdl:alerts:spike_newest:"
BEAT_HEARTBEAT_KEY = "spotdl:beat:heartbeat"

# How often the watchdog checks (breaker release, failure spike, beat heartbeat).
WATCHDOG_INTERVAL_SECONDS = 60
# Per phase (connect/read/write/pool), not end to end, and name resolution isn't covered:
# a homeserver whose DNS hangs holds the meta slot (or the test request) longer.
SEND_TIMEOUT_SECONDS = 10.0
# An enqueued alert older than this is dropped, not sent (see enqueue).
ALERT_TASK_EXPIRES_SECONDS = 300
# Matrix accepts far more; this keeps a quoted traceback from flooding the room.
MAX_BODY_CHARS = 2000
# v33: the homeserver sits behind Cloudflare, which bans default library User-Agents
# (HTTP 403 "error code: 1010") -- same explicit UA shape as .github/scripts/matrix_notify.py.
USER_AGENT = "spotdl-web-alerts/1 (+https://github.com/vb2007/spotdl-web)"

_PENDING_KEY = "spotdl_pending_alerts"
_ENV_VARS = ("MATRIX_HOMESERVER_URL", "MATRIX_ACCESS_TOKEN", "MATRIX_ROOM_ID")


class MatrixConfig(NamedTuple):
    homeserver_url: str
    access_token: str
    room_id: str


class AlertsNotConfigured(Exception):
    pass


class AlertSendError(Exception):
    """Carries only a redacted, token-free description of what went wrong."""


def _config_values() -> tuple[str, str, str]:
    settings = get_settings()
    token = settings.matrix_access_token.get_secret_value() if settings.matrix_access_token else ""
    return (
        (settings.matrix_homeserver_url or "").strip().rstrip("/"),
        token.strip(),
        (settings.matrix_room_id or "").strip(),
    )


def matrix_config() -> MatrixConfig | None:
    url, token, room = _config_values()
    if not (url and token and room):
        return None
    return MatrixConfig(url, token, room)


def is_configured() -> bool:
    return matrix_config() is not None


def missing_config_vars() -> list[str]:
    return [name for name, value in zip(_ENV_VARS, _config_values()) if not value]


def log_startup_state() -> None:
    config = matrix_config()
    if config is None:
        logger.info(
            "alerts: Matrix alerts are off (%s unset)", ", ".join(missing_config_vars())
        )
    else:
        logger.info("alerts: Matrix alerts are on (room %s)", config.room_id)


def format_body(text: str) -> str:
    """The message exactly as it reaches the room: labelled (dev and production share
    the room), redacted, and capped."""
    label = "spotdl-web"
    if (get_settings().spotdl_env or "").strip().lower() == DEV_ENV_MARKER:
        label = "spotdl-web (dev)"
    body = redact_text(f"[{label}] {text}")
    if len(body) > MAX_BODY_CHARS:
        body = body[: MAX_BODY_CHARS - 1] + "…"
    return body


_SAFE_TEXT_ERRORS = (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError)


def send_now(text: str) -> None:
    """One PUT to the room. Raises AlertsNotConfigured or AlertSendError; never retries."""
    config = matrix_config()
    if config is None:
        raise AlertsNotConfigured()
    if not config.access_token.isprintable():
        # h11 would refuse the header and quote it, repr-escaped, in its error (review
        # round 5) -- so a malformed token never reaches a request at all.
        raise AlertSendError("MATRIX_ACCESS_TOKEN contains a non-printable character")
    url = (
        f"{config.homeserver_url}/_matrix/client/v3/rooms/{quote(config.room_id, safe='')}"
        f"/send/m.room.message/{uuid.uuid4().hex}"
    )
    try:
        response = httpx.put(
            url,
            json={"msgtype": "m.notice", "body": format_body(text)},
            headers={
                "Authorization": f"Bearer {config.access_token}",
                "User-Agent": USER_AGENT,
            },
            timeout=SEND_TIMEOUT_SECONDS,
        )
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
        # Only connect/timeout/network errors keep their text (host and errno). Anything
        # else -- a protocol error can quote a header value, h11's "Illegal header value
        # b'Bearer ...'", repr-escaped so no literal scrub would match -- is reported by
        # class name alone. InvalidURL (a malformed MATRIX_HOMESERVER_URL) isn't an
        # HTTPError subclass, hence the explicit tuple.
        if isinstance(exc, _SAFE_TEXT_ERRORS):
            message = f"{type(exc).__name__}: {exc}".replace(config.access_token, "[token]")
        else:
            message = type(exc).__name__
        raise AlertSendError(redact_text(message)) from None
    if response.status_code >= 400:
        raise AlertSendError(
            redact_text(f"HTTP {response.status_code}: {response.text[:200]}")
        )


_redis_client: redis.Redis | None = None
_redis_pid: int | None = None


def _redis() -> redis.Redis:
    # Per process: the watchdog's process forks prefork children, which build their own.
    global _redis_client, _redis_pid
    if _redis_client is None or _redis_pid != os.getpid():
        _redis_client = redis.Redis.from_url(get_settings().redis_url)
        _redis_pid = os.getpid()
    return _redis_client


def _claim_cooldown(category: str, fingerprint: str, cooldown_seconds: int) -> bool:
    key = f"{COOLDOWN_KEY_PREFIX}{category}:{fingerprint}"
    stamp = datetime.now(timezone.utc).isoformat()
    return bool(_redis().set(key, stamp, nx=True, ex=max(1, int(cooldown_seconds))))


def deliver(category: str, fingerprint: str, text: str, cooldown_seconds: int) -> str:
    """Cooldown gate, then send. Returns "sent", "suppressed" or "failed"; never raises.
    The cooldown is claimed before sending, so a failed send isn't retried inside the
    window either -- "logged once and dropped"."""
    try:
        claimed = _claim_cooldown(category, fingerprint, cooldown_seconds)
    except redis.RedisError as exc:
        # Can't tell whether it was already sent -- dropping beats double-sending.
        logger.warning(
            "alerts: %s alert dropped, cooldown check failed (%s)", category, type(exc).__name__
        )
        return "failed"
    if not claimed:
        logger.info(
            "alerts: %s alert suppressed (cooldown, fingerprint %s)", category, fingerprint
        )
        return "suppressed"
    try:
        send_now(text)
    except AlertsNotConfigured:
        logger.info("alerts: %s alert not sent, Matrix alerts are off", category)
        return "failed"
    except AlertSendError as exc:
        logger.warning("alerts: %s alert not sent: %s", category, exc)
        return "failed"
    except Exception as exc:
        # Belt and braces for "never raises": anything unforeseen is a dropped alert too.
        logger.warning("alerts: %s alert not sent (%s)", category, type(exc).__name__)
        return "failed"
    logger.info("alerts: %s alert sent (fingerprint %s)", category, fingerprint)
    return "sent"


def category_enabled(settings_row, category: str) -> bool:
    field = TOGGLE_FIELDS.get(category)
    return True if field is None else bool(getattr(settings_row, field))


def enqueue(category: str, fingerprint: str, text: str) -> None:
    """Fire and forget onto worker-meta. A no-op when alerts are off; never raises, and
    never waits on a broker retry (retry=False)."""
    if not is_configured():
        return
    # Redacted here too, not only in format_body: the text travels through the broker
    # (Redis) as a task argument, and Celery's own "Task ... received/succeeded" log lines
    # echo task args -- found by v36's real-stack redaction check.
    text = redact_text(text)
    try:
        from app.tasks.alerts import send_alert

        # expires: a message only reached after a crash (prefetched, redelivered after the
        # visibility timeout) is discarded rather than sent hours late (review round 6).
        send_alert.apply_async(
            args=[category, fingerprint, text],
            queue="meta",
            retry=False,
            expires=ALERT_TASK_EXPIRES_SECONDS,
        )
    except Exception as exc:
        logger.warning("alerts: could not enqueue %s alert (%s)", category, type(exc).__name__)


def enqueue_after_commit(db: Session, category: str, fingerprint: str, text: str) -> None:
    """Queues an alert on `db` that is enqueued only once its transaction commits, and
    dropped if it rolls back -- so the room never hears about a breaker trip that was
    never persisted."""
    db.info.setdefault(_PENDING_KEY, []).append((category, fingerprint, text))


@event.listens_for(Session, "after_commit")
def _enqueue_pending(session: Session) -> None:
    for category, fingerprint, text in session.info.pop(_PENDING_KEY, []):
        enqueue(category, fingerprint, text)


@event.listens_for(Session, "after_rollback")
def _drop_pending(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)


def format_duration(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def mark_breaker_open(trip_fingerprint: str) -> None:
    try:
        _redis().set(BREAKER_OPEN_KEY, trip_fingerprint)
    except redis.RedisError as exc:
        logger.warning("alerts: could not record breaker-open marker (%s)", type(exc).__name__)


def record_beat_heartbeat() -> None:
    """Called on every dispatch_due_tracks tick, whether or not alerts are configured.
    Best-effort: a Redis hiccup loses one heartbeat, never the tick."""
    try:
        _redis().set(BEAT_HEARTBEAT_KEY, f"{time.time():.3f}")
    except redis.RedisError as exc:
        logger.warning("alerts: could not write beat heartbeat (%s)", type(exc).__name__)


# --- the watchdog's checks -------------------------------------------------------------


def failure_spike(db: Session, threshold: int, window_minutes: int, now: datetime):
    """(fingerprint, text, newest finished_at) when the newest `threshold` real attempts inside the window all
    failed with one error_type, else None. Computed from track_attempts (v35's
    error_type): only completed/failed rows count -- holds, dedup skips and cancels never
    touched the network, so they neither break nor extend a run. `lookup` failures are
    left out the same way: "Not found" is terminal and about the track itself (a playlist
    of unavailable tracks fails them back to back), never a sign YouTube changed. A
    reclaimed-stuck row (failed, no error_type) does break a run."""
    from app.models import TrackAttempt, TrackAttemptOutcome, TrackErrorType

    if threshold < 1:
        return None
    rows = db.execute(
        select(
            TrackAttempt.outcome,
            TrackAttempt.error_type,
            TrackAttempt.error_message,
            TrackAttempt.finished_at,
        )
        .where(
            TrackAttempt.outcome.in_([TrackAttemptOutcome.COMPLETED, TrackAttemptOutcome.FAILED]),
            TrackAttempt.finished_at >= now - timedelta(minutes=window_minutes),
            (TrackAttempt.error_type.is_(None)) | (TrackAttempt.error_type != TrackErrorType.LOOKUP),
        )
        .order_by(TrackAttempt.finished_at.desc())
        .limit(threshold)
    ).all()
    if len(rows) < threshold:
        return None
    if any(row.outcome != TrackAttemptOutcome.FAILED for row in rows):
        return None
    error_types = {row.error_type for row in rows}
    if len(error_types) != 1 or None in error_types:
        return None
    error_type = error_types.pop()
    latest = (rows[0].error_message or "").strip()
    if len(latest) > 300:
        latest = latest[:299] + "…"
    text = (
        f"Failure spike: the last {threshold} download attempts all failed with "
        f"{error_type.value} (within {window_minutes}m). Latest error: {latest or '(none)'}. "
        f"If YouTube changed something, YOUTUBE_PLAYER_CLIENTS may need retuning."
    )
    return error_type.value, text, rows[0].finished_at


def breaker_released(worker_state, now: datetime) -> bool:
    """The trip's pause is over and nothing else holds downloads: a manual pause still
    on means "downloads resume" would be false, so the release waits for it too. No
    worker_state row at all means nothing ever tripped."""
    if worker_state is None:
        return True
    if worker_state.paused:
        return False
    tripped_until = worker_state.breaker_tripped_until
    if tripped_until is None:
        return True
    if tripped_until.tzinfo is None:
        tripped_until = tripped_until.replace(tzinfo=timezone.utc)
    return tripped_until <= now


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else value


_DELETE_IF_EQUALS = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) "
    "else return 0 end"
)


def _delete_if_equals(key: str, value) -> bool:
    return bool(_redis().eval(_DELETE_IF_EQUALS, 1, key, value))


def beat_heartbeat_age(now_epoch: float, fallback_epoch: float) -> float:
    """Seconds since beat's last tick. No heartbeat at all (a fresh Redis, or beat never
    started) counts from `fallback_epoch` -- the watchdog's own start -- so a stack that's
    still booting gets one full threshold of grace."""
    raw = _redis().get(BEAT_HEARTBEAT_KEY)
    # max(): Redis is persistent (appendonly), so after any downtime the key still holds the
    # last pre-shutdown tick -- without the grace, every restart after >threshold of downtime
    # would announce a dead beat (and burn the cooldown a real one then needs).
    last = max(float(raw), fallback_epoch) if raw is not None else fallback_epoch
    return max(0.0, now_epoch - last)


class Watchdog:
    """Runs as its own small process (alert_watchdog.py, started and supervised by
    worker-meta's AlertWatchdogStep, gated by RUN_ALERT_WATCHDOG). Deliberately not a
    beat-scheduled task: beat is one of the things it watches, and a dead beat would
    silently take the check with it.

    A separate process, not a thread: worker-meta's prefork main process keeps
    forking children (worker_max_tasks_per_child), and a fork taken while a thread holds
    a lock (logging, psycopg, ssl) can leave the new child deadlocked on it -- that child
    would be one of the two slots beat's dispatch runs on. As its own interpreter, it shares
    nothing with that process. It imports only config/models/app_settings (never spotdl: ~70 MB
    resident, measured, against ~220 MB with spotdl).

    It uses its own NullPool engine: a connection per check, nothing held between them."""

    def __init__(self) -> None:
        self.started_at = time.time()
        self._engine = create_engine(get_settings().database_url, poolclass=NullPool)

    def check_once(self) -> None:
        from app.models import WorkerState
        from app.services import app_settings

        now = datetime.now(timezone.utc)
        # The open-trip marker is read *before* the breaker state (review round 6): a marker
        # set after the DB read belongs to a newer trip, which a stale `released` must never
        # be paired with. Compare-and-delete below then covers read -> delete.
        open_trip = _redis().get(BREAKER_OPEN_KEY)
        # Everything the checks need is read first and the session closed *before* any
        # send: a send can hang for a while (per-phase timeouts, unbounded DNS), and an
        # open transaction would hold AccessShare locks a deploy's migrate would queue on.
        with Session(self._engine) as db:
            row = app_settings.get_alert_settings(db)
            enabled = {category: category_enabled(row, category) for category in TOGGLE_FIELDS}
            cooldown = row.alert_cooldown_minutes * 60
            stale_after = row.alert_beat_stale_seconds
            released = breaker_released(db.get(WorkerState, 1), now)
            spike = None
            if enabled[CATEGORY_SPIKE]:
                spike = failure_spike(
                    db, row.alert_spike_threshold, row.alert_spike_window_minutes, now
                )
            db.commit()

        # Compare-and-delete: an escalation marked between the read and the delete is a
        # newer trip, whose own release must still be announced later.
        if open_trip is not None and released and _delete_if_equals(BREAKER_OPEN_KEY, open_trip):
            if enabled[CATEGORY_BREAKER]:
                deliver(
                    CATEGORY_BREAKER,
                    f"release:{_text(open_trip)}",
                    "Circuit breaker released: downloads resume.",
                    cooldown,
                )

        if spike is not None:
            fingerprint, text, newest = spike
            newest_key = f"{SPIKE_NEWEST_KEY_PREFIX}{fingerprint}"
            seen = _redis().get(newest_key)
            stamp = newest.isoformat()
            if seen is not None and _text(seen) == stamp:
                logger.info(
                    "alerts: spike alert not re-sent, no new attempt since the last one "
                    "(fingerprint %s)",
                    fingerprint,
                )
            elif deliver(CATEGORY_SPIKE, fingerprint, text, cooldown) == "sent":
                _redis().set(newest_key, stamp, ex=7 * 24 * 3600)

        if enabled[CATEGORY_BEAT_STALE]:
            age = beat_heartbeat_age(time.time(), self.started_at)
            if age > stale_after:
                deliver(
                    CATEGORY_BEAT_STALE,
                    "stale",
                    f"Beat looks dead: no dispatch tick for {int(age)}s "
                    f"(threshold {stale_after}s). Nothing new is "
                    f"being dispatched until it's back.",
                    cooldown,
                )

    def run(self) -> None:
        while True:
            try:
                self.check_once()
            except Exception:
                logger.exception("alerts: watchdog check failed; retrying next interval")
            time.sleep(WATCHDOG_INTERVAL_SECONDS)


def spawn_watchdog() -> subprocess.Popen:
    """Starts app/services/alert_watchdog.py as a child of the calling process (worker-meta's
    main process; supervised by celery_app's AlertWatchdogStep). A fresh interpreter via
    `python -m`, not multiprocessing's spawn: spawn's child re-resolves `app` from the
    parent's sys.path order, which in local dev picked the image's installed copy over the
    ./backend/app bind mount (found live in v36). `-m` from the working directory resolves
    /app/app first, the same way the worker itself does."""
    return subprocess.Popen(
        [sys.executable, "-m", "app.services.alert_watchdog"], cwd=os.getcwd()
    )
