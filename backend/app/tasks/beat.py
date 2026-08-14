import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.config import get_settings
from app.db import SessionLocal
from app.models import Job, Track, TrackState, UserSettings
from app.services import archive, events, retry
from app.services.serializers import track_song_meta
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
        .returning(Track.id, Track.job_id, Track.song_json)
    ).all()
    db.commit()
    if not reclaimed:
        return

    # One bulk lookup for every reclaimed track's owner, never a per-row query
    # (CLAUDE.md invariant) -- the RETURNING clause above only has job_id to offer.
    job_ids = {job_id for _, job_id, _ in reclaimed}
    owner_by_job = dict(db.execute(select(Job.id, Job.user_id).where(Job.id.in_(job_ids))).all())
    for track_id, job_id, song_json in reclaimed:
        logger.warning(
            "dispatch_due_tracks: reclaimed stale track %s (stuck past %s)",
            track_id,
            threshold,
        )
        events.publish_track_event(
            owner_by_job[job_id],
            track_id,
            job_id,
            TrackState.WAITING.value,
            scheduled_at=now,
            **track_song_meta(song_json),
        )


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

        due_rows = db.execute(
            select(Track, Job.user_id)
            .join(Job, Track.job_id == Job.id)
            .where(Track.state == TrackState.WAITING, Track.scheduled_at <= now)
            .order_by(Job.priority.desc(), Track.scheduled_at.asc())
            .with_for_update(skip_locked=True, of=Track)
        ).all()
        due_tracks = [track for track, _ in due_rows]
        for track in due_tracks:
            track.state = TrackState.QUEUED
        db.commit()

        for track, user_id in due_rows:
            events.publish_track_event(
                user_id,
                track.id,
                track.job_id,
                track.state.value,
                attempt_count=track.attempt_count,
                **track_song_meta(track.song_json),
            )

        for track in due_tracks:
            download_track.delay(str(track.id))
    finally:
        db.close()


@celery_app.task(name="app.tasks.beat.archive_due_jobs")
def archive_due_jobs() -> None:
    """Hourly (not every 30s like dispatch_due_tracks -- this is housekeeping, and it
    competes with that task for the same worker-meta process). Iterates every user with
    a non-null `retention_days` and archives their eligible jobs older than that many
    days; a null retention_days (the default) means this user is never touched."""
    db = SessionLocal()
    try:
        user_rows = db.execute(
            select(UserSettings.user_id, UserSettings.retention_days).where(
                UserSettings.retention_days.is_not(None)
            )
        ).all()
        for user_id, retention_days in user_rows:
            jobs = archive.archive_jobs(db, user_id, older_than=timedelta(days=retention_days))
            for job in jobs:
                logger.info("archive_due_jobs: archived job %s for user %s", job.id, user_id)
                events.publish_job_event(user_id, job.id, job.state.value, archived=True)
    finally:
        db.close()
