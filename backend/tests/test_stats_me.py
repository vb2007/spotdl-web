"""v66: GET /api/stats/me -- one user's own download stats, owner-scoped by construction."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    DownloadedTrack,
    Job,
    JobSourceType,
    JobState,
    Track,
    TrackAttempt,
    TrackAttemptOutcome,
    TrackErrorType,
    TrackState,
    User,
)
from app.services import stats

_numbers: dict[uuid.UUID, int] = {}


def _job(db_session, owner, *, state=JobState.EXPANDED, created_at=None, archived_at=None):
    job = Job(
        source_url=f"https://open.spotify.com/album/{uuid.uuid4().hex}",
        source_type=JobSourceType.ALBUM,
        state=state,
        user_id=owner.id,
        archived_at=archived_at,
    )
    if created_at is not None:
        job.created_at = created_at
    db_session.add(job)
    db_session.flush()
    return job


def _track(db_session, job, state=TrackState.COMPLETED, created_at=None, spotify_id=None):
    track = Track(
        job_id=job.id,
        spotify_track_id=spotify_id or uuid.uuid4().hex,
        song_json={"name": "Song", "artists": ["Somebody"]},
        state=state,
    )
    if created_at is not None:
        track.created_at = created_at
    db_session.add(track)
    db_session.flush()
    return track


def _attempt(db_session, track, finished_at, outcome, error_type=None):
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
        )
    )
    db_session.flush()


@pytest.fixture()
def now():
    return datetime(2026, 10, 16, 12, 30, tzinfo=timezone.utc)


@pytest.fixture()
def seeded(db_session, make_user, now):
    """Alice's and Bob's rows side by side: every number Alice reads must be hers alone."""
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    hour = now.replace(minute=5)

    a_job = _job(db_session, alice, created_at=now - timedelta(hours=5))
    # Queued 1h, 2h and 4h before their files landed: median 2h.
    for waited in (1, 2, 4):
        t = _track(db_session, a_job, created_at=hour - timedelta(hours=waited))
        _attempt(db_session, t, hour, TrackAttemptOutcome.COMPLETED)
    retried = _track(db_session, a_job, state=TrackState.WAITING, created_at=now - timedelta(hours=5))
    _attempt(db_session, retried, hour - timedelta(hours=2), TrackAttemptOutcome.FAILED, TrackErrorType.AUDIO_PROVIDER)
    _attempt(db_session, retried, hour - timedelta(hours=1), TrackAttemptOutcome.FAILED, TrackErrorType.NO_OUTPUT)
    missing = _track(db_session, a_job, state=TrackState.LOOKUP_FAILED, created_at=now - timedelta(hours=5))
    _attempt(db_session, missing, hour, TrackAttemptOutcome.FAILED, TrackErrorType.LOOKUP)
    # Not network attempts: never counted.
    _attempt(db_session, retried, hour, TrackAttemptOutcome.HELD)
    # Outside the 24h window.
    old = _track(db_session, a_job, created_at=now - timedelta(days=3))
    _attempt(db_session, old, now - timedelta(days=2), TrackAttemptOutcome.COMPLETED)

    # Bob: lots of everything, none of it Alice's.
    b_job = _job(db_session, bob, created_at=now - timedelta(hours=2))
    for _ in range(5):
        t = _track(db_session, b_job, created_at=hour - timedelta(hours=10))
        _attempt(db_session, t, hour, TrackAttemptOutcome.COMPLETED)
    bt = _track(db_session, b_job, state=TrackState.WAITING)
    _attempt(db_session, bt, hour, TrackAttemptOutcome.FAILED, TrackErrorType.OTHER)
    db_session.flush()
    return {"alice": alice, "bob": bob, "a_job": a_job, "b_job": b_job}


def test_attempt_counts_are_the_users_own(db_session, seeded, now):
    result = stats.my_stats(db_session, seeded["alice"].id, "24h", now)
    assert result["attempts"] == {
        "attempts": 6,
        "completed": 3,
        "failed": 2,
        "not_found": 1,
        "success_rate": 3 / 5,
    }
    bob = stats.my_stats(db_session, seeded["bob"].id, "24h", now)
    assert bob["attempts"]["completed"] == 5 and bob["attempts"]["failed"] == 1


def test_completed_per_bucket_and_wider_window(db_session, seeded, now):
    result = stats.my_stats(db_session, seeded["alice"].id, "24h", now)
    assert result["completed"]["counts"][-1] == 3
    assert result["completed"]["total"] == 3
    assert len(result["completed"]["buckets"]) == 24 == len(result["completed"]["counts"])
    week = stats.my_stats(db_session, seeded["alice"].id, "7d", now)
    assert week["completed"]["total"] == 4


def test_failures_by_class_use_the_admin_builder_narrowed_to_the_user(db_session, seeded, now):
    result = stats.my_stats(db_session, seeded["alice"].id, "24h", now)
    series = {s["error_type"]: s for s in result["failures"]["series"]}
    assert set(series) == {"audio_provider", "no_output", "lookup"}
    assert series["audio_provider"]["counts"][-3] == 1
    assert series["no_output"]["counts"][-2] == 1
    assert series["lookup"]["counts"][-1] == 1
    # Bob's `other` failure is in the global numbers, not in Alice's.
    assert "other" in {s["error_type"] for s in stats.admin_stats(db_session, "24h", now)["failures"]["series"]}


def test_time_to_complete_median(db_session, seeded, now):
    result = stats.my_stats(db_session, seeded["alice"].id, "24h", now)
    assert result["time_to_complete"] == {"median_seconds": 2 * 3600.0, "tracks": 3}


def test_jobs_submitted_in_the_window_by_status(db_session, make_user, now):
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    complete = _job(db_session, alice, created_at=now - timedelta(hours=1))
    _track(db_session, complete)
    partial = _job(db_session, alice, created_at=now - timedelta(hours=2), archived_at=now)
    _track(db_session, partial)
    _track(db_session, partial, state=TrackState.LOOKUP_FAILED)
    active = _job(db_session, alice, created_at=now - timedelta(hours=3))
    _track(db_session, active, state=TrackState.QUEUED)
    _job(db_session, alice, state=JobState.CANCELLED, created_at=now - timedelta(hours=4))
    # Outside the window, and someone else's.
    _track(db_session, _job(db_session, alice, created_at=now - timedelta(days=2)))
    _track(db_session, _job(db_session, bob, created_at=now - timedelta(hours=1)))

    result = stats.my_stats(db_session, alice.id, "24h", now)
    assert result["jobs"] == {
        "total": 4,
        "by_status": {"settled:complete": 1, "settled:partial": 1, "active": 1, "cancelled": 1},
    }


def test_library_contribution_counts_own_downloads_once_and_reads_sizes(db_session, make_user, now, tmp_path):
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    files = {}
    for name, size in (("a.opus", 1000), ("b.opus", 250), ("bob.opus", 5000)):
        path = tmp_path / name
        path.write_bytes(b"x" * size)
        files[name] = str(path)
    db_session.add_all(
        [
            DownloadedTrack(spotify_track_id="sa", file_path=files["a.opus"], format="opus"),
            DownloadedTrack(spotify_track_id="sb", file_path=files["b.opus"], format="opus"),
            DownloadedTrack(spotify_track_id="sbob", file_path=files["bob.opus"], format="opus"),
            DownloadedTrack(spotify_track_id="sgone", file_path=str(tmp_path / "gone.opus"), format="opus"),
        ]
    )
    job = _job(db_session, alice)
    _track(db_session, job, spotify_id="sa")
    # The same track again in a second job of hers: one file.
    _track(db_session, _job(db_session, alice), spotify_id="sa")
    _track(db_session, job, spotify_id="sb")
    # A file whose ledger row points nowhere the disk shows.
    _track(db_session, job, spotify_id="sgone")
    # Bob downloaded this one; Alice's copy resolved as a duplicate: not her contribution.
    _track(db_session, _job(db_session, bob), spotify_id="sbob")
    _track(db_session, job, state=TrackState.SKIPPED_DUPLICATE, spotify_id="sbob")
    db_session.flush()

    assert stats.my_stats(db_session, alice.id, "24h", now)["library"] == {
        "files": 3,
        "bytes": 1250,
        "unreadable": 1,
    }
    assert stats.my_stats(db_session, bob.id, "24h", now)["library"] == {
        "files": 1,
        "bytes": 5000,
        "unreadable": 0,
    }


def test_empty_for_a_new_user(db_session, make_user, now):
    result = stats.my_stats(db_session, make_user("new@example.com").id, "30d", now)
    assert result["attempts"]["attempts"] == 0 and result["attempts"]["success_rate"] is None
    assert result["completed"]["total"] == 0 and len(result["completed"]["counts"]) == 30
    assert result["failures"]["series"] == []
    assert result["time_to_complete"] == {"median_seconds": None, "tracks": 0}
    assert result["jobs"] == {"total": 0, "by_status": {}}
    assert result["library"] == {"files": 0, "bytes": 0, "unreadable": 0}


def _seed_live(db_session, owner, completed: int, failed: int):
    """Rows at the real clock's now, for the endpoint (which reads it)."""
    finished = datetime.now(timezone.utc) - timedelta(minutes=1)
    job = _job(db_session, owner, created_at=finished - timedelta(minutes=5))
    for _ in range(completed):
        _attempt(db_session, _track(db_session, job, created_at=finished - timedelta(minutes=5)), finished,
                 TrackAttemptOutcome.COMPLETED)
    for _ in range(failed):
        _attempt(db_session, _track(db_session, job, state=TrackState.WAITING), finished,
                 TrackAttemptOutcome.FAILED, TrackErrorType.AUDIO_PROVIDER)
    db_session.commit()


def test_endpoint_answers_the_session_user_and_no_parameter_targets_another(
    authenticated_client, db_session, make_user
):
    me = db_session.query(User).filter(User.email == "allowed@example.com").one()
    bob = make_user("bob@example.com")
    _seed_live(db_session, me, completed=2, failed=0)
    _seed_live(db_session, bob, completed=7, failed=3)

    body = authenticated_client.get("/api/stats/me").json()
    assert body["window"] == "24h"
    assert (body["attempts"]["completed"], body["attempts"]["failed"]) == (2, 0)
    # Nothing in the query string can name somebody else: unknown parameters are ignored,
    # and the answer stays the session user's.
    for query in (
        f"user_id={bob.id}",
        f"user={bob.id}",
        "owner=bob@example.com",
        "view=all",
        "all_users=true",
        "view=others",
    ):
        again = authenticated_client.get(f"/api/stats/me?{query}").json()
        assert (again["attempts"]["completed"], again["attempts"]["failed"]) == (2, 0), query
    # Not a path parameter either.
    assert authenticated_client.get(f"/api/stats/{bob.id}").status_code in (404, 405)


def test_an_admin_reads_their_own_not_the_global_numbers(admin_client, db_session, make_user):
    admin = db_session.query(User).filter(User.email == "admin@example.com").one()
    _seed_live(db_session, admin, completed=1, failed=0)
    _seed_live(db_session, make_user("bob@example.com"), completed=4, failed=2)

    mine = admin_client.get("/api/stats/me?view=all").json()
    assert (mine["attempts"]["completed"], mine["attempts"]["failed"]) == (1, 0)
    everyone = admin_client.get("/api/admin/stats").json()
    assert sum(p["completed"] for p in everyone["network_paths"]) == 5


def test_endpoint_windows_and_offsets(authenticated_client):
    body = authenticated_client.get("/api/stats/me?window=7d&utc_offset_minutes=120").json()
    assert (body["window"], body["utc_offset_minutes"], body["bucket_seconds"]) == ("7d", 120, 86400)
    assert authenticated_client.get("/api/stats/me?window=1y").status_code == 422
    for bad in ("841", "-721", "abc"):
        assert authenticated_client.get(f"/api/stats/me?utc_offset_minutes={bad}").status_code == 422


def test_unauthenticated_gets_401(client):
    assert client.get("/api/stats/me").status_code == 401


def test_endpoint_measures_the_library_after_its_snapshot(authenticated_client, db_session, tmp_path):
    me = db_session.query(User).filter(User.email == "allowed@example.com").one()
    path = tmp_path / "mine.opus"
    path.write_bytes(b"x" * 4321)
    db_session.add(DownloadedTrack(spotify_track_id="smine", file_path=str(path), format="opus"))
    _track(db_session, _job(db_session, me), spotify_id="smine")
    db_session.commit()
    assert authenticated_client.get("/api/stats/me").json()["library"] == {
        "files": 1,
        "bytes": 4321,
        "unreadable": 0,
    }


def test_a_window_switch_can_skip_the_library(authenticated_client, db_session, tmp_path):
    me = db_session.query(User).filter(User.email == "allowed@example.com").one()
    path = tmp_path / "mine.opus"
    path.write_bytes(b"x" * 10)
    db_session.add(DownloadedTrack(spotify_track_id="sskip", file_path=str(path), format="opus"))
    _track(db_session, _job(db_session, me), spotify_id="sskip")
    db_session.commit()
    body = authenticated_client.get("/api/stats/me?window=7d&library=false").json()
    assert body["library"] is None and body["window"] == "7d"
    assert authenticated_client.get("/api/stats/me?window=7d").json()["library"]["files"] == 1
