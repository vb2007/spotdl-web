"""v18's `GET /api/tracks` and `GET /api/jobs/{id}/tracks` -- composed filters, query
count constancy, and `counts_by_state`."""

import uuid

from app.models import Job, JobSourceType, JobState, Track, TrackState


def _make_job(db_session, owner, *, source_type=JobSourceType.ALBUM):
    job = Job(
        source_url=f"https://open.spotify.com/{source_type.value}/{uuid.uuid4().hex[:8]}",
        source_type=source_type,
        state=JobState.EXPANDED,
        user_id=owner.id,
    )
    db_session.add(job)
    db_session.commit()
    return job


def _add_track(db_session, job, *, name, artists=None, state=TrackState.COMPLETED):
    track = Track(
        job_id=job.id,
        spotify_track_id=f"{job.id}-{uuid.uuid4().hex[:6]}",
        song_json={"name": name, "artists": artists or []},
        state=state,
    )
    db_session.add(track)
    db_session.commit()
    return track


def test_search_state_and_source_type_compose_together(authenticated_client, db_session, owner):
    album = _make_job(db_session, owner, source_type=JobSourceType.ALBUM)
    playlist = _make_job(db_session, owner, source_type=JobSourceType.PLAYLIST)

    target = _add_track(db_session, album, name="Bohemian Rhapsody", artists=["Queen"], state=TrackState.WAITING)
    _add_track(db_session, album, name="Bohemian Rhapsody", artists=["Queen"], state=TrackState.COMPLETED)  # wrong state
    _add_track(db_session, playlist, name="Bohemian Rhapsody", artists=["Queen"], state=TrackState.WAITING)  # wrong source_type
    _add_track(db_session, album, name="Something Else", state=TrackState.WAITING)  # wrong search term

    response = authenticated_client.get(
        "/api/tracks", params={"q": "bohemian", "state": "waiting", "source_type": "album"}
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["id"] for i in items] == [str(target.id)]


def test_job_status_filter_on_tracks_endpoint_matches_parent_job_rollup(authenticated_client, db_session, owner):
    active_job = _make_job(db_session, owner)
    _add_track(db_session, active_job, name="A", state=TrackState.DOWNLOADING)
    settled_job = _make_job(db_session, owner)
    settled_track = _add_track(db_session, settled_job, name="B", state=TrackState.COMPLETED)

    response = authenticated_client.get("/api/tracks", params={"status": "settled:complete"})
    items = response.json()["items"]
    assert [i["id"] for i in items] == [str(settled_track.id)]


def test_query_count_for_track_listing_is_constant(authenticated_client, db_session, owner, count_queries):
    job = _make_job(db_session, owner)
    _add_track(db_session, job, name="One")

    with count_queries() as few_statements:
        response = authenticated_client.get("/api/tracks")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1

    for i in range(20):
        _add_track(db_session, job, name=f"Track {i}")

    with count_queries() as many_statements:
        response2 = authenticated_client.get("/api/tracks")
    assert response2.status_code == 200
    assert len(response2.json()["items"]) == 21

    assert len(many_statements) == len(few_statements)


def test_job_tracks_endpoint_counts_by_state_ignores_its_own_state_filter(authenticated_client, db_session, owner):
    job = _make_job(db_session, owner)
    _add_track(db_session, job, name="A", state=TrackState.COMPLETED)
    _add_track(db_session, job, name="B", state=TrackState.WAITING)
    _add_track(db_session, job, name="C", state=TrackState.WAITING)

    response = authenticated_client.get(f"/api/jobs/{job.id}/tracks", params={"state": "completed"})
    body = response.json()
    assert len(body["items"]) == 1
    assert body["counts_by_state"] == {"completed": 1, "waiting": 2}


def test_job_tracks_endpoint_pagination_and_sort(authenticated_client, db_session, owner):
    job = _make_job(db_session, owner)
    for name in ["Charlie", "Alpha", "Bravo"]:
        _add_track(db_session, job, name=name)

    page1 = authenticated_client.get(
        f"/api/jobs/{job.id}/tracks", params={"sort": "title", "dir": "asc", "limit": 2}
    ).json()
    assert [i["title"] for i in page1["items"]] == ["Alpha", "Bravo"]

    page2 = authenticated_client.get(
        f"/api/jobs/{job.id}/tracks",
        params={"sort": "title", "dir": "asc", "limit": 2, "cursor": page1["next_cursor"]},
    ).json()
    assert [i["title"] for i in page2["items"]] == ["Charlie"]
    assert page2["next_cursor"] is None


def test_non_admin_all_users_flag_ignored_on_tracks_endpoint(client, db_session, make_user, session_cookie):
    owner = make_user("owner@example.com")
    other = make_user("other@example.com")
    owner_cookie = session_cookie("owner@example.com")

    job_owner = _make_job(db_session, owner)
    _add_track(db_session, job_owner, name="Mine")
    job_other = _make_job(db_session, other)
    _add_track(db_session, job_other, name="TheirsNotMine")

    client.cookies.clear()
    client.cookies.update(owner_cookie)
    response = client.get("/api/tracks", params={"all_users": "true"})
    titles = {i["title"] for i in response.json()["items"]}
    assert titles == {"Mine"}
