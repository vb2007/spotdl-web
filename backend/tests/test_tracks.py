import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    DownloadedTrack,
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
from app.services import attempts, proxies, retry


def _aware(dt: datetime) -> datetime:
    # SQLite (used for these in-process tests, see v02/v03 gotchas) round-trips a
    # timestamptz column as a naive datetime; a no-op against real Postgres/psycopg.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _make_track(
    db_session, owner, *, state, scheduled_at=None, attempt_count=0, output_path=None, spotify_track_id="abc123"
):
    job = Job(
        source_url="https://open.spotify.com/track/abc",
        source_type=JobSourceType.TRACK,
        user_id=owner.id,
    )
    db_session.add(job)
    db_session.commit()

    track = Track(
        job_id=job.id,
        spotify_track_id=spotify_track_id,
        song_json={"name": "Song A"},
        state=state,
        scheduled_at=scheduled_at,
        attempt_count=attempt_count,
        output_path=output_path,
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


@pytest.mark.parametrize(
    "state",
    [TrackState.COMPLETED, TrackState.SKIPPED_DUPLICATE, TrackState.CANCELLED, TrackState.LOOKUP_FAILED],
)
def test_cancel_track_refuses_a_terminal_state_with_409(authenticated_client, db_session, owner, state):
    """v56 (A2): a terminal track, `lookup_failed` included (the UI never offers cancel on
    it), answers 409 with its state and stays as it is. Before v56 a `lookup_failed` track
    was turned `cancelled`, and the other terminal states were a silent 200."""
    track = _make_track(db_session, owner, state=state)

    response = authenticated_client.delete(f"/api/tracks/{track.id}")

    assert response.status_code == 409
    assert response.json()["code"] == "track_not_cancellable"
    assert response.json()["params"] == {"state": state.value}
    assert db_session.get(Track, track.id).state == state


def test_get_track_returns_the_track_with_its_job_summary(authenticated_client, db_session, owner):
    """v56 (A3)."""
    track = _make_track(
        db_session, owner, state=TrackState.WAITING, scheduled_at=datetime.now(timezone.utc), attempt_count=2
    )

    response = authenticated_client.get(f"/api/tracks/{track.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(track.id)
    assert body["state"] == "waiting"
    assert body["title"] == "Song A"
    assert body["attempt_count"] == 2
    assert body["job"] == {
        "id": str(track.job_id),
        "source_url": "https://open.spotify.com/track/abc",
        "source_type": "track",
        "owner_email": owner.email,
        "owner_username": owner.username,
        "title": "Song A",
    }


def test_get_unknown_track_returns_404_and_needs_a_session(client, authenticated_client):
    assert authenticated_client.get(f"/api/tracks/{uuid.uuid4()}").status_code == 404
    authenticated_client.cookies.clear()
    assert authenticated_client.get(f"/api/tracks/{uuid.uuid4()}").status_code == 401


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


def test_a_non_admins_second_retry_now_in_one_step_gets_429(authenticated_client, db_session, owner):
    """v56 (A8, #69): once per ladder step. The first press dispatches without resetting
    the step; the second, while still at that step, is refused with the time left until
    the track is tried anyway."""
    track = _make_track(
        db_session, owner, state=TrackState.WAITING, scheduled_at=datetime.now(timezone.utc) + timedelta(hours=4), attempt_count=2
    )

    first = authenticated_client.post(f"/api/tracks/{track.id}/retry")
    assert first.status_code == 200
    assert first.json()["attempt_count"] == 2
    # Not dispatched yet (the breaker holds it, or beat's next pass hasn't come), but due.
    db_session.refresh(track)
    track.scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    db_session.commit()

    second = authenticated_client.post(f"/api/tracks/{track.id}/retry")

    assert second.status_code == 429
    assert second.json()["code"] == "retry_cooldown"
    assert 595 <= second.json()["params"]["retry_after"] <= 600
    assert second.json()["params"]["paused"] is False
    assert second.headers["retry-after"] == str(second.json()["params"]["retry_after"])
    db_session.expire_all()
    assert _aware(db_session.get(Track, track.id).scheduled_at) > datetime.now(timezone.utc) + timedelta(minutes=9)


def test_a_non_admin_may_retry_now_again_at_the_next_step(authenticated_client, db_session, owner):
    track = _make_track(db_session, owner, state=TrackState.WAITING, scheduled_at=datetime.now(timezone.utc), attempt_count=2)
    assert authenticated_client.post(f"/api/tracks/{track.id}/retry").status_code == 200
    # The dispatched attempt failed: the ladder moved on a step (retry.record_failure).
    db_session.refresh(track)
    track.attempt_count = 3
    track.scheduled_at = datetime.now(timezone.utc) + timedelta(hours=12)
    db_session.commit()

    assert authenticated_client.post(f"/api/tracks/{track.id}/retry").status_code == 200


def test_retry_cooldown_counts_to_the_breakers_clear_when_that_is_later(authenticated_client, db_session, owner):
    track = _make_track(db_session, owner, state=TrackState.WAITING, scheduled_at=datetime.now(timezone.utc), attempt_count=1)
    assert authenticated_client.post(f"/api/tracks/{track.id}/retry").status_code == 200
    retry.get_worker_state(db_session).breaker_tripped_until = datetime.now(timezone.utc) + timedelta(hours=2)
    db_session.commit()

    second = authenticated_client.post(f"/api/tracks/{track.id}/retry")

    assert second.status_code == 429
    assert 2 * 3600 - 5 <= second.json()["params"]["retry_after"] <= 2 * 3600


def test_retry_cooldown_says_when_downloads_are_paused(authenticated_client, db_session, owner):
    """A manual pause has no end time, so the 429 says so instead of "the next pass"."""
    track = _make_track(db_session, owner, state=TrackState.WAITING, scheduled_at=datetime.now(timezone.utc), attempt_count=1)
    assert authenticated_client.post(f"/api/tracks/{track.id}/retry").status_code == 200
    retry.get_worker_state(db_session).paused = True
    db_session.commit()

    second = authenticated_client.post(f"/api/tracks/{track.id}/retry")

    assert second.status_code == 429
    assert second.json()["params"]["paused"] is True


@pytest.mark.parametrize("track_state", [TrackState.LOOKUP_FAILED, TrackState.WAITING])
def test_retry_refuses_a_track_whose_job_was_cancelled(authenticated_client, db_session, owner, track_state):
    """v56 (A2): a job cancel leaves a not-found track as it is; retrying it must not start a
    download under a job that says cancelled (and can no longer be cancelled)."""
    track = _make_track(db_session, owner, state=track_state)
    db_session.get(Job, track.job_id).state = JobState.CANCELLED
    db_session.commit()

    response = authenticated_client.post(f"/api/tracks/{track.id}/retry")

    assert response.status_code == 409
    assert response.json()["code"] == "job_cancelled"
    db_session.expire_all()
    assert db_session.get(Track, track.id).state == track_state


def test_a_cancel_then_a_retry_of_its_not_found_track_is_refused_end_to_end(authenticated_client, db_session, owner):
    track = _make_track(db_session, owner, state=TrackState.LOOKUP_FAILED)
    waiting = Track(job_id=track.job_id, spotify_track_id="w", song_json={"name": "W"}, state=TrackState.WAITING)
    db_session.add(waiting)
    db_session.get(Job, track.job_id).state = JobState.EXPANDED
    db_session.commit()

    assert authenticated_client.delete(f"/api/jobs/{track.job_id}").status_code == 200
    assert authenticated_client.post(f"/api/tracks/{track.id}/retry").status_code == 409


def test_an_admins_retry_now_is_unrestricted(admin_client, db_session, make_user):
    track = _make_track(
        db_session, make_user("owner@example.com"), state=TrackState.WAITING, scheduled_at=datetime.now(timezone.utc) + timedelta(hours=4), attempt_count=2
    )

    answers = [admin_client.post(f"/api/tracks/{track.id}/retry").status_code for _ in range(3)]

    assert answers == [200, 200, 200]
    db_session.expire_all()
    assert db_session.get(Track, track.id).retry_now_step is None


def test_a_non_admins_lookup_failed_retry_is_unrestricted(authenticated_client, db_session, owner):
    """The rule covers skipping a ladder wait. A not-found has none; retrying it is how a
    user asks for another search, so it isn't limited (and it doesn't use up the step)."""
    track = _make_track(db_session, owner, state=TrackState.LOOKUP_FAILED, attempt_count=2)
    assert authenticated_client.post(f"/api/tracks/{track.id}/retry").status_code == 200
    db_session.expire_all()
    assert db_session.get(Track, track.id).retry_now_step is None


def test_two_retry_now_presses_at_once_dispatch_once_on_real_connections(committed_db, monkeypatch):
    """v56 (A8) on two real connections: the second press waits on the first's row lock, then
    sees the step used and answers 429. Without the lock both read the step unused."""
    from concurrency import Gate, Thread, blocked_or_done
    from sqlalchemy import event

    from app.errors import ApiError
    from app.models import User
    from app.routers import tracks as tracks_router

    monkeypatch.setattr(tracks_router.events, "publish_track_event", lambda *a, **kw: None)
    with committed_db() as db:
        user = User(email="owner@example.com", is_admin=False)
        db.add(user)
        db.flush()
        job = Job(source_url="https://open.spotify.com/track/abc", source_type=JobSourceType.TRACK, user_id=user.id)
        db.add(job)
        db.flush()
        track = Track(
            job_id=job.id,
            spotify_track_id="race",
            song_json={"name": "Race"},
            state=TrackState.WAITING,
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
            attempt_count=1,
        )
        db.add(track)
        db.commit()
        user_id, track_id = user.id, track.id
    gate = Gate("the first retry-now, before its commit")

    def press(gated: bool):
        with committed_db() as db:
            if gated:
                event.listen(db, "before_commit", gate, once=True)
            return tracks_router.retry_track(track_id, db=db, user=db.get(User, user_id))

    first = Thread(press, True, name="first press")
    gate.wait_reached()
    second = Thread(press, False, name="second press")
    held_off = blocked_or_done(second)
    gate.open()

    assert first.join()["state"] == "waiting"
    with pytest.raises(ApiError) as refused:
        second.join()
    assert held_off == "blocked"
    assert refused.value.status_code == 429
    assert refused.value.code == "retry_cooldown"


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


def test_list_track_attempts_returns_history_oldest_first_with_expected_fields(
    authenticated_client, db_session, owner
):
    track = _make_track(db_session, owner, state=TrackState.WAITING, attempt_count=2)
    # Credentialed on purpose: v35 (b)'s label must never carry user:pass.
    proxy = Proxy(url="http://user:s3cret@10.0.0.7:8080", source=ProxySource.FILE, enabled=True)
    db_session.add(proxy)
    db_session.commit()

    now = datetime.now(timezone.utc)
    db_session.add(
        TrackAttempt(
            track_id=track.id,
            attempt_number=1,
            started_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=2) + timedelta(seconds=12.5),
            outcome=TrackAttemptOutcome.FAILED,
            error_type=TrackErrorType.AUDIO_PROVIDER,
            error_message="provider exploded",
            network_path=NetworkPath.DIRECT_IPV4,
        )
    )
    db_session.commit()
    # Through the real write path: it stores the proxy's label with the row (v56, A4).
    attempts.record_attempt(
        db_session,
        track.id,
        now - timedelta(hours=1),
        now - timedelta(hours=1),
        TrackAttemptOutcome.FAILED,
        proxy_id=proxy.id,
        error_message="proxy also failed",
        network_path=NetworkPath.PROXY,
    )
    db_session.commit()

    response = authenticated_client.get(f"/api/tracks/{track.id}/attempts")

    assert response.status_code == 200
    body = response.json()
    assert [row["attempt_number"] for row in body] == [1, 2]
    assert body[0]["proxy_id"] is None
    assert body[1]["proxy_id"] == str(proxy.id)
    assert body[1]["error_message"] == "proxy also failed"
    assert body[1]["outcome"] == "failed"
    # v35 (b)
    assert body[0]["network_path"] == "direct-ipv4"
    assert body[0]["error_type"] == "audio_provider"
    assert body[0]["duration_seconds"] == 12.5
    assert body[0]["proxy_label"] is None
    assert body[1]["network_path"] == "proxy"
    assert body[1]["proxy_label"] == "http://10.0.0.7:8080"
    assert "s3cret" not in response.text
    assert "user:" not in response.text


def _proxied_attempt(db_session, owner, url: str):
    track = _make_track(db_session, owner, state=TrackState.WAITING, attempt_count=1)
    proxy = Proxy(url=url, source=ProxySource.MANUAL, enabled=True)
    db_session.add(proxy)
    db_session.commit()
    track.used_proxy_id = proxy.id
    now = datetime.now(timezone.utc)
    attempts.record_attempt(
        db_session, track.id, now, now, TrackAttemptOutcome.FAILED, proxy_id=proxy.id, network_path=NetworkPath.PROXY
    )
    db_session.commit()
    return track, proxy


def test_record_attempt_stores_the_redacted_proxy_label(db_session, owner):
    """v56 (A4): captured at write time, without the credential."""
    track, _proxy = _proxied_attempt(db_session, owner, "http://user:s3cret@10.0.0.7:8080")
    row = db_session.query(TrackAttempt).filter(TrackAttempt.track_id == track.id).one()
    assert row.proxy_label == "http://10.0.0.7:8080"


def test_record_attempt_labels_an_unparseable_proxy_url_plainly(db_session, owner):
    # sync_from_file doesn't validate URLs; a bad port must not fail the attempt's write.
    track, _proxy = _proxied_attempt(db_session, owner, "http://user:s3cret@10.0.0.7:notaport")
    row = db_session.query(TrackAttempt).filter(TrackAttempt.track_id == track.id).one()
    assert row.proxy_label == "proxy"


@pytest.mark.parametrize("via", ["track", "job"])
@pytest.mark.parametrize("state", [TrackState.WAITING, TrackState.DOWNLOADING])
def test_cancel_keeps_the_proxy_only_of_a_download_still_running(authenticated_client, db_session, owner, state, via):
    """v56 (A4): a cancel lets a running download go on to its end, so a `downloading` track
    keeps its used_proxy_id (proxies.proxy_in_use holds the proxy's delete for it). Any other
    track's is an ended attempt's, and keeping it would hold up that proxy's delete for the
    whole stale-track window."""
    track = _make_track(db_session, owner, state=state, attempt_count=1)
    proxy = Proxy(url="http://10.0.0.33:8080", source=ProxySource.MANUAL, enabled=True)
    db_session.add(proxy)
    db_session.commit()
    track.used_proxy_id = proxy.id
    db_session.commit()

    path = f"/api/tracks/{track.id}" if via == "track" else f"/api/jobs/{track.job_id}"
    assert authenticated_client.delete(path).status_code == 200

    db_session.expire_all()
    cancelled = db_session.get(Track, track.id)
    assert cancelled.state == TrackState.CANCELLED
    assert cancelled.used_proxy_id == (proxy.id if state == TrackState.DOWNLOADING else None)
    assert proxies.proxy_in_use(db_session, db_session.get(Proxy, proxy.id), datetime.now(timezone.utc)) is (
        state == TrackState.DOWNLOADING
    )


def test_cancel_keeps_the_proxy_of_a_reclaimed_download_still_running(authenticated_client, db_session, owner):
    """v56 (A4) on v55: beat's reclaim leaves a still-running download's track `waiting`. A
    cancel then must keep its proxy, or the proxy could be deleted under that download."""
    track = _make_track(db_session, owner, state=TrackState.DOWNLOADING, attempt_count=1)
    proxy = Proxy(url="http://10.0.0.34:8080", source=ProxySource.MANUAL, enabled=True)
    db_session.add(proxy)
    db_session.commit()
    track.used_proxy_id = proxy.id
    track.state = TrackState.WAITING
    now = datetime.now(timezone.utc)
    attempts.record_attempt(
        db_session, track.id, now, now, TrackAttemptOutcome.FAILED, error_message=f"{attempts.RECLAIM_PREFIX}stuck"
    )
    db_session.commit()

    assert authenticated_client.delete(f"/api/tracks/{track.id}").status_code == 200

    db_session.expire_all()
    assert db_session.get(Track, track.id).used_proxy_id == proxy.id
    assert proxies.proxy_in_use(db_session, db_session.get(Proxy, proxy.id), datetime.now(timezone.utc)) is True


def test_a_superseded_reclaim_row_takes_the_proxy_label(db_session, owner):
    """v56 (A4) with v55 (E3): a still-running download's outcome rewrites beat's reclaim row
    in place, and that rewrite names the proxy too, not only a freshly added row."""
    track = _make_track(db_session, owner, state=TrackState.WAITING, attempt_count=1)
    proxy = Proxy(url="http://user:s3cret@10.0.0.9:8080", source=ProxySource.MANUAL, enabled=True)
    db_session.add(proxy)
    db_session.commit()
    now = datetime.now(timezone.utc)
    entry = attempts.latest_attempt_number(db_session, track.id)
    attempts.record_attempt(
        db_session, track.id, now, now, TrackAttemptOutcome.FAILED, error_message=f"{attempts.RECLAIM_PREFIX}stuck"
    )
    attempts.record_attempt(
        db_session,
        track.id,
        now,
        now,
        TrackAttemptOutcome.COMPLETED,
        proxy_id=proxy.id,
        network_path=NetworkPath.PROXY,
        supersede_reclaim_after=entry,
    )
    db_session.commit()

    row = db_session.query(TrackAttempt).filter(TrackAttempt.track_id == track.id).one()
    assert (row.outcome, row.proxy_id, row.proxy_label) == (
        TrackAttemptOutcome.COMPLETED,
        proxy.id,
        "http://10.0.0.9:8080",
    )


def test_deleting_a_used_proxy_keeps_its_label_on_the_history(admin_client, db_session, make_user):
    """v56 (A4): before v56 this delete was a 500 (the FKs had no ON DELETE). Now the
    references go NULL and every attempt keeps naming the proxy it went through."""
    track, proxy = _proxied_attempt(db_session, make_user("owner@example.com"), "http://user:s3cret@10.0.0.7:8080")

    assert admin_client.delete(f"/api/proxies/{proxy.id}").status_code == 204

    db_session.expire_all()
    assert db_session.get(Proxy, proxy.id) is None
    assert db_session.get(Track, track.id).used_proxy_id is None
    history = admin_client.get(f"/api/tracks/{track.id}/attempts").json()
    assert [(row["proxy_id"], row["proxy_label"]) for row in history] == [(None, "http://10.0.0.7:8080")]


def test_list_track_attempts_empty_for_a_track_with_no_history(authenticated_client, db_session, owner):
    track = _make_track(db_session, owner, state=TrackState.PENDING)

    response = authenticated_client.get(f"/api/tracks/{track.id}/attempts")

    assert response.status_code == 200
    assert response.json() == []


def test_download_track_file_returns_accel_redirect_and_disposition(authenticated_client, db_session, owner):
    track = _make_track(
        db_session,
        owner,
        state=TrackState.COMPLETED,
        output_path="/downloads/Daft Punk - One More Time.mp3",
    )

    response = authenticated_client.get(f"/api/tracks/{track.id}/file")

    assert response.status_code == 200
    assert response.headers["x-accel-redirect"] == "/internal-downloads/Daft%20Punk%20-%20One%20More%20Time.mp3"
    assert response.headers["content-disposition"] == (
        'attachment; filename="Daft Punk - One More Time.mp3"; '
        "filename*=UTF-8''Daft%20Punk%20-%20One%20More%20Time.mp3"
    )


def test_download_track_file_encodes_non_ascii_filename(authenticated_client, db_session, owner):
    track = _make_track(
        db_session,
        owner,
        state=TrackState.COMPLETED,
        output_path="/downloads/Björk - Jóga.mp3",
    )

    response = authenticated_client.get(f"/api/tracks/{track.id}/file")

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert 'filename="Bjrk - Jga.mp3"' in disposition
    assert "filename*=UTF-8''Bj%C3%B6rk%20-%20J%C3%B3ga.mp3" in disposition


def test_download_track_file_strips_control_characters_from_ascii_fallback(
    authenticated_client, db_session, owner
):
    """Fresh-eyes review finding: a bare `encode('ascii', 'ignore')` lets a literal CR/LF
    in the (DB-sourced, not-actually-trusted) filename straight through into the
    `Content-Disposition` header, which real ASGI servers reject with a 500 instead of the
    clean response this endpoint is supposed to guarantee either way."""
    track = _make_track(
        db_session,
        owner,
        state=TrackState.COMPLETED,
        output_path="/downloads/Evil\r\nX-Injected: yes.mp3",
    )

    response = authenticated_client.get(f"/api/tracks/{track.id}/file")

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "\r" not in disposition
    assert "\n" not in disposition
    assert 'filename="EvilX-Injected: yes.mp3"' in disposition


def test_download_track_file_prefers_ledger_path_over_track_output_path(authenticated_client, db_session, owner):
    """The ledger is what v28's library move will repoint (CLAUDE.md's master-v3
    invariants) -- this proves the endpoint reads from there first, which is what lets it
    keep working unchanged once a move actually happens."""
    track = _make_track(
        db_session,
        owner,
        state=TrackState.COMPLETED,
        output_path="/downloads/stale/Song.mp3",
        spotify_track_id="moved-track",
    )
    db_session.add(
        DownloadedTrack(
            spotify_track_id="moved-track",
            file_path="/downloads/moved/Song.mp3",
            format="mp3",
        )
    )
    db_session.commit()

    response = authenticated_client.get(f"/api/tracks/{track.id}/file")

    assert response.status_code == 200
    assert response.headers["x-accel-redirect"] == "/internal-downloads/moved/Song.mp3"


def test_download_track_file_head_matches_get_without_a_body(authenticated_client, db_session, owner):
    """v35 (e): the frontend probes with HEAD before starting a real browser download."""
    track = _make_track(
        db_session,
        owner,
        state=TrackState.COMPLETED,
        output_path="/downloads/Daft Punk - One More Time.mp3",
    )

    head = authenticated_client.head(f"/api/tracks/{track.id}/file")
    get = authenticated_client.get(f"/api/tracks/{track.id}/file")

    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["x-accel-redirect"] == get.headers["x-accel-redirect"]
    assert head.headers["content-disposition"] == get.headers["content-disposition"]

    missing = _make_track(db_session, owner, state=TrackState.WAITING)
    assert authenticated_client.head(f"/api/tracks/{missing.id}/file").status_code == 404


def test_download_track_file_404_when_track_never_had_a_file(authenticated_client, db_session, owner):
    track = _make_track(db_session, owner, state=TrackState.WAITING)

    response = authenticated_client.get(f"/api/tracks/{track.id}/file")

    assert response.status_code == 404


def test_download_track_file_still_downloadable_when_job_archived(authenticated_client, db_session, owner):
    """v27's plan: availability keys on the file existing at its recorded path, never on
    archived_at -- a job archived by v19's retention sweep still has its file."""
    track = _make_track(
        db_session, owner, state=TrackState.COMPLETED, output_path="/downloads/Song.mp3"
    )
    job = db_session.get(Job, track.job_id)
    job.archived_at = datetime.now(timezone.utc)
    db_session.commit()

    response = authenticated_client.get(f"/api/tracks/{track.id}/file")

    assert response.status_code == 200


def test_download_track_file_rejects_path_outside_allowed_root(authenticated_client, db_session, owner):
    """A corrupted/tampered output_path must never turn into an X-Accel-Redirect outside
    the downloads root -- this endpoint turns that column into an authorization boundary
    (v27's plan)."""
    track = _make_track(db_session, owner, state=TrackState.COMPLETED, output_path="/etc/passwd")

    response = authenticated_client.get(f"/api/tracks/{track.id}/file")

    assert response.status_code == 404


def test_download_track_file_rejects_traversal_via_dotdot(authenticated_client, db_session, owner):
    track = _make_track(
        db_session, owner, state=TrackState.COMPLETED, output_path="/downloads/../secrets/leak.mp3"
    )

    response = authenticated_client.get(f"/api/tracks/{track.id}/file")

    assert response.status_code == 404


def test_download_track_file_serves_a_moved_track_via_library_root(authenticated_client, db_session, owner):
    """v28: a track whose ledger row was repointed to the sorted library root (not the
    downloads root) must still resolve -- CLAUDE.md's "Sort & move vs. file downloads"
    invariant. Uses the default library_target_dir (AppSettings seeds it on first read)
    rather than overriding it, since this endpoint must work against that default."""
    from app.services import app_settings

    library_root = app_settings.DEFAULT_LIBRARY_TARGET_DIR
    track = _make_track(
        db_session,
        owner,
        state=TrackState.COMPLETED,
        output_path=f"{library_root}/Daft Punk - Discovery - (2001)/01 - One More Time.mp3",
    )

    response = authenticated_client.get(f"/api/tracks/{track.id}/file")

    assert response.status_code == 200
    assert (
        response.headers["x-accel-redirect"]
        == "/internal-library/Daft%20Punk%20-%20Discovery%20-%20%282001%29/01%20-%20One%20More%20Time.mp3"
    )


def test_download_unknown_track_file_returns_404(authenticated_client, db_session):
    assert authenticated_client.get(f"/api/tracks/{uuid.uuid4()}/file").status_code == 404


def test_download_track_file_requires_session(client):
    assert client.get(f"/api/tracks/{uuid.uuid4()}/file").status_code == 401


def test_attempt_with_a_malformed_proxy_url_still_lists(authenticated_client, db_session, owner):
    """v35 (b): proxies.redact() raises on a bad port; the history must still render."""
    track = _make_track(db_session, owner, state=TrackState.WAITING)
    proxy = Proxy(url="http://10.0.0.7:notaport", source=ProxySource.FILE, enabled=True)
    db_session.add(proxy)
    db_session.commit()
    now = datetime.now(timezone.utc)
    attempts.record_attempt(
        db_session, track.id, now, now, TrackAttemptOutcome.FAILED, proxy_id=proxy.id, network_path=NetworkPath.PROXY
    )
    db_session.commit()

    response = authenticated_client.get(f"/api/tracks/{track.id}/attempts")

    assert response.status_code == 200
    assert response.json()[0]["proxy_label"] == "proxy"


def test_a_proxy_deleted_mid_attempt_still_lets_the_attempt_commit_on_real_connections(committed_db):
    """v56 (A4): with ON DELETE SET NULL an admin can delete a manual proxy while a download
    runs through it. download_track's session already loaded that proxy (picking it), so the
    attempt row it writes afterwards must not name the gone proxy (a ForeignKeyViolation
    would roll back the whole commit, a completed download's ledger row with it)."""
    from app.models import User

    with committed_db() as db:
        user = User(email="owner@example.com", is_admin=False)
        db.add(user)
        db.flush()
        job = Job(source_url="https://open.spotify.com/track/abc", source_type=JobSourceType.TRACK, user_id=user.id)
        db.add(job)
        db.flush()
        track = Track(job_id=job.id, spotify_track_id="mid", song_json={"name": "Mid"}, state=TrackState.DOWNLOADING)
        proxy = Proxy(url="http://u:p@10.0.0.9:8080", source=ProxySource.MANUAL, enabled=True)
        db.add_all([track, proxy])
        db.commit()
        track_id, proxy_id = track.id, proxy.id

    worker = committed_db()
    try:
        worker.get(Proxy, proxy_id)  # picked: in the worker session's identity map
        worker.get(Track, track_id).used_proxy_id = proxy_id
        worker.commit()  # expires both
        with committed_db() as admin:  # the admin's delete, while the download runs
            admin.delete(admin.get(Proxy, proxy_id))
            admin.commit()
        now = datetime.now(timezone.utc)
        attempts.record_attempt(
            worker, track_id, now, now, TrackAttemptOutcome.COMPLETED, proxy_id=proxy_id, network_path=NetworkPath.PROXY
        )
        worker.commit()
    finally:
        worker.close()

    with committed_db() as db:
        row = db.query(TrackAttempt).filter(TrackAttempt.track_id == track_id).one()
        assert (row.proxy_id, row.proxy_label, row.network_path) == (None, None, NetworkPath.PROXY)
        assert db.get(Track, track_id).used_proxy_id is None


def test_a_proxy_delete_waits_for_an_attempt_being_recorded_on_real_connections(committed_db):
    """v56 (A4): record_attempt reads the proxy locked (FOR NO KEY UPDATE), so an admin's delete landing
    while the attempt's transaction is open waits for its commit, then nulls the new row's
    proxy_id; the row keeps the label (no ForeignKeyViolation, no lost download)."""
    from concurrency import Gate, Thread, blocked_or_done
    from sqlalchemy import event

    from app.models import User

    with committed_db() as db:
        user = User(email="owner@example.com", is_admin=False)
        db.add(user)
        db.flush()
        job = Job(source_url="https://open.spotify.com/track/abc", source_type=JobSourceType.TRACK, user_id=user.id)
        db.add(job)
        db.flush()
        track = Track(job_id=job.id, spotify_track_id="lock", song_json={"name": "Lock"}, state=TrackState.DOWNLOADING)
        proxy = Proxy(url="http://u:p@10.0.0.8:8080", source=ProxySource.MANUAL, enabled=True)
        db.add_all([track, proxy])
        db.commit()
        track_id, proxy_id = track.id, proxy.id
    gate = Gate("the attempt, recorded, before its commit")

    def record():
        with committed_db() as db:
            event.listen(db, "before_commit", gate, once=True)
            now = datetime.now(timezone.utc)
            attempts.record_attempt(
                db, track_id, now, now, TrackAttemptOutcome.COMPLETED, proxy_id=proxy_id, network_path=NetworkPath.PROXY
            )
            db.commit()

    recorder = Thread(record, name="download_track's attempt")
    gate.wait_reached()

    def delete():
        with committed_db() as db:
            db.delete(db.get(Proxy, proxy_id))
            db.commit()

    deleter = Thread(delete, name="admin's proxy delete")
    held_off = blocked_or_done(deleter)
    gate.open()
    recorder.join()
    deleter.join()

    assert held_off == "blocked"
    with committed_db() as db:
        row = db.query(TrackAttempt).filter(TrackAttempt.track_id == track_id).one()
        assert (row.proxy_id, row.proxy_label) == (None, "http://10.0.0.8:8080")


def test_an_attempt_written_without_a_label_still_shows_its_existing_proxy(authenticated_client, db_session, owner):
    """v56 (A4): an old worker still running during the deploy writes attempts after the
    migration's backfill, without a label; while their proxy exists, the history names it."""
    track = _make_track(db_session, owner, state=TrackState.WAITING)
    proxy = Proxy(url="http://user:s3cret@10.0.0.40:8080", source=ProxySource.MANUAL, enabled=True)
    db_session.add(proxy)
    db_session.commit()
    now = datetime.now(timezone.utc)
    db_session.add(
        TrackAttempt(
            track_id=track.id, attempt_number=1, started_at=now, finished_at=now,
            outcome=TrackAttemptOutcome.FAILED, proxy_id=proxy.id, network_path=NetworkPath.PROXY,
        )
    )
    db_session.commit()

    response = authenticated_client.get(f"/api/tracks/{track.id}/attempts")

    assert response.json()[0]["proxy_label"] == "http://10.0.0.40:8080"
    assert "s3cret" not in response.text
