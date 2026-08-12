import uuid
from datetime import datetime, timedelta, timezone

from app.models import Job, JobSourceType, Track, TrackState
from app.services import retry


def _aware(dt: datetime) -> datetime:
    # SQLite (used for these in-process tests, see v02/v03 gotchas) round-trips a
    # timestamptz column as a naive datetime; a no-op against real Postgres/psycopg.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _make_track(db_session, owner, *, state, scheduled_at=None, attempt_count=0):
    job = Job(
        source_url="https://open.spotify.com/track/abc",
        source_type=JobSourceType.TRACK,
        user_id=owner.id,
    )
    db_session.add(job)
    db_session.commit()

    track = Track(
        job_id=job.id,
        spotify_track_id="abc123",
        song_json={"name": "Song A"},
        state=state,
        scheduled_at=scheduled_at,
        attempt_count=attempt_count,
    )
    db_session.add(track)
    db_session.commit()
    return track


def test_cancel_track_marks_cancelled_and_clears_schedule(authenticated_client, db_session, owner):
    track = _make_track(
        db_session, owner, state=TrackState.WAITING, scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )

    response = authenticated_client.delete(f"/api/tracks/{track.id}")

    assert response.status_code == 200
    assert response.json()["state"] == "cancelled"
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.CANCELLED
    assert updated.scheduled_at is None


def test_cancel_track_is_a_noop_on_terminal_states(authenticated_client, db_session, owner):
    track = _make_track(db_session, owner, state=TrackState.COMPLETED)

    response = authenticated_client.delete(f"/api/tracks/{track.id}")

    assert response.status_code == 200
    assert response.json()["state"] == "completed"
    assert db_session.get(Track, track.id).state == TrackState.COMPLETED


def test_cancel_unknown_track_returns_404(authenticated_client, db_session):
    assert authenticated_client.delete(f"/api/tracks/{uuid.uuid4()}").status_code == 404


def test_retry_track_resets_schedule_and_dispatches_when_breaker_clear(authenticated_client, db_session, owner):
    track = _make_track(
        db_session,
        owner,
        state=TrackState.WAITING,
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=12),
        attempt_count=2,
    )

    response = authenticated_client.post(f"/api/tracks/{track.id}/retry")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "waiting"
    assert body["breaker_held"] is False
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING
    assert _aware(updated.scheduled_at) <= datetime.now(timezone.utc) + timedelta(seconds=5)


def test_retry_track_flips_lookup_failed_back_to_waiting(authenticated_client, db_session, owner):
    track = _make_track(db_session, owner, state=TrackState.LOOKUP_FAILED, scheduled_at=None)

    response = authenticated_client.post(f"/api/tracks/{track.id}/retry")

    assert response.status_code == 200
    assert response.json()["state"] == "waiting"
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING
    assert updated.scheduled_at is not None


def test_retry_track_held_while_breaker_tripped(authenticated_client, db_session, owner):
    track = _make_track(db_session, owner, state=TrackState.WAITING)

    worker_state = retry.get_worker_state(db_session)
    worker_state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.commit()

    response = authenticated_client.post(f"/api/tracks/{track.id}/retry")

    assert response.status_code == 200
    body = response.json()
    assert body["breaker_held"] is True
    # scheduled_at is still reset to now -- the breaker gate lives in dispatch_due_tracks,
    # not here -- so a retry immediately becomes eligible the instant the breaker clears.
    updated = db_session.get(Track, track.id)
    assert updated.state == TrackState.WAITING


def test_retry_track_rejects_non_retryable_states(authenticated_client, db_session, owner):
    track = _make_track(db_session, owner, state=TrackState.DOWNLOADING)

    response = authenticated_client.post(f"/api/tracks/{track.id}/retry")

    assert response.status_code == 409


def test_retry_track_rejects_when_job_is_archived(authenticated_client, db_session, owner):
    """v20 gap: archiving is only ever reachable once a job is settled/failed/cancelled
    (archive._ARCHIVABLE_LIFECYCLES), none of which can have a waiting/lookup_failed
    track -- except by reviving one right back through this exact endpoint. Without this
    gate, a track inside an archived (soft-deleted-from-view) job could still get
    dispatched for a real download by the real running beat, silently breaking "archived
    means settled, not just hidden.\""""
    track = _make_track(db_session, owner, state=TrackState.LOOKUP_FAILED, scheduled_at=None)
    job = db_session.get(Job, track.job_id)
    job.archived_at = datetime.now(timezone.utc)
    db_session.commit()

    response = authenticated_client.post(f"/api/tracks/{track.id}/retry")

    assert response.status_code == 409
    assert db_session.get(Track, track.id).state == TrackState.LOOKUP_FAILED


def test_retry_unknown_track_returns_404(authenticated_client, db_session):
    assert authenticated_client.post(f"/api/tracks/{uuid.uuid4()}/retry").status_code == 404


def test_tracks_endpoints_require_session(client):
    assert client.delete(f"/api/tracks/{uuid.uuid4()}").status_code == 401
    assert client.post(f"/api/tracks/{uuid.uuid4()}/retry").status_code == 401
    assert client.get("/api/tracks").status_code == 401


def test_list_tracks_returns_every_track_across_every_job_in_one_call(authenticated_client, db_session, owner):
    a = _make_track(db_session, owner, state=TrackState.WAITING)
    b = _make_track(db_session, owner, state=TrackState.COMPLETED)

    response = authenticated_client.get("/api/tracks")

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["items"]}
    assert ids == {str(a.id), str(b.id)}
