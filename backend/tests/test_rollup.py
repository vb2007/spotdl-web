"""v18's rollup status -- both derivations (`rollup.derive_rollup`, used by the
single-job `job_to_dict` call sites, and the SQL `CASE` builders used by the paginated
listing) proven against the same explicit branches the plan calls out by name."""

import uuid

from app.models import Job, JobSourceType, JobState, Track, TrackState
from app.services import rollup


def _make_job_with_tracks(db_session, owner, job_state, track_states, source_url=None):
    job = Job(
        source_url=source_url or f"https://open.spotify.com/album/{uuid.uuid4().hex[:8]}",
        source_type=JobSourceType.ALBUM,
        state=job_state,
        user_id=owner.id,
    )
    db_session.add(job)
    db_session.commit()
    for i, state in enumerate(track_states):
        db_session.add(
            Track(
                job_id=job.id,
                spotify_track_id=f"{job.id}-{i}",
                song_json={"name": f"Song {i}"},
                state=state,
            )
        )
    db_session.commit()
    return job


_BRANCHES = [
    ("all_completed", JobState.EXPANDED, [TrackState.COMPLETED] * 9 + [TrackState.SKIPPED_DUPLICATE], "settled", "complete"),
    ("nine_plus_one_lookup_failed", JobState.EXPANDED, [TrackState.COMPLETED] * 9 + [TrackState.LOOKUP_FAILED], "settled", "partial"),
    ("one_downloading_nine_completed", JobState.EXPANDED, [TrackState.DOWNLOADING] + [TrackState.COMPLETED] * 9, "active", None),
    ("all_waiting", JobState.EXPANDED, [TrackState.WAITING] * 5, "waiting", None),
    ("zero_tracks_failed", JobState.FAILED, [], "failed", None),
    ("zero_tracks_expanding", JobState.EXPANDING, [], "expanding", None),
    ("cancelled_with_some_completed", JobState.CANCELLED, [TrackState.CANCELLED, TrackState.COMPLETED], "cancelled", None),
]


def test_derive_rollup_matches_every_named_branch(db_session, owner):
    for name, job_state, track_states, expected_lifecycle, expected_outcome in _BRANCHES:
        job = _make_job_with_tracks(db_session, owner, job_state, track_states)
        counts: dict[str, int] = {}
        for state in track_states:
            counts[state.value] = counts.get(state.value, 0) + 1
        result = rollup.derive_rollup(job.state, counts)
        assert (result.lifecycle, result.outcome) == (expected_lifecycle, expected_outcome), name


def test_job_to_dict_status_field_matches_every_named_branch(authenticated_client, db_session, owner):
    """Same branches, proven through the real single-job HTTP response (`GET
    /api/jobs/{id}`) rather than calling `derive_rollup` directly -- the actual code path
    `create_job`/`get_job`/etc. use."""
    for name, job_state, track_states, expected_lifecycle, expected_outcome in _BRANCHES:
        job = _make_job_with_tracks(db_session, owner, job_state, track_states)
        response = authenticated_client.get(f"/api/jobs/{job.id}")
        assert response.status_code == 200, name
        status = response.json()["status"]
        assert (status["lifecycle"], status["outcome"]) == (expected_lifecycle, expected_outcome), name


def test_list_jobs_status_filter_matches_every_named_branch_via_sql(authenticated_client, db_session, owner):
    """Same branches again, this time through `GET /api/jobs?status=...` -- the SQL
    `CASE`-expression path (`job_listing.list_jobs`), proving it agrees with the Python
    derivation above rather than just asserting it in isolation."""
    jobs_by_name = {}
    for name, job_state, track_states, expected_lifecycle, expected_outcome in _BRANCHES:
        jobs_by_name[name] = _make_job_with_tracks(db_session, owner, job_state, track_states)

    for name, job_state, track_states, expected_lifecycle, expected_outcome in _BRANCHES:
        token = rollup.status_key(expected_lifecycle, expected_outcome)
        response = authenticated_client.get(f"/api/jobs?status={token}")
        assert response.status_code == 200, name
        ids = {item["id"] for item in response.json()["items"]}
        assert str(jobs_by_name[name].id) in ids, name
        # And every *other* branch's job must be absent from this status's results.
        for other_name, other_job in jobs_by_name.items():
            if other_name == name:
                continue
            other_branch = next(b for b in _BRANCHES if b[0] == other_name)
            if (other_branch[3], other_branch[4]) == (expected_lifecycle, expected_outcome):
                continue
            assert str(other_job.id) not in ids, f"{other_name} leaked into status={token}"


def test_bare_settled_status_filter_matches_both_outcomes(authenticated_client, db_session, owner):
    complete_job = _make_job_with_tracks(db_session, owner, JobState.EXPANDED, [TrackState.COMPLETED] * 3)
    partial_job = _make_job_with_tracks(
        db_session, owner, JobState.EXPANDED, [TrackState.COMPLETED, TrackState.LOOKUP_FAILED]
    )
    active_job = _make_job_with_tracks(db_session, owner, JobState.EXPANDED, [TrackState.DOWNLOADING])

    response = authenticated_client.get("/api/jobs?status=settled")
    ids = {item["id"] for item in response.json()["items"]}
    assert ids == {str(complete_job.id), str(partial_job.id)}
    assert str(active_job.id) not in ids


def test_derive_job_title_prefers_list_name_then_track_name_then_source_url():
    assert rollup.derive_job_title("https://x/album/1", {"list_name": "My Album", "name": "Track"}) == "My Album"
    assert rollup.derive_job_title("https://x/album/1", {"name": "Track"}) == "Track"
    assert rollup.derive_job_title("https://x/album/1", None) == "https://x/album/1"
    assert rollup.derive_job_title("https://x/album/1", {}) == "https://x/album/1"
