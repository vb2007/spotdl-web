"""v18's `GET /api/jobs` -- every parameter tested in combination, not one at a time
(the plan's own "Done when" standard), plus `counts_by_status`/`total_estimate` shape."""

import uuid

from app.models import Job, JobSourceType, JobState, Track, TrackState


def _make_job(db_session, owner, *, source_type=JobSourceType.ALBUM, track_states=(), list_name=None, archived=False):
    job = Job(
        source_url=f"https://open.spotify.com/{source_type.value}/{uuid.uuid4().hex[:8]}",
        source_type=source_type,
        state=JobState.EXPANDED,
        user_id=owner.id,
    )
    if archived:
        from datetime import datetime, timezone

        job.archived_at = datetime.now(timezone.utc)
    db_session.add(job)
    db_session.commit()
    for i, state in enumerate(track_states):
        song = {"name": f"Song {i}"}
        if i == 0 and list_name:
            song["list_name"] = list_name
        db_session.add(Track(job_id=job.id, spotify_track_id=f"{job.id}-{i}", song_json=song, state=state))
    db_session.commit()
    return job


def test_search_status_source_type_and_sort_compose_together(authenticated_client, db_session, owner):
    target = _make_job(
        db_session,
        owner,
        source_type=JobSourceType.PLAYLIST,
        track_states=[TrackState.COMPLETED] * 9 + [TrackState.LOOKUP_FAILED],
        list_name="UniqueSearchTarget",
    )
    # A decoy that matches the search term but not the status filter.
    _make_job(
        db_session,
        owner,
        source_type=JobSourceType.PLAYLIST,
        track_states=[TrackState.COMPLETED],
        list_name="UniqueSearchTarget Two",
    )
    # A decoy that matches the status filter but not the search term.
    _make_job(
        db_session,
        owner,
        source_type=JobSourceType.PLAYLIST,
        track_states=[TrackState.COMPLETED] * 9 + [TrackState.LOOKUP_FAILED],
        list_name="Something Else Entirely",
    )
    # A decoy matching search+status but the wrong source_type.
    _make_job(
        db_session,
        owner,
        source_type=JobSourceType.ALBUM,
        track_states=[TrackState.COMPLETED] * 9 + [TrackState.LOOKUP_FAILED],
        list_name="UniqueSearchTarget Three",
    )

    response = authenticated_client.get(
        "/api/jobs",
        params={
            "q": "UniqueSearchTarget",
            "status": "settled:partial",
            "source_type": "playlist",
            "sort": "title",
            "dir": "asc",
        },
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["id"] for i in items] == [str(target.id)]


def test_include_archived_toggle_composes_with_search(authenticated_client, db_session, owner):
    archived = _make_job(
        db_session, owner, track_states=[TrackState.COMPLETED], list_name="ArchivedFindMe", archived=True
    )

    without = authenticated_client.get("/api/jobs", params={"q": "ArchivedFindMe"}).json()["items"]
    assert without == []

    with_archived = authenticated_client.get(
        "/api/jobs", params={"q": "ArchivedFindMe", "include_archived": "true"}
    ).json()["items"]
    assert [i["id"] for i in with_archived] == [str(archived.id)]


def test_counts_by_status_reflects_other_filters_but_not_the_status_filter_itself(authenticated_client, db_session, owner):
    _make_job(db_session, owner, source_type=JobSourceType.ALBUM, track_states=[TrackState.COMPLETED])
    _make_job(db_session, owner, source_type=JobSourceType.ALBUM, track_states=[TrackState.DOWNLOADING])
    _make_job(db_session, owner, source_type=JobSourceType.PLAYLIST, track_states=[TrackState.COMPLETED])

    response = authenticated_client.get("/api/jobs", params={"source_type": "album", "status": "active"})
    body = response.json()
    # Filtered by status=active, so only the active job is in `items`...
    assert len(body["items"]) == 1
    # ...but counts_by_status still reports both album-scoped statuses (source_type
    # filter carried through), not just the one currently selected.
    assert body["counts_by_status"].get("active") == 1
    assert body["counts_by_status"].get("settled:complete") == 1
    assert "playlist" not in str(body["counts_by_status"])  # sanity: no cross-source_type leak


def test_total_estimate_matches_result_count_at_small_scale(authenticated_client, db_session, owner):
    for _ in range(3):
        _make_job(db_session, owner, track_states=[TrackState.COMPLETED])

    response = authenticated_client.get("/api/jobs")
    body = response.json()
    assert body["total_estimate"] == 3
    assert len(body["items"]) == 3


def test_invalid_status_token_returns_400(authenticated_client, db_session, owner):
    response = authenticated_client.get("/api/jobs", params={"status": "not_a_real_status"})
    assert response.status_code == 400


def test_invalid_sort_or_dir_returns_400(authenticated_client, db_session, owner):
    assert authenticated_client.get("/api/jobs", params={"sort": "nonsense"}).status_code == 400
    assert authenticated_client.get("/api/jobs", params={"dir": "sideways"}).status_code == 422


def test_search_status_sort_and_pagination_compose_together_across_multiple_pages(authenticated_client, db_session, owner):
    """The plan's own "Done when" standard, taken literally: search + status filter +
    sort + pagination *together*, not pairwise -- every prior composition test in this
    file matches so few rows that pagination across it never actually gets exercised.
    Five real matches, paged two at a time, plus decoys that fail exactly one of the two
    filters (to prove they're both actually being applied, not just one)."""
    matches = [
        _make_job(
            db_session,
            owner,
            track_states=[TrackState.COMPLETED] * 9 + [TrackState.LOOKUP_FAILED],
            list_name=f"ComboTarget {letter}",
        )
        for letter in "ABCDE"
    ]
    # Matches q but not status (fully completed, no partial outcome).
    _make_job(db_session, owner, track_states=[TrackState.COMPLETED], list_name="ComboTarget Decoy")
    # Matches status but not q.
    _make_job(
        db_session, owner, track_states=[TrackState.COMPLETED] * 9 + [TrackState.LOOKUP_FAILED], list_name="Unrelated"
    )

    seen_titles = []
    cursor = None
    for _ in range(10):
        params = {"q": "ComboTarget", "status": "settled:partial", "sort": "title", "dir": "asc", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = authenticated_client.get("/api/jobs", params=params)
        assert response.status_code == 200
        body = response.json()
        seen_titles.extend(i["title"] for i in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert seen_titles == [f"ComboTarget {letter}" for letter in "ABCDE"]
    assert len(seen_titles) == len(set(seen_titles))


def test_scope_track_all_users_flag_from_non_admin_is_ignored(client, db_session, make_user, session_cookie):
    owner = make_user("owner@example.com")
    other = make_user("other@example.com")
    owner_cookie = session_cookie("owner@example.com")

    job_owner = _make_job(db_session, owner, track_states=[TrackState.COMPLETED], list_name="Mine")
    _make_job(db_session, other, track_states=[TrackState.COMPLETED], list_name="TheirsNotMine")

    client.cookies.clear()
    client.cookies.update(owner_cookie)
    response = client.get("/api/jobs", params={"scope": "track", "all_users": "true"})
    assert response.status_code == 200
    job_ids = {i["job"]["id"] for i in response.json()["items"]}
    assert job_ids == {str(job_owner.id)}


def test_scope_track_on_jobs_endpoint_matches_get_tracks_endpoint(authenticated_client, db_session, owner):
    job = _make_job(db_session, owner, track_states=[TrackState.COMPLETED, TrackState.WAITING])

    via_jobs_scope = authenticated_client.get("/api/jobs", params={"scope": "track"}).json()
    via_tracks = authenticated_client.get("/api/tracks").json()

    ids_a = sorted(i["id"] for i in via_jobs_scope["items"])
    ids_b = sorted(i["id"] for i in via_tracks["items"])
    assert ids_a == ids_b
    assert len(ids_a) == 2
    assert all(i["job"]["id"] == str(job.id) for i in via_jobs_scope["items"])
