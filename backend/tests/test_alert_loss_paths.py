"""v59 (O1): every way the slot stack lost an alert before the outbox (docs/GOTCHAS.md v59
lists each run), now delivered. These tests raise alerts the way production does
(alerts.enqueue, a breaker trip's commit) and drive delivery only through alert_support's
`deliver`, `meta_killed` and `redis_down`, never an outbox function, so the same file runs
against v36's Celery path too: there every one of them fails, which the PR shows."""

from app.services import alerts, retry
from app.models import TrackErrorType

from alert_support import (  # noqa: F401 (fixtures)
    clock,
    configured,
    deliver,
    fake_redis,
    homeserver,
    meta_killed,
    redis_down,
    sessions,
)

TEXT = "Library sweep finished: 3/3 processed, 3 moved, 0 already present, 0 quarantined, 0 errors."
BODY = f"[spotdl-web] {TEXT}"


def _arrived(homeserver) -> list[str]:
    # Late deliveries carry a "(raised ..., delivered late)" note; the alert is what counts.
    return [m.split(" (raised ")[0] for m in homeserver.messages]


def test_an_alert_behind_a_meta_backlog_past_five_minutes_still_arrives(
    configured, homeserver, clock, deliver
):
    """Path A: v36's message expired after 300s on a busy `meta` queue ("Discarding revoked
    task"), and nothing ever sent it."""
    alerts.enqueue(alerts.CATEGORY_LIBRARY, "run1", TEXT)
    clock.advance(310)
    deliver()
    assert _arrived(homeserver) == [BODY]


def test_a_breaker_trip_behind_a_meta_backlog_still_arrives(
    configured, db_session, homeserver, clock, deliver
):
    """Path A for the 2026-10-18 shape: a trip whose alert waits out a backlog."""
    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = retry.BREAKER_TRIP_THRESHOLD
    retry.maybe_trip_breaker(db_session, TrackErrorType.NO_OUTPUT)
    db_session.commit()
    clock.advance(310)
    deliver()
    (message,) = _arrived(homeserver)
    assert message.startswith("[spotdl-web] Circuit breaker tripped: downloads paused for 30m")


def test_an_alert_prefetched_when_worker_meta_is_killed_still_arrives(
    configured, homeserver, clock, deliver, meta_killed
):
    """Path B: v36's prefetched message sat in Redis's `unacked` until the 6h visibility
    timeout, by when its 300s expiry had long passed."""
    alerts.enqueue(alerts.CATEGORY_LIBRARY, "run1", TEXT)
    meta_killed()
    clock.advance(120)
    deliver()
    clock.advance(6 * 3600)
    deliver()
    assert _arrived(homeserver) == [BODY]


def test_an_alert_mid_send_when_worker_meta_is_killed_arrives_once(
    configured, homeserver, clock, deliver
):
    """Path B: v36's send_alert was acked before it ran (acks_late=False), so a kill
    mid-send dropped it."""
    homeserver.answer("killed")
    alerts.enqueue(alerts.CATEGORY_LIBRARY, "run1", TEXT)
    deliver()
    clock.advance(180)
    deliver()
    assert _arrived(homeserver) == [BODY]


def test_an_alert_answered_with_a_5xx_is_retried_until_it_arrives(
    configured, homeserver, clock, deliver
):
    """Path D: v36 logged "not sent: HTTP 503" and dropped it."""
    homeserver.answer(503, 502)
    alerts.enqueue(alerts.CATEGORY_LIBRARY, "run1", TEXT)
    deliver()
    clock.advance(30)
    deliver()
    clock.advance(120)
    deliver()
    assert _arrived(homeserver) == [BODY]


def test_an_alert_answered_with_a_429_is_retried_until_it_arrives(
    configured, homeserver, clock, deliver
):
    """Path D: the same for Matrix's rate limit."""
    homeserver.answer((429, {"errcode": "M_LIMIT_EXCEEDED", "retry_after_ms": 5000}))
    alerts.enqueue(alerts.CATEGORY_LIBRARY, "run1", TEXT)
    deliver()
    clock.advance(30)
    deliver()
    assert _arrived(homeserver) == [BODY]


def test_a_failed_first_send_doesnt_cost_the_repeat_its_cooldown(
    configured, homeserver, clock, deliver
):
    """Path C: v36 claimed the cooldown before sending, so a failed send suppressed the
    same alert raised again inside the window, and the room heard neither."""
    homeserver.answer(503)
    alerts.enqueue(alerts.CATEGORY_BEAT_STALE, "stale", "Beat looks dead: no dispatch tick for 200s.")
    deliver()
    clock.advance(60)
    alerts.enqueue(alerts.CATEGORY_BEAT_STALE, "stale", "Beat looks dead: no dispatch tick for 260s.")
    deliver()
    assert _arrived(homeserver) == ["[spotdl-web] Beat looks dead: no dispatch tick for 200s."]


def test_an_alert_raised_while_redis_is_down_still_arrives(
    configured, homeserver, clock, deliver, redis_down
):
    """Path E: v36's enqueue couldn't reach the broker ("could not enqueue library alert
    (OperationalError)") and dropped it."""
    with redis_down():
        alerts.enqueue(alerts.CATEGORY_LIBRARY, "run1", TEXT)
    deliver()
    assert _arrived(homeserver) == [BODY]
