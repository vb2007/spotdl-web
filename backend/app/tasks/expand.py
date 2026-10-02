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


@celery_app.task(name="app.tasks.expand.expand_job")
def expand_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None:
            logger.warning("expand_job: job %s not found", job_id)
            return
        # Cancelled while still queued for worker-meta: the user said "don't download
        # this", so don't even spend the Spotify round trips (minutes, for an artist).
        if job.state != JobState.EXPANDING:
            logger.info("expand_job: job %s is %s, not expanding; skipping", job_id, job.state.value)
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
            db.execute(
                update(Job)
                .where(Job.id == job.id, Job.state == JobState.EXPANDING)
                .values(state=JobState.EXPANDED)
            )
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
                logger.info("expand_job: job %s was cancelled mid-expansion; keeping it cancelled", job_id)
                return
            db.refresh(job)
            events.publish_job_event(job.user_id, job.id, job.state.value, error=job.error)
        else:
            for track in tracks:
                download_track.delay(str(track.id))
    finally:
        db.close()
