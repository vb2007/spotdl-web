"""v69: what a removal does to the person's downloads, on real commits (`committed_db`).

A job that has started (an attempt, or a dedup result) runs to the end; one that hasn't is held
(`jobs.held_at`, lifecycle `held`): none of its tracks is attempted until the address is added
again, which resumes it. The removal and download_track's move to `downloading` serialize on the
job row; the race test at the end runs both orders on two real connections."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from concurrency import Gate, Thread, blocked_or_done
from sqlalchemy import event

from app.models import (
    AllowedEmail,
    Job,
    JobSourceType,
    JobState,
    Track,
    TrackAttempt,
    TrackState,
    User,
    WorkerState,
)
from app.services import allowlist, archive, dedup, downloads, events, expansion, job_status, rollup, tagging, watch
from app.services.job_listing import list_jobs
from app.tasks import beat as beat_task
from app.tasks import download as download_task
from app.tasks import expand as expand_task

_LONG_AGO = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture()
def world(committed_db, monkeypatch, tmp_path):
    """Every task on real sessions, every network call and publish faked. `sent` lists each
    `download_track.delay`, `downloaded` each track that reached spotdl."""
    state = SimpleNamespace(sent=[], downloaded=[], track_events=[], control=[], expanded=[])
    for module in (download_task, beat_task, expand_task):
        monkeypatch.setattr(module, "SessionLocal", committed_db)
    monkeypatch.setattr(dedup, "SessionLocal", committed_db)
    monkeypatch.setattr(download_task.download_track, "delay", lambda track_id: state.sent.append(uuid.UUID(track_id)))
    monkeypatch.setattr(dedup, "is_already_downloaded", lambda spotify_track_id: None)
    monkeypatch.setattr(events, "publish_track_event", lambda *a, **k: state.track_events.append(a))
    monkeypatch.setattr(events, "publish_job_event", lambda *a, **k: None)
    monkeypatch.setattr(events, "publish_control", lambda user_id, kind: state.control.append((user_id, kind)))
    monkeypatch.setattr(job_status, "publish_change", lambda *a, **k: None)
    monkeypatch.setattr(job_status, "publish_changes", lambda *a, **k: None)
    monkeypatch.setattr(download_task.Song, "from_dict", classmethod(lambda cls, data: data))
    monkeypatch.setattr(tagging, "is_supported_format", lambda path: False)

    class _Downloader:
        progress_handler = SimpleNamespace(update_callback=None)
        audio_providers = []

    monkeypatch.setattr(downloads, "get_downloader", lambda *a, **k: _Downloader())
    output = tmp_path / "song.opus"
    output.write_bytes(b"audio")

    def download_one(song, downloader):
        state.downloaded.append(song)
        return downloads.DownloadResult(song, output)

    monkeypatch.setattr(downloads, "download_one", download_one)
    state.db = committed_db
    return state


def _user(db, email="removed@example.com") -> User:
    user = User(email=email, is_admin=False)
    db.add(user)
    db.merge(AllowedEmail(email=email))
    db.flush()
    return user


def _job(db, user, *, state=JobState.EXPANDED, source_type=JobSourceType.ALBUM, tracks=()) -> Job:
    job = Job(user_id=user.id, source_url=f"https://open.spotify.com/album/{uuid.uuid4().hex[:8]}", source_type=source_type, state=state)
    db.add(job)
    db.flush()
    for index, (track_state, attempt_count) in enumerate(tracks):
        db.add(
            Track(
                job_id=job.id,
                spotify_track_id=f"{job.id.hex[:8]}{index}",
                song_json={"name": f"Song {index}"},
                state=track_state,
                attempt_count=attempt_count,
                scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1) if track_state == TrackState.WAITING else None,
            )
        )
    db.flush()
    return job


def _scenario(db):
    """The plan's four: album A started (one completed, the rest queued), artist B started (one
    waiting on the ladder), album C not started (all queued), artist D still expanding. Plus the
    jobs a removal never holds."""
    user = _user(db)
    jobs = SimpleNamespace(
        a=_job(db, user, tracks=[(TrackState.COMPLETED, 0), (TrackState.QUEUED, 0), (TrackState.QUEUED, 0)]),
        b=_job(db, user, source_type=JobSourceType.ARTIST, tracks=[(TrackState.WAITING, 1), (TrackState.PENDING, 0)]),
        c=_job(db, user, tracks=[(TrackState.QUEUED, 0), (TrackState.QUEUED, 0)]),
        d=_job(db, user, source_type=JobSourceType.ARTIST, state=JobState.EXPANDING),
        # A reclaimed track (`waiting`, no attempt) doesn't start a job.
        reclaimed=_job(db, user, tracks=[(TrackState.WAITING, 0), (TrackState.PENDING, 0)]),
        # A dedup result does.
        dedup=_job(db, user, tracks=[(TrackState.SKIPPED_DUPLICATE, 0), (TrackState.PENDING, 0)]),
        lookup=_job(db, user, tracks=[(TrackState.LOOKUP_FAILED, 0), (TrackState.PENDING, 0)]),
        cancelled=_job(db, user, state=JobState.CANCELLED, tracks=[(TrackState.CANCELLED, 0)]),
        failed=_job(db, user, state=JobState.FAILED),
    )
    archived = _job(db, user, tracks=[(TrackState.PENDING, 0)])
    archived.archived_at = datetime.now(timezone.utc)
    jobs.archived = archived
    db.commit()
    # Plain ids: the rows detach when the caller's session closes.
    return SimpleNamespace(id=user.id), SimpleNamespace(
        **{name: SimpleNamespace(id=job.id) for name, job in vars(jobs).items()}
    )


def _admin(db) -> uuid.UUID:
    admin = User(email="admin@example.com", is_admin=True)  # allowed without a row
    db.add(admin)
    db.commit()
    return admin.id


def _held(db, job_id) -> bool:
    return db.get(Job, job_id, populate_existing=True).held_at is not None


def test_the_removal_holds_exactly_the_unstarted_jobs(world):
    with world.db() as db:
        user, jobs = _scenario(db)
        ids = {name: job.id for name, job in vars(jobs).items()}
    with world.db() as db:
        removal = allowlist.remove(db, "Removed@Example.com")
    assert set(removal.held_job_ids) == {ids["c"], ids["d"], ids["reclaimed"]}
    with world.db() as db:
        for name, job_id in ids.items():
            assert _held(db, job_id) == (name in {"c", "d", "reclaimed"}), name
    assert world.control == [(user.id, events.CONTROL_REVOKED)]


def test_a_held_jobs_queued_messages_drain_with_no_attempt(world):
    with world.db() as db:
        _, jobs = _scenario(db)
        c_tracks = [t.id for t in db.query(Track).filter(Track.job_id == jobs.c.id)]
        breaker_before = db.get(WorkerState, 1).consecutive_failures
    with world.db() as db:
        allowlist.remove(db, "removed@example.com")
    for track_id in c_tracks:
        download_task.download_track(str(track_id))
    with world.db() as db:
        for track_id in c_tracks:
            track = db.get(Track, track_id)
            assert (track.state, track.scheduled_at) == (TrackState.PENDING, None)
        assert db.query(TrackAttempt).filter(TrackAttempt.track_id.in_(c_tracks)).count() == 0
        assert db.get(WorkerState, 1).consecutive_failures == breaker_before
    assert world.downloaded == [] and world.track_events == []


def test_a_started_jobs_tracks_still_download(world):
    with world.db() as db:
        _, jobs = _scenario(db)
        a_queued = [t.id for t in db.query(Track).filter(Track.job_id == jobs.a.id, Track.state == TrackState.QUEUED)]
    with world.db() as db:
        allowlist.remove(db, "removed@example.com")
    for track_id in a_queued:
        download_task.download_track(str(track_id))
    with world.db() as db:
        assert {db.get(Track, t).state for t in a_queued} == {TrackState.COMPLETED}
    assert len(world.downloaded) == len(a_queued)


def test_beat_dispatches_a_started_jobs_ladder_retry_when_due(world):
    with world.db() as db:
        _, jobs = _scenario(db)
        b_waiting = db.query(Track).filter(Track.job_id == jobs.b.id, Track.state == TrackState.WAITING).one()
        b_waiting.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        b_waiting_id = b_waiting.id
        db.commit()
    with world.db() as db:
        allowlist.remove(db, "removed@example.com")
    beat_task.dispatch_due_tracks()
    assert b_waiting_id in world.sent


def test_the_stale_sweep_and_beat_meet_the_same_gate(world, monkeypatch):
    """A held job's still-queued track, reclaimed by the stale sweep before its message drains:
    beat dispatches it again, and the gate puts it back to `pending` (no attempt)."""
    with world.db() as db:
        _, jobs = _scenario(db)
        track = db.query(Track).filter(Track.job_id == jobs.c.id).first()
        track_id = track.id
    with world.db() as db:
        allowlist.remove(db, "removed@example.com")
    with world.db() as db:
        db.get(Track, track_id).updated_at = _LONG_AGO
        db.commit()
    beat_task.dispatch_due_tracks()  # reclaims it (waiting, due now) ...
    beat_task.dispatch_due_tracks()  # ... and dispatches it
    assert track_id in world.sent
    download_task.download_track(str(track_id))
    with world.db() as db:
        track = db.get(Track, track_id)
        assert (track.state, track.scheduled_at) == (TrackState.PENDING, None)
        outcomes = [row.outcome.value for row in db.query(TrackAttempt).filter(TrackAttempt.track_id == track_id)]
        assert outcomes == ["held"]  # the reclaim's own row, never an attempt
    assert world.downloaded == []
    # Beat has nothing more to send: the track isn't due.
    world.sent.clear()
    beat_task.dispatch_due_tracks()
    assert track_id not in world.sent


def test_a_held_expanding_job_finishes_expanding_and_enqueues_nothing(world, monkeypatch):
    songs = [SimpleNamespace(song_id=f"song{i}", json={"name": f"Song {i}"}) for i in range(3)]
    monkeypatch.setattr(expansion, "expand", lambda url: songs)
    with world.db() as db:
        _, jobs = _scenario(db)
        d_id = jobs.d.id
    with world.db() as db:
        allowlist.remove(db, "removed@example.com")
    expand_task.expand_job(str(d_id))
    with world.db() as db:
        job = db.get(Job, d_id)
        assert job.state == JobState.EXPANDED and job.held_at is not None
        tracks = db.query(Track).filter(Track.job_id == d_id).all()
        assert len(tracks) == 3
        assert {(t.state, t.scheduled_at) for t in tracks} == {(TrackState.PENDING, None)}
    assert world.sent == []
    beat_task.dispatch_due_tracks()
    assert world.sent == []


def _list(db, admin_id, status_tokens=()):
    return list_jobs(
        db,
        user_id=admin_id,
        is_admin=True,
        view="others",
        q=None,
        status_tokens=list(status_tokens),
        source_type=None,
        include_archived=False,
        sort="created_at",
        dir="desc",
        limit=50,
        cursor=None,
    )


def test_held_shows_in_the_rollup_and_archiving_leaves_it_alone(world):
    with world.db() as db:
        user, jobs = _scenario(db)
        admin_id = _admin(db)
    with world.db() as db:
        allowlist.remove(db, "removed@example.com")
    with world.db() as db:
        page = _list(db, admin_id)
        by_id = {item["id"]: item for item in page["items"]}
        for job in (jobs.c, jobs.d):
            assert by_id[str(job.id)]["status"] == {"lifecycle": "held", "outcome": None}
            assert by_id[str(job.id)]["held_at"] is not None
        assert by_id[str(jobs.a.id)]["status"]["lifecycle"] == "active"
        assert page["counts_by_status"]["held"] == 3
        held_only = _list(db, admin_id, ["held"])
        assert {item["id"] for item in held_only["items"]} == {str(jobs.c.id), str(jobs.d.id), str(jobs.reclaimed.id)}
        archived = archive.archive_jobs(db, user.id)
        assert not {job.id for job in archived} & {jobs.c.id, jobs.d.id, jobs.reclaimed.id}


def test_derive_rollup_agrees_with_the_sql():
    assert rollup.derive_rollup(JobState.EXPANDED, {"pending": 2}, held=True).key == "held"
    assert rollup.derive_rollup(JobState.EXPANDING, {}, held=True).key == "held"
    assert rollup.derive_rollup(JobState.CANCELLED, {}, held=True).key == "cancelled"
    assert rollup.derive_rollup(JobState.FAILED, {}, held=True).key == "failed"
    assert "held" in rollup.VALID_STATUS_TOKENS


def test_a_removed_owners_watched_job_isnt_re_expanded(world, monkeypatch):
    claimed = []
    monkeypatch.setattr(watch, "claim_run", lambda job_id: claimed.append(job_id) or "token")
    monkeypatch.setattr(watch, "started_this_hour", lambda db, now: 0)
    monkeypatch.setattr(expand_task.expand_job, "delay", lambda *a, **k: None)
    with world.db() as db:
        removed = _user(db)
        kept = _user(db, "kept@example.com")
        admin = User(email="admin@example.com", is_admin=True)  # allowed without a row
        db.add(admin)
        db.flush()
        admin_id = admin.id
        due = datetime.now(timezone.utc) - timedelta(minutes=1)
        watched = {}
        for name, owner in (("removed", removed), ("kept", kept), ("admin", admin)):
            job = _job(db, owner, source_type=JobSourceType.PLAYLIST, tracks=[(TrackState.COMPLETED, 0)])
            job.watch_interval_hours, job.next_expand_at = 24, due
            watched[name] = job.id
        db.commit()
    with world.db() as db:
        allowlist.remove(db, "removed@example.com")
    beat_task.dispatch_due_tracks()
    assert set(claimed) == {watched["kept"], watched["admin"]}
    with world.db() as db:
        # Still due: the first tick after the address is back runs it.
        assert db.get(Job, watched["removed"]).next_expand_at == due
        allowlist.add(db, "removed@example.com", db.get(User, admin_id))
    claimed.clear()
    beat_task.dispatch_due_tracks()
    assert claimed == [watched["removed"]]


def test_re_adding_resumes_the_held_jobs_once_each(world):
    with world.db() as db:
        user, jobs = _scenario(db)
        admin_id = _admin(db)
        c_tracks = {t.id for t in db.query(Track).filter(Track.job_id == jobs.c.id)}
        reclaimed_pending = {
            t.id for t in db.query(Track).filter(Track.job_id == jobs.reclaimed.id, Track.state == TrackState.PENDING)
        }
    with world.db() as db:
        allowlist.remove(db, "removed@example.com")
    for track_id in c_tracks:
        download_task.download_track(str(track_id))  # drained back to pending
    world.sent.clear()
    with world.db() as db:
        addition = allowlist.add(db, "removed@example.com", db.get(User, admin_id))
    assert addition.user_id == user.id
    assert set(addition.resumed_job_ids) == {jobs.c.id, jobs.d.id, jobs.reclaimed.id}
    assert sorted(world.sent) == sorted(c_tracks | reclaimed_pending)
    assert len(world.sent) == len(set(world.sent))
    with world.db() as db:
        assert not any(_held(db, job_id) for job_id in (jobs.c.id, jobs.d.id))
        # Sent, so no marker is left for beat to send them a second time.
        assert {db.get(Track, t).scheduled_at for t in c_tracks} == {None}
    world.sent.clear()
    beat_task.dispatch_due_tracks()
    assert not set(world.sent) & c_tracks
    for track_id in c_tracks:
        download_task.download_track(str(track_id))
    with world.db() as db:
        assert {db.get(Track, t).state for t in c_tracks} == {TrackState.COMPLETED}


def test_a_broker_failure_on_resume_leaves_the_rest_to_beat(world, monkeypatch):
    with world.db() as db:
        _, jobs = _scenario(db)
        admin_id = _admin(db)
        c_tracks = [t.id for t in db.query(Track).filter(Track.job_id == jobs.c.id)]
    with world.db() as db:
        allowlist.remove(db, "removed@example.com")
    for track_id in c_tracks:
        download_task.download_track(str(track_id))

    def refuse(track_id):
        raise ConnectionError("broker down")

    monkeypatch.setattr(download_task.download_track, "delay", refuse)
    with world.db() as db:
        assert allowlist.add(db, "removed@example.com", db.get(User, admin_id)).enqueued == 0
    monkeypatch.setattr(download_task.download_track, "delay", lambda track_id: world.sent.append(uuid.UUID(track_id)))
    world.sent.clear()
    beat_task.dispatch_due_tracks()
    assert set(c_tracks) <= set(world.sent)


# --- the race ---------------------------------------------------------------------------


def _one_queued_track(db) -> tuple[uuid.UUID, uuid.UUID]:
    user = _user(db)
    job = _job(db, user, tracks=[(TrackState.QUEUED, 0)])
    db.commit()
    return job.id, db.query(Track.id).filter(Track.job_id == job.id).scalar()


def test_race_the_track_commits_downloading_first_and_the_job_runs_on(world, monkeypatch):
    with world.db() as db:
        job_id, track_id = _one_queued_track(db)
    gate = Gate("download_track: job row FOR SHARE held, before the downloading commit")
    real_held = download_task._job_held
    calls = []

    def held_then_pause(db, job):
        # The second read is the claim's (the first is the gate's, committed at once).
        answer = real_held(db, job)
        calls.append(answer)
        if len(calls) == 2:
            gate()
        return answer

    monkeypatch.setattr(download_task, "_job_held", held_then_pause)
    task = Thread(download_task.download_track, str(track_id), name="download_track")
    gate.wait_reached()

    def run_removal():
        with world.db() as db:
            return allowlist.remove(db, "removed@example.com")

    removal = Thread(run_removal, name="removal")
    assert blocked_or_done(removal) == "blocked"  # its FOR UPDATE waits on the FOR SHARE
    gate.open()
    task.join()
    assert removal.join().held_job_ids == []
    with world.db() as db:
        assert db.get(Job, job_id).held_at is None
        assert db.get(Track, track_id).state == TrackState.COMPLETED
    assert len(world.downloaded) == 1


def test_race_the_removal_commits_first_and_the_track_never_starts(world):
    with world.db() as db:
        job_id, track_id = _one_queued_track(db)
    gate = Gate("removal: hold written, before its commit")
    removal_db = world.db()
    event.listen(removal_db, "before_commit", gate, once=True)
    removal = Thread(allowlist.remove, removal_db, "removed@example.com", name="removal")
    gate.wait_reached()
    task = Thread(download_task.download_track, str(track_id), name="download_track")
    # The task passed its plain-read gate (nothing committed yet) and now waits on the row lock.
    assert blocked_or_done(task) == "blocked"
    gate.open()
    assert removal.join().held_job_ids == [job_id]
    task.join()
    removal_db.close()
    with world.db() as db:
        assert db.get(Job, job_id).held_at is not None
        track = db.get(Track, track_id)
        assert track.state == TrackState.PENDING
        assert db.query(TrackAttempt).filter(TrackAttempt.track_id == track_id).count() == 0
    assert world.downloaded == []


def test_race_a_re_add_waits_for_the_gate_and_then_enqueues_the_track(world, monkeypatch):
    """Review round 1: the gate's read and its `pending` write are one locked transaction. A
    re-add landing between them (unlocked, it did) found the track still `queued`, claimed
    nothing, and the write then left it `pending` with no message and no schedule, forever."""
    with world.db() as db:
        job_id, track_id = _one_queued_track(db)
        admin_id = _admin(db)
    with world.db() as db:
        allowlist.remove(db, "removed@example.com")
    gate = Gate("download_track: the hold gate's read, before its pending write")
    real_held = download_task._job_held

    def held_then_pause(db, job):
        answer = real_held(db, job)
        if answer:
            gate()
        return answer

    monkeypatch.setattr(download_task, "_job_held", held_then_pause)
    task = Thread(download_task.download_track, str(track_id), name="download_track")
    gate.wait_reached()

    def run_add():
        with world.db() as db:
            return allowlist.add(db, "removed@example.com", db.get(User, admin_id))

    add = Thread(run_add, name="re-add")
    assert blocked_or_done(add) == "blocked"  # its job lock waits on the gate's FOR SHARE
    gate.open()
    task.join()
    addition = add.join()
    assert addition.resumed_job_ids == [job_id]
    assert world.sent == [track_id]  # enqueued once, by the re-add
    with world.db() as db:
        assert db.get(Track, track_id).state == TrackState.PENDING
        assert db.get(Job, job_id).held_at is None


def test_a_job_with_nothing_to_run_isnt_held(world):
    """Review round 1: an empty expanded job (an empty playlist) or one whose tracks were all
    cancelled has nothing a hold could stop; holding it offered a cancel that answers 409."""
    with world.db() as db:
        user = _user(db)
        empty = _job(db, user, source_type=JobSourceType.PLAYLIST).id
        all_cancelled = _job(db, user, tracks=[(TrackState.CANCELLED, 0)]).id
        db.commit()
    with world.db() as db:
        assert allowlist.remove(db, "removed@example.com").held_job_ids == []


def test_a_re_expansion_already_queued_adds_nothing_after_the_removal(world, monkeypatch):
    """Review round 1: beat stops starting a removed owner's watched jobs; a run already queued
    (a "check now", a tick just before) ends without adding a track."""
    monkeypatch.setattr(watch, "start_run", lambda job_id, marker: True)
    read = []
    monkeypatch.setattr(expansion, "expand", lambda url: read.append(url) or [])
    with world.db() as db:
        user = _user(db)
        job = _job(db, user, source_type=JobSourceType.PLAYLIST, tracks=[(TrackState.COMPLETED, 0)])
        job.watch_interval_hours = 24
        job_id = job.id
        db.commit()
    with world.db() as db:
        allowlist.remove(db, "removed@example.com")
    expand_task.expand_job(str(job_id), reexpand=True, marker="token")
    with world.db() as db:
        assert db.query(Track).filter(Track.job_id == job_id).count() == 1
