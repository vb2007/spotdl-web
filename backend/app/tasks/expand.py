import logging
import uuid

from app.db import SessionLocal
from app.models import Job, JobState, Track
from app.services import expansion
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.expand.expand_job")
def expand_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None:
            logger.warning("expand_job: job %s not found", job_id)
            return

        try:
            songs = expansion.expand(job.source_url)
        except Exception as exc:
            # get_simple_songs raises assorted exception types (QueryError, SpotifyError,
            # ValueError, network errors) for malformed/unreachable URLs — all terminal here.
            logger.warning("expand_job: job %s failed to expand: %s", job_id, exc)
            job.state = JobState.FAILED
            job.error = str(exc)
            db.commit()
            return

        for song in songs:
            db.add(
                Track(
                    job_id=job.id,
                    spotify_track_id=song.song_id,
                    song_json=song.json,
                )
            )
        job.state = JobState.EXPANDED
        db.commit()
    finally:
        db.close()
