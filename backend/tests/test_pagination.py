"""v18's cursor (keyset) pagination -- the specific failure mode it exists to avoid:
offset pagination silently skips/duplicates rows when the table is written to between
page fetches. Tested here against the real `GET /api/jobs` endpoint under exactly that
condition, not just the `pagination` module in isolation."""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

from app.models import Job, JobSourceType, JobState, Track, TrackState
from app.services import pagination

# SQLite's CURRENT_TIMESTAMP (what `func.now()` maps to) has one-second resolution, so a
# tight test loop creating several jobs can easily give them all the *same* created_at,
# leaving the id (an unordered UUID) as the only tiebreaker -- explicit, strictly
# increasing timestamps make "sort=created_at" deterministic instead of flaky.
_next_created_at = itertools.count()


def _make_job(db_session, owner, source_url=None):
    job = Job(
        source_url=source_url or f"https://open.spotify.com/album/{uuid.uuid4().hex[:8]}",
        source_type=JobSourceType.ALBUM,
        state=JobState.EXPANDED,
        user_id=owner.id,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=next(_next_created_at)),
    )
    db_session.add(job)
    db_session.commit()
    return job


def test_paging_forward_through_every_job_visits_each_exactly_once(authenticated_client, db_session, owner):
    jobs = [_make_job(db_session, owner) for _ in range(7)]

    seen = []
    cursor = None
    for _ in range(10):
        response = authenticated_client.get(
            "/api/jobs", params={"sort": "created_at", "dir": "asc", "limit": 2, **({"cursor": cursor} if cursor else {})}
        )
        assert response.status_code == 200
        body = response.json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert seen == [str(j.id) for j in jobs]
    assert len(seen) == len(set(seen))


def test_pages_stay_correct_when_a_row_is_archived_between_fetches(authenticated_client, db_session, owner):
    """The concrete failure offset pagination has: mutating rows *before* the still-
    unfetched tail between two page fetches must not cause the next page to skip or
    duplicate anything, because the cursor encodes "after this exact row", not a
    position/count that a concurrent removal would shift."""
    j1, j2, j3, j4, j5 = (_make_job(db_session, owner) for _ in range(5))

    page1 = authenticated_client.get("/api/jobs", params={"sort": "created_at", "dir": "asc", "limit": 2}).json()
    assert [i["id"] for i in page1["items"]] == [str(j1.id), str(j2.id)]

    # Concurrent writes between page1 and page2: archive j1 (already returned) and j3
    # (not yet returned, sitting in the still-unfetched tail) -- both should disappear
    # from the default (non-archived) listing without disturbing j4/j5's positions.
    from datetime import datetime, timezone

    j1_row = db_session.get(Job, j1.id)
    j3_row = db_session.get(Job, j3.id)
    j1_row.archived_at = datetime.now(timezone.utc)
    j3_row.archived_at = datetime.now(timezone.utc)
    db_session.commit()
    _make_job(db_session, owner)  # j6, newer than everything -- must not appear before j5 in asc order

    page2 = authenticated_client.get(
        "/api/jobs", params={"sort": "created_at", "dir": "asc", "limit": 2, "cursor": page1["next_cursor"]}
    ).json()
    assert [i["id"] for i in page2["items"]] == [str(j4.id), str(j5.id)]

    page3 = authenticated_client.get(
        "/api/jobs", params={"sort": "created_at", "dir": "asc", "limit": 2, "cursor": page2["next_cursor"]}
    ).json()
    remaining_ids = [i["id"] for i in page3["items"]]
    assert str(j1.id) not in remaining_ids
    assert str(j2.id) not in remaining_ids
    assert str(j3.id) not in remaining_ids
    assert page3["next_cursor"] is None


def test_nullable_sort_key_keeps_nulls_last_regardless_of_direction(authenticated_client, db_session, owner):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    has_retry = _make_job(db_session, owner)
    db_session.add(
        Track(
            job_id=has_retry.id,
            spotify_track_id="w",
            song_json={"name": "W"},
            state=TrackState.WAITING,
            scheduled_at=now + timedelta(hours=2),
        )
    )
    no_retry = _make_job(db_session, owner)
    db_session.add(
        Track(job_id=no_retry.id, spotify_track_id="c", song_json={"name": "C"}, state=TrackState.COMPLETED)
    )
    db_session.commit()

    asc = authenticated_client.get("/api/jobs", params={"sort": "next_retry", "dir": "asc", "limit": 50}).json()
    desc = authenticated_client.get("/api/jobs", params={"sort": "next_retry", "dir": "desc", "limit": 50}).json()

    assert [i["id"] for i in asc["items"]] == [str(has_retry.id), str(no_retry.id)]
    assert [i["id"] for i in desc["items"]] == [str(has_retry.id), str(no_retry.id)]


def test_malformed_cursor_returns_400_not_500(authenticated_client, db_session, owner):
    _make_job(db_session, owner)
    response = authenticated_client.get("/api/jobs", params={"cursor": "not-a-real-cursor"})
    assert response.status_code == 400


def test_encode_decode_cursor_round_trips_uuid_and_datetime():
    from datetime import datetime, timezone

    row_id = uuid.uuid4()
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cursor = pagination.encode_cursor((when, row_id))
    decoded_when, decoded_id = pagination.decode_cursor(cursor)
    assert decoded_when == when
    assert decoded_id == row_id
    assert isinstance(decoded_id, uuid.UUID)
