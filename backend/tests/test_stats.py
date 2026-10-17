"""v44: GET /api/admin/stats -- the global aggregates behind the admin stats page."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    BreakerEvent,
    BreakerEventKind,
    Job,
    JobSourceType,
    JobState,
    NetworkPath,
    Proxy,
    ProxySource,
    Track,
    TrackAttempt,
    TrackAttemptOutcome,
    TrackErrorType,
    TrackState,
)
from app.services import stats

SECRET_PROXY = "http://user:hunter2@10.1.2.3:3128"
OTHER_PROXY = "http://5.6.7.8:8080"
TITLE = "VeryUniqueSongTitle"


def _job(db_session, owner, marker="album"):
    job = Job(
        source_url=f"https://open.spotify.com/album/{marker}{uuid.uuid4().hex}",
        source_type=JobSourceType.ALBUM,
        state=JobState.EXPANDED,
        user_id=owner.id,
    )
    db_session.add(job)
    db_session.flush()
    return job


def _track(db_session, job, state=TrackState.COMPLETED, created_at=None):
    track = Track(
        job_id=job.id,
        spotify_track_id=uuid.uuid4().hex,
        song_json={"name": TITLE, "artists": ["Somebody"]},
        state=state,
    )
    if created_at is not None:
        track.created_at = created_at
    db_session.add(track)
    db_session.flush()
    return track


_numbers: dict[uuid.UUID, int] = {}


def _attempt(db_session, track, finished_at, outcome, *, path=None, error_type=None, proxy=None):
    number = _numbers.get(track.id, 0) + 1
    _numbers[track.id] = number
    db_session.add(
        TrackAttempt(
            track_id=track.id,
            attempt_number=number,
            started_at=finished_at - timedelta(seconds=30),
            finished_at=finished_at,
            outcome=outcome,
            error_type=error_type,
            error_message=f"failed via {SECRET_PROXY}" if error_type else None,
            network_path=path,
            proxy_id=proxy.id if proxy is not None else None,
        )
    )


@pytest.fixture()
def now():
    # Mid-hour, so "this hour" and "an hour ago" are unambiguous buckets.
    return datetime(2026, 10, 16, 12, 30, tzinfo=timezone.utc)


@pytest.fixture()
def seeded(db_session, make_user, now):
    """Two users' rows (stats are global), attempts on every path, inside and outside the
    window, two proxies, breaker history and a live queue."""
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    proxy = Proxy(url=SECRET_PROXY, source=ProxySource.MANUAL, enabled=True,
                  last_success_at=now - timedelta(hours=2), cooldown_until=now + timedelta(minutes=10))
    idle = Proxy(url=OTHER_PROXY, source=ProxySource.FILE, enabled=False,
                 cooldown_until=now - timedelta(minutes=1))
    db_session.add_all([proxy, idle])
    db_session.flush()

    a = _track(db_session, _job(db_session, alice, marker="AliceSecretAlbum"))
    b = _track(db_session, _job(db_session, bob))
    hour = now.replace(minute=5)  # this hour's bucket
    # ipv4: 3 completed, 1 audio_provider, 1 lookup (not found)
    for _ in range(3):
        _attempt(db_session, a, hour, TrackAttemptOutcome.COMPLETED, path=NetworkPath.DIRECT_IPV4)
    _attempt(db_session, b, hour - timedelta(hours=1), TrackAttemptOutcome.FAILED,
             path=NetworkPath.DIRECT_IPV4, error_type=TrackErrorType.AUDIO_PROVIDER)
    _attempt(db_session, b, hour, TrackAttemptOutcome.FAILED,
             path=NetworkPath.DIRECT_IPV4, error_type=TrackErrorType.LOOKUP)
    # ipv6: 1 no_output
    _attempt(db_session, a, hour - timedelta(hours=3), TrackAttemptOutcome.FAILED,
             path=NetworkPath.DIRECT_IPV6, error_type=TrackErrorType.NO_OUTPUT)
    # proxy: 1 completed, 2 other
    _attempt(db_session, b, hour, TrackAttemptOutcome.COMPLETED, path=NetworkPath.PROXY, proxy=proxy)
    for _ in range(2):
        _attempt(db_session, b, hour - timedelta(hours=1), TrackAttemptOutcome.FAILED,
                 path=NetworkPath.PROXY, error_type=TrackErrorType.OTHER, proxy=proxy)
    # unknown path: a reclaimed-stuck failure, no error type
    _attempt(db_session, a, hour, TrackAttemptOutcome.FAILED)
    # Not attempts at all: never counted.
    _attempt(db_session, a, hour, TrackAttemptOutcome.HELD)
    _attempt(db_session, a, hour, TrackAttemptOutcome.SKIPPED_DUPLICATE)
    _attempt(db_session, a, hour, TrackAttemptOutcome.CANCELLED, path=NetworkPath.DIRECT_IPV4)
    # Outside the 24h window, inside 7d.
    _attempt(db_session, a, now - timedelta(days=3), TrackAttemptOutcome.FAILED,
             path=NetworkPath.DIRECT_IPV4, error_type=TrackErrorType.AUDIO_PROVIDER)

    # Breaker: a 6h pause from 26h ago that's over; a trip 30h ago (outside 24h, pause over
    # before the window); and one from before the window whose pause reaches into it.
    db_session.add_all([
        BreakerEvent(kind=BreakerEventKind.TRIPPED, occurred_at=now - timedelta(hours=30),
                     step_seconds=1800, trip_count=1, paused_until=now - timedelta(hours=29, minutes=30)),
        BreakerEvent(kind=BreakerEventKind.ESCALATED, occurred_at=now - timedelta(hours=25),
                     step_seconds=7200, trip_count=2, paused_until=now - timedelta(hours=23)),
        BreakerEvent(kind=BreakerEventKind.RELEASED, occurred_at=now - timedelta(hours=23)),
        BreakerEvent(kind=BreakerEventKind.TRIPPED, occurred_at=now - timedelta(hours=2),
                     step_seconds=1800, trip_count=1, paused_until=now - timedelta(hours=1, minutes=30)),
        BreakerEvent(kind=BreakerEventKind.RELEASED, occurred_at=now - timedelta(hours=1, minutes=45),
                     manual=True),
    ])

    # Queue: 2 waiting (the oldest 5 days old), 1 pending, 1 downloading.
    _track(db_session, _job(db_session, alice), TrackState.WAITING, created_at=now - timedelta(days=5))
    _track(db_session, _job(db_session, bob), TrackState.WAITING, created_at=now - timedelta(days=1))
    _track(db_session, _job(db_session, bob), TrackState.PENDING)
    _track(db_session, _job(db_session, bob), TrackState.DOWNLOADING)
    db_session.commit()
    return {"proxy": proxy}


def test_network_paths_count_real_attempts_only(db_session, seeded, now):
    result = stats.admin_stats(db_session, "24h", now)
    paths = {p["path"]: p for p in result["network_paths"]}

    assert [p["path"] for p in result["network_paths"]] == [
        "direct-ipv4", "direct-ipv6", "proxy", "unknown"
    ]
    assert paths["direct-ipv4"] == {
        "path": "direct-ipv4", "attempts": 5, "completed": 3, "failed": 1, "not_found": 1,
        # The owner's definition: "not found" is about the track, not the route.
        "success_rate": 3 / 4,
    }
    assert paths["direct-ipv6"]["attempts"] == 1 and paths["direct-ipv6"]["success_rate"] == 0
    assert paths["proxy"]["attempts"] == 3 and paths["proxy"]["completed"] == 1
    assert paths["unknown"]["attempts"] == 1 and paths["unknown"]["failed"] == 1


def test_unused_paths_read_as_zero_not_missing(db_session, now):
    result = stats.admin_stats(db_session, "24h", now)

    assert [p["path"] for p in result["network_paths"]] == ["direct-ipv4", "direct-ipv6", "proxy"]
    assert all(p["attempts"] == 0 and p["success_rate"] is None for p in result["network_paths"])


def test_wider_window_includes_older_attempts(db_session, seeded, now):
    result = stats.admin_stats(db_session, "7d", now)
    paths = {p["path"]: p for p in result["network_paths"]}

    assert paths["direct-ipv4"]["attempts"] == 6
    assert result["bucket_seconds"] == 86400
    assert len(result["failures"]["buckets"]) == 7
    assert result["failures"]["buckets"][-1] == "2026-10-16T00:00:00+00:00"
    assert len(stats.admin_stats(db_session, "30d", now)["failures"]["buckets"]) == 30


def test_bucket_length_is_not_reused_across_windows(db_session, seeded, now):
    """The bucket expression's length/offset are inlined literals: a compiled 24h statement
    must never be served from SQLAlchemy's cache for a 7d one."""
    stats.admin_stats(db_session, "24h", now)
    series = {s["error_type"]: s["counts"] for s in stats.admin_stats(db_session, "7d", now)["failures"]["series"]}
    # Today: 1 audio_provider (an hour ago), 1 lookup, 2 other, 1 no_output, 1 unknown;
    # three days ago: 1 audio_provider.
    assert series["audio_provider"] == [0, 0, 0, 1, 0, 0, 1]
    assert series["other"][-1] == 2 and series["lookup"][-1] == 1


def test_day_buckets_follow_the_viewers_clock(db_session, make_user, now):
    """Owner's choice: a day bucket is the viewer's own day. 23:30 UTC on the 15th is
    01:30 on the 16th in Budapest (UTC+2), so it lands in the 16th's bucket there."""
    track = _track(db_session, _job(db_session, make_user("tz@example.com")))
    _attempt(db_session, track, datetime(2026, 10, 15, 23, 30, tzinfo=timezone.utc),
             TrackAttemptOutcome.FAILED, path=NetworkPath.DIRECT_IPV4,
             error_type=TrackErrorType.AUDIO_PROVIDER)
    db_session.commit()

    utc = stats.admin_stats(db_session, "7d", now)["failures"]
    local = stats.admin_stats(db_session, "7d", now, utc_offset_minutes=120)["failures"]

    assert utc["series"][0]["counts"][-2:] == [1, 0]
    assert local["series"][0]["counts"][-2:] == [0, 1]
    # Local midnight of the 16th, as an instant.
    assert local["buckets"][-1] == "2026-10-15T22:00:00+00:00"


def test_proxies_by_redacted_label_with_current_cooldown_only(db_session, seeded, now):
    result = stats.admin_stats(db_session, "24h", now)

    assert result["proxies"] == [
        {
            "label": "10.1.2.3:3128", "enabled": True,
            "attempts": 3, "completed": 1, "failed": 2, "not_found": 0, "success_rate": 1 / 3,
            "last_success_at": (now - timedelta(hours=2)).isoformat(),
            "cooldown_until": (now + timedelta(minutes=10)).isoformat(),
        },
        {
            "label": "5.6.7.8:8080", "enabled": False,
            "attempts": 0, "completed": 0, "failed": 0, "not_found": 0, "success_rate": None,
            "last_success_at": None,
            # Its cooldown ended a minute ago: not current.
            "cooldown_until": None,
        },
    ]


def test_failures_by_error_type_land_in_their_hour(db_session, seeded, now):
    failures = stats.admin_stats(db_session, "24h", now)["failures"]

    assert len(failures["buckets"]) == 24
    assert failures["buckets"][0] == "2026-10-15T13:00:00+00:00"
    assert failures["buckets"][-1] == "2026-10-16T12:00:00+00:00"
    series = {s["error_type"]: s for s in failures["series"]}
    assert [s["error_type"] for s in failures["series"]] == [
        "audio_provider", "lookup", "other", "no_output", "unknown"
    ]
    assert series["audio_provider"]["counts"][22] == 1 and series["audio_provider"]["total"] == 1
    assert series["lookup"]["counts"][23] == 1
    assert series["other"]["counts"][22] == 2
    assert series["no_output"]["counts"][20] == 1
    assert series["unknown"]["counts"][23] == 1
    assert sum(sum(s["counts"]) for s in failures["series"]) == 6


def test_breaker_history_includes_a_pause_reaching_into_the_window(db_session, seeded, now):
    breaker = stats.admin_stats(db_session, "24h", now)["breaker"]

    kinds = [(e["kind"], e["occurred_at"]) for e in breaker["events"]]
    assert kinds == [
        ("escalated", (now - timedelta(hours=25)).isoformat()),
        ("released", (now - timedelta(hours=23)).isoformat()),
        ("tripped", (now - timedelta(hours=2)).isoformat()),
        ("released", (now - timedelta(hours=1, minutes=45)).isoformat()),
    ]
    assert breaker["events"][0]["step_seconds"] == 7200
    assert breaker["events"][3]["manual"] is True
    # Only trips that started inside the window count as the window's trips.
    assert breaker["trips"] == 1


def test_current_breaker_state(db_session, now):
    from app.models import WorkerState

    db_session.add(WorkerState(id=1, paused=True, breaker_trip_count=2,
                               breaker_tripped_until=now + timedelta(minutes=40)))
    db_session.commit()
    assert stats.admin_stats(db_session, "24h", now)["breaker"]["current"] == {
        "paused": True,
        "holding_until": (now + timedelta(minutes=40)).isoformat(),
        "trip_count": 2,
    }
    # A pause that ran out a moment ago, not yet recorded as released, is over.
    assert stats.admin_stats(db_session, "24h", now + timedelta(hours=1))["breaker"]["current"][
        "holding_until"
    ] is None


def test_queue_depth_and_oldest_waiting_age(db_session, seeded, now):
    queue = stats.admin_stats(db_session, "24h", now)["queue"]

    assert queue["counts"] == {"pending": 1, "queued": 0, "downloading": 1, "waiting": 2}
    assert queue["oldest_waiting_since"] == (now - timedelta(days=5)).isoformat()
    assert queue["oldest_waiting_age_seconds"] == 5 * 86400


def test_empty_database(db_session, now):
    result = stats.admin_stats(db_session, "24h", now)

    assert result["proxies"] == []
    assert result["failures"]["series"] == []
    assert result["breaker"] == {
        "current": {"paused": False, "holding_until": None, "trip_count": 0},
        "events": [],
        "trips": 0,
    }
    assert result["queue"] == {
        "counts": {"pending": 0, "queued": 0, "downloading": 0, "waiting": 0},
        "oldest_waiting_since": None,
        "oldest_waiting_age_seconds": None,
    }


def test_endpoint_returns_counts_only(admin_client, db_session, seeded):
    response = admin_client.get("/api/admin/stats?window=7d")
    assert response.status_code == 200
    body = response.text

    assert json.loads(body)["window"] == "7d"
    for leak in (TITLE, "AliceSecretAlbum", "open.spotify.com", "Somebody", "alice@example.com", "bob@example.com",
                 "admin@example.com", "hunter2", "user:", SECRET_PROXY, OTHER_PROXY, "http://", str(seeded["proxy"].id)):
        assert leak not in body, leak


def test_endpoint_defaults_to_24h_and_rejects_an_unknown_window(admin_client):
    body = admin_client.get("/api/admin/stats").json()
    assert body["window"] == "24h" and body["utc_offset_minutes"] == 0
    assert admin_client.get("/api/admin/stats?window=1y").status_code == 422
    assert admin_client.get("/api/admin/stats?utc_offset_minutes=120").json()["utc_offset_minutes"] == 120
    for bad in ("841", "-721", "abc"):
        assert admin_client.get(f"/api/admin/stats?utc_offset_minutes={bad}").status_code == 422


def test_non_admin_gets_404_not_403(authenticated_client):
    for url in ("/api/admin/stats", "/api/admin/stats?window=30d", "/api/admin/stats?window=1y"):
        response = authenticated_client.get(url)
        assert response.status_code == 404
        # Indistinguishable from a route that doesn't exist.
        assert response.json() == authenticated_client.get("/api/admin/nothing-here").json()


def test_unauthenticated_gets_401(client):
    assert client.get("/api/admin/stats").status_code == 401
