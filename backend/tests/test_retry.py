from datetime import datetime, timedelta, timezone

from app.models import Job, JobSourceType, Track, TrackErrorType, TrackState, User, WorkerState
from app.services import retry
from spotdl.providers.audio.base import AudioProviderError


def _aware(dt: datetime) -> datetime:
    # SQLite (used for these in-process tests, see v02/v03 gotchas) round-trips a
    # timestamptz column as a naive datetime; a no-op against real Postgres/psycopg.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _owner(db_session) -> User:
    user = db_session.query(User).filter(User.email == "owner@example.com").one_or_none()
    if user is None:
        user = User(email="owner@example.com", is_admin=False)
        db_session.add(user)
        db_session.flush()
    return user


def _make_track(db_session):
    job = Job(
        source_url="https://open.spotify.com/track/abc",
        source_type=JobSourceType.TRACK,
        user_id=_owner(db_session).id,
    )
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
    assert (
        retry.classify_error(retry.NoOutputFileError("spotdl returned no output file"))
        == TrackErrorType.NO_OUTPUT
    )


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


def test_record_failure_no_output_advances_ladder_and_breaker(db_session):
    """v23: NO_OUTPUT is spotdl swallowing a real AudioProviderError internally (see
    retry.NoOutputFileError's docstring) -- it must feed the breaker exactly like a
    directly-raised AudioProviderError does, unlike the OTHER bucket below."""
    track = _make_track(db_session)
    before = datetime.now(timezone.utc)

    retry.record_failure(
        db_session, track, TrackErrorType.NO_OUTPUT, "spotdl returned no output file for this track"
    )
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
    # v40.1: the trip itself starts a fresh streak.
    assert worker_state.consecutive_failures == 0
    assert worker_state.breaker_trip_count == 1
    assert worker_state.breaker_tripped_until is not None
    assert _aware(worker_state.breaker_tripped_until) - datetime.now(timezone.utc) >= timedelta(minutes=29)


def test_one_failure_after_a_trip_does_not_retrip(db_session):
    """v40.1, the production wedge: the streak used to survive the trip, so after every
    release a single failure re-tripped at the top step, and a queue of tracks that can
    never succeed held the breaker shut forever. Re-tripping now takes a full new streak."""
    track = _make_track(db_session)
    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = retry.BREAKER_TRIP_THRESHOLD - 1
    worker_state.breaker_trip_count = 5
    db_session.commit()

    retry.record_failure(db_session, track, TrackErrorType.NO_OUTPUT, "no output")
    db_session.commit()
    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.breaker_trip_count == 6
    first_trip_until = worker_state.breaker_tripped_until

    # The release (time passing) followed by one more failure.
    worker_state.breaker_tripped_until = None
    db_session.commit()
    retry.record_failure(db_session, track, TrackErrorType.NO_OUTPUT, "no output")
    db_session.commit()

    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.consecutive_failures == 1
    assert worker_state.breaker_tripped_until is None
    assert worker_state.breaker_trip_count == 6
    assert first_trip_until is not None

    # A full new streak still re-trips, at the escalated step (escalation only resets on
    # a success).
    for _ in range(retry.BREAKER_TRIP_THRESHOLD - 1):
        retry.record_failure(db_session, track, TrackErrorType.AUDIO_PROVIDER, "rate limited")
        db_session.commit()
    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.breaker_trip_count == 7
    assert _aware(worker_state.breaker_tripped_until) - datetime.now(timezone.utc) >= timedelta(
        hours=5, minutes=59
    )


def test_record_transport_failure_keeps_the_rung_and_never_feeds_the_breaker(db_session):
    track = _make_track(db_session)
    track.attempt_count = 2
    worker_state = retry.get_worker_state(db_session)
    worker_state.consecutive_failures = retry.BREAKER_TRIP_THRESHOLD - 1
    db_session.commit()
    before = datetime.now(timezone.utc)

    retry.record_transport_failure(db_session, track, "proxy unreachable")
    db_session.commit()

    assert track.state == TrackState.WAITING
    assert track.attempt_count == 2
    assert track.last_error_type == TrackErrorType.OTHER
    assert track.last_error == "proxy unreachable"
    assert _aware(track.scheduled_at) - before >= retry.next_delay(0) - timedelta(seconds=1)
    worker_state = db_session.get(WorkerState, 1)
    assert worker_state.consecutive_failures == retry.BREAKER_TRIP_THRESHOLD - 1
    assert worker_state.breaker_tripped_until is None


def test_is_proxy_transport_error_walks_the_chain():
    from requests.exceptions import ProxyError as RequestsProxyError
    from urllib3.exceptions import ProxyError as Urllib3ProxyError

    assert retry.is_proxy_transport_error(RequestsProxyError("Max retries exceeded"))
    assert retry.is_proxy_transport_error(Urllib3ProxyError("Unable to connect to proxy", None))
    assert retry.is_proxy_transport_error(retry.ProxyTransportError("dead"))
    try:
        try:
            raise RuntimeError("ERROR: Unable to download webpage: Tunnel connection failed: 502")
        except RuntimeError as inner:
            raise AudioProviderError("YT-DLP download error - url") from inner
    except AudioProviderError as chained:
        assert retry.is_proxy_transport_error(chained)
    assert not retry.is_proxy_transport_error(AudioProviderError("HTTP Error 429"))
    assert not retry.is_proxy_transport_error(LookupError("No results found"))


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
