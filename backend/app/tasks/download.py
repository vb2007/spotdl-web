import logging
import uuid
from datetime import datetime, timezone

from spotdl.types.song import Song

from app.config import get_settings
from app.db import SessionLocal
from app.models import DownloadedTrack, Track, TrackState
from app.services import dedup, downloads, proxies, retry
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

        settings = get_settings()

        # Attempt 1 is always direct (per the locked "direct first -> wait out the ladder
        # -> then proxy" strategy); only the *following* attempt, once its ladder wait has
        # already elapsed, prefers a proxy.
        proxy = proxies.pick_proxy(db) if track.attempt_count >= 1 else None
        proxy_id = proxy.id if proxy is not None else None
        proxy_url = proxy.url if proxy is not None else None

        track.state = TrackState.DOWNLOADING
        if proxy_id is not None:
            track.used_proxy_id = proxy_id
            logger.info("download_track: track %s attempting via proxy %s", track_id, proxy_url)
        db.commit()

        try:
            song = Song.from_dict(track.song_json)
            downloader = downloads.get_downloader(
                settings.default_format, settings.default_bitrate, proxy=proxy_url
            )
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
            if proxy_id is not None:
                proxies.record_proxy_result(db, proxy_id, success=True)
            retry.record_success(db, track)
            db.commit()
        except Exception as exc:
            logger.exception("download_track: track %s failed", track_id)
            db.rollback()
            track = db.get(Track, uuid.UUID(track_id))
            error_type = retry.classify_error(exc)
            retry.record_failure(db, track, error_type, str(exc))
            if proxy_id is not None:
                proxies.record_proxy_result(db, proxy_id, success=False)
            db.commit()
    finally:
        db.close()
