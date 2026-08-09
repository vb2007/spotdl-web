import uuid

from app.models import Job, JobSourceType, JobState, Track, TrackState
from app.routers import auth
from app.routers import jobs as jobs_router


def _login(client, monkeypatch):
    async def fake_login(email, password):
        return True

    monkeypatch.setattr(auth.upstream_auth, "login", fake_login)
    client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "x"})


def _stub_expand_job(monkeypatch):
    enqueued = []
    monkeypatch.setattr(jobs_router.expand_job, "delay", lambda job_id: enqueued.append(job_id))
    return enqueued


def test_create_job_enqueues_expansion_and_returns_expanding_state(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    enqueued = _stub_expand_job(monkeypatch)

    response = client.post("/api/jobs", json={"url": "https://open.spotify.com/track/abc"})

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "expanding"
    assert body["source_type"] == "track"
    assert body["track_counts"] == {}
    assert enqueued == [body["id"]]


def test_create_job_classifies_source_type_from_url(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    _stub_expand_job(monkeypatch)

    cases = {
        "https://open.spotify.com/playlist/xyz": "playlist",
        "https://open.spotify.com/album/xyz": "album",
        "https://open.spotify.com/artist/xyz": "artist",
        "some search term": "search",
    }
    for url, expected in cases.items():
        response = client.post("/api/jobs", json={"url": url})
        assert response.json()["source_type"] == expected


def test_list_and_get_job_include_track_counts(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    _stub_expand_job(monkeypatch)

    create_response = client.post("/api/jobs", json={"url": "https://open.spotify.com/track/abc"})
    job_id = create_response.json()["id"]

    job = db_session.get(Job, uuid.UUID(job_id))
    job.state = JobState.EXPANDED
    db_session.add(
        Track(
            job_id=job.id,
            spotify_track_id="abc",
            song_json={"name": "Song"},
            state=TrackState.PENDING,
        )
    )
    db_session.commit()

    list_response = client.get("/api/jobs")
    assert list_response.status_code == 200
    listed = next(j for j in list_response.json() if j["id"] == job_id)
    assert listed["state"] == "expanded"
    assert listed["track_counts"] == {"pending": 1}

    get_response = client.get(f"/api/jobs/{job_id}")
    assert get_response.status_code == 200
    assert get_response.json()["track_counts"] == {"pending": 1}


def _make_job_with_tracks(db_session, states=(TrackState.PENDING, TrackState.PENDING)):
    job = Job(
        source_url="https://open.spotify.com/album/x",
        source_type=JobSourceType.ALBUM,
        state=JobState.EXPANDED,
    )
    db_session.add(job)
    db_session.commit()
    for index, state in enumerate(states):
        db_session.add(
            Track(
                job_id=job.id,
                spotify_track_id=f"{job.id}-{index}",
                song_json={"name": "Song"},
                state=state,
            )
        )
    db_session.commit()
    return job


def test_list_jobs_query_count_does_not_grow_with_job_count(
    client, db_session, monkeypatch, count_queries
):
    """v15's N+1 guard. Before the fix, job_to_dict ran one grouped-count query per job,
    so five jobs cost four more statements than one -- this asserts the count stays flat
    instead of inferring it from timing."""
    _login(client, monkeypatch)

    _make_job_with_tracks(db_session)
    with count_queries() as one_job_statements:
        first = client.get("/api/jobs")
    assert first.status_code == 200
    assert len(first.json()) == 1

    for _ in range(4):
        _make_job_with_tracks(db_session)
    with count_queries() as five_job_statements:
        second = client.get("/api/jobs")
    assert second.status_code == 200
    assert len(second.json()) == 5

    # Differential, not an absolute: the session lookup require_session does is constant
    # but isn't this test's business, and pinning an exact total would make an unrelated
    # auth change break this test for the wrong reason.
    assert len(five_job_statements) == len(one_job_statements)
    # ...and the absolute is small enough to prove it really is one aggregate, not N.
    assert len(five_job_statements) <= 4


def test_list_jobs_track_counts_are_attributed_per_job(client, db_session, monkeypatch):
    """The correctness half of the N+1 fix: the classic bulk-aggregate bug is grouping by
    state alone and smearing every job's counts together."""
    _login(client, monkeypatch)

    busy = _make_job_with_tracks(
        db_session, states=(TrackState.PENDING, TrackState.PENDING, TrackState.COMPLETED)
    )
    waiting = _make_job_with_tracks(db_session, states=(TrackState.WAITING,))
    empty = _make_job_with_tracks(db_session, states=())

    by_id = {job["id"]: job for job in client.get("/api/jobs").json()}

    assert by_id[str(busy.id)]["track_counts"] == {"pending": 2, "completed": 1}
    assert by_id[str(waiting.id)]["track_counts"] == {"waiting": 1}
    assert by_id[str(empty.id)]["track_counts"] == {}


def test_list_job_tracks_projects_display_fields_and_stays_pending(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    _stub_expand_job(monkeypatch)

    create_response = client.post("/api/jobs", json={"url": "https://open.spotify.com/track/abc"})
    job_id = create_response.json()["id"]

    job = db_session.get(Job, uuid.UUID(job_id))
    db_session.add(
        Track(
            job_id=job.id,
            spotify_track_id="abc",
            song_json={"name": "Test Song", "artists": ["Artist A"], "album_name": "Album A"},
        )
    )
    db_session.commit()

    response = client.get(f"/api/jobs/{job_id}/tracks")
    assert response.status_code == 200
    [track] = response.json()
    assert track["title"] == "Test Song"
    assert track["artists"] == ["Artist A"]
    assert track["album"] == "Album A"
    assert track["state"] == "pending"


def test_get_unknown_job_returns_404(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    response = client.get(f"/api/jobs/{uuid.uuid4()}")
    assert response.status_code == 404


def test_jobs_endpoints_require_session(client):
    assert client.post("/api/jobs", json={"url": "x"}).status_code == 401
    assert client.get("/api/jobs").status_code == 401
    assert client.get(f"/api/jobs/{uuid.uuid4()}").status_code == 401
    assert client.get(f"/api/jobs/{uuid.uuid4()}/tracks").status_code == 401
    assert client.delete(f"/api/jobs/{uuid.uuid4()}").status_code == 401


def test_cancel_job_marks_job_and_non_terminal_tracks_cancelled(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    _stub_expand_job(monkeypatch)

    create_response = client.post("/api/jobs", json={"url": "https://open.spotify.com/album/xyz"})
    job_id = create_response.json()["id"]
    job = db_session.get(Job, uuid.UUID(job_id))
    job.state = JobState.EXPANDED

    downloading = Track(
        job_id=job.id, spotify_track_id="a", song_json={"name": "A"}, state=TrackState.DOWNLOADING
    )
    waiting = Track(
        job_id=job.id, spotify_track_id="b", song_json={"name": "B"}, state=TrackState.WAITING
    )
    completed = Track(
        job_id=job.id, spotify_track_id="c", song_json={"name": "C"}, state=TrackState.COMPLETED
    )
    skipped = Track(
        job_id=job.id,
        spotify_track_id="d",
        song_json={"name": "D"},
        state=TrackState.SKIPPED_DUPLICATE,
    )
    db_session.add_all([downloading, waiting, completed, skipped])
    db_session.commit()

    response = client.delete(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "cancelled"
    # Pins the ordering constraint that track_counts must be read *after* the cancel
    # commit (jobs.py) -- reporting pre-cancel counts here would mean job_to_dict's
    # counts argument was hoisted above the commit by a future refactor.
    assert body["track_counts"] == {
        "cancelled": 2,
        "completed": 1,
        "skipped_duplicate": 1,
    }

    assert db_session.get(Track, downloading.id).state == TrackState.CANCELLED
    assert db_session.get(Track, waiting.id).state == TrackState.CANCELLED
    assert db_session.get(Track, waiting.id).scheduled_at is None
    # Already-terminal tracks are left exactly as they were.
    assert db_session.get(Track, completed.id).state == TrackState.COMPLETED
    assert db_session.get(Track, skipped.id).state == TrackState.SKIPPED_DUPLICATE


def test_cancel_unknown_job_returns_404(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    response = client.delete(f"/api/jobs/{uuid.uuid4()}")
    assert response.status_code == 404


def test_set_job_priority_sets_exact_value(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    _stub_expand_job(monkeypatch)

    job_id = client.post("/api/jobs", json={"url": "https://open.spotify.com/track/abc"}).json()["id"]

    response = client.patch(f"/api/jobs/{job_id}/priority", json={"priority": 7})

    assert response.status_code == 200
    assert response.json()["priority"] == 7
    assert db_session.get(Job, uuid.UUID(job_id)).priority == 7


def test_set_priority_on_unknown_job_returns_404(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    response = client.patch(f"/api/jobs/{uuid.uuid4()}/priority", json={"priority": 1})
    assert response.status_code == 404


def test_bump_job_sets_priority_above_current_max(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    _stub_expand_job(monkeypatch)

    first_id = client.post("/api/jobs", json={"url": "https://open.spotify.com/track/a"}).json()["id"]
    second_id = client.post("/api/jobs", json={"url": "https://open.spotify.com/track/b"}).json()["id"]
    db_session.get(Job, uuid.UUID(first_id)).priority = 3
    db_session.commit()

    response = client.post(f"/api/jobs/{second_id}/bump")

    assert response.status_code == 200
    assert response.json()["priority"] == 4
    assert db_session.get(Job, uuid.UUID(second_id)).priority == 4


def test_bump_unknown_job_returns_404(client, db_session, monkeypatch):
    _login(client, monkeypatch)
    response = client.post(f"/api/jobs/{uuid.uuid4()}/bump")
    assert response.status_code == 404


def test_priority_endpoints_require_session(client):
    job_id = uuid.uuid4()
    assert client.patch(f"/api/jobs/{job_id}/priority", json={"priority": 1}).status_code == 401
    assert client.post(f"/api/jobs/{job_id}/bump").status_code == 401
