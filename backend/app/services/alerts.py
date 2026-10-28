"""Matrix alerts (v36) -- conditions that need a human, pushed into the same Matrix room
v33's deploy pipeline posts to (one bot, one room, see docs/DEPLOYMENT.md).

Categories (plan/master-v4/v36-alerting.md, plus v59's worker_down):

- `breaker`: the circuit breaker tripped, escalated, or released. Trip/escalation is
  recorded at the trip point itself (retry.maybe_trip_breaker), in the trip's own
  transaction; release is noticed by the watchdog below.
- `spike`: the last N real attempts (any track) all failed with the same error_type, the
  early warning that YouTube changed something (v31.1's YOUTUBE_PLAYER_CLIENTS).
- `beat_stale`: beat's heartbeat (written by every dispatch_due_tracks tick) is too old.
- `worker_down` (v59): due tracks wait, the breaker is closed, and worker-dl has started
  nothing for longer than the threshold.
- `library`: a library sweep finished or crashed (tasks/library.py).
- `test`: the admin settings page's "send test alert" button.

v59: delivery is durable. Raising an alert inserts a row into the `alert_outbox` table
(`record`; `enqueue` for callers without a session) and returns: that is where the cooldown
and the category toggle are decided, and an alert held back is recorded too, as
`suppressed` (a watchdog category switched off isn't even checked, as in v36, so it leaves no
row; one switched off after an alert was recorded is suppressed at send time). `deliver_due` sends the due rows, oldest first, with backoff
(DELIVERY_BACKOFF_SECONDS), and gives a row up as `failed` once it is still unsent
ALERT_GIVE_UP_AFTER after it was raised. It runs from beat's `deliver_alerts` tick on
worker-meta and from the watchdog after each check (beat is one of the things alerted on: a
dead beat must still be announced). Before v59 an alert was a fire-and-forget Celery message
(retry=False, expires=300) that a busy meta queue, a worker-meta restart or one failed request
lost without a trace (docs/GOTCHAS.md v59). The Matrix transaction id is the row id, so a
retry of a send whose answer was lost can't post twice.

Never in the hot path: a download or request only ever inserts a row (inside a savepoint,
logged and swallowed on any error); the sends happen on worker-meta and in the watchdog. A
failed send is a log warning and a row state, never an error anywhere else.

Unconfigured (any of MATRIX_HOMESERVER_URL / MATRIX_ACCESS_TOKEN / MATRIX_ROOM_ID unset)
means alerts are off: nothing is recorded, the watchdog doesn't check, and worker-meta's
startup log says so once. The token is read here and nowhere else, and only ever goes into
the Authorization header -- never a log line, an exception message or an API response.

Cooldown: an alert whose (category, fingerprint) was already recorded pending or sent within
`app_settings.alert_cooldown_minutes` (default 60) is recorded `suppressed`, under an advisory
lock on that pair so two processes can't both decide "first". Fingerprints are chosen so that
only a *repeat* of the same condition is suppressed: one per breaker trip
(`trip:<step>:<tripped_until>`, and `release:<that trip>`), the spiking error_type, one fixed
key for a stale beat and one for a down worker, and a per-run key for library sweeps (never
suppressed).

Every message body goes through redact_text() (spotdl's errors echo proxy credentials,
CLAUDE.md invariant) before it is stored, and again right before it is sent.
"""

import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, NamedTuple
from urllib.parse import quote

import httpx
import redis
from sqlalchemy import create_engine, delete, exists, func, select, update
from sqlalchemy.orm import Session, aliased
from sqlalchemy.pool import NullPool

from app.config import DEV_ENV_MARKER, get_settings
from app.services.redaction import redact_text

logger = logging.getLogger(__name__)

CATEGORY_BREAKER = "breaker"
CATEGORY_SPIKE = "spike"
CATEGORY_BEAT_STALE = "beat_stale"
CATEGORY_WORKER_DOWN = "worker_down"
CATEGORY_LIBRARY = "library"
CATEGORY_TEST = "test"

# Category -> its app_settings on/off column. `test` has none: the button always sends.
TOGGLE_FIELDS = {
    CATEGORY_BREAKER: "alerts_breaker_enabled",
    CATEGORY_SPIKE: "alerts_spike_enabled",
    CATEGORY_BEAT_STALE: "alerts_beat_stale_enabled",
    CATEGORY_WORKER_DOWN: "alerts_worker_down_enabled",
    CATEGORY_LIBRARY: "alerts_library_enabled",
}

# Per error_type: finished_at of the newest attempt in the last spike alert recorded, so the
# same rows aren't re-announced once the cooldown lapses with no new attempt since.
SPIKE_NEWEST_KEY_PREFIX = "spotdl:alerts:spike_newest:"
BEAT_HEARTBEAT_KEY = "spotdl:beat:heartbeat"

# How often the watchdog checks (breaker release, failure spike, beat heartbeat, worker-dl).
WATCHDOG_INTERVAL_SECONDS = 60
# Per phase (connect/read/write/pool), not end to end, and name resolution isn't covered:
# a homeserver whose DNS hangs holds the meta slot (or the test request) longer.
SEND_TIMEOUT_SECONDS = 10.0
# Matrix accepts far more; this keeps a quoted traceback from flooding the room.
MAX_BODY_CHARS = 2000
# v33: the homeserver sits behind Cloudflare, which bans default library User-Agents
# (HTTP 403 "error code: 1010") -- same explicit UA shape as .github/scripts/matrix_notify.py.
USER_AGENT = "spotdl-web-alerts/1 (+https://github.com/vb2007/spotdl-web)"

# v59: the outbox's delivery schedule. A failed send waits the next step (the last one
# repeats); a 429's own retry_after is honoured when it is longer.
# Every wait stays under Synapse's ~30 min transaction-id memory (review round 3): a retry
# right after a send whose answer was lost then lands on the same txn and posts nothing.
DELIVERY_BACKOFF_SECONDS = (30, 120, 600, 1200)
ALERT_GIVE_UP_AFTER = timedelta(hours=24)
ALERT_RETENTION = timedelta(days=30)
# A claimed row is held this far ahead while its send runs (three 10s phases, plus DNS):
# another deliverer skips it meanwhile, and a crashed one's row comes back after it, with
# the same transaction id.
DELIVERY_LEASE_SECONDS = 120
# Sends per pass at most; a backlog drains over the next ticks.
DELIVERY_BATCH = 20
# A row sent this long after it was raised says when it was raised: "downloads paused for
# 30m" read three hours late must not read as now.
LATE_NOTE_AFTER = timedelta(minutes=2)
BODY_PREVIEW_CHARS = 280
# A suppressed row's last_error: a code, which the frontend translates (the backend stays
# language-neutral). A send failure's last_error is the homeserver's or httpx's own words.
SUPPRESSED_COOLDOWN = "cooldown"
SUPPRESSED_CATEGORY_OFF = "category_off"
# One delivery pass at a time across worker-meta's slots and the watchdog (pg advisory lock
# key), and how long a pass keeps claiming rows: a pass never holds a meta slot for long.
DELIVERY_LOCK_KEY = 5_905_901
DELIVERY_PASS_SECONDS = 20.0

_ENV_VARS = ("MATRIX_HOMESERVER_URL", "MATRIX_ACCESS_TOKEN", "MATRIX_ROOM_ID")
# Refusals about one message, not the homeserver: that row is given up at once and the pass
# goes on, so it can't hold its category back for 24h (review round 2). Only a 413 or Matrix's
# own errcodes for a body it won't take: a bare 400 is as likely a proxy or a malformed room id,
# which is every row's problem, and backs off like a 5xx (review round 3).
ROW_ONLY_ERRCODES = ("M_NOT_JSON", "M_BAD_JSON", "M_TOO_LARGE")


class MatrixConfig(NamedTuple):
    homeserver_url: str
    access_token: str
    room_id: str


class AlertsNotConfigured(Exception):
    pass


class AlertSendError(Exception):
    """Carries only a redacted, token-free description of what went wrong, and a 429's
    retry_after (seconds) when the homeserver gave one."""

    def __init__(
        self, message: str, retry_after: float | None = None, row_only: bool = False
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.row_only = row_only


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


def _errcode(response: httpx.Response) -> str | None:
    try:
        value = response.json().get("errcode")
    except Exception:
        return None
    return value if isinstance(value, str) else None


def _retry_after(response: httpx.Response) -> float | None:
    try:
        value = response.json().get("retry_after_ms")
    except Exception:
        return None
    return value / 1000 if isinstance(value, (int, float)) and value > 0 else None


def _put(config: MatrixConfig, body: str, txn_id: str) -> None:
    """One PUT of an already formatted body. Raises AlertSendError; never retries."""
    if not config.access_token.isprintable():
        # h11 would refuse the header and quote it, repr-escaped, in its error (review
        # round 5) -- so a malformed token never reaches a request at all.
        raise AlertSendError("MATRIX_ACCESS_TOKEN contains a non-printable character")
    url = (
        f"{config.homeserver_url}/_matrix/client/v3/rooms/{quote(config.room_id, safe='')}"
        f"/send/m.room.message/{quote(txn_id, safe='')}"
    )
    try:
        response = httpx.put(
            url,
            json={"msgtype": "m.notice", "body": redact_text(body)},
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
            redact_text(f"HTTP {response.status_code}: {response.text[:200]}"),
            retry_after=_retry_after(response) if response.status_code == 429 else None,
            row_only=response.status_code == 413 or _errcode(response) in ROW_ONLY_ERRCODES,
        )


def send_now(text: str, txn_id: str | None = None) -> None:
    """One PUT to the room, outside the outbox. Raises AlertsNotConfigured or
    AlertSendError; never retries."""
    config = matrix_config()
    if config is None:
        raise AlertsNotConfigured()
    _put(config, format_body(text), txn_id or uuid.uuid4().hex)


_redis_client: redis.Redis | None = None
_redis_pid: int | None = None


def _redis() -> redis.Redis:
    # Per process: the watchdog's process forks prefork children, which build their own.
    global _redis_client, _redis_pid
    if _redis_client is None or _redis_pid != os.getpid():
        _redis_client = redis.Redis.from_url(get_settings().redis_url)
        _redis_pid = os.getpid()
    return _redis_client


def category_enabled(settings_row, category: str) -> bool:
    field = TOGGLE_FIELDS.get(category)
    return True if field is None else bool(getattr(settings_row, field))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _hhmm(value: datetime) -> str:
    return f"{_aware(value).astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC"


# --- the outbox: recording ---------------------------------------------------------------


def record(db: Session, category: str, fingerprint: str, text: str):
    """Records an alert in `db`'s transaction (the caller commits), so it is delivered only
    if that transaction commits: the room never hears about a breaker trip that was never
    persisted. Decides the category toggle and the cooldown here, recording a held-back
    alert as `suppressed` with its reason code in last_error (SUPPRESSED_*; the history panel
    translates it), at most once per window per alert. Returns the row's state, or None when
    alerts are off or recording failed. Never raises: the insert runs in a savepoint, so an
    error (the table missing mid-deploy, say) leaves the caller's transaction intact, and is
    one log warning."""
    from app.models import AlertOutbox, AlertState
    from app.services import app_settings

    if not is_configured():
        return None
    body = format_body(text)
    # The column's width, here once, so the cooldown lookup reads the same value it stores.
    fingerprint = fingerprint[:200]
    try:
        with db.begin_nested():
            row = app_settings.get_alert_settings(db)
            enabled = category_enabled(row, category) if category != CATEGORY_TEST else True
            cooldown = timedelta(minutes=row.alert_cooldown_minutes)
            # Two processes recording the same alert at once both see "nothing yet" without
            # it. Transaction-scoped, so it's held until the caller commits the row.
            db.execute(
                select(func.pg_advisory_xact_lock(func.hashtextextended(f"alert:{category}:{fingerprint}", 0)))
            )
            # The server's clock at insert, not the caller's `now`: the delivery order is by
            # created_at, and it must follow the order the rows really got written (see
            # Watchdog._record_release).
            created_at = db.execute(select(func.clock_timestamp())).scalar_one()
            same = (AlertOutbox.category == category) & (AlertOutbox.fingerprint == fingerprint)
            window_start = created_at - cooldown
            reason = None
            if not enabled:
                reason = SUPPRESSED_CATEGORY_OFF
            elif db.execute(
                select(
                    exists().where(
                        same,
                        # Still unsent covers it whatever its age (the room hears it once, when
                        # the homeserver is back); sent covers it for the window.
                        (AlertOutbox.state == AlertState.PENDING)
                        | (
                            (AlertOutbox.state == AlertState.SENT)
                            # From when the room heard it: a late delivery starts the window late.
                            & (func.coalesce(AlertOutbox.sent_at, AlertOutbox.created_at) > window_start)
                        ),
                    )
                )
            ).scalar_one():
                reason = SUPPRESSED_COOLDOWN
            state = AlertState.SUPPRESSED if reason else AlertState.PENDING
            # A condition that lasts (beat dead, worker-dl down) is re-raised every watchdog
            # minute: one suppressed row per window records the decision without burying the
            # history in identical ones.
            insert = state == AlertState.PENDING or not db.execute(
                select(
                    exists().where(
                        same,
                        AlertOutbox.state == AlertState.SUPPRESSED,
                        AlertOutbox.created_at > window_start,
                    )
                )
            ).scalar_one()
            if insert:
                db.add(
                    AlertOutbox(
                        category=category,
                        fingerprint=fingerprint,
                        body=body,
                        created_at=created_at,
                        state=state,
                        attempts=0,
                        next_attempt_at=created_at if state == AlertState.PENDING else None,
                        last_error=reason,
                    )
                )
    except Exception as exc:
        logger.warning("alerts: could not record %s alert (%s)", category, type(exc).__name__)
        return None
    if state == AlertState.PENDING:
        logger.info("alerts: %s alert recorded (fingerprint %s)", category, fingerprint)
    elif insert:
        logger.info(
            "alerts: %s alert suppressed (%s, fingerprint %s)", category, reason, fingerprint
        )
    else:
        logger.debug(
            "alerts: %s alert suppressed again (%s, fingerprint %s)", category, reason, fingerprint
        )
    return state


def enqueue(category: str, fingerprint: str, text: str) -> None:
    """`record` in a session of its own, committed at once: for callers with no transaction
    of their own to tie the alert to. A no-op when alerts are off; never raises."""
    if not is_configured():
        return
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        record(db, category, fingerprint, text)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("alerts: could not record %s alert (%s)", category, type(exc).__name__)
    finally:
        db.close()


def send_test(db: Session, text: str) -> None:
    """The settings page's test alert: sent at once, bypassing the toggles and the cooldown
    (the point is to check the wiring), and recorded as sent or failed for the history. A
    failed send isn't retried: the admin sees the failure now. Only a request that dies
    mid-send leaves its row to a delivery pass, after the lease, under the same transaction id.
    Raises AlertsNotConfigured or AlertSendError, as send_now does."""
    from app.models import AlertOutbox, AlertState

    config = matrix_config()
    if config is None:
        raise AlertsNotConfigured()
    now = _utcnow()
    # Inserted already claimed (attempts 1, a lease ahead), so no delivery pass picks it up
    # while this request sends it; if the request dies mid-send, the lease runs out and a
    # pass finishes it, under the same transaction id.
    txn = uuid.uuid4().hex
    try:
        row = AlertOutbox(
            category=CATEGORY_TEST,
            fingerprint=uuid.uuid4().hex,
            body=format_body(text),
            created_at=now,
            state=AlertState.PENDING,
            attempts=1,
            next_attempt_at=now + timedelta(seconds=DELIVERY_LEASE_SECONDS),
        )
        db.add(row)
        db.flush()
        row_id, body, txn = row.id, row.body, row.id.hex
        db.commit()
    except Exception as exc:
        # The wiring check must work even when the history can't be written (mid-deploy, the
        # table not migrated yet): send it unrecorded (review round 3). Under the row's own txn
        # once it had one: a commit that failed after the server had committed leaves a leased
        # row a pass sends later, and the same txn makes that one land on this message
        # (review round 4).
        db.rollback()
        logger.warning("alerts: test alert not recorded (%s); sending it anyway", type(exc).__name__)
        _put(config, format_body(text), txn)
        return
    # Read before the commit: after it, touching the row would open a transaction that stays
    # idle through the send.
    error: AlertSendError | None = None
    try:
        _put(config, body, txn)
    except AlertSendError as exc:
        error = exc
    # Only while still pending: a send that outlived its lease may have been finished by a
    # delivery pass meanwhile (same txn id), whose outcome stands.
    values = (
        {"state": AlertState.SENT, "sent_at": _utcnow(), "next_attempt_at": None}
        if error is None
        else {"state": AlertState.FAILED, "last_error": str(error), "next_attempt_at": None}
    )
    try:
        db.execute(
            update(AlertOutbox)
            .where(AlertOutbox.id == row_id, AlertOutbox.state == AlertState.PENDING)
            .values(**values)
        )
        db.commit()
    except Exception as exc:
        # The send's own answer is what the admin asked for: a failed history write mustn't
        # turn a delivered test into a 500 (the leased row is sent again under the same txn
        # by a pass, which posts nothing new; review round 6).
        db.rollback()
        logger.warning("alerts: test alert outcome not recorded (%s)", type(exc).__name__)
    if error is not None:
        raise error


# --- the outbox: delivery ----------------------------------------------------------------


def backoff_seconds(attempts: int, retry_after: float | None = None) -> float:
    """The wait after the `attempts`-th failed send (1-based)."""
    step = DELIVERY_BACKOFF_SECONDS[min(max(attempts, 1) - 1, len(DELIVERY_BACKOFF_SECONDS) - 1)]
    return max(float(step), retry_after or 0.0)


def _with_late_note(body: str, created_at: datetime, now: datetime) -> str:
    if now - _aware(created_at) < LATE_NOTE_AFTER:
        return body
    return f"{body} (raised {_hhmm(created_at)}, delivered late)"


def _give_up_overdue(db: Session, now: datetime) -> None:
    from app.models import AlertOutbox, AlertState

    given_up = db.execute(
        update(AlertOutbox)
        .where(
            AlertOutbox.state == AlertState.PENDING,
            AlertOutbox.created_at <= now - ALERT_GIVE_UP_AFTER,
            # A row whose send is running right now is left to that send's outcome.
            AlertOutbox.next_attempt_at <= now,
        )
        .values(state=AlertState.FAILED, next_attempt_at=None)
        .returning(AlertOutbox.category, AlertOutbox.fingerprint)
    ).all()
    for category, fingerprint in given_up:
        logger.warning(
            "alerts: %s alert given up, still unsent after %s (fingerprint %s)",
            category,
            ALERT_GIVE_UP_AFTER,
            fingerprint,
        )


def _claim_next(db: Session, now: datetime):
    """The oldest due row whose category has no older pending row, claimed: attempts + 1,
    held a lease ahead. One row per category in flight, oldest first, so a category's alerts
    reach the room in the order they were raised (a release never overtakes its trip while
    that trip backs off). Returns (id, body, created_at, attempts) or None."""
    from app.models import AlertOutbox, AlertState

    from app.services import app_settings

    settings_row = app_settings.get_alert_settings(db)
    older = aliased(AlertOutbox)
    while True:
        row = db.execute(
            select(AlertOutbox)
            .where(
                AlertOutbox.state == AlertState.PENDING,
                AlertOutbox.next_attempt_at <= now,
                ~exists().where(
                    older.state == AlertState.PENDING,
                    older.category == AlertOutbox.category,
                    older.created_at < AlertOutbox.created_at,
                ),
            )
            .order_by(AlertOutbox.created_at, AlertOutbox.id)
            .limit(1)
            .with_for_update(skip_locked=True, of=AlertOutbox)
        ).scalar_one_or_none()
        if row is None:
            return None
        # A category switched off after the alert was raised (during an outage, say) isn't
        # sent when the homeserver is back: v36 checked the toggle at send time too (review
        # round 3).
        if row.category == CATEGORY_TEST or category_enabled(settings_row, row.category):
            break
        row.state = AlertState.SUPPRESSED
        row.last_error = SUPPRESSED_CATEGORY_OFF
        row.next_attempt_at = None
        db.flush()
    row.attempts += 1
    row.next_attempt_at = now + timedelta(seconds=DELIVERY_LEASE_SECONDS)
    return row.id, row.body, row.created_at, row.attempts, row.category, row.fingerprint


def deliver_due(make_session: Callable[[], Session], *, limit: int = DELIVERY_BATCH) -> int:
    """One delivery pass: sends due outbox rows one at a time, each claimed in a short
    transaction of its own and sent with no transaction open (a send can hang for a while,
    and an open transaction would hold locks a deploy's migrate queues on). Stops at the first
    failed send (the homeserver is most likely down for every row alike) and stops claiming
    after DELIVERY_PASS_SECONDS. One pass at a time. Returns how many were sent. Never raises."""
    from app.models import AlertOutbox, AlertState

    config = matrix_config()
    if config is None:
        # Nothing can be sent; what was raised before Matrix was switched off is still given
        # up on time, rather than reading "sending" for its 30 days (review round 5).
        try:
            with make_session() as db:
                _give_up_overdue(db, _utcnow())
                db.commit()
        except Exception as exc:
            logger.warning("alerts: give-up sweep failed (%s)", type(exc).__name__)
        return 0
    sent = 0
    started = time.monotonic()
    try:
        with make_session() as lock:
            # One pass at a time (beat's ticks on both meta slots, and the watchdog): a pass
            # that finds one running returns at once instead of holding a slot behind it. The
            # lock lives in this session's own transaction, which touches no table, so no
            # migrate ever waits on it while the sends run.
            if not lock.execute(
                select(func.pg_try_advisory_xact_lock(DELIVERY_LOCK_KEY))
            ).scalar_one():
                return 0
            with make_session() as db:
                _give_up_overdue(db, _utcnow())
                db.commit()
            for _ in range(limit):
                if time.monotonic() - started > DELIVERY_PASS_SECONDS:
                    break  # the next pass (30s) picks up the rest
                with make_session() as db:
                    claimed = _claim_next(db, _utcnow())
                    db.commit()
                if claimed is None:
                    break
                row_id, body, created_at, attempts, category, fingerprint = claimed
                error: AlertSendError | None = None
                try:
                    _put(config, _with_late_note(body, created_at, _utcnow()), row_id.hex)
                except AlertSendError as exc:
                    error = exc
                except Exception as exc:
                    # Belt and braces for "never raises": anything unforeseen is a failed send too.
                    error = AlertSendError(type(exc).__name__)
                now = _utcnow()
                next_attempt_at, final_state = None, None
                with make_session() as db:
                    row = db.get(AlertOutbox, row_id, with_for_update=True)
                    # A test alert's request may have recorded `failed` while this pass's send of
                    # the same row (same txn) was landing: the message arrived (review round 5).
                    late_test_success = (
                        row is not None
                        and error is None
                        and row.category == CATEGORY_TEST
                        and row.state == AlertState.FAILED
                    )
                    if row is not None and (row.state == AlertState.PENDING or late_test_success):
                        if error is None:
                            row.state = AlertState.SENT
                            row.sent_at = now
                            row.next_attempt_at = None
                        else:
                            row.last_error = str(error)
                            if error.row_only or now - _aware(row.created_at) >= ALERT_GIVE_UP_AFTER:
                                row.state = AlertState.FAILED
                                row.next_attempt_at = None
                            else:
                                row.next_attempt_at = now + timedelta(
                                    seconds=backoff_seconds(attempts, error.retry_after)
                                )
                        next_attempt_at = row.next_attempt_at
                        final_state = row.state
                    db.commit()
                if final_state is None:
                    continue  # settled meanwhile by someone else; its outcome stands
                if error is None:
                    sent += 1
                    logger.info(
                        "alerts: %s alert sent (fingerprint %s, attempt %s)", category, fingerprint, attempts
                    )
                    continue
                if final_state == AlertState.FAILED:
                    logger.warning(
                        "alerts: %s alert given up after %s attempts: %s", category, attempts, error
                    )
                    if error.row_only:
                        continue
                else:
                    logger.warning(
                        "alerts: %s alert not sent (attempt %s, next at %s): %s",
                        category,
                        attempts,
                        f"{next_attempt_at:%H:%M:%S}" if next_attempt_at else "-",
                        error,
                    )
                break
            try:
                lock.commit()
            except Exception:
                # Only the lock's own empty transaction (an idle-in-transaction timeout, say):
                # every row's outcome is already committed.
                pass
    except Exception as exc:
        logger.warning("alerts: delivery pass failed (%s)", type(exc).__name__)
    return sent


def prune_outbox(db: Session, now: datetime | None = None) -> int:
    """Rows older than ALERT_RETENTION go, pending ones included (a pending row that old was
    given up long ago; the guard is the give-up rule, not this)."""
    from app.models import AlertOutbox

    now = now or _utcnow()
    return db.execute(
        delete(AlertOutbox).where(AlertOutbox.created_at < now - ALERT_RETENTION)
    ).rowcount


def format_duration(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


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
    reclaimed-stuck row (failed, no error_type) does break a run. Proxy transport failures
    (v40.1) are left out too."""
    from app.models import TrackAttempt, TrackAttemptOutcome, TrackErrorType
    from app.services.attempts import TRANSPORT_FAILURE_PREFIX

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
            # v40.1: a proxy that failed to carry the request says nothing about YouTube
            # either; a dead pool is the proxies page's news, not a "YouTube changed" spike.
            (TrackAttempt.error_message.is_(None))
            | ~TrackAttempt.error_message.startswith(TRANSPORT_FAILURE_PREFIX),
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
    return _aware(tripped_until) <= now


def _newest_trip(db: Session):
    """(fingerprint, state) of the newest breaker trip/escalation alert recorded, or None."""
    from app.models import AlertOutbox

    return db.execute(
        select(AlertOutbox.fingerprint, AlertOutbox.state)
        .where(
            AlertOutbox.category == CATEGORY_BREAKER,
            AlertOutbox.fingerprint.startswith("trip:"),
        )
        .order_by(AlertOutbox.created_at.desc())
        .limit(1)
    ).first()


def _release_recorded(db: Session, trip_fingerprint: str) -> bool:
    from app.models import AlertOutbox

    return db.execute(
        select(
            exists().where(
                AlertOutbox.category == CATEGORY_BREAKER,
                AlertOutbox.fingerprint == f"release:{trip_fingerprint}",
            )
        )
    ).scalar_one()


def due_backlog(db: Session, now: datetime):
    """(oldest due time, how many) over the tracks that should be with worker-dl by now:
    queued (dispatched), waiting/pending and due (beat's next tick dispatches them), or pending
    with no scheduled_at, which expand_job has already sent to the broker (v56's outbox marker
    is cleared by that send, so its updated_at is when it was sent). (None, 0) when there are
    none."""
    from app.models import Track, TrackState

    due_at = func.coalesce(Track.scheduled_at, Track.updated_at)
    oldest, count = db.execute(
        select(func.min(due_at), func.count()).where(
            Track.state.in_((TrackState.QUEUED, TrackState.WAITING, TrackState.PENDING)),
            due_at <= now,
        )
    ).one()
    return oldest, count


def last_consumed(db: Session, now: datetime):
    """The latest moment worker-dl is known to have worked a track: the end of the newest
    attempt it recorded (beat's reclaim rows are recorded on a stuck invocation's behalf, so
    they prove nothing), or `now` while it has a track in `downloading` younger than
    STALE_TRACK_AFTER_SECONDS (a download's progress isn't written to the database, so a long
    one is busy, not down, until beat's stale sweep would call it stuck; review round 2). None
    if neither exists."""
    from app.models import Track, TrackAttempt, TrackState
    from app.services.attempts import RECLAIM_PREFIX

    # finished_at, not started_at (review round 3): v55 merges a track's repeated holds into
    # one row that keeps its first start, while its finish moves on with each hold. With
    # --concurrency=1 the newest finish is at least as recent as the newest start, and indexed.
    finished = db.execute(
        select(TrackAttempt.finished_at)
        .where(
            (TrackAttempt.error_message.is_(None))
            | ~TrackAttempt.error_message.startswith(RECLAIM_PREFIX),
            (TrackAttempt.warning_message.is_(None))
            | ~TrackAttempt.warning_message.startswith(RECLAIM_PREFIX),
        )
        .order_by(TrackAttempt.finished_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    downloading = db.execute(
        select(func.max(Track.updated_at)).where(Track.state == TrackState.DOWNLOADING)
    ).scalar_one_or_none()
    if downloading is not None and now - _aware(downloading) < timedelta(
        seconds=get_settings().stale_track_after_seconds
    ):
        downloading = now
    moments = [_aware(m) for m in (finished, downloading) if m is not None]
    return max(moments) if moments else None


def worker_down_since(
    oldest_due: datetime | None,
    consumed: datetime | None,
    open_since: datetime,
    previous: datetime | None,
) -> datetime | None:
    """The moment since which due work has waited with nothing taken by worker-dl (None when
    nothing is due). The caller compares it to the threshold, so a busy worker-dl, whose last
    start keeps moving, never reaches it.

    The plan's signal is the newest attempt's start against the oldest due scheduled_at, but
    the due time alone misleads twice: a track that fell due during a trip only became
    dispatchable when the breaker closed (`open_since`), and beat's stale sweep rewrites a
    stuck track's scheduled_at to its own tick, so on its own the oldest due time would restart
    every STALE_TRACK_AFTER_SECONDS (1800s in production) and never age past a longer
    threshold. So the watchdog keeps the first such moment (`previous`) for as long as the
    backlog lasts with nothing consumed. No new heartbeat: these two existing readings and the
    watchdog's own memory are enough (docs/GOTCHAS.md v59)."""
    if oldest_due is None:
        return None
    if previous is not None and (consumed is None or consumed <= previous):
        return previous
    # Idle since the latest of the three: a worker-dl that took tracks and then died midway
    # through a backlog is idle from its last start, however long the backlog has been due.
    moments = [_aware(oldest_due), open_since]
    if consumed is not None:
        moments.append(consumed)
    return max(moments)


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else value


def beat_heartbeat_age(now_epoch: float, fallback_epoch: float) -> float:
    """Seconds since beat's last tick. No heartbeat at all (a fresh Redis, or beat never
    started) counts from `fallback_epoch` -- the watchdog's own start -- so a stack that's
    still booting gets one full threshold of grace."""
    return heartbeat_age(_redis().get(BEAT_HEARTBEAT_KEY), now_epoch, fallback_epoch)


def heartbeat_age(raw, now_epoch: float, fallback_epoch: float) -> float:
    """beat_heartbeat_age's arithmetic, for a heartbeat value already read."""
    # max(): Redis is persistent (appendonly), so after any downtime the key still holds the
    # last pre-shutdown tick -- without the grace, every restart after >threshold of downtime
    # would announce a dead beat (and burn the cooldown a real one then needs).
    last = max(float(raw), fallback_epoch) if raw is not None else fallback_epoch
    return max(0.0, now_epoch - last)


class RedisOutageLog:
    """v59 (O5): a Redis outage's log lines, throttled. The first failed check logs one
    traceback; while it lasts, one "still down (N checks)" line every STILL_DOWN_EVERY; the
    first check that reaches Redis again logs the recovery. Before v59 the watchdog logged a
    full traceback on every 60s check, and the API's health check on every 30s probe.
    `prefix`/`first` name the caller; `level` is the first line's."""

    STILL_DOWN_EVERY = 600.0

    def __init__(
        self,
        log: logging.Logger,
        prefix: str = "alerts",
        first: str = "Redis unreachable; skipping the checks that need it",
        level: int = logging.WARNING,
    ) -> None:
        self._log = log
        self._prefix = prefix
        self._first = first
        self._level = level
        self.down_since: float | None = None
        self.checks = 0
        self._last_line = 0.0

    def failed(self, now: float) -> None:
        self.checks += 1
        if self.down_since is None:
            self.down_since = now
            self._last_line = now
            self._log.log(self._level, "%s: %s", self._prefix, self._first, exc_info=True)
        elif now - self._last_line >= self.STILL_DOWN_EVERY:
            self._last_line = now
            self._log.warning("%s: Redis still down (%s checks)", self._prefix, self.checks)

    def reached(self, now: float) -> None:
        if self.down_since is None:
            return
        self._log.info(
            "%s: Redis reachable again after %ss (%s failed checks)",
            self._prefix,
            int(now - self.down_since),
            self.checks,
        )
        self.down_since = None
        self.checks = 0


class Watchdog:
    """Runs as its own small process (alert_watchdog.py, started and supervised by
    worker-meta's AlertWatchdogStep, gated by RUN_ALERT_WATCHDOG). Deliberately not a
    beat-scheduled task: beat is one of the things it watches, and a dead beat would
    silently take the check with it. For the same reason it also runs a delivery pass after
    each check (v59): beat's `deliver_alerts` tick dies with beat.

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
        self.redis_outage = RedisOutageLog(logger)
        # worker_down_since's memory: when dispatch last became possible (None while the
        # breaker or a pause holds it), and since when the current backlog has waited.
        self._open_since: datetime | None = None
        self._backlog_since: datetime | None = None
        self._redis_failed_this_check = False
        self._redis_ok_this_check = False
        self._redis_back_at = 0.0

    def _session(self) -> Session:
        return Session(self._engine)

    def _redis_read(self, read):
        """`read()`'s value, or None with the outage noted when Redis is unreachable."""
        try:
            value = read()
        except redis.RedisError:
            # Counted once per check, however many of its reads fail.
            if not self._redis_failed_this_check:
                self._redis_failed_this_check = True
                self.redis_outage.failed(time.time())
            return None, False
        self._redis_ok_this_check = True
        if self.redis_outage.down_since is not None and not self._redis_failed_this_check:
            # The first answer after an outage: beat's grace starts here.
            self._redis_back_at = time.time()
        return value, True

    def check_once(self) -> None:
        self._redis_failed_this_check = False
        self._redis_ok_this_check = False
        try:
            self._check()
        finally:
            # A recovery is the check's verdict, not one read's: a flapping Redis that fails
            # one read and answers the next mustn't log "reachable again" and then a fresh
            # traceback (review round 5).
            if self._redis_ok_this_check and not self._redis_failed_this_check:
                self.redis_outage.reached(time.time())
            # Whatever went wrong above, what is already pending still goes out: with beat
            # dead, this is the only delivery pass there is (review round 5).
            deliver_due(self._session)

    def _check(self) -> None:
        from app.db import begin_snapshot
        from app.models import AlertState, WorkerState
        from app.services import app_settings

        now = datetime.now(timezone.utc)
        # Everything the checks need is read first, in one snapshot, and the session closed
        # before anything is recorded or sent.
        with self._session() as db:
            begin_snapshot(db)
            row = app_settings.get_alert_settings(db)
            enabled = {category: category_enabled(row, category) for category in TOGGLE_FIELDS}
            stale_after = row.alert_beat_stale_seconds
            # Never shorter than the pacing sleep (+1 min): it runs while the track is still
            # `queued`, with no attempt row, so a healthy worker-dl reads as idle through it
            # (review round 5).
            down_after = max(
                timedelta(minutes=row.alert_worker_down_minutes),
                timedelta(seconds=get_settings().pacing_max_sec + 60),
            )
            worker_state = db.get(WorkerState, 1)
            released = breaker_released(worker_state, now)
            newest_trip = _newest_trip(db) if released else None
            release_due = (
                newest_trip is not None
                and newest_trip.state == AlertState.SENT
                and not _release_recorded(db, newest_trip.fingerprint)
            )
            spike = None
            if enabled[CATEGORY_SPIKE]:
                spike = failure_spike(
                    db, row.alert_spike_threshold, row.alert_spike_window_minutes, now
                )
            backlog = None
            if enabled[CATEGORY_WORKER_DOWN]:
                backlog = (*due_backlog(db, now), last_consumed(db, now))
            db.commit()

        # A trip is released only for a trip the room heard about (sent), once per trip.
        if release_due:
            self._record_release(newest_trip.fingerprint)

        # Grace from the watchdog's start, and from Redis' return after an outage: beat can't
        # tick without its broker, so its last heartbeat is as old as the outage, and "Beat
        # looks dead" would reach the room just as beat resumes (live review round 2).
        raw_heartbeat, beat_known = self._redis_read(lambda: _redis().get(BEAT_HEARTBEAT_KEY))
        beat_age = (
            heartbeat_age(raw_heartbeat, time.time(), max(self.started_at, self._redis_back_at))
            if beat_known
            else 0.0
        )
        beat_alive = beat_known and beat_age <= stale_after

        if spike is not None:
            fingerprint, text, newest = spike
            newest_key = f"{SPIKE_NEWEST_KEY_PREFIX}{fingerprint}"
            seen, known = self._redis_read(lambda: _redis().get(newest_key))
            stamp = newest.isoformat()
            if not known:
                pass
            elif seen is not None and _text(seen) == stamp:
                logger.info(
                    "alerts: spike alert not re-sent, no new attempt since the last one "
                    "(fingerprint %s)",
                    fingerprint,
                )
            # Stamped only when it will reach the room, as v36 stamped only a sent one: a
            # suppressed repeat mustn't move it, or the reminder after the cooldown is lost.
            elif self._record(CATEGORY_SPIKE, fingerprint, text) == AlertState.PENDING:
                self._redis_read(lambda: _redis().set(newest_key, stamp, ex=7 * 24 * 3600))

        if enabled[CATEGORY_BEAT_STALE] and beat_known and not beat_alive:
            self._record(
                CATEGORY_BEAT_STALE,
                "stale",
                f"Beat looks dead: no dispatch tick for {int(beat_age)}s "
                f"(threshold {stale_after}s). Nothing new is "
                f"being dispatched until it's back.",
            )

        self._check_worker_down(now, released, backlog, down_after, beat_alive)

    def _check_worker_down(self, now, released, backlog, down_after, beat_alive) -> None:
        if not released:
            # Tripped or paused: nothing is dispatched, so nothing is owed to worker-dl.
            self._open_since = None
            self._backlog_since = None
            return
        if not beat_alive:
            # Beat isn't dispatching (its own alert covers that; a worker-dl with nothing
            # dispatched to it isn't down), and while Redis is out nothing reaches worker-dl
            # either. Dispatch reopens when they're back, with a full threshold of grace, as
            # after a breaker release (review round 6).
            self._open_since = None
            self._backlog_since = None
            return
        if self._open_since is None:
            self._open_since = now
        if backlog is None:
            self._backlog_since = None
            return
        oldest_due, count, consumed = backlog
        self._backlog_since = worker_down_since(
            oldest_due, consumed, self._open_since, self._backlog_since
        )
        if self._backlog_since is None or now - self._backlog_since <= down_after:
            return
        # "At least": the watchdog's own view starts at its start or the breaker's release.
        idle = format_duration(timedelta(minutes=int((now - self._backlog_since).total_seconds() // 60)))
        last = f"the last one ended {_hhmm(consumed)}" if consumed else "none recorded yet"
        self._record(
            CATEGORY_WORKER_DOWN,
            "stalled",
            # No "oldest due since": beat's stale sweep rewrites a stuck track's scheduled_at, so
            # it could read later than the idle time it sits beside (live review round 2).
            f"worker-dl isn't taking due tracks: {count} track(s) are due with the breaker "
            f"closed, and no download has started for at least {idle} ({last}). Either worker-dl is down or stuck, or these tracks' queue "
            f"messages were lost; nothing downloads until that's fixed.",
        )

    def _record(self, category: str, fingerprint: str, text: str):
        with self._session() as db:
            state = record(db, category, fingerprint, text)
            db.commit()
        return state

    def _record_release(self, trip_fingerprint: str) -> None:
        """Re-checked under a share lock on worker_state: a trip commits its worker_state
        update and its alert row together, so either it committed first (the re-read sees it
        tripped again, or its newer row, and no release is recorded), or it waits for this
        transaction and its row is written after the release's, which keeps the room's order
        right ("released", then the new trip)."""
        from app.models import WorkerState

        with self._session() as db:
            worker_state = db.execute(
                select(WorkerState).where(WorkerState.id == 1).with_for_update(read=True)
            ).scalar_one_or_none()
            newest = _newest_trip(db)
            if (
                breaker_released(worker_state, datetime.now(timezone.utc))
                and newest is not None
                and newest.fingerprint == trip_fingerprint
                and not _release_recorded(db, trip_fingerprint)
            ):
                record(
                    db,
                    CATEGORY_BREAKER,
                    f"release:{trip_fingerprint}",
                    "Circuit breaker released: downloads resume.",
                )
            db.commit()

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


def outbox_page(db: Session, cursor: str | None, limit: int) -> dict:
    """v59 (O6): one page of the outbox, newest first, for the admin's history panel."""
    from app.models import AlertOutbox
    from app.services import pagination

    sort_key = pagination.SortKey(AlertOutbox.created_at)
    stmt = pagination.apply_cursor(
        select(AlertOutbox), sort_key, AlertOutbox.id, descending=True, cursor=cursor
    ).limit(limit + 1)
    rows = db.execute(stmt).scalars().all()
    page, more = rows[:limit], len(rows) > limit
    return {
        "configured": is_configured(),
        "items": [
            {
                "id": str(row.id),
                "created_at": _aware(row.created_at).isoformat(),
                "category": row.category,
                "state": row.state.value,
                "attempts": row.attempts,
                "next_attempt_at": _aware(row.next_attempt_at).isoformat()
                if row.next_attempt_at
                else None,
                "sent_at": _aware(row.sent_at).isoformat() if row.sent_at else None,
                "last_error": row.last_error,
                "body_preview": row.body
                if len(row.body) <= BODY_PREVIEW_CHARS
                else row.body[: BODY_PREVIEW_CHARS - 1] + "…",
            }
            for row in page
        ],
        "next_cursor": pagination.cursor_for_row(page[-1].created_at, page[-1].id)
        if more
        else None,
    }
