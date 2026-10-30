"""v63: watched jobs (beat's re-expansion under the hourly cap), expand_job's re-expand mode,
"check now" (`POST /api/jobs/{id}/reexpand`), `PUT /api/jobs/{id}/watch` and "retry failed"
(`POST /api/jobs/{id}/retry-failed`)."""

import time
from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.models import (
    Job,
    JobSourceType,
    JobState,
    Track,
    TrackAttempt,
    TrackAttemptOutcome,
    TrackState,
    User,
)
from app.routers import jobs as jobs_router
from app.services import events, expansion, job_status, retry, watch
from app.tasks import beat as beat_task
from app.tasks import expand as expand_task


class _FakeMarkers:
    """The two commands watch.py's run marker uses, with real expiry."""

    def __init__(self) -> None:
        self.values: dict[str, tuple[str, float]] = {}

    def set(self, key, value, nx=False, ex=None):
        if key in self.values and self.values[key][1] > time.monotonic():
            if nx:
                return None
        self.values[key] = (value, time.monotonic() + (ex or 10**9))
        return True

    def get(self, key):
        held = self.values.get(key)
        return None if held is None or held[1] <= time.monotonic() else held[0].encode()

    def delete(self, key):
        return int(self.values.pop(key, None) is not None)


@pytest.fixture(autouse=True)
def markers(monkeypatch) -> _FakeMarkers:
    fake = _FakeMarkers()
    monkeypatch.setattr(watch, "_redis", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _quiet_events(monkeypatch):
    """No test here reaches the stack's Redis through a publish."""
    monkeypatch.setattr(events, "publish", lambda *args, **kwargs: None)
    monkeypatch.setattr(job_status, "publish_change", lambda *args, **kwargs: None)
    monkeypatch.setattr(job_status, "publish_changes", lambda *args, **kwargs: None)


@pytest.fixture()
def sent_expansions(monkeypatch) -> list:
    sent = []

    def fake_delay(job_id, reexpand=False, marker=None):
        sent.append((job_id, reexpand))

    monkeypatch.setattr(expand_task.expand_job, "delay", fake_delay)
    return sent


@pytest.fixture()
def sent_downloads(monkeypatch) -> list:
    sent = []
    monkeypatch.setattr(expand_task.download_track, "delay", lambda track_id: sent.append(track_id))
    return sent


class _NonClosingSession:
    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


class _FakeSong:
    def __init__(self, song_id):
        self.song_id = song_id
        self.json = {"name": f"Song {song_id}", "song_id": song_id}


def _user(db_session, email="owner@example.com", *, is_admin=False) -> User:
    user = db_session.query(User).filter(User.email == email).one_or_none()
    if user is None:
        user = User(email=email, is_admin=is_admin)
        db_session.add(user)
        db_session.flush()
    return user


def _job(
    db_session,
    user,
    *,
    source_type=JobSourceType.PLAYLIST,
    state=JobState.EXPANDED,
    track_ids=(),
    track_state=TrackState.COMPLETED,
    **fields,
) -> Job:
    job = Job(
        source_url=f"https://open.spotify.com/{source_type.value}/x",
        source_type=source_type,
        state=state,
        user_id=user.id,
        **fields,
    )
    db_session.add(job)
    db_session.flush()
    for spotify_id in track_ids:
        db_session.add(
            Track(job_id=job.id, spotify_track_id=spotify_id, song_json={"name": spotify_id}, state=track_state)
        )
    db_session.commit()
    return job


def _job_track_ids(db_session, job) -> list[str]:
    db_session.expire_all()
    return sorted(t.spotify_track_id for t in db_session.query(Track).filter(Track.job_id == job.id))


def _reexpand(db_session, monkeypatch, job, songs):
    """Runs a re-expansion as beat or "check now" would, claim included (`last_expanded_at`)."""
    job.last_expanded_at = datetime.now(timezone.utc)
    db_session.commit()
    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(expansion, "expand", lambda url: [_FakeSong(s) for s in songs])
    expand_task.expand_job(str(job.id), reexpand=True)


# --- expand_job's re-expand mode ---------------------------------------------------------


def test_reexpand_adds_only_the_tracks_new_to_the_job(db_session, monkeypatch, sent_downloads, markers):
    job = _job(db_session, _user(db_session), track_ids=("a", "b"))
    markers.set(f"{watch.KEY_PREFIX}{job.id}", "1")

    _reexpand(db_session, monkeypatch, job, ["a", "b", "c", "c"])

    assert _job_track_ids(db_session, job) == ["a", "b", "c"]
    new = db_session.query(Track).filter(Track.job_id == job.id, Track.spotify_track_id == "c").one()
    assert new.state == TrackState.PENDING
    # Handed to the broker through the outbox marker, as a first expansion's tracks are.
    assert sent_downloads == [str(new.id)]
    assert new.scheduled_at is None
    # The run's marker is cleared when it ends.
    assert markers.values == {}


def test_reexpand_keeps_a_track_gone_from_the_playlist(db_session, monkeypatch, sent_downloads):
    job = _job(db_session, _user(db_session), track_ids=("a", "b"))

    _reexpand(db_session, monkeypatch, job, ["a"])

    assert _job_track_ids(db_session, job) == ["a", "b"]
    assert sent_downloads == []


def test_reexpand_with_nothing_changed_adds_nothing(db_session, monkeypatch, sent_downloads):
    job = _job(db_session, _user(db_session), source_type=JobSourceType.ARTIST, track_ids=("a", "b"))
    published = []
    monkeypatch.setattr(events, "publish_job_event", lambda *args, **kwargs: published.append((args, kwargs)))

    _reexpand(db_session, monkeypatch, job, ["b", "a"])

    assert _job_track_ids(db_session, job) == ["a", "b"]
    assert sent_downloads == []
    # The row still re-reads its watch (its next check moved when the run was claimed), and
    # only the row: the event says it's the watch, so an open job keeps its loaded tracks.
    assert published == [((job.user_id, job.id, "expanded"), {"watch": True})]


def test_reexpand_announces_new_tracks_as_the_first_expansion_does(db_session, monkeypatch, sent_downloads):
    job = _job(db_session, _user(db_session), track_ids=("a",))
    published, changes = [], []
    monkeypatch.setattr(events, "publish_job_event", lambda *args, **kwargs: published.append((args, kwargs)))
    monkeypatch.setattr(job_status, "publish_change", lambda db, job_id, **kw: changes.append(job_id))

    _reexpand(db_session, monkeypatch, job, ["a", "n"])

    # New tracks: a full `expanded`, so an open job re-reads its track list too.
    assert published == [((job.user_id, job.id, "expanded"), {"watch": False})]
    assert changes == [job.id]


@pytest.mark.parametrize(
    "fields",
    [
        {"state": JobState.CANCELLED},
        {"state": JobState.FAILED},
        {"state": JobState.EXPANDING},
        {"archived_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    ],
)
def test_reexpand_leaves_a_job_that_isnt_expanded_and_unarchived(db_session, monkeypatch, sent_downloads, fields):
    job = _job(db_session, _user(db_session), track_ids=("a",), **fields)
    calls = []
    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(expansion, "expand", lambda url: calls.append(url) or [_FakeSong("n")])

    expand_task.expand_job(str(job.id), reexpand=True)

    assert calls == []
    assert _job_track_ids(db_session, job) == ["a"]


def test_reexpand_adds_nothing_to_a_job_cancelled_during_the_spotify_read(db_session, monkeypatch, sent_downloads):
    job = _job(db_session, _user(db_session), track_ids=("a",), track_state=TrackState.QUEUED)
    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))

    def cancel_meanwhile(url):
        db_session.query(Job).filter(Job.id == job.id).update({Job.state: JobState.CANCELLED})
        db_session.commit()
        return [_FakeSong("a"), _FakeSong("n")]

    monkeypatch.setattr(expansion, "expand", cancel_meanwhile)
    expand_task.expand_job(str(job.id), reexpand=True)

    assert _job_track_ids(db_session, job) == ["a"]
    assert sent_downloads == []


def test_a_failed_spotify_read_leaves_the_job_and_clears_the_marker(db_session, monkeypatch, markers):
    job = _job(db_session, _user(db_session), track_ids=("a",))
    markers.set(f"{watch.KEY_PREFIX}{job.id}", "1")
    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))

    def boom(url):
        raise RuntimeError("Spotify said no")

    monkeypatch.setattr(expansion, "expand", boom)
    expand_task.expand_job(str(job.id), reexpand=True)

    db_session.refresh(job)
    assert job.state == JobState.EXPANDED
    assert job.error is None
    assert markers.values == {}


def test_new_tracks_counts_only_what_reexpansion_added(db_session, monkeypatch, sent_downloads):
    job = _job(db_session, _user(db_session), track_ids=("a", "b"))
    assert watch.new_tracks(db_session, job.id) == 0
    _reexpand(db_session, monkeypatch, job, ["a", "b", "c", "d"])
    assert watch.new_tracks(db_session, job.id) == 2


# --- beat's watched-job selection ------------------------------------------------------


def _watched(db_session, user, *, due_at, **fields) -> Job:
    return _job(
        db_session, user, track_ids=("a",), watch_interval_hours=24, next_expand_at=due_at, **fields
    )


def _tick(db_session, monkeypatch):
    monkeypatch.setattr(beat_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(beat_task.download_track, "delay", lambda track_id: None)
    beat_task.dispatch_due_tracks()


def test_beat_starts_a_due_watched_job_and_schedules_its_next_check(db_session, monkeypatch, sent_expansions, markers):
    now = datetime.now(timezone.utc)
    due = _watched(db_session, _user(db_session), due_at=now - timedelta(minutes=1))
    later = _watched(db_session, _user(db_session), due_at=now + timedelta(hours=1))

    _tick(db_session, monkeypatch)

    assert sent_expansions == [(str(due.id), True)]
    db_session.refresh(due)
    db_session.refresh(later)
    assert due.last_expanded_at >= now
    # The claim's lease until the task starts; the start schedules the interval.
    assert due.next_expand_at == due.last_expanded_at + watch.CLAIM_LEASE
    assert later.last_expanded_at is None
    assert f"{watch.KEY_PREFIX}{due.id}" in markers.values


@pytest.mark.parametrize(
    "fields",
    [
        {"state": JobState.CANCELLED},
        {"state": JobState.FAILED},
        {"archived_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        {"source_type": JobSourceType.ALBUM},
    ],
)
def test_beat_skips_a_watched_job_it_mustnt_reexpand(db_session, monkeypatch, sent_expansions, fields):
    _watched(db_session, _user(db_session), due_at=datetime.now(timezone.utc) - timedelta(minutes=1), **fields)
    _tick(db_session, monkeypatch)
    assert sent_expansions == []


def test_beat_reexpands_while_the_breaker_is_tripped(db_session, monkeypatch, sent_expansions):
    job = _watched(db_session, _user(db_session), due_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    state = retry.get_worker_state(db_session)
    state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.commit()

    _tick(db_session, monkeypatch)

    assert sent_expansions == [(str(job.id), True)]


def test_the_hourly_cap_starts_k_and_leaves_the_rest_for_the_next_hour(db_session, monkeypatch, sent_expansions):
    monkeypatch.setattr(get_settings(), "reexpand_max_per_hour", 2)
    now = datetime.now(timezone.utc)
    jobs = [
        _watched(db_session, _user(db_session), due_at=now - timedelta(minutes=10 - i)) for i in range(3)
    ]

    _tick(db_session, monkeypatch)
    _tick(db_session, monkeypatch)

    # Oldest due first; the third stays due.
    assert sent_expansions == [(str(jobs[0].id), True), (str(jobs[1].id), True)]
    db_session.refresh(jobs[2])
    assert jobs[2].last_expanded_at is None
    assert jobs[2].next_expand_at <= now

    # An hour on, the first two's starts are out of the window: the third runs.
    for job in jobs[:2]:
        db_session.refresh(job)
        job.last_expanded_at -= timedelta(hours=1, seconds=1)
    db_session.commit()
    _tick(db_session, monkeypatch)
    assert sent_expansions[2:] == [(str(jobs[2].id), True)]


def test_the_cap_counts_check_now_runs(db_session, monkeypatch, sent_expansions):
    monkeypatch.setattr(get_settings(), "reexpand_max_per_hour", 1)
    now = datetime.now(timezone.utc)
    _job(db_session, _user(db_session), track_ids=("a",), last_expanded_at=now - timedelta(minutes=5))
    _watched(db_session, _user(db_session), due_at=now - timedelta(minutes=1))

    _tick(db_session, monkeypatch)

    assert sent_expansions == []


def test_beat_leaves_a_due_job_whose_check_now_is_running(db_session, monkeypatch, sent_expansions, markers):
    job = _watched(db_session, _user(db_session), due_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    markers.set(f"{watch.KEY_PREFIX}{job.id}", "1")

    _tick(db_session, monkeypatch)

    assert sent_expansions == []
    db_session.refresh(job)
    assert job.last_expanded_at is None


def test_a_refused_send_leaves_the_job_due_and_uncounted(db_session, monkeypatch, markers):
    now = datetime.now(timezone.utc)
    due_at = now - timedelta(minutes=1)
    job = _watched(db_session, _user(db_session), due_at=due_at)

    def refuse(job_id, reexpand=False, marker=None):
        raise ConnectionError("broker down")

    monkeypatch.setattr(expand_task.expand_job, "delay", refuse)
    _tick(db_session, monkeypatch)

    db_session.refresh(job)
    assert job.last_expanded_at is None
    assert job.next_expand_at == due_at
    assert markers.values == {}


def test_a_watched_job_pass_error_never_stops_track_dispatch(db_session, monkeypatch):
    def boom(db):
        raise RuntimeError("bad pass")

    monkeypatch.setattr(beat_task, "_dispatch_due_watched_jobs", boom)
    job = _job(db_session, _user(db_session))
    track = Track(
        job_id=job.id,
        spotify_track_id="w",
        song_json={"name": "w"},
        state=TrackState.WAITING,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(track)
    db_session.commit()

    _tick(db_session, monkeypatch)

    db_session.refresh(track)
    assert track.state == TrackState.QUEUED


def test_no_celery_eta_or_countdown_in_the_watch_paths():
    import inspect

    for module in (beat_task, expand_task, jobs_router, watch):
        source = inspect.getsource(module)
        assert "countdown" not in source and "eta=" not in source and "apply_async" not in source, module


# --- PUT /api/jobs/{id}/watch ------------------------------------------------------------


def test_owner_watches_and_unwatches_a_playlist(authenticated_client, db_session, owner):
    job = _job(db_session, owner, track_ids=("a",))
    before = datetime.now(timezone.utc)

    response = authenticated_client.put(f"/api/jobs/{job.id}/watch", json={"interval_hours": 24})
    assert response.status_code == 200
    body = response.json()
    assert body["watch_interval_hours"] == 24
    next_at = datetime.fromisoformat(body["next_expand_at"])
    assert before + timedelta(hours=24) <= next_at <= datetime.now(timezone.utc) + timedelta(hours=24)

    # The same interval again keeps the check already scheduled.
    again = authenticated_client.put(f"/api/jobs/{job.id}/watch", json={"interval_hours": 24}).json()
    assert again["next_expand_at"] == body["next_expand_at"]

    off = authenticated_client.put(f"/api/jobs/{job.id}/watch", json={"interval_hours": None}).json()
    assert off["watch_interval_hours"] is None
    assert off["next_expand_at"] is None


@pytest.mark.parametrize("interval", [0, 23, 24 * 365 + 1, "24", 1.5, True, [24]])
def test_watch_rejects_an_interval_outside_a_day_to_a_year(authenticated_client, db_session, owner, interval):
    job = _job(db_session, owner)
    response = authenticated_client.put(f"/api/jobs/{job.id}/watch", json={"interval_hours": interval})
    assert response.status_code == 422
    assert response.json()["code"] == "watch_interval_invalid"


@pytest.mark.parametrize("source_type", [JobSourceType.ALBUM, JobSourceType.TRACK, JobSourceType.SEARCH])
def test_only_a_playlist_or_artist_is_watchable(authenticated_client, db_session, owner, source_type):
    job = _job(db_session, owner, source_type=source_type)
    response = authenticated_client.put(f"/api/jobs/{job.id}/watch", json={"interval_hours": 168})
    assert response.status_code == 409
    assert response.json()["code"] == "job_not_watchable"
    assert response.json()["params"]["reason"] == "source_type"


@pytest.mark.parametrize(
    "fields,reason",
    [
        ({"state": JobState.CANCELLED}, "state"),
        ({"state": JobState.EXPANDING}, "state"),
        ({"archived_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}, "archived"),
    ],
)
def test_a_job_not_expanded_or_archived_isnt_watchable(authenticated_client, db_session, owner, fields, reason):
    job = _job(db_session, owner, **fields)
    response = authenticated_client.put(f"/api/jobs/{job.id}/watch", json={"interval_hours": 168})
    assert response.status_code == 409
    assert response.json()["params"]["reason"] == reason


def test_an_admin_watches_another_users_job(admin_client, db_session):
    job = _job(db_session, _user(db_session, "someone@example.com"), source_type=JobSourceType.ARTIST)
    response = admin_client.put(f"/api/jobs/{job.id}/watch", json={"interval_hours": 720})
    assert response.status_code == 200
    assert response.json()["watch_interval_hours"] == 720


def test_the_listing_carries_the_watch_and_the_new_count(authenticated_client, db_session, owner):
    job = _job(db_session, owner, track_ids=("a",), watch_interval_hours=168)
    item = next(j for j in authenticated_client.get("/api/jobs").json()["items"] if j["id"] == str(job.id))
    assert item["watch_interval_hours"] == 168
    assert item["new_tracks"] == 0
    assert "next_expand_at" in item and "last_expanded_at" in item


# --- POST /api/jobs/{id}/reexpand ---------------------------------------------------------


def test_check_now_refuses_a_search_job(authenticated_client, db_session, owner, sent_expansions):
    job = _job(db_session, owner, source_type=JobSourceType.SEARCH, track_ids=("a",))
    response = authenticated_client.post(f"/api/jobs/{job.id}/reexpand")
    assert response.status_code == 409
    assert response.json()["code"] == "job_not_reexpandable"
    assert response.json()["params"]["reason"] == "source_type"
    assert sent_expansions == []


def test_owner_checks_now(authenticated_client, db_session, owner, sent_expansions, markers):
    job = _job(db_session, owner, source_type=JobSourceType.ALBUM, track_ids=("a",))
    response = authenticated_client.post(f"/api/jobs/{job.id}/reexpand")
    assert response.status_code == 202
    assert sent_expansions == [(str(job.id), True)]
    assert response.json()["last_expanded_at"] is not None
    assert f"{watch.KEY_PREFIX}{job.id}" in markers.values


def test_check_now_moves_a_watched_jobs_next_check(authenticated_client, db_session, owner, sent_expansions):
    job = _job(
        db_session,
        owner,
        watch_interval_hours=24,
        next_expand_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    body = authenticated_client.post(f"/api/jobs/{job.id}/reexpand").json()
    last = datetime.fromisoformat(body["last_expanded_at"])
    assert datetime.fromisoformat(body["next_expand_at"]) == last + watch.CLAIM_LEASE


def test_a_second_check_while_one_runs_is_a_409(authenticated_client, db_session, owner, sent_expansions):
    job = _job(db_session, owner)
    assert authenticated_client.post(f"/api/jobs/{job.id}/reexpand").status_code == 202
    second = authenticated_client.post(f"/api/jobs/{job.id}/reexpand")
    assert second.status_code == 409
    assert second.json()["code"] == "reexpand_running"
    assert len(sent_expansions) == 1


def test_check_now_runs_again_once_the_last_run_ended(
    authenticated_client, db_session, owner, sent_expansions, monkeypatch
):
    job = _job(db_session, owner, track_ids=("a",))
    assert authenticated_client.post(f"/api/jobs/{job.id}/reexpand").status_code == 202
    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(expansion, "expand", lambda url: [_FakeSong("a")])
    expand_task.expand_job(str(job.id), reexpand=True)
    assert authenticated_client.post(f"/api/jobs/{job.id}/reexpand").status_code == 202


def test_an_admin_checks_another_users_job(admin_client, db_session, sent_expansions):
    job = _job(db_session, _user(db_session, "someone@example.com"))
    assert admin_client.post(f"/api/jobs/{job.id}/reexpand").status_code == 202


@pytest.mark.parametrize(
    "fields,code",
    [
        ({"state": JobState.FAILED}, "job_not_reexpandable"),
        ({"state": JobState.CANCELLED}, "job_not_reexpandable"),
        ({"state": JobState.EXPANDING}, "job_not_reexpandable"),
        ({"archived_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}, "job_archived"),
    ],
)
def test_check_now_needs_an_expanded_unarchived_job(
    authenticated_client, db_session, owner, sent_expansions, fields, code
):
    job = _job(db_session, owner, **fields)
    response = authenticated_client.post(f"/api/jobs/{job.id}/reexpand")
    assert response.status_code == 409
    assert response.json()["code"] == code
    assert sent_expansions == []


def test_a_refused_check_now_send_is_a_503_and_frees_the_job(
    authenticated_client, db_session, owner, monkeypatch, markers
):
    job = _job(db_session, owner)

    def refuse(job_id, reexpand=False, marker=None):
        raise ConnectionError("broker down")

    monkeypatch.setattr(expand_task.expand_job, "delay", refuse)
    response = authenticated_client.post(f"/api/jobs/{job.id}/reexpand")
    assert response.status_code == 503
    assert response.json()["code"] == "queue_unavailable"
    db_session.refresh(job)
    assert job.last_expanded_at is None
    assert markers.values == {}


# --- POST /api/jobs/{id}/retry-failed ----------------------------------------------------


def _failed_job(db_session, user, *, waiting=3, not_found=2, attempt_count=1) -> Job:
    job = _job(db_session, user, source_type=JobSourceType.ALBUM)
    later = datetime.now(timezone.utc) + timedelta(hours=4)
    for i in range(waiting):
        db_session.add(
            Track(
                job_id=job.id,
                spotify_track_id=f"w{i}",
                song_json={"name": f"w{i}"},
                state=TrackState.WAITING,
                scheduled_at=later,
                attempt_count=attempt_count,
            )
        )
    for i in range(not_found):
        db_session.add(
            Track(job_id=job.id, spotify_track_id=f"n{i}", song_json={"name": f"n{i}"}, state=TrackState.LOOKUP_FAILED)
        )
    db_session.add(Track(job_id=job.id, spotify_track_id="done", song_json={"name": "d"}, state=TrackState.COMPLETED))
    db_session.commit()
    return job


def _tracks(db_session, job, state):
    db_session.expire_all()
    return db_session.query(Track).filter(Track.job_id == job.id, Track.state == state).all()


def test_retry_failed_makes_every_waiting_track_due_now(authenticated_client, db_session, owner):
    job = _failed_job(db_session, owner)
    before = datetime.now(timezone.utc)

    response = authenticated_client.post(f"/api/jobs/{job.id}/retry-failed")

    assert response.status_code == 200
    body = response.json()
    assert (body["retried"], body["cooldown"], body["overridden"]) == (3, 0, 0)
    waiting = _tracks(db_session, job, TrackState.WAITING)
    assert len(waiting) == 3
    assert all(t.scheduled_at <= datetime.now(timezone.utc) and t.scheduled_at >= before for t in waiting)
    # Not-found tracks stay terminal without the admin's override.
    assert len(_tracks(db_session, job, TrackState.LOOKUP_FAILED)) == 2
    assert body["job"]["id"] == str(job.id)


def test_retry_failed_holds_a_non_admin_to_one_retry_per_step(authenticated_client, db_session, owner):
    job = _failed_job(db_session, owner)
    # One of them was retried in this step already (single retry, v56 A8).
    one = _tracks(db_session, job, TrackState.WAITING)[0]
    one.retry_now_step = one.attempt_count
    later = one.scheduled_at
    db_session.commit()

    body = authenticated_client.post(f"/api/jobs/{job.id}/retry-failed").json()
    assert (body["retried"], body["cooldown"]) == (2, 1)
    db_session.refresh(one)
    assert one.scheduled_at == later

    # A second press in the same step retries none of them.
    again = authenticated_client.post(f"/api/jobs/{job.id}/retry-failed").json()
    assert (again["retried"], again["cooldown"]) == (0, 3)

    # The next step (a failed attempt advances attempt_count) frees them again.
    for track in _tracks(db_session, job, TrackState.WAITING):
        track.attempt_count += 1
    db_session.commit()
    assert authenticated_client.post(f"/api/jobs/{job.id}/retry-failed").json()["retried"] == 3


def test_an_admins_retry_failed_isnt_held_per_step(admin_client, db_session, admin_user):
    job = _failed_job(db_session, admin_user)
    for track in _tracks(db_session, job, TrackState.WAITING):
        track.retry_now_step = track.attempt_count
    db_session.commit()
    assert admin_client.post(f"/api/jobs/{job.id}/retry-failed").json()["retried"] == 3


def test_admin_include_not_found_queues_them_and_records_manual_override(
    admin_client, db_session, sent_downloads, monkeypatch
):
    monkeypatch.setattr(jobs_router.download_track, "delay", lambda track_id: sent_downloads.append(track_id))
    job = _failed_job(db_session, _user(db_session, "someone@example.com"))

    response = admin_client.post(f"/api/jobs/{job.id}/retry-failed?include_not_found=true")

    assert response.status_code == 200
    assert response.json()["overridden"] == 2
    queued = _tracks(db_session, job, TrackState.QUEUED)
    assert sorted(t.spotify_track_id for t in queued) == ["n0", "n1"]
    assert sorted(sent_downloads) == sorted(str(t.id) for t in queued)
    rows = db_session.query(TrackAttempt).filter(TrackAttempt.track_id.in_([t.id for t in queued])).all()
    assert len(rows) == 2
    assert {r.outcome for r in rows} == {TrackAttemptOutcome.MANUAL_OVERRIDE}
    assert all(r.network_path is None and r.warning_message for r in rows)
    # Not a network attempt: the display counters don't move.
    assert all(t.attempts_made == 0 and t.failure_count == 0 for t in queued)
    history = admin_client.get(f"/api/tracks/{queued[0].id}/attempts").json()
    assert [a["outcome"] for a in history] == ["manual_override"]


def test_a_non_admin_cant_include_not_found(authenticated_client, db_session, owner):
    job = _failed_job(db_session, owner)
    response = authenticated_client.post(f"/api/jobs/{job.id}/retry-failed?include_not_found=true")
    assert response.status_code == 403
    assert response.json()["code"] == "admin_required"
    assert len(_tracks(db_session, job, TrackState.LOOKUP_FAILED)) == 2
    assert all(t.scheduled_at > datetime.now(timezone.utc) for t in _tracks(db_session, job, TrackState.WAITING))


@pytest.mark.parametrize(
    "fields,code",
    [
        ({"archived_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}, "job_archived"),
        ({"state": JobState.CANCELLED}, "job_cancelled"),
    ],
)
def test_retry_failed_refuses_an_archived_or_cancelled_job(authenticated_client, db_session, owner, fields, code):
    job = _failed_job(db_session, owner)
    for name, value in fields.items():
        setattr(job, name, value)
    db_session.commit()
    response = authenticated_client.post(f"/api/jobs/{job.id}/retry-failed")
    assert response.status_code == 409
    assert response.json()["code"] == code


def test_retry_failed_says_when_the_breaker_holds(authenticated_client, db_session, owner):
    job = _failed_job(db_session, owner)
    state = retry.get_worker_state(db_session)
    state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.commit()
    assert authenticated_client.post(f"/api/jobs/{job.id}/retry-failed").json()["breaker_held"] is True


# --- review round 1 ----------------------------------------------------------------------


def test_a_new_batch_shares_one_stamp(db_session, monkeypatch, sent_downloads):
    job = _job(db_session, _user(db_session), track_ids=("a",))
    _reexpand(db_session, monkeypatch, job, ["a", "x", "y", "z"])
    db_session.expire_all()
    stamps = {
        t.created_at
        for t in db_session.query(Track).filter(Track.job_id == job.id, Track.spotify_track_id != "a")
    }
    assert len(stamps) == 1
    assert watch.new_tracks(db_session, job.id) == 3


def test_a_job_whose_first_read_was_empty_counts_its_first_batch_as_first(
    db_session, monkeypatch, sent_downloads
):
    job = _job(db_session, _user(db_session))
    _reexpand(db_session, monkeypatch, job, ["x", "y"])
    assert watch.new_tracks(db_session, job.id) == 0


def test_a_failed_read_still_announces_the_job(db_session, monkeypatch):
    job = _job(db_session, _user(db_session), track_ids=("a",))
    published = []
    monkeypatch.setattr(events, "publish_job_event", lambda *args, **kwargs: published.append((args, kwargs)))
    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))

    def boom(url):
        raise RuntimeError("Spotify said no")

    monkeypatch.setattr(expansion, "expand", boom)
    expand_task.expand_job(str(job.id), reexpand=True)
    assert published == [((job.user_id, job.id, "expanded"), {"watch": True})]


def test_watch_needs_the_interval_key(authenticated_client, db_session, owner):
    job = _job(db_session, owner, watch_interval_hours=24)
    response = authenticated_client.put(f"/api/jobs/{job.id}/watch", json={})
    assert response.status_code == 422
    db_session.refresh(job)
    assert job.watch_interval_hours == 24


def test_cancelling_a_watched_job_ends_its_watch(authenticated_client, db_session, owner):
    job = _job(
        db_session,
        owner,
        track_ids=("a",),
        track_state=TrackState.QUEUED,
        watch_interval_hours=24,
        next_expand_at=datetime.now(timezone.utc) + timedelta(hours=3),
    )
    body = authenticated_client.delete(f"/api/jobs/{job.id}").json()
    assert body["watch_interval_hours"] is None
    assert body["next_expand_at"] is None


def test_a_failed_commit_releases_the_check_now_marker(
    authenticated_client, db_session, owner, monkeypatch, markers, sent_expansions
):
    job = _job(db_session, owner)
    real_commit = db_session.commit
    calls = {"n": 0}

    def failing_commit():
        # The handler's refresh-with-lock is followed by this commit: fail that one.
        calls["n"] += 1
        if any(v for v in markers.values):
            raise RuntimeError("database went away")
        return real_commit()

    monkeypatch.setattr(db_session, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        authenticated_client.post(f"/api/jobs/{job.id}/reexpand")
    assert markers.values == {}
    assert sent_expansions == []


# --- review round 2 ----------------------------------------------------------------------


def test_a_watched_job_is_never_archived(authenticated_client, db_session, owner):
    """Owner's decision (2026-10-30): clear log, retention and the library sweep all go
    through archive_jobs, which leaves a watched job alone."""
    from app.services import archive

    watched = _job(db_session, owner, track_ids=("a",), watch_interval_hours=24)
    plain = _job(db_session, owner, track_ids=("b",))

    response = authenticated_client.post("/api/jobs/archive", json={"all_settled": True})
    assert response.json()["archived_ids"] == [str(plain.id)]
    assert archive.archive_jobs(db_session, owner.id, older_than=timedelta(0)) == []
    db_session.refresh(watched)
    assert watched.archived_at is None

    # Stopping the watch makes it archivable again.
    authenticated_client.put(f"/api/jobs/{watched.id}/watch", json={"interval_hours": None})
    assert authenticated_client.post("/api/jobs/archive", json={"all_settled": True}).json()[
        "archived_ids"
    ] == [str(watched.id)]


def test_archive_rechecks_under_the_lock(db_session, monkeypatch):
    """A job that got pending tracks (a re-expansion) between the eligibility read and the
    write isn't archived."""
    from app.services import archive

    user = _user(db_session)
    job = _job(db_session, user, track_ids=("a",))
    real = archive._eligible_job_ids
    calls = []

    def eligible_then_reexpanded(db, user_id, job_ids, older_than):
        result = real(db, user_id, job_ids, older_than)
        if not calls:
            db.add(Track(job_id=job.id, spotify_track_id="new", song_json={"name": "n"}, state=TrackState.PENDING))
            db.flush()
        calls.append(result)
        return real(db, user_id, job_ids, older_than) if len(calls) > 1 else result

    monkeypatch.setattr(archive, "_eligible_job_ids", eligible_then_reexpanded)
    assert archive.archive_jobs(db_session, user.id) == []
    db_session.refresh(job)
    assert job.archived_at is None


def test_retry_failed_cooldown_counts_only_tracks_held_by_the_step_rule(authenticated_client, db_session, owner):
    job = _failed_job(db_session, owner)
    tracks = _tracks(db_session, job, TrackState.WAITING)
    tracks[0].retry_now_step = tracks[0].attempt_count
    # One left `waiting` but no longer for this request: beat queued it meanwhile.
    tracks[1].state = TrackState.QUEUED
    db_session.commit()
    body = authenticated_client.post(f"/api/jobs/{job.id}/retry-failed").json()
    assert (body["retried"], body["cooldown"]) == (1, 1)


def test_watch_and_check_now_announce_the_job_to_its_owner(admin_client, db_session, monkeypatch, sent_expansions):
    published = []
    monkeypatch.setattr(events, "publish_job_event", lambda *args, **kwargs: published.append((args, kwargs)))
    other = _user(db_session, "someone@example.com")
    job = _job(db_session, other)
    admin_client.put(f"/api/jobs/{job.id}/watch", json={"interval_hours": 24})
    admin_client.post(f"/api/jobs/{job.id}/reexpand")
    assert published == [((other.id, job.id, "expanded"), {"watch": True})] * 2


# --- review round 3 ----------------------------------------------------------------------


def test_a_refused_check_now_keeps_a_watch_set_meanwhile(
    authenticated_client, db_session, owner, monkeypatch, markers
):
    job = _job(db_session, owner)

    def refuse_after_a_watch(job_id, reexpand=False, marker=None):
        # Another request watches the job while this one's send is failing.
        db_session.query(Job).filter(Job.id == job.id).update(
            {
                Job.watch_interval_hours: 24,
                Job.next_expand_at: datetime.now(timezone.utc) + timedelta(hours=24),
            }
        )
        db_session.commit()
        raise ConnectionError("broker down")

    monkeypatch.setattr(expand_task.expand_job, "delay", refuse_after_a_watch)
    assert authenticated_client.post(f"/api/jobs/{job.id}/reexpand").status_code == 503
    db_session.refresh(job)
    assert job.last_expanded_at is None
    assert job.watch_interval_hours == 24
    assert job.next_expand_at is not None


def test_new_tracks_counts_nothing_for_a_job_never_re_expanded(db_session):
    job = _job(db_session, _user(db_session), track_ids=("a",))
    # A later-stamped track on a job no re-expansion ever touched (an older path's).
    db_session.add(
        Track(
            job_id=job.id,
            spotify_track_id="late",
            song_json={"name": "late"},
            state=TrackState.COMPLETED,
            created_at=datetime.now(timezone.utc) + timedelta(seconds=5),
        )
    )
    db_session.commit()
    assert watch.new_tracks(db_session, job.id) == 0


# --- review round 4 ----------------------------------------------------------------------


def test_beats_refused_send_keeps_an_interval_changed_meanwhile(db_session, monkeypatch, markers):
    now = datetime.now(timezone.utc)
    due_at = now - timedelta(minutes=1)
    job = _watched(db_session, _user(db_session), due_at=due_at)
    weekly = now + timedelta(hours=168)

    def refuse_after_a_change(job_id, reexpand=False, marker=None):
        # The owner switched to weekly while the broker stalled.
        db_session.query(Job).filter(Job.id == job.id).update(
            {Job.watch_interval_hours: 168, Job.next_expand_at: weekly}
        )
        db_session.commit()
        raise ConnectionError("broker down")

    monkeypatch.setattr(expand_task.expand_job, "delay", refuse_after_a_change)
    _tick(db_session, monkeypatch)

    db_session.refresh(job)
    assert job.last_expanded_at is None
    assert job.next_expand_at == weekly


# --- review round 5 ----------------------------------------------------------------------


def test_a_started_run_schedules_the_interval_before_its_read(db_session, monkeypatch, sent_expansions):
    now = datetime.now(timezone.utc)
    job = _watched(db_session, _user(db_session), due_at=now - timedelta(minutes=1))
    _tick(db_session, monkeypatch)
    db_session.refresh(job)
    claimed = job.last_expanded_at
    assert job.next_expand_at == claimed + watch.CLAIM_LEASE

    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))

    def boom(url):
        raise RuntimeError("Spotify said no")

    monkeypatch.setattr(expansion, "expand", boom)
    expand_task.expand_job(str(job.id), reexpand=True)
    db_session.refresh(job)
    assert job.next_expand_at == claimed + timedelta(hours=24)


def test_a_run_lost_after_its_claim_is_claimed_again_after_the_lease(db_session, monkeypatch, sent_expansions, markers):
    now = datetime.now(timezone.utc)
    job = _watched(db_session, _user(db_session), due_at=now - timedelta(minutes=1))
    _tick(db_session, monkeypatch)
    assert len(sent_expansions) == 1
    # The message was lost (no task ever started); its marker expired.
    markers.values.clear()
    db_session.refresh(job)
    job.last_expanded_at -= watch.CLAIM_LEASE + timedelta(seconds=1)
    job.next_expand_at -= watch.CLAIM_LEASE + timedelta(seconds=1)
    db_session.commit()
    _tick(db_session, monkeypatch)
    assert len(sent_expansions) == 2


def test_a_started_run_keeps_a_watch_changed_after_its_claim(db_session, monkeypatch, sent_expansions):
    now = datetime.now(timezone.utc)
    job = _watched(db_session, _user(db_session), due_at=now - timedelta(minutes=1))
    _tick(db_session, monkeypatch)
    weekly = now + timedelta(hours=168)
    db_session.refresh(job)
    job.watch_interval_hours, job.next_expand_at = 168, weekly
    db_session.commit()
    _reexpand_without_claim = lambda: expand_task.expand_job(str(job.id), reexpand=True)  # noqa: E731
    monkeypatch.setattr(expand_task, "SessionLocal", lambda: _NonClosingSession(db_session))
    monkeypatch.setattr(expansion, "expand", lambda url: [_FakeSong("a")])
    _reexpand_without_claim()
    db_session.refresh(job)
    assert job.next_expand_at == weekly


# --- review round 6 ----------------------------------------------------------------------


def test_the_marker_lasts_as_long_as_the_lease():
    assert watch.RUN_MARKER_TTL_SECONDS == watch.CLAIM_LEASE.total_seconds()


def test_a_run_never_frees_a_later_claim(markers):
    job_id = "00000000-0000-4000-8000-000000000063"
    first = watch.claim_run(job_id)
    # Its marker expired behind a backed-up queue; a second run was claimed meanwhile.
    markers.values.clear()
    second = watch.claim_run(job_id)
    assert first and second and first != second
    watch.release_run(job_id, first)
    assert watch.claim_run(job_id) is None
    watch.release_run(job_id, second)
    assert watch.claim_run(job_id) is not None


def test_a_held_marker_takes_no_slot_of_the_budget(db_session, monkeypatch, sent_expansions, markers):
    monkeypatch.setattr(get_settings(), "reexpand_max_per_hour", 1)
    now = datetime.now(timezone.utc)
    busy = _watched(db_session, _user(db_session), due_at=now - timedelta(minutes=5))
    other = _watched(db_session, _user(db_session), due_at=now - timedelta(minutes=1))
    markers.set(f"{watch.KEY_PREFIX}{busy.id}", "someone-else")
    _tick(db_session, monkeypatch)
    assert sent_expansions == [(str(other.id), True)]
