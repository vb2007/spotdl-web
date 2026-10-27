from datetime import datetime, timedelta, timezone

import pytest


def test_get_retention_settings_defaults_to_null(authenticated_client, db_session):
    response = authenticated_client.get("/api/settings/retention")

    assert response.status_code == 200
    assert response.json() == {"retention_days": None}


def test_update_retention_settings_persists(authenticated_client, db_session):
    updated = authenticated_client.patch("/api/settings/retention", json={"retention_days": 30})

    assert updated.status_code == 200
    assert updated.json() == {"retention_days": 30}

    refetched = authenticated_client.get("/api/settings/retention")
    assert refetched.json() == {"retention_days": 30}


def test_update_retention_settings_can_disable_with_null(authenticated_client, db_session):
    authenticated_client.patch("/api/settings/retention", json={"retention_days": 30})

    response = authenticated_client.patch("/api/settings/retention", json={"retention_days": None})

    assert response.status_code == 200
    assert response.json() == {"retention_days": None}


@pytest.mark.parametrize("days", [0, -1, 36501, 10**9])
def test_update_retention_settings_rejects_a_value_out_of_range(authenticated_client, db_session, days):
    """v56 (A5): 1..36500 (the /account form's own bound), else 422. Before v56 only a
    non-positive value was refused (400), and a huge one was stored."""
    authenticated_client.patch("/api/settings/retention", json={"retention_days": 30})

    response = authenticated_client.patch("/api/settings/retention", json={"retention_days": days})

    assert response.status_code == 422
    assert response.json()["code"] == "retention_out_of_range"
    assert response.json()["params"] == {"min": 1, "max": 36500}
    assert authenticated_client.get("/api/settings/retention").json() == {"retention_days": 30}


@pytest.mark.parametrize("days", [1, 36500])
def test_update_retention_settings_accepts_both_bounds(authenticated_client, db_session, days):
    response = authenticated_client.patch("/api/settings/retention", json={"retention_days": days})

    assert response.status_code == 200
    assert response.json() == {"retention_days": days}


def test_a_huge_retention_value_no_longer_breaks_the_archive_sweep(
    authenticated_client, db_session, owner, make_user, monkeypatch
):
    """v56 (A5): `retention_days=10**9` used to be stored, and the hourly sweep's
    `timedelta(days=10**9)` then raised OverflowError, stopping it for every user after that
    one. Now it's refused, the largest value that can be stored sweeps without error, and a
    user with a short retention beside it is still archived."""
    from app.models import Job, JobSourceType, JobState, Track, TrackState
    from app.services import user_settings
    from app.tasks import beat

    monkeypatch.setattr(beat, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(beat.events, "publish_job_event", lambda *a, **kw: None)

    assert authenticated_client.patch("/api/settings/retention", json={"retention_days": 10**9}).status_code == 422
    assert authenticated_client.patch("/api/settings/retention", json={"retention_days": 36500}).status_code == 200
    later = make_user("later@example.com")
    user_settings.update_retention(db_session, later.id, 1)
    old = datetime.now(timezone.utc) - timedelta(days=30)
    jobs = []
    for user in (owner, later):
        job = Job(
            user_id=user.id,
            source_url="https://open.spotify.com/track/old",
            source_type=JobSourceType.TRACK,
            state=JobState.EXPANDED,
            created_at=old,
        )
        db_session.add(job)
        db_session.flush()
        db_session.add(
            Track(job_id=job.id, spotify_track_id=f"old-{user.id}", song_json={}, state=TrackState.COMPLETED, updated_at=old)
        )
        jobs.append(job)
    db_session.commit()

    beat.archive_due_jobs()

    owners_job, laters_job = jobs
    db_session.refresh(owners_job)
    db_session.refresh(laters_job)
    assert owners_job.archived_at is None  # 30 days old is well inside 36500
    assert laters_job.archived_at is not None


def test_retention_settings_are_isolated_per_user(authenticated_client, db_session, session_cookie):
    authenticated_client.patch("/api/settings/retention", json={"retention_days": 7})

    # A second identity on the same client via session_cookie, not a second login (which
    # would just overwrite the shared cookie jar -- see conftest.py's session_cookie doc).
    other_cookies = session_cookie("other@example.com")
    other_response = authenticated_client.get("/api/settings/retention", cookies=other_cookies)

    assert other_response.json() == {"retention_days": None}


def test_non_admin_can_read_and_write_their_own_retention_setting(authenticated_client, db_session):
    # Unlike /api/settings/output, retention is deliberately open to every user, not
    # admin-gated -- a plain authenticated_client succeeding here is the point.
    response = authenticated_client.patch("/api/settings/retention", json={"retention_days": 14})
    assert response.status_code == 200


def test_retention_settings_endpoints_require_session(client):
    assert client.get("/api/settings/retention").status_code == 401
    assert client.patch("/api/settings/retention", json={"retention_days": 1}).status_code == 401
