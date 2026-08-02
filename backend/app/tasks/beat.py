import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Job, Track, TrackState
from app.services import events, retry
from app.tasks.celery_app import celery_app
from app.tasks.download import download_track

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.beat.dispatch_due_tracks")
def dispatch_due_tracks() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        worker_state = retry.get_worker_state(db)
        db.commit()
        if retry.breaker_active(worker_state, now):
            # No query at all while tripped/paused — avoids a thundering herd of tracks
            # all becoming due at once right when the breaker releases.
            return

        due_tracks = (
            db.execute(
                select(Track)
                .join(Job, Track.job_id == Job.id)
                .where(Track.state == TrackState.WAITING, Track.scheduled_at <= now)
                .order_by(Job.priority.desc(), Track.scheduled_at.asc())
                .with_for_update(skip_locked=True, of=Track)
            )
            .scalars()
            .all()
        )
        for track in due_tracks:
            track.state = TrackState.QUEUED
        db.commit()

        for track in due_tracks:
            events.publish_track_event(
                track.id, track.job_id, track.state.value, attempt_count=track.attempt_count
            )

        for track in due_tracks:
            download_track.delay(str(track.id))
    finally:
        db.close()
