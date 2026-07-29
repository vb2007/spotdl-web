from datetime import datetime, timedelta, timezone

from app.models import Job, JobSourceType, Track, TrackErrorType, TrackState, WorkerState
from app.services import retry
from spotdl.providers.audio.base import AudioProviderError


def _aware(dt: datetime) -> datetime:
    # SQLite (used for these in-process tests, see v02/v03 gotchas) round-trips a
    # timestamptz column as a naive datetime; a no-op against real Postgres/psycopg.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _make_track(db_session):
    job = Job(source_url="https://open.spotify.com/track/abc", source_type=JobSourceType.TRACK)
    db_session.add(job)
    db_session.commit()

    track = Track(job_id=job.id, spotify_track_id="abc123", song_json={"name": "Song A"})
    db_session.add(track)
    db_session.commit()
    return track


def test_classify_error_maps_known_exception_types():
    assert retry.classify_error(AudioProviderError("rate limited")) == TrackErrorType.AUDIO_PROVIDER
    assert retry.classify_error(LookupError("no result")) == TrackErrorType.LOOKUP
    assert retry.classify_error(RuntimeError("boom")) == TrackErrorType.OTHER


def test_next_delay_follows_ladder_and_caps_at_final_step(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(
        get_settings(), "ladder_seconds", [900, 3600, 14400, 43200, 86400], raising=False
    )
    assert retry.next_delay(0) == timedelta(seconds=900)
    assert retry.next_delay(1) == timedelta(seconds=3600)
    assert retry.next_delay(4) == timedelta(seconds=86400)
    assert retry.next_delay(10) == timedelta(seconds=86400)


def test_record_failure_lookup_is_terminal_and_never_reschedules(db_session):
    track = _make_track(db_session)

    retry.record_failure(db_session, track, TrackErrorType.LOOKUP, "no result found")
    db_session.commit()

    assert track.state == TrackState.LOOKUP_FAILED
    assert track.last_error_type == TrackErrorType.LOOKUP
    assert track.scheduled_at is None
    assert track.attempt_count == 0


def test_record_failure_audio_provider_advances_ladder_and_breaker(db_session):
    track = _make_track(db_session)
    before = datetime.now(timezone.utc)

    retry.record_failure(db_session, track, TrackErrorType.AUDIO_PROVIDER, "rate limited")
    db_session.commit()

    assert track.state == TrackState.WAITING
    assert track.attempt_count == 1
    assert track.scheduled_at is not None
    assert _aware(track.scheduled_at) - before >= timedelta(minutes=14)

    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.consecutive_failures == 1
    assert worker_state.breaker_tripped_until is None


def test_record_failure_other_shares_ladder_but_does_not_feed_breaker(db_session):
    track = _make_track(db_session)
    # Pre-create the singleton row so "no failure recorded" is provable as consecutive_failures
    # staying at 0, rather than the row simply never having been created.
    retry.get_worker_state(db_session)
    db_session.commit()

    retry.record_failure(db_session, track, TrackErrorType.OTHER, "weird crash")
    db_session.commit()

    assert track.state == TrackState.WAITING
    assert track.attempt_count == 1
    assert track.scheduled_at is not None

    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.consecutive_failures == 0


def test_breaker_trips_after_five_consecutive_failures(db_session):
    track = _make_track(db_session)

    for _ in range(5):
        retry.record_failure(db_session, track, TrackErrorType.AUDIO_PROVIDER, "rate limited")
        db_session.commit()

    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.consecutive_failures == 5
    assert worker_state.breaker_trip_count == 1
    assert worker_state.breaker_tripped_until is not None
    assert _aware(worker_state.breaker_tripped_until) - datetime.now(timezone.utc) >= timedelta(minutes=29)


def test_breaker_escalates_delay_on_successive_trips(db_session):
    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = 5
    worker_state.breaker_trip_count = 1
    db_session.commit()

    retry.maybe_trip_breaker(db_session)
    db_session.commit()

    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.breaker_trip_count == 2
    assert _aware(worker_state.breaker_tripped_until) - datetime.now(timezone.utc) >= timedelta(
        hours=1, minutes=59
    )


def test_breaker_caps_delay_at_third_trip_and_beyond(db_session):
    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = 5
    worker_state.breaker_trip_count = 5
    db_session.commit()

    retry.maybe_trip_breaker(db_session)
    db_session.commit()

    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.breaker_trip_count == 6
    assert _aware(worker_state.breaker_tripped_until) - datetime.now(timezone.utc) >= timedelta(
        hours=5, minutes=59
    )


def test_record_success_resets_breaker_state(db_session):
    track = _make_track(db_session)
    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = 4
    worker_state.breaker_trip_count = 2
    worker_state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(hours=2)
    db_session.commit()

    retry.record_success(db_session, track)
    db_session.commit()

    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.consecutive_failures == 0
    assert worker_state.breaker_trip_count == 0
    assert worker_state.breaker_tripped_until is None


def test_breaker_active_checks_paused_and_tripped_until():
    now = datetime.now(timezone.utc)

    tripped = WorkerState(id=1, paused=False, breaker_tripped_until=now + timedelta(minutes=5))
    assert retry.breaker_active(tripped, now) is True

    expired = WorkerState(id=1, paused=False, breaker_tripped_until=now - timedelta(minutes=5))
    assert retry.breaker_active(expired, now) is False

    paused = WorkerState(id=1, paused=True, breaker_tripped_until=None)
    assert retry.breaker_active(paused, now) is True

    idle = WorkerState(id=1, paused=False, breaker_tripped_until=None)
    assert retry.breaker_active(idle, now) is False
