import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.config import get_settings
from app.db import SessionLocal
from app.models import Job, Track, TrackState
from app.services import events, retry
from app.tasks.celery_app import celery_app
from app.tasks.download import download_track

logger = logging.getLogger(__name__)


def stale_track_after() -> timedelta:
    """A track stuck in DOWNLOADING/QUEUED past this long means whatever was supposed to
    finish it (a crashed worker, a container restart during a hard-killed download) never
    did. celery_app.py's task_acks_late + visibility_timeout is the primary redelivery
    mechanism for this; the sweep below is the independent DB-level safety net for cases
    that mechanism doesn't cover (e.g. a message already acked by a pre-fix worker, or the
    broker losing state). Read from settings (not a module constant) so
    STALE_TRACK_AFTER_SECONDS can be shortened for verification the same way
    LADDER_SECONDS already is — the 1800s production default would otherwise make manually
    confirming this sweep fires a 30-minute wait. With worker-dl's --concurrency=1,
    reclaiming a track that's genuinely still running just means a duplicate attempt,
    which the dedup ledger already absorbs."""
    return timedelta(seconds=get_settings().stale_track_after_seconds)


def _reclaim_stale_tracks(db) -> None:
    now = datetime.now(timezone.utc)
    threshold = stale_track_after()
    stale_cutoff = now - threshold
    reclaimed = db.execute(
        update(Track)
        .where(
            Track.state.in_([TrackState.DOWNLOADING, TrackState.QUEUED]),
            Track.updated_at < stale_cutoff,
        )
        .values(state=TrackState.WAITING, scheduled_at=now)
        .returning(Track.id, Track.job_id)
    ).all()
    db.commit()
    for track_id, job_id in reclaimed:
        logger.warning(
            "dispatch_due_tracks: reclaimed stale track %s (stuck past %s)",
            track_id,
            threshold,
        )
        events.publish_track_event(track_id, job_id, TrackState.WAITING.value, scheduled_at=now)


@celery_app.task(name="app.tasks.beat.dispatch_due_tracks")
def dispatch_due_tracks() -> None:
    db = SessionLocal()
    try:
        # Independent of the breaker/pause gate below — a stuck track needs reclaiming
        # regardless, it just won't be re-dispatched until the breaker clears.
        _reclaim_stale_tracks(db)

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
