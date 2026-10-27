"""v59: the alert outbox -- recording (the cooldown and toggles decided at insert, suppressed
rows kept), delivery (backoff, give-up, per-category order, the transaction id), the breaker
trip and its release, the worker-down check, the throttled Redis-outage log, the hourly
prune and the admin's history endpoint."""

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import (
    AlertOutbox,
    AlertState,
    Job,
    JobSourceType,
    Track,
    TrackAttempt,
    TrackAttemptOutcome,
    TrackErrorType,
    TrackState,
    WorkerState,
)
from app.services import alerts, app_settings, retry
from app.services.attempts import RECLAIM_PREFIX
from app.tasks import alerts as alert_tasks

from alert_support import (  # noqa: F401 (fixtures)
    WorkerKilled,
    clock,
    configured,
    fake_redis,
    homeserver,
    sessions,
)


def _rows(db_session, category=None):
    stmt = select(AlertOutbox).order_by(AlertOutbox.created_at)
    if category is not None:
        stmt = stmt.where(AlertOutbox.category == category)
    return db_session.execute(stmt).scalars().all()


def _record(db_session, category, fingerprint, text="text"):
    state = alerts.record(db_session, category, fingerprint, text)
    db_session.commit()
    return state


# --- recording ---------------------------------------------------------------------------


def test_record_is_a_noop_when_unconfigured(db_session):
    assert alerts.record(db_session, alerts.CATEGORY_LIBRARY, "fp", "text") is None
    db_session.commit()
    assert _rows(db_session) == []


def test_every_body_is_stored_redacted_and_labelled(configured, db_session):
    """Done-when: a credential-bearing proxy error never reaches the outbox (or the history
    endpoint, which reads it) in the clear."""
    _record(
        db_session,
        alerts.CATEGORY_SPIKE,
        "other",
        "Latest error: ProxyError('Unable to connect to proxy', "
        "OSError('Tunnel connection failed: 407')) via http://alice:s3cret@203.0.113.5:8080",
    )
    (row,) = _rows(db_session)
    assert row.state == AlertState.PENDING
    assert "alice" not in row.body and "s3cret" not in row.body
    assert row.body.startswith("[spotdl-web] Latest error:")
    assert "http://203.0.113.5:8080" in row.body
    assert row.next_attempt_at is not None and row.attempts == 0


def test_cooldown_decisions_are_recorded_as_suppressed(configured, db_session, caplog):
    caplog.set_level("INFO", logger="app.services.alerts")
    assert _record(db_session, "spike", "no_output", "one") == AlertState.PENDING
    assert _record(db_session, "spike", "no_output", "two") == AlertState.SUPPRESSED
    # A different fingerprint (or category) is a different alert.
    assert _record(db_session, "spike", "other", "three") == AlertState.PENDING
    assert _record(db_session, "breaker", "no_output", "four") == AlertState.PENDING
    suppressed = [r for r in _rows(db_session) if r.state == AlertState.SUPPRESSED]
    assert len(suppressed) == 1
    assert suppressed[0].last_error.startswith("cooldown: the same alert was raised at ")
    assert suppressed[0].next_attempt_at is None
    assert "spike alert suppressed (cooldown" in caplog.text


def test_the_cooldown_window_comes_from_settings(configured, db_session):
    app_settings.update_alert_settings(db_session, alert_cooldown_minutes=1)
    db_session.commit()
    _record(db_session, "spike", "x")
    (first,) = _rows(db_session)
    first.created_at = first.created_at - timedelta(minutes=2)
    db_session.commit()
    assert _record(db_session, "spike", "x") == AlertState.PENDING


def test_neither_failed_nor_suppressed_rows_hold_the_cooldown(configured, db_session):
    """Only what the room heard, or is about to: a given-up alert is news again, and a run of
    suppressed rows doesn't stretch the window."""
    _record(db_session, "beat_stale", "stale")
    (first,) = _rows(db_session)
    first.state = AlertState.FAILED
    db_session.commit()
    assert _record(db_session, "beat_stale", "stale") == AlertState.PENDING


def test_a_switched_off_category_is_recorded_suppressed(configured, db_session):
    app_settings.update_alert_settings(db_session, alerts_library_enabled=False)
    db_session.commit()
    assert _record(db_session, "library", "run1") == AlertState.SUPPRESSED
    (row,) = _rows(db_session)
    assert row.last_error == "category switched off in settings"


def test_recording_never_breaks_the_callers_transaction(configured, db_session, monkeypatch, caplog):
    def broken(db):
        raise RuntimeError("app_settings unreadable")

    monkeypatch.setattr(app_settings, "get_alert_settings", broken)
    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = 3
    assert alerts.record(db_session, "breaker", "trip:x", "text") is None
    db_session.commit()  # the caller's own work still commits
    assert db_session.get(WorkerState, 1).consecutive_failures == 3
    assert _rows(db_session) == []
    assert "could not record breaker alert (RuntimeError)" in caplog.text


def test_enqueue_records_in_a_session_of_its_own(configured, db_session, sessions):
    alerts.enqueue("library", "run1", "Library sweep finished.")
    (row,) = _rows(db_session)
    assert (row.category, row.fingerprint, row.state) == ("library", "run1", AlertState.PENDING)


def test_a_v36_send_alert_message_still_in_the_broker_is_recorded(configured, db_session, sessions):
    alert_tasks.send_alert("library", "run-old", "left over from before the deploy")
    (row,) = _rows(db_session)
    assert row.fingerprint == "run-old" and row.state == AlertState.PENDING


# --- the trip point ----------------------------------------------------------------------


def _track(db_session, make_user, state=TrackState.DOWNLOADING, email="allowed@example.com", **fields):
    user = make_user(email)
    job = Job(
        user_id=user.id,
        source_url="https://open.spotify.com/track/x",
        source_type=JobSourceType.TRACK,
    )
    db_session.add(job)
    db_session.flush()
    track = Track(job_id=job.id, spotify_track_id=uuid.uuid4().hex, song_json={}, state=state, **fields)
    db_session.add(track)
    db_session.flush()
    return track


def test_a_breaker_trip_is_recorded_in_the_trips_own_transaction(configured, db_session, make_user):
    track = _track(db_session, make_user)
    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = retry.BREAKER_TRIP_THRESHOLD - 1
    retry.record_failure(db_session, track, TrackErrorType.NO_OUTPUT, "no file")
    db_session.commit()

    (row,) = _rows(db_session)
    assert row.category == "breaker" and row.fingerprint.startswith("trip:30m:")
    assert "Circuit breaker tripped: downloads paused for 30m" in row.body
    assert "trip #1" in row.body and "last error no_output" in row.body


def test_an_escalation_names_the_new_step(configured, db_session):
    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = 5
    worker_state.breaker_trip_count = 1
    retry.maybe_trip_breaker(db_session, TrackErrorType.AUDIO_PROVIDER)
    db_session.commit()
    (row,) = _rows(db_session)
    assert row.fingerprint.startswith("trip:2h:")
    assert "Circuit breaker escalated: downloads paused for 2h" in row.body


def test_a_rolled_back_trip_records_nothing(configured, db_session):
    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = 5
    db_session.commit()
    retry.maybe_trip_breaker(db_session)
    db_session.rollback()
    assert _rows(db_session) == []


def test_below_threshold_records_nothing(configured, db_session, make_user):
    track = _track(db_session, make_user)
    retry.record_failure(db_session, track, TrackErrorType.AUDIO_PROVIDER, "429")
    db_session.commit()
    assert _rows(db_session) == []


# --- delivery ----------------------------------------------------------------------------


def test_a_due_row_is_sent_under_its_own_id_as_the_transaction(
    configured, db_session, sessions, homeserver, clock
):
    _record(db_session, "library", "run1", "Library sweep finished.")
    assert alerts.deliver_due(sessions) == 1
    (row,) = _rows(db_session)
    assert row.state == AlertState.SENT and row.attempts == 1 and row.sent_at is not None
    assert row.next_attempt_at is None
    (request,) = homeserver.requests
    assert request["txn"] == row.id.hex
    assert homeserver.messages == ["[spotdl-web] Library sweep finished."]
    assert alerts.deliver_due(sessions) == 0


def test_a_failed_send_backs_off_30s_2m_10m_then_hourly(
    configured, db_session, sessions, homeserver, clock
):
    _record(db_session, "beat_stale", "stale")
    homeserver.answer(*["unreachable"] * 6)
    for attempts, wait in ((1, 30), (2, 120), (3, 600), (4, 3600), (5, 3600)):
        assert alerts.deliver_due(sessions) == 0
        (row,) = _rows(db_session)
        db_session.refresh(row)
        assert row.state == AlertState.PENDING
        assert row.attempts == attempts
        assert row.next_attempt_at == clock.now + timedelta(seconds=wait)
        assert row.last_error == "ConnectError: [Errno 111] Connection refused"
        # Not due yet: a pass in between doesn't try.
        alerts.deliver_due(sessions)
        assert len(homeserver.requests) == attempts
        clock.advance(wait)
    assert alerts.deliver_due(sessions) == 0  # the 6th "unreachable"
    assert alerts.deliver_due(sessions) == 0  # backing off again
    clock.advance(3600)
    assert alerts.deliver_due(sessions) == 1
    assert len(homeserver.messages) == 1
    assert len({r["txn"] for r in homeserver.requests}) == 1


def test_a_429_waits_at_least_its_retry_after(configured, db_session, sessions, homeserver, clock):
    _record(db_session, "spike", "no_output")
    homeserver.answer((429, {"errcode": "M_LIMIT_EXCEEDED", "retry_after_ms": 300_000}))
    alerts.deliver_due(sessions)
    (row,) = _rows(db_session)
    assert row.next_attempt_at == clock.now + timedelta(seconds=300)
    assert row.last_error.startswith("HTTP 429:")


def test_a_row_still_unsent_after_24h_is_given_up(configured, db_session, sessions, homeserver, clock, caplog):
    _record(db_session, "spike", "no_output")
    homeserver.answer("unreachable")
    alerts.deliver_due(sessions)
    clock.advance(24 * 3600 + 1)
    alerts.deliver_due(sessions)
    (row,) = _rows(db_session)
    assert row.state == AlertState.FAILED and row.next_attempt_at is None
    assert len(homeserver.requests) == 1
    assert "spike alert given up" in caplog.text


def test_a_row_backing_off_past_24h_is_given_up_without_another_try(
    configured, db_session, sessions, homeserver, clock
):
    _record(db_session, "spike", "no_output")
    (row,) = _rows(db_session)
    clock.now = row.created_at + timedelta(hours=24) - timedelta(seconds=1)
    homeserver.answer(503)
    alerts.deliver_due(sessions)
    db_session.refresh(row)
    assert row.state == AlertState.PENDING
    clock.advance(30)
    alerts.deliver_due(sessions)
    db_session.refresh(row)
    assert row.state == AlertState.FAILED and row.attempts == 1
    assert len(homeserver.requests) == 1


def test_a_category_reaches_the_room_in_the_order_raised(
    configured, db_session, sessions, homeserver, clock
):
    """A release never overtakes its backing-off trip; another category isn't held up by it."""
    _record(db_session, "breaker", "trip:30m:a", "tripped")
    _record(db_session, "breaker", "release:trip:30m:a", "released")
    _record(db_session, "library", "run1", "sweep")
    homeserver.answer(503)
    assert alerts.deliver_due(sessions) == 0  # the trip failed; the pass stops there
    assert alerts.deliver_due(sessions) == 1  # trip backing off: library goes, release waits
    assert homeserver.messages == ["[spotdl-web] sweep"]
    clock.advance(30)
    assert alerts.deliver_due(sessions) == 2
    assert homeserver.messages == ["[spotdl-web] sweep", "[spotdl-web] tripped", "[spotdl-web] released"]


def test_a_sender_killed_mid_send_doesnt_post_twice(configured, db_session, sessions, homeserver, clock):
    _record(db_session, "breaker", "trip:30m:a", "tripped")
    homeserver.answer("posted-then-killed")
    with pytest.raises(WorkerKilled):
        alerts.deliver_due(sessions)
    db_session.rollback()
    (row,) = _rows(db_session)
    # Claimed (lease ahead), so no other pass takes it meanwhile...
    assert row.state == AlertState.PENDING and row.attempts == 1
    assert alerts.deliver_due(sessions) == 0
    # ...and after the lease the retry reuses the transaction id: the room has it once.
    clock.advance(alerts.DELIVERY_LEASE_SECONDS)
    assert alerts.deliver_due(sessions) == 1
    assert [r["txn"] for r in homeserver.requests] == [row.id.hex, row.id.hex]
    assert homeserver.messages == ["[spotdl-web] tripped"]


def test_deliver_due_never_raises(configured, db_session, sessions, monkeypatch, clock):
    _record(db_session, "spike", "x")

    def boom(*a, **k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(alerts.httpx, "put", boom)
    assert alerts.deliver_due(sessions) == 0
    (row,) = _rows(db_session)
    assert row.last_error == "RuntimeError" and row.state == AlertState.PENDING

    def no_database():
        raise RuntimeError("database down")

    assert alerts.deliver_due(no_database) == 0


def test_deliver_due_is_a_noop_when_unconfigured(db_session, sessions, homeserver):
    db_session.add(
        AlertOutbox(
            category="spike", fingerprint="x", body="b", created_at=datetime.now(timezone.utc),
            state=AlertState.PENDING, next_attempt_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()
    assert alerts.deliver_due(sessions) == 0
    assert homeserver.requests == []


def test_a_late_delivery_says_when_it_was_raised(configured, db_session, sessions, homeserver, clock):
    _record(db_session, "breaker", "trip:30m:a", "Circuit breaker tripped.")
    clock.advance(3 * 3600)
    alerts.deliver_due(sessions)
    (body,) = homeserver.messages
    assert body.startswith("[spotdl-web] Circuit breaker tripped. (raised ")
    assert body.endswith(" UTC, delivered late)")


def test_the_hourly_prune_keeps_30_days(configured, db_session, sessions):
    _record(db_session, "library", "old")
    _record(db_session, "library", "new")
    old = next(r for r in _rows(db_session) if r.fingerprint == "old")
    old.created_at = datetime.now(timezone.utc) - timedelta(days=31)
    db_session.commit()
    alert_tasks.prune_alert_outbox()
    assert [r.fingerprint for r in _rows(db_session)] == ["new"]


def test_the_test_alert_is_recorded_sent(admin_client, configured, db_session, homeserver):
    assert admin_client.post("/api/settings/alerts/test").json() == {"sent": True}
    (row,) = _rows(db_session)
    assert (row.category, row.state, row.attempts) == ("test", AlertState.SENT, 1)
    assert homeserver.requests[0]["txn"] == row.id.hex


def test_a_failed_test_alert_is_recorded_failed_and_never_retried(
    admin_client, configured, db_session, sessions, homeserver, clock
):
    homeserver.answer("unreachable")
    assert admin_client.post("/api/settings/alerts/test").status_code == 502
    (row,) = _rows(db_session)
    assert row.state == AlertState.FAILED
    clock.advance(3600)
    alerts.deliver_due(sessions)
    assert len(homeserver.requests) == 1


# --- the watchdog: release, spike, beat, worker-down -------------------------------------


@pytest.fixture()
def watchdog(db_session, fake_redis, sessions, homeserver, clock):
    dog = alerts.Watchdog.__new__(alerts.Watchdog)
    dog.started_at = time.time()
    dog.redis_outage = alerts.RedisOutageLog(alerts.logger)
    dog._open_since = None
    dog._backlog_since = None
    dog._session = sessions
    fake_redis.store[alerts.BEAT_HEARTBEAT_KEY] = f"{time.time():.3f}"
    return dog


def _trip_row(db_session, fingerprint="trip:30m:20261018T191647", state=AlertState.SENT):
    _record(db_session, "breaker", fingerprint, "Circuit breaker tripped.")
    row = next(r for r in _rows(db_session) if r.fingerprint == fingerprint)
    row.state = state
    db_session.commit()
    return row


def test_a_release_is_recorded_once_for_a_trip_the_room_heard_about(
    configured, watchdog, db_session, homeserver
):
    retry.get_worker_state(db_session)
    db_session.commit()
    _trip_row(db_session)
    watchdog.check_once()
    watchdog.check_once()
    releases = [r for r in _rows(db_session, "breaker") if r.fingerprint.startswith("release:")]
    assert [(r.fingerprint, r.state) for r in releases] == [
        ("release:trip:30m:20261018T191647", AlertState.SENT)
    ]
    assert homeserver.messages == ["[spotdl-web] Circuit breaker released: downloads resume."]


def test_no_release_before_the_trip_itself_was_sent(configured, watchdog, db_session):
    trip = _trip_row(db_session, state=AlertState.PENDING)
    trip.next_attempt_at = datetime.now(timezone.utc) + timedelta(hours=1)  # backing off
    db_session.commit()
    watchdog.check_once()
    assert [r.fingerprint for r in _rows(db_session, "breaker")] == [trip.fingerprint]


def test_no_release_while_tripped_or_paused(configured, watchdog, db_session):
    _trip_row(db_session)
    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(minutes=10)
    db_session.commit()
    watchdog.check_once()
    worker_state.breaker_tripped_until = None
    worker_state.paused = True
    db_session.commit()
    watchdog.check_once()
    assert len(_rows(db_session, "breaker")) == 1


def test_a_release_is_never_paired_with_a_newer_trip(configured, watchdog, db_session):
    """The re-check under worker_state's lock: a trip recorded after the watchdog's read
    is newer, and the old trip's release is no longer the room's news."""
    _trip_row(db_session, "trip:30m:old")
    _trip_row(db_session, "trip:2h:new", state=AlertState.PENDING)
    watchdog._record_release("trip:30m:old")
    assert not [r for r in _rows(db_session, "breaker") if r.fingerprint.startswith("release:")]


def test_a_release_with_the_breaker_switched_off_is_recorded_suppressed(configured, watchdog, db_session):
    _trip_row(db_session)
    app_settings.update_alert_settings(db_session, alerts_breaker_enabled=False)
    db_session.commit()
    watchdog.check_once()
    watchdog.check_once()
    (release,) = [r for r in _rows(db_session, "breaker") if r.fingerprint.startswith("release:")]
    assert release.state == AlertState.SUPPRESSED


def _attempt(db_session, track, minutes_ago, outcome, error_type=None, message=None, warning=None):
    finished = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    number = (
        db_session.execute(
            select(TrackAttempt.attempt_number)
            .where(TrackAttempt.track_id == track.id)
            .order_by(TrackAttempt.attempt_number.desc())
            .limit(1)
        ).scalar_one_or_none()
        or 0
    ) + 1
    db_session.add(
        TrackAttempt(
            track_id=track.id,
            attempt_number=number,
            started_at=finished,
            finished_at=finished,
            outcome=outcome,
            error_type=error_type,
            error_message=message,
            warning_message=warning,
        )
    )
    db_session.flush()


def test_a_spike_is_re_raised_only_with_a_newer_attempt(configured, watchdog, db_session, make_user):
    track = _track(db_session, make_user)
    for i in range(5):
        _attempt(db_session, track, 5 - i, TrackAttemptOutcome.FAILED, TrackErrorType.NO_OUTPUT)
    db_session.commit()
    watchdog.check_once()
    watchdog.check_once()
    assert len(_rows(db_session, "spike")) == 1
    _attempt(db_session, track, 0, TrackAttemptOutcome.FAILED, TrackErrorType.NO_OUTPUT)
    db_session.commit()
    watchdog.check_once()
    # Raised again, and suppressed by the cooldown: recorded, not sent.
    assert [r.state for r in _rows(db_session, "spike")] == [AlertState.SENT, AlertState.SUPPRESSED]


def test_a_stale_beat_is_raised(configured, watchdog, db_session, fake_redis):
    fake_redis.store[alerts.BEAT_HEARTBEAT_KEY] = f"{time.time() - 600:.3f}"
    watchdog.started_at = time.time() - 900
    watchdog.check_once()
    (row,) = _rows(db_session, "beat_stale")
    assert "Beat looks dead: no dispatch tick for 6" in row.body


# worker-down -------------------------------------------------------------------------------

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _at(minutes):
    return T0 + timedelta(minutes=minutes)


def test_worker_down_since_rules():
    since = alerts.worker_down_since
    # Nothing due: nothing owed.
    assert since(None, _at(0), _at(-60), None) is None
    # Something started after the oldest due track fell due: worker-dl is alive.
    assert since(_at(0), _at(5), _at(-60), None) is None
    # Nothing since: unconsumed from the due time...
    assert since(_at(0), _at(-10), _at(-60), None) == _at(0)
    # ...or from when dispatch reopened, if that came later (a trip held it).
    assert since(_at(0), _at(-10), _at(20), None) == _at(20)
    assert since(_at(0), None, _at(-60), None) == _at(0)
    # Beat's stale sweep rewrites scheduled_at to its tick: the first moment is kept.
    assert since(_at(30), _at(-10), _at(-60), _at(0)) == _at(0)
    # Until something is consumed after it.
    assert since(_at(30), _at(31), _at(-60), _at(0)) is None


@pytest.fixture()
def backlog(db_session, make_user):
    """A queued track due 40 minutes ago, worker-dl's last attempt 60 minutes ago, and a
    watchdog that has seen the breaker closed for an hour."""
    now = datetime.now(timezone.utc)
    track = _track(db_session, make_user, state=TrackState.QUEUED, scheduled_at=now - timedelta(minutes=40))
    _attempt(db_session, track, 60, TrackAttemptOutcome.FAILED, TrackErrorType.AUDIO_PROVIDER, "429")
    retry.get_worker_state(db_session)
    db_session.commit()
    return track


def test_worker_down_fires_with_due_work_and_the_breaker_closed(configured, watchdog, db_session, backlog):
    watchdog._open_since = datetime.now(timezone.utc) - timedelta(hours=1)
    watchdog.check_once()
    (row,) = _rows(db_session, "worker_down")
    assert row.fingerprint == "stalled"
    assert row.body.startswith("[spotdl-web] worker-dl looks down: 1 due track(s) have waited 40m")
    assert "no download has started since (the last one started " in row.body


def test_worker_down_waits_its_threshold(configured, watchdog, db_session, backlog):
    app_settings.update_alert_settings(db_session, alert_worker_down_minutes=60)
    db_session.commit()
    watchdog._open_since = datetime.now(timezone.utc) - timedelta(hours=1)
    watchdog.check_once()
    assert _rows(db_session, "worker_down") == []


def test_worker_down_is_silent_while_the_breaker_is_tripped(configured, watchdog, db_session, backlog):
    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(minutes=30)
    db_session.commit()
    watchdog._open_since = datetime.now(timezone.utc) - timedelta(hours=1)
    watchdog.check_once()
    assert _rows(db_session, "worker_down") == []
    # ...and the release restarts the clock: tracks due during the trip only just became
    # dispatchable.
    assert watchdog._open_since is None
    worker_state.breaker_tripped_until = None
    db_session.commit()
    watchdog.check_once()
    assert _rows(db_session, "worker_down") == []


def test_worker_down_leaves_a_dead_beat_to_its_own_alert(configured, watchdog, db_session, backlog, fake_redis):
    fake_redis.store[alerts.BEAT_HEARTBEAT_KEY] = f"{time.time() - 900:.3f}"
    watchdog.started_at = time.time() - 3600
    watchdog._open_since = datetime.now(timezone.utc) - timedelta(hours=1)
    watchdog.check_once()
    assert _rows(db_session, "worker_down") == []
    assert len(_rows(db_session, "beat_stale")) == 1


def test_worker_down_ignores_beats_reclaim_rows(configured, watchdog, db_session, backlog):
    """The stale sweep records rows for a stuck invocation: they prove nothing about
    worker-dl, so they don't count as consumption."""
    _attempt(
        db_session, backlog, 1, TrackAttemptOutcome.HELD,
        warning=f"{RECLAIM_PREFIX}still queued past staleness threshold (0:30:00)",
    )
    db_session.commit()
    watchdog._open_since = datetime.now(timezone.utc) - timedelta(hours=1)
    watchdog.check_once()
    assert len(_rows(db_session, "worker_down")) == 1


def test_worker_down_counts_a_download_in_progress(configured, watchdog, db_session, backlog, make_user):
    _track(db_session, make_user, state=TrackState.DOWNLOADING, email="second@example.com")
    db_session.commit()
    watchdog._open_since = datetime.now(timezone.utc) - timedelta(hours=1)
    watchdog.check_once()
    assert _rows(db_session, "worker_down") == []


def test_worker_down_switched_off(configured, watchdog, db_session, backlog):
    app_settings.update_alert_settings(db_session, alerts_worker_down_enabled=False)
    db_session.commit()
    watchdog._open_since = datetime.now(timezone.utc) - timedelta(hours=1)
    watchdog.check_once()
    assert _rows(db_session, "worker_down") == []


# --- O5: a Redis outage's log ------------------------------------------------------------


def test_a_25_minute_redis_outage_logs_one_traceback_two_still_down_lines_and_a_recovery(caplog):
    caplog.set_level("INFO", logger="app.services.alerts")
    outage = alerts.RedisOutageLog(alerts.logger)
    start = 10_000.0
    for minute in range(25):
        try:
            raise ConnectionError("Error 111 connecting to redis:6379")
        except ConnectionError:
            outage.failed(start + 60 * minute)
    outage.reached(start + 60 * 25)
    outage.reached(start + 60 * 26)
    records = [r for r in caplog.records if r.name == "app.services.alerts"]
    assert [r.getMessage() for r in records] == [
        "alerts: Redis unreachable; skipping the checks that need it",
        "alerts: Redis still down (11 checks)",
        "alerts: Redis still down (21 checks)",
        "alerts: Redis reachable again after 1500s (25 failed checks)",
    ]
    assert records[0].exc_info is not None
    assert all(r.exc_info is None for r in records[1:])


def test_the_watchdog_keeps_its_database_checks_through_a_redis_outage(
    configured, watchdog, db_session, monkeypatch, caplog
):
    import redis

    class Down:
        def get(self, *a, **k):
            raise redis.ConnectionError("Error 111")

        set = get

    monkeypatch.setattr(alerts, "_redis", lambda: Down())
    _trip_row(db_session)
    watchdog.check_once()
    watchdog.check_once()
    # The release (database only) still went out...
    assert any(r.fingerprint.startswith("release:") for r in _rows(db_session, "breaker"))
    # ...and the outage is one traceback, not one per check.
    tracebacks = [r for r in caplog.records if r.levelno == logging.WARNING and r.exc_info]
    assert len(tracebacks) == 1
    assert "watchdog check failed" not in caplog.text


# --- O6: the history endpoint ------------------------------------------------------------


def test_the_history_pages_newest_first(admin_client, configured, db_session):
    for i in range(5):
        _record(db_session, "library", f"run{i}", f"sweep {i} " + "x" * 400)
    first = admin_client.get("/api/admin/alerts", params={"limit": 3}).json()
    assert first["configured"] is True
    assert [item["body_preview"][:21] for item in first["items"]] == [
        "[spotdl-web] sweep 4 ",
        "[spotdl-web] sweep 3 ",
        "[spotdl-web] sweep 2 ",
    ]
    item = first["items"][0]
    assert set(item) == {
        "id", "created_at", "category", "state", "attempts", "next_attempt_at", "sent_at",
        "last_error", "body_preview",
    }
    assert len(item["body_preview"]) == alerts.BODY_PREVIEW_CHARS
    assert item["state"] == "pending"
    second = admin_client.get(
        "/api/admin/alerts", params={"limit": 3, "cursor": first["next_cursor"]}
    ).json()
    assert [i["body_preview"][:20] for i in second["items"]] == [
        "[spotdl-web] sweep 1",
        "[spotdl-web] sweep 0",
    ]
    assert second["next_cursor"] is None


def test_the_history_rejects_a_bad_cursor_and_limit(admin_client):
    assert admin_client.get("/api/admin/alerts", params={"cursor": "nope"}).status_code == 400
    assert admin_client.get("/api/admin/alerts", params={"limit": 0}).status_code == 422
    assert admin_client.get("/api/admin/alerts", params={"limit": 101}).status_code == 422


def test_the_history_is_404_for_a_non_admin_and_401_signed_out(authenticated_client, client):
    response = authenticated_client.get("/api/admin/alerts")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    authenticated_client.cookies.clear()
    assert authenticated_client.get("/api/admin/alerts").status_code == 401
