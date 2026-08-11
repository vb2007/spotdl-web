"""v17's threat model, exercised end to end: a non-owner (admin or not) must never
observe or affect another user's jobs/tracks through list endpoints or direct-id
endpoints. Direct-id endpoints return 404, never 403, so an id's existence is never
confirmed to a non-owner. The SSE stream's equivalent property is proven from the wire
against the real stack (see the plan's verification section), not here."""

import pytest

from app.models import Job, JobSourceType, JobState, Track, TrackState


def _make_job(db_session, owner, *, state=JobState.EXPANDED):
    job = Job(
        source_url="https://open.spotify.com/album/x",
        source_type=JobSourceType.ALBUM,
        state=state,
        user_id=owner.id,
    )
    db_session.add(job)
    db_session.commit()
    return job


def _make_track(db_session, job, *, state=TrackState.WAITING):
    track = Track(
        job_id=job.id,
        spotify_track_id=f"{job.id}-track",
        song_json={"name": "Song"},
        state=state,
    )
    db_session.add(track)
    db_session.commit()
    return track


def _as(client, cookie: dict[str, str]):
    """Switches the shared `client` fixture to a given identity for the calls that
    follow -- set directly on the client's own jar (clearing first) rather than passed
    per-request, since per-request `cookies=` is deprecated on httpx's TestClient and
    ambiguous about persistence besides."""
    client.cookies.clear()
    client.cookies.update(cookie)
    return client


def test_list_jobs_and_tracks_contain_zero_of_the_other_users_rows(client, db_session, make_user, session_cookie):
    user_a = make_user("a@example.com")
    user_b = make_user("b@example.com")
    cookie_a = session_cookie("a@example.com")
    cookie_b = session_cookie("b@example.com")

    job_a = _make_job(db_session, user_a)
    _make_track(db_session, job_a)
    job_b = _make_job(db_session, user_b)
    _make_track(db_session, job_b)

    jobs_as_b = _as(client, cookie_b).get("/api/jobs").json()["items"]
    assert all(j["id"] != str(job_a.id) for j in jobs_as_b)
    assert any(j["id"] == str(job_b.id) for j in jobs_as_b)

    tracks_as_b = _as(client, cookie_b).get("/api/tracks").json()["items"]
    assert all(t["job_id"] != str(job_a.id) for t in tracks_as_b)

    jobs_as_a = _as(client, cookie_a).get("/api/jobs").json()["items"]
    assert all(j["id"] != str(job_b.id) for j in jobs_as_a)


_DIRECT_ID_CASES = [
    ("GET", "/api/jobs/{job_id}"),
    ("GET", "/api/jobs/{job_id}/tracks"),
    ("DELETE", "/api/jobs/{job_id}"),
    ("DELETE", "/api/tracks/{track_id}"),
    ("POST", "/api/tracks/{track_id}/retry"),
    ("PATCH", "/api/jobs/{job_id}/priority"),
    ("POST", "/api/jobs/{job_id}/bump"),
]


@pytest.mark.parametrize("method, path_template", _DIRECT_ID_CASES)
def test_direct_id_endpoint_404s_for_non_owner(
    method, path_template, client, db_session, make_user, session_cookie
):
    """Tested endpoint by endpoint (parametrized, not looped-and-asserted-once) -- one
    passing endpoint proves nothing about the others, per the plan's own standard."""
    owner = make_user("owner@example.com")
    stranger_cookie = session_cookie("stranger@example.com")

    job = _make_job(db_session, owner)
    track = _make_track(db_session, job, state=TrackState.WAITING)

    path = path_template.format(job_id=job.id, track_id=track.id)
    kwargs = {"json": {"priority": 1}} if method == "PATCH" else {}

    response = _as(client, stranger_cookie).request(method, path, **kwargs)

    assert response.status_code == 404


def test_direct_id_endpoint_200s_for_the_real_owner(client, db_session, make_user, session_cookie):
    """Sanity check alongside the 404 sweep above: the same job/track *does* resolve for
    its actual owner, so the 404s above are proven to be an ownership check and not a
    routing bug that 404s for everyone."""
    owner = make_user("owner@example.com")
    owner_cookie = session_cookie("owner@example.com")
    job = _make_job(db_session, owner)

    assert _as(client, owner_cookie).get(f"/api/jobs/{job.id}").status_code == 200
    assert _as(client, owner_cookie).post(f"/api/jobs/{job.id}/bump").status_code == 200


def test_admin_has_full_read_and_write_access_to_a_foreign_job(client, db_session, make_user, session_cookie):
    owner = make_user("owner@example.com")
    make_user("root@example.com", is_admin=True)
    admin_cookie = session_cookie("root@example.com", is_admin=True)

    job = _make_job(db_session, owner)
    track = _make_track(db_session, job, state=TrackState.WAITING)

    get_response = _as(client, admin_cookie).get(f"/api/jobs/{job.id}")
    assert get_response.status_code == 200
    assert get_response.json()["owner_email"] == "owner@example.com"

    assert _as(client, admin_cookie).post(f"/api/jobs/{job.id}/bump").status_code == 200
    assert _as(client, admin_cookie).post(f"/api/tracks/{track.id}/retry").status_code == 200
    assert _as(client, admin_cookie).delete(f"/api/jobs/{job.id}").status_code == 200


def test_all_users_flag_from_non_admin_is_silently_ignored(client, db_session, make_user, session_cookie):
    owner = make_user("owner@example.com")
    other = make_user("other@example.com")
    owner_cookie = session_cookie("owner@example.com")

    _make_job(db_session, owner)
    _make_job(db_session, other)

    response = _as(client, owner_cookie).get("/api/jobs?all_users=true")
    owners = {j["owner_email"] for j in response.json()["items"]}
    assert owners == {"owner@example.com"}


def test_admin_default_view_is_own_jobs_only_and_all_users_reveals_the_rest(
    client, db_session, make_user, session_cookie
):
    owner = make_user("owner@example.com")
    make_user("root@example.com", is_admin=True)
    admin_cookie = session_cookie("root@example.com", is_admin=True)

    job = _make_job(db_session, owner)

    default_view = _as(client, admin_cookie).get("/api/jobs").json()["items"]
    assert all(j["id"] != str(job.id) for j in default_view)

    all_view = _as(client, admin_cookie).get("/api/jobs?all_users=true").json()["items"]
    assert any(j["id"] == str(job.id) for j in all_view)


def test_search_and_scope_track_never_surface_another_users_rows(client, db_session, make_user, session_cookie):
    """v18 adds real new query paths (search, scope=track, status/state filters) --
    exactly the kind of new surface the project's data-separation invariant calls out as
    needing its own re-run of the cross-user sweep, not just the list endpoints v17
    already covered."""
    stranger = make_user("stranger@example.com")
    victim_job = _make_job(db_session, stranger)
    victim_track = Track(
        job_id=victim_job.id,
        spotify_track_id="victim",
        song_json={"name": "VeryUniqueSearchableTitle", "artists": ["Nobody"]},
        state=TrackState.WAITING,
    )
    db_session.add(victim_track)
    db_session.commit()

    attacker_cookie = session_cookie("attacker@example.com")
    _as(client, attacker_cookie)

    # A search term that *does* match the victim's track must still come back empty for
    # a non-owner, non-admin caller -- across every surface that accepts `q`.
    for path in ("/api/jobs", "/api/jobs?scope=track", "/api/tracks"):
        response = client.get(f"{path}{'&' if '?' in path else '?'}q=VeryUniqueSearchableTitle")
        assert response.status_code == 200
        assert response.json()["items"] == [], path

    # Same for the victim's job's own /{id}/tracks endpoint -- direct-id, must 404.
    assert client.get(f"/api/jobs/{victim_job.id}/tracks?q=VeryUnique").status_code == 404

    # And status/state filters must not become a side channel either.
    for path in ("/api/jobs?status=waiting", "/api/tracks?state=waiting"):
        response = client.get(path)
        assert response.status_code == 200
        ids = {item["id"] for item in response.json()["items"]}
        assert str(victim_job.id) not in ids
        assert str(victim_track.id) not in ids
