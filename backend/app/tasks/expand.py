import logging
import uuid

from sqlalchemy import update

from app.db import SessionLocal
from app.models import Job, JobState, Track, TrackState
from app.services import events, expansion
from app.services.serializers import track_song_meta
from app.tasks.celery_app import celery_app
from app.tasks.download import download_track

logger = logging.getLogger(__name__)


def _enqueue_pending_tracks(db, job: Job, why: str) -> None:
    """Enqueues `job`'s tracks still `pending`. For a job whose EXPANDED commit landed but
    whose enqueue loop never ran to the end -- the task was killed (and redelivered), or
    the refresh/publish right after the commit raised. (A broker error *inside* the
    success path's own enqueue loop is not covered: the task fails, is acked, and the
    rest stay `pending` -- see docs/GOTCHAS.md's v34.1 entry.) Nothing else ever picks a
    `pending` track up (beat dispatches only `waiting`,
    the stale sweep reclaims only `queued`/`downloading`). A pending track that the
    interrupted run did enqueue gets a second message; download_track drops any message
    whose track has already moved on to `waiting`/`lookup_failed`, so it can't jump the
    retry ladder."""
    pending = (
        db.query(Track.id)
        .filter(Track.job_id == job.id, Track.state == TrackState.PENDING)
        .all()
    )
    logger.info("expand_job: job %s %s; enqueueing %d pending tracks", job.id, why, len(pending))
    for (track_id,) in pending:
        download_track.delay(str(track_id))


@celery_app.task(name="app.tasks.expand.expand_job")
def expand_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None:
            logger.warning("expand_job: job %s not found", job_id)
            return
        # Cancelled while still queued for worker-expand: the user said "don't download
        # this", so don't even spend the Spotify round trips (minutes, for an artist).
        # `failed` likewise has nothing left to do.
        if job.state in (JobState.CANCELLED, JobState.FAILED):
            logger.info("expand_job: job %s is %s, not expanding; skipping", job_id, job.state.value)
            return
        # A redelivery (acks_late) of a run that committed EXPANDED but died before it
        # finished enqueueing: the tracks exist, so don't re-expand (that would insert
        # every track a second time).
        if job.state == JobState.EXPANDED:
            _enqueue_pending_tracks(db, job, "already expanded (redelivery)")
            return

        events.publish_job_event(job.user_id, job.id, job.state.value)

        try:
            songs = expansion.expand(job.source_url)
            tracks = []
            for song in songs:
                track = Track(
                    job_id=job.id,
                    spotify_track_id=song.song_id,
                    song_json=song.json,
                )
                db.add(track)
                tracks.append(track)

            # A conditional UPDATE, not a blind attribute assignment: expansion is a
            # multi-second Spotify round trip, long enough for a `DELETE /api/jobs/{id}`
            # cancel to land mid-flight. A plain `job.state = EXPANDED; db.commit()` would
            # silently clobber that cancel back to `expanded`. The WHERE clause makes the
            # write a no-op if the row moved on while we were running, and db.refresh
            # reads the row's real current state afterward rather than trusting the
            # `job` object loaded at task start.
            result = db.execute(
                update(Job)
                .where(Job.id == job.id, Job.state == JobState.EXPANDING)
                .values(state=JobState.EXPANDED)
            )
            if result.rowcount == 0:
                db.refresh(job)
                already_has_tracks = (
                    db.query(Track.id).filter(Track.job_id == job.id).first() is not None
                )
                if job.state != JobState.CANCELLED or already_has_tracks:
                    # Another run of this same job (a redelivery overlapping the
                    # original) already expanded it -- and possibly the user cancelled it
                    # since: its tracks are the real ones, so drop this run's uncommitted
                    # copies instead of committing a second set.
                    db.rollback()
                    logger.info(
                        "expand_job: job %s was expanded by another run; discarding this one's tracks",
                        job_id,
                    )
                    return
            db.commit()
            db.refresh(job)

            if job.state == JobState.CANCELLED:
                for track in tracks:
                    track.state = TrackState.CANCELLED
                db.commit()
                for track in tracks:
                    events.publish_track_event(
                        job.user_id,
                        track.id,
                        track.job_id,
                        track.state.value,
                        **track_song_meta(track.song_json),
                    )
                return

            events.publish_job_event(job.user_id, job.id, job.state.value)
        except Exception as exc:
            # Covers both expansion.expand() itself (assorted exception types spotdl raises
            # for malformed/unreachable URLs) and any DB error while inserting tracks (e.g. a
            # NOT NULL violation from a song missing spotify_track_id) — either way the job
            # must land in `failed` with a readable error, never hang in `expanding` forever.
            logger.warning("expand_job: job %s failed to expand: %s", job_id, exc)
            db.rollback()
            # Conditional for the same reason as the success path's UPDATE: a cancel that
            # landed mid-expansion must stay `cancelled`. The user already said "don't
            # download this"; relabelling it `failed` afterwards would put it back in
            # their incoming list as an error they never asked about.
            result = db.execute(
                update(Job)
                .where(Job.id == job.id, Job.state == JobState.EXPANDING)
                .values(state=JobState.FAILED, error=str(exc))
            )
            db.commit()
            if result.rowcount == 0:
                db.refresh(job)
                if job.state == JobState.EXPANDED:
                    # The failure came *after* the EXPANDED commit (e.g. the refresh or
                    # a publish above raised): the tracks are committed, so enqueue them
                    # rather than leave them `pending` forever under an acked task.
                    _enqueue_pending_tracks(db, job, "failed after its EXPANDED commit")
                    return
                logger.info(
                    "expand_job: job %s is %s, not expanding; not marking it failed",
                    job_id,
                    job.state.value,
                )
                return
            db.refresh(job)
            events.publish_job_event(job.user_id, job.id, job.state.value, error=job.error)
        else:
            for track in tracks:
                download_track.delay(str(track.id))
    finally:
        db.close()
