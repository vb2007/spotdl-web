import logging
import uuid
from datetime import datetime, timezone

from spotdl.types.song import Song

from app.config import get_settings
from app.db import SessionLocal
from app.models import DownloadedTrack, Track, TrackState
from app.services import dedup, downloads, retry
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.download.download_track")
def download_track(track_id: str) -> None:
    db = SessionLocal()
    try:
        track = db.get(Track, uuid.UUID(track_id))
        if track is None:
            logger.warning("download_track: track %s not found", track_id)
            return

        # Covers the race where this task was already enqueued just before the breaker
        # tripped (or the worker was paused) — dispatch_due_tracks is the primary gate and
        # normally won't enqueue in this state at all.
        now = datetime.now(timezone.utc)
        worker_state = retry.get_worker_state(db)
        if retry.breaker_active(worker_state, now):
            track.state = TrackState.WAITING
            track.scheduled_at = worker_state.breaker_tripped_until or (now + retry.next_delay(0))
            db.commit()
            return

        existing_path = dedup.is_already_downloaded(track.spotify_track_id)
        if existing_path is not None:
            track.state = TrackState.SKIPPED_DUPLICATE
            track.output_path = str(existing_path)
            db.commit()
            return

        track.state = TrackState.DOWNLOADING
        db.commit()

        settings = get_settings()
        # Proxy escalation seam: second+ attempts should prefer a proxy once one exists.
        # TODO(v07): draw a proxy from the pool when use_proxy is True and pass it to
        # get_downloader — no pool exists yet, so this only marks the decision point.
        use_proxy = track.attempt_count >= 1  # noqa: F841
        try:
            song = Song.from_dict(track.song_json)
            downloader = downloads.get_downloader(settings.default_format, settings.default_bitrate)
            _, output_path = downloads.download_one(song, downloader)
            if output_path is None:
                raise RuntimeError("spotdl returned no output file for this track")

            track.state = TrackState.COMPLETED
            track.output_path = str(output_path)
            db.merge(
                DownloadedTrack(
                    spotify_track_id=track.spotify_track_id,
                    file_path=str(output_path),
                    format=settings.default_format,
                    bitrate=settings.default_bitrate,
                )
            )
            retry.record_success(db, track)
            db.commit()
        except Exception as exc:
            logger.exception("download_track: track %s failed", track_id)
            db.rollback()
            track = db.get(Track, uuid.UUID(track_id))
            error_type = retry.classify_error(exc)
            retry.record_failure(db, track, error_type, str(exc))
            db.commit()
    finally:
        db.close()
