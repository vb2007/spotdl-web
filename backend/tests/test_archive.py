from datetime import datetime, timedelta, timezone

from app.models import DownloadedTrack, Job, JobSourceType, JobState, Track, TrackState, User
from app.services import archive


def _owner(db_session, email="owner@example.com") -> User:
    user = db_session.query(User).filter(User.email == email).one_or_none()
    if user is None:
        user = User(email=email, is_admin=False)
        db_session.add(user)
        db_session.flush()
    return user


def _make_job(db_session, owner, *, job_state=JobState.EXPANDED, track_states=()) -> Job:
    job = Job(
        source_url="https://open.spotify.com/album/x",
        source_type=JobSourceType.ALBUM,
        state=job_state,
        user_id=owner.id,
    )
    db_session.add(job)
    db_session.commit()
    for index, state in enumerate(track_states):
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


def test_archive_jobs_archives_only_settled_failed_or_cancelled_jobs_for_the_owner(db_session):
    owner = _owner(db_session)
    stranger = _owner(db_session, "stranger@example.com")

    active = _make_job(db_session, owner, track_states=(TrackState.PENDING,))
    waiting = _make_job(db_session, owner, track_states=(TrackState.WAITING,))
    settled = _make_job(db_session, owner, track_states=(TrackState.COMPLETED,))
    failed = _make_job(db_session, owner, job_state=JobState.FAILED, track_states=())
    cancelled = _make_job(db_session, owner, job_state=JobState.CANCELLED, track_states=(TrackState.CANCELLED,))
    others_settled = _make_job(db_session, stranger, track_states=(TrackState.COMPLETED,))

    archived = archive.archive_jobs(db_session, owner.id)
    archived_ids = {job.id for job in archived}

    assert archived_ids == {settled.id, failed.id, cancelled.id}
    for job_id in (active.id, waiting.id):
        assert db_session.get(Job, job_id).archived_at is None
    assert db_session.get(Job, others_settled.id).archived_at is None


def test_archive_jobs_never_archives_a_waiting_job_regardless_of_age(db_session):
    owner = _owner(db_session)
    job = _make_job(db_session, owner, track_states=(TrackState.WAITING,))
    long_ago = datetime.now(timezone.utc) - timedelta(days=365)
    job.created_at = long_ago
    for track in db_session.query(Track).filter(Track.job_id == job.id):
        track.updated_at = long_ago
    db_session.commit()

    archived = archive.archive_jobs(db_session, owner.id, older_than=timedelta(days=1))

    assert archived == []
    assert db_session.get(Job, job.id).archived_at is None


def test_archive_jobs_age_is_measured_from_newest_track_activity_not_job_created_at(db_session):
    owner = _owner(db_session)
    job = _make_job(db_session, owner, track_states=(TrackState.COMPLETED,))
    # job.created_at is old, but the track was touched recently -- must NOT be eligible
    # for a 1-day threshold.
    job.created_at = datetime.now(timezone.utc) - timedelta(days=365)
    db_session.commit()

    archived = archive.archive_jobs(db_session, owner.id, older_than=timedelta(days=1))

    assert archived == []
    assert db_session.get(Job, job.id).archived_at is None


def test_archive_jobs_sweep_archives_settled_jobs_past_the_threshold(db_session):
    owner = _owner(db_session)
    job = _make_job(db_session, owner, track_states=(TrackState.COMPLETED,))
    stale_activity = datetime.now(timezone.utc) - timedelta(days=10)
    for track in db_session.query(Track).filter(Track.job_id == job.id):
        track.updated_at = stale_activity
    db_session.commit()

    archived = archive.archive_jobs(db_session, owner.id, older_than=timedelta(days=1))

    assert [job.id for job in archived] == [job.id]
    assert db_session.get(Job, job.id).archived_at is not None


def test_archive_jobs_with_job_ids_restricts_to_the_given_ids(db_session):
    owner = _owner(db_session)
    first = _make_job(db_session, owner, track_states=(TrackState.COMPLETED,))
    second = _make_job(db_session, owner, track_states=(TrackState.COMPLETED,))

    archived = archive.archive_jobs(db_session, owner.id, job_ids=[first.id])

    assert [job.id for job in archived] == [first.id]
    assert db_session.get(Job, second.id).archived_at is None


def test_archive_jobs_ignores_job_ids_belonging_to_another_user(db_session):
    owner = _owner(db_session)
    stranger = _owner(db_session, "stranger@example.com")
    theirs = _make_job(db_session, stranger, track_states=(TrackState.COMPLETED,))

    archived = archive.archive_jobs(db_session, owner.id, job_ids=[theirs.id])

    assert archived == []
    assert db_session.get(Job, theirs.id).archived_at is None


def test_archive_jobs_never_touches_downloaded_tracks(db_session):
    owner = _owner(db_session)
    job = _make_job(db_session, owner, track_states=(TrackState.COMPLETED,))
    db_session.add(
        DownloadedTrack(spotify_track_id="abc123", file_path="/downloads/a.mp3", format="mp3")
    )
    db_session.commit()
    before = db_session.query(DownloadedTrack).count()

    archive.archive_jobs(db_session, owner.id)

    assert db_session.query(DownloadedTrack).count() == before
    row = db_session.query(DownloadedTrack).filter(DownloadedTrack.spotify_track_id == "abc123").one()
    assert row.file_path == "/downloads/a.mp3"
    assert db_session.get(Job, job.id).archived_at is not None


def test_unarchive_jobs_restores_only_owned_archived_jobs(db_session):
    owner = _owner(db_session)
    stranger = _owner(db_session, "stranger@example.com")
    mine = _make_job(db_session, owner, track_states=(TrackState.COMPLETED,))
    theirs = _make_job(db_session, stranger, track_states=(TrackState.COMPLETED,))
    archive.archive_jobs(db_session, owner.id)
    archive.archive_jobs(db_session, stranger.id)

    restored = archive.unarchive_jobs(db_session, owner.id, [mine.id, theirs.id])

    assert [job.id for job in restored] == [mine.id]
    assert db_session.get(Job, mine.id).archived_at is None
    assert db_session.get(Job, theirs.id).archived_at is not None


def test_unarchive_jobs_on_a_non_archived_job_is_a_noop(db_session):
    owner = _owner(db_session)
    job = _make_job(db_session, owner, track_states=(TrackState.COMPLETED,))

    restored = archive.unarchive_jobs(db_session, owner.id, [job.id])

    assert restored == []
