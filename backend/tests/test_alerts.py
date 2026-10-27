"""v36: Matrix alerts -- configuration, sending and redaction, the watchdog's spike rule and
process supervision, and the admin settings/test endpoints. v59's outbox (recording, the
cooldown, delivery, the trip/release, worker-down, the history endpoint) is
test_alert_outbox.py, and the O1 loss paths are test_alert_loss_paths.py."""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pydantic import SecretStr

from app.config import get_settings
from app.models import (
    Job,
    JobSourceType,
    LibrarySortRun,
    LibrarySortState,
    Track,
    TrackAttempt,
    TrackAttemptOutcome,
    TrackErrorType,
    TrackState,
    WorkerState,
)
from app.services import alerts
from app.tasks import library as library_task

from alert_support import TOKEN, configured, fake_redis  # noqa: F401 (fixtures)


@pytest.fixture()
def sent(monkeypatch):
    """Captures every PUT send_now makes instead of reaching the network."""
    calls: list[dict] = []

    def fake_put(url, json, headers, timeout):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return httpx.Response(200, json={"event_id": "$x"})

    monkeypatch.setattr(alerts.httpx, "put", fake_put)
    return calls


# --- configuration -----------------------------------------------------------------------


def test_alerts_off_when_any_variable_is_missing_or_blank(monkeypatch, caplog):
    base = {
        "matrix_homeserver_url": "https://matrix.example.org",
        "matrix_access_token": SecretStr(TOKEN),
        "matrix_room_id": "!room:example.org",
    }
    for missing, blank in (("matrix_homeserver_url", None), ("matrix_room_id", "  ")):
        settings = get_settings().model_copy(update={**base, missing: blank})
        monkeypatch.setattr(alerts, "get_settings", lambda s=settings: s)
        assert alerts.matrix_config() is None
    settings = get_settings().model_copy(update={**base, "matrix_access_token": None})
    monkeypatch.setattr(alerts, "get_settings", lambda: settings)
    assert alerts.missing_config_vars() == ["MATRIX_ACCESS_TOKEN"]

    caplog.set_level("INFO", logger="app.services.alerts")
    alerts.log_startup_state()
    assert "Matrix alerts are off (MATRIX_ACCESS_TOKEN unset)" in caplog.text


def test_token_is_a_secret_in_settings_repr(configured):
    assert TOKEN not in repr(configured)
    assert TOKEN not in str(configured.model_dump())


# --- sending + redaction -----------------------------------------------------------------


def test_send_now_puts_an_m_notice_with_bearer_token_and_user_agent(configured, sent):
    alerts.send_now("hello")
    (call,) = sent
    assert call["url"].startswith(
        "https://matrix.example.org/_matrix/client/v3/rooms/%21room%3Aexample.org"
        "/send/m.room.message/"
    )
    assert call["json"] == {"msgtype": "m.notice", "body": "[spotdl-web] hello"}
    assert call["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert call["headers"]["User-Agent"].startswith("spotdl-web-alerts/")


def test_each_send_uses_a_fresh_txn_id(configured, sent):
    alerts.send_now("a")
    alerts.send_now("b")
    assert sent[0]["url"].rsplit("/", 1)[1] != sent[1]["url"].rsplit("/", 1)[1]


def test_body_is_redacted_before_it_leaves_the_process(configured, sent):
    alerts.send_now("download failed: ProxyError http://user:pass@203.0.113.5:8080 refused")
    body = sent[0]["json"]["body"]
    assert "user:pass" not in body
    assert "http://203.0.113.5:8080" in body


def test_dev_messages_are_labelled(configured, sent, monkeypatch):
    dev = configured.model_copy(update={"spotdl_env": "dev"})
    monkeypatch.setattr(alerts, "get_settings", lambda: dev)
    alerts.send_now("x")
    assert sent[0]["json"]["body"] == "[spotdl-web (dev)] x"


def test_long_bodies_are_capped(configured, sent):
    alerts.send_now("x" * 5000)
    assert len(sent[0]["json"]["body"]) == alerts.MAX_BODY_CHARS


def test_send_failure_never_carries_the_token(configured, monkeypatch):
    def unreachable(url, json, headers, timeout):
        raise httpx.ConnectError("[Errno -2] Name or service not known")

    monkeypatch.setattr(alerts.httpx, "put", unreachable)
    with pytest.raises(alerts.AlertSendError) as excinfo:
        alerts.send_now("x")
    assert TOKEN not in str(excinfo.value)
    assert "ConnectError" in str(excinfo.value)


def test_malformed_homeserver_url_is_a_send_error(configured, monkeypatch):
    bad = configured.model_copy(update={"matrix_homeserver_url": "http://[not a url"})
    monkeypatch.setattr(alerts, "get_settings", lambda: bad)
    with pytest.raises(alerts.AlertSendError):
        alerts.send_now("x")


def test_a_control_character_token_never_reaches_a_request_or_an_error(configured, monkeypatch):
    bad_token = "fake-token-PART\ntail"
    bad = configured.model_copy(update={"matrix_access_token": SecretStr(bad_token)})
    monkeypatch.setattr(alerts, "get_settings", lambda: bad)
    calls = []
    monkeypatch.setattr(alerts.httpx, "put", lambda *a, **k: calls.append(1))
    with pytest.raises(alerts.AlertSendError) as excinfo:
        alerts.send_now("x")
    assert calls == []
    assert "PART" not in str(excinfo.value)


def test_protocol_errors_report_the_class_name_only(configured, monkeypatch):
    # A real h11 refusal, against a real listening socket -- its text quotes the header
    # repr-escaped, which is what a literal scrub can't match.
    import socket

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    real_put = httpx.put

    def put_with_bad_header(url, json, headers, timeout):
        headers = {**headers, "X-Probe": f"Bearer {TOKEN}\x00tail"}
        return real_put(
            f"http://127.0.0.1:{listener.getsockname()[1]}/x", json=json, headers=headers, timeout=2
        )

    monkeypatch.setattr(alerts.httpx, "put", put_with_bad_header)
    with pytest.raises(alerts.AlertSendError) as excinfo:
        alerts.send_now("x")
    listener.close()
    assert str(excinfo.value) == "LocalProtocolError"


def test_watchdog_step_respawns_a_dead_watchdog(monkeypatch):
    from app.tasks.celery_app import AlertWatchdogStep

    class Proc:
        def __init__(self, code):
            self.code = code

        def poll(self):
            return self.code

    spawned = []
    monkeypatch.setattr(alerts, "spawn_watchdog", lambda: spawned.append(1) or Proc(None))
    step = AlertWatchdogStep.__new__(AlertWatchdogStep)
    step.process = Proc(None)
    step._supervise()
    assert spawned == []
    step.process = Proc(-9)
    step._supervise()
    assert spawned == [1] and step.process.poll() is None


def test_http_error_status_is_a_send_error(configured, monkeypatch):
    monkeypatch.setattr(
        alerts.httpx, "put", lambda *a, **k: httpx.Response(403, text="error code: 1010")
    )
    with pytest.raises(alerts.AlertSendError, match="HTTP 403"):
        alerts.send_now("x")


# --- watchdog checks ---------------------------------------------------------------------


def _track(db_session, make_user):
    user = make_user("allowed@example.com")
    job = Job(
        user_id=user.id,
        source_url="https://open.spotify.com/track/x",
        source_type=JobSourceType.TRACK,
    )
    db_session.add(job)
    db_session.flush()
    track = Track(job_id=job.id, spotify_track_id=uuid.uuid4().hex, song_json={}, state=TrackState.DOWNLOADING)
    db_session.add(track)
    db_session.flush()
    return track


def _attempt(db_session, track, minutes_ago, outcome, error_type=None, message=None, n=[0]):
    n[0] += 1
    finished = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    db_session.add(
        TrackAttempt(
            track_id=track.id,
            attempt_number=n[0],
            started_at=finished,
            finished_at=finished,
            outcome=outcome,
            error_type=error_type,
            error_message=message,
        )
    )
    db_session.flush()


def test_spike_fires_on_n_consecutive_same_type_failures(db_session, make_user):
    track = _track(db_session, make_user)
    _attempt(db_session, track, 50, TrackAttemptOutcome.COMPLETED)
    for i in range(3):
        _attempt(db_session, track, 10 - i, TrackAttemptOutcome.FAILED, TrackErrorType.NO_OUTPUT, f"e{i}")
    # Holds/skips/cancels don't touch the network and don't break the run.
    _attempt(db_session, track, 1, TrackAttemptOutcome.HELD)
    now = datetime.now(timezone.utc)

    spike = alerts.failure_spike(db_session, 3, 60, now)
    assert spike is not None
    fingerprint, text, _newest = spike
    assert fingerprint == "no_output"
    assert "last 3 download attempts all failed with no_output" in text
    assert "Latest error: e2" in text

    # 4 in a row would need the completed attempt to be a failure too.
    assert alerts.failure_spike(db_session, 4, 60, now) is None


def test_spike_needs_one_error_type_and_the_window(db_session, make_user):
    track = _track(db_session, make_user)
    _attempt(db_session, track, 30, TrackAttemptOutcome.FAILED, TrackErrorType.NO_OUTPUT)
    _attempt(db_session, track, 4, TrackAttemptOutcome.FAILED, TrackErrorType.OTHER)
    _attempt(db_session, track, 3, TrackAttemptOutcome.FAILED, TrackErrorType.NO_OUTPUT)
    _attempt(db_session, track, 2, TrackAttemptOutcome.FAILED, TrackErrorType.NO_OUTPUT)
    now = datetime.now(timezone.utc)
    # The newest 3 mix other into no_output.
    assert alerts.failure_spike(db_session, 3, 60, now) is None
    assert alerts.failure_spike(db_session, 2, 60, now)[0] == "no_output"
    # Inside a 10-minute window only 3 rows remain: not 4 in a row.
    assert alerts.failure_spike(db_session, 4, 10, now) is None


def test_lookup_failures_never_make_a_spike(db_session, make_user):
    track = _track(db_session, make_user)
    _attempt(db_session, track, 9, TrackAttemptOutcome.FAILED, TrackErrorType.NO_OUTPUT)
    for i in range(5):
        _attempt(db_session, track, 8 - i, TrackAttemptOutcome.FAILED, TrackErrorType.LOOKUP)
    _attempt(db_session, track, 1, TrackAttemptOutcome.FAILED, TrackErrorType.NO_OUTPUT)
    now = datetime.now(timezone.utc)
    assert alerts.failure_spike(db_session, 3, 60, now) is None
    # ...and they don't break a run either: the two no_output rows are consecutive.
    assert alerts.failure_spike(db_session, 2, 60, now)[0] == "no_output"


def test_proxy_transport_failures_never_make_a_spike(db_session, make_user):
    """v40.1: a dead proxy pool fails attempts back to back as `other`, which says nothing
    about YouTube -- not a "retune YOUTUBE_PLAYER_CLIENTS" alert."""
    from app.services.attempts import TRANSPORT_FAILURE_PREFIX

    track = _track(db_session, make_user)
    _attempt(db_session, track, 9, TrackAttemptOutcome.FAILED, TrackErrorType.OTHER, "real other")
    for i in range(5):
        _attempt(
            db_session, track, 8 - i, TrackAttemptOutcome.FAILED, TrackErrorType.OTHER,
            TRANSPORT_FAILURE_PREFIX + "the proxy was unreachable (ProxyError: ...)",
        )
    _attempt(db_session, track, 1, TrackAttemptOutcome.FAILED, TrackErrorType.OTHER, "real other")
    now = datetime.now(timezone.utc)
    assert alerts.failure_spike(db_session, 3, 60, now) is None
    # Left out like lookups, so they don't break a run of real ones either.
    assert alerts.failure_spike(db_session, 2, 60, now)[0] == "other"


def test_breaker_released_once_the_pause_has_passed():
    now = datetime.now(timezone.utc)
    assert alerts.breaker_released(None, now)
    assert not alerts.breaker_released(WorkerState(breaker_tripped_until=None, paused=True), now)
    assert alerts.breaker_released(WorkerState(breaker_tripped_until=None), now)
    assert alerts.breaker_released(WorkerState(breaker_tripped_until=now - timedelta(seconds=1)), now)
    assert not alerts.breaker_released(WorkerState(breaker_tripped_until=now + timedelta(minutes=5)), now)


def test_beat_heartbeat_age_falls_back_to_watchdog_start(fake_redis):
    assert alerts.beat_heartbeat_age(1000.0, 900.0) == 100.0
    fake_redis.store[alerts.BEAT_HEARTBEAT_KEY] = "990.5"
    assert alerts.beat_heartbeat_age(1000.0, 900.0) == pytest.approx(9.5)
    # A heartbeat left over from before downtime (Redis is persistent) gets the same grace.
    fake_redis.store[alerts.BEAT_HEARTBEAT_KEY] = "100.0"
    assert alerts.beat_heartbeat_age(1000.0, 900.0) == 100.0


def test_watchdog_step_survives_a_failed_spawn(monkeypatch):
    from app.tasks.celery_app import AlertWatchdogStep

    def no_memory():
        raise OSError(12, "Cannot allocate memory")

    monkeypatch.setattr(alerts, "spawn_watchdog", no_memory)
    step = AlertWatchdogStep.__new__(AlertWatchdogStep)
    step._spawn()
    assert step.process is None
    monkeypatch.setattr(alerts, "spawn_watchdog", lambda: "proc")
    step._supervise()
    assert step.process == "proc"


def test_record_beat_heartbeat_survives_redis_down(monkeypatch):
    import redis

    class Down:
        def set(self, *a, **k):
            raise redis.ConnectionError("down")

    monkeypatch.setattr(alerts, "_redis", lambda: Down())
    alerts.record_beat_heartbeat()  # must not raise


# --- library sweep -----------------------------------------------------------------------


def test_library_alert_texts(monkeypatch):
    queued = []
    monkeypatch.setattr(alerts, "enqueue", lambda *args: queued.append(args))
    finished = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    run = LibrarySortRun(
        id=1, state=LibrarySortState.IDLE, errors=[], processed=3, total=3, moved=2,
        skipped_present=1, quarantined=0, finished_at=finished,
    )
    library_task._alert_sweep_finished(run)
    run.errors = [{"file": "/downloads/a.mp3", "error": "source file missing on disk"}]
    library_task._alert_sweep_finished(run)
    library_task._alert_sweep_finished(run, crash="OSError: http://u:p@198.51.100.1:3128 gone")

    (c1, f1, ok), (_, _, partial), (_, _, crashed) = queued
    assert (c1, f1) == ("library", finished.isoformat())
    assert ok == (
        "Library sweep finished: 3/3 processed, 2 moved, 1 already present, 0 quarantined, 0 errors."
    )
    assert partial.startswith("Library sweep finished with errors:")
    assert "/downloads/a.mp3: source file missing on disk" in partial
    assert crashed.startswith("Library sweep failed: OSError")
    # Redaction happens once, on the way out (format_body), for every category.
    assert "u:p@" not in alerts.format_body(crashed)


# --- settings endpoints ------------------------------------------------------------------


def test_alert_settings_round_trip_for_admin(admin_client, configured):
    body = admin_client.get("/api/settings/alerts").json()
    assert body == {
        "configured": True,
        "alerts_breaker_enabled": True,
        "alerts_spike_enabled": True,
        "alerts_beat_stale_enabled": True,
        "alerts_library_enabled": True,
        "alerts_worker_down_enabled": True,
        "alert_spike_threshold": 5,
        "alert_spike_window_minutes": 60,
        "alert_beat_stale_seconds": 180,
        "alert_worker_down_minutes": 15,
        "alert_cooldown_minutes": 60,
    }
    updated = admin_client.patch(
        "/api/settings/alerts", json={"alerts_spike_enabled": False, "alert_spike_threshold": 8}
    ).json()
    assert updated["alerts_spike_enabled"] is False
    assert updated["alert_spike_threshold"] == 8
    assert updated["alerts_breaker_enabled"] is True


def test_alert_settings_never_expose_the_credentials(admin_client, configured):
    raw = admin_client.get("/api/settings/alerts").text
    assert TOKEN not in raw
    assert "matrix.example.org" not in raw and "!room" not in raw


def test_alert_settings_reject_meaningless_values(admin_client):
    response = admin_client.patch("/api/settings/alerts", json={"alert_beat_stale_seconds": 30})
    assert response.status_code == 400
    response = admin_client.patch("/api/settings/alerts", json={"alert_spike_threshold": 1})
    assert response.status_code == 400
    response = admin_client.patch("/api/settings/alerts", json={"alert_cooldown_minutes": 2**31})
    assert response.status_code == 400
    response = admin_client.patch("/api/settings/alerts", json={"alert_worker_down_minutes": 1})
    assert response.status_code == 400


def test_alert_settings_are_admin_only(authenticated_client):
    assert authenticated_client.get("/api/settings/alerts").status_code == 403
    assert authenticated_client.patch("/api/settings/alerts", json={}).status_code == 403


def test_test_alert_is_404_for_a_non_admin(authenticated_client, configured, sent):
    response = authenticated_client.post("/api/settings/alerts/test")
    assert response.status_code == 404
    assert sent == []


def test_test_alert_delivers_for_an_admin(admin_client, configured, sent):
    response = admin_client.post("/api/settings/alerts/test")
    assert response.status_code == 200
    assert response.json() == {"sent": True}
    assert "Test alert" in sent[0]["json"]["body"]


def test_test_alert_unconfigured_is_409(admin_client):
    assert admin_client.post("/api/settings/alerts/test").status_code == 409


def test_test_alert_send_failure_is_502_without_the_token(admin_client, configured, monkeypatch):
    def unreachable(url, json, headers, timeout):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(alerts.httpx, "put", unreachable)
    response = admin_client.post("/api/settings/alerts/test")
    assert response.status_code == 502
    assert TOKEN not in response.text
