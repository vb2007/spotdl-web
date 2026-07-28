import logging
import uuid

from spotdl.types.song import Song

from app.config import get_settings
from app.db import SessionLocal
from app.models import DownloadedTrack, Track, TrackState
from app.services import dedup, downloads
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

        existing_path = dedup.is_already_downloaded(track.spotify_track_id)
        if existing_path is not None:
            track.state = TrackState.SKIPPED_DUPLICATE
            track.output_path = str(existing_path)
            db.commit()
            return

        track.state = TrackState.DOWNLOADING
        db.commit()

        settings = get_settings()
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
            db.commit()
        except Exception as exc:
            # v06 replaces this branch with ladder/breaker error classification
            # (AudioProviderError vs LookupError vs other) — for now every failure is
            # naive: log it fully and mark the track failed, without taking down the
            # rest of the job's tracks.
            logger.exception("download_track: track %s failed", track_id)
            db.rollback()
            track = db.get(Track, uuid.UUID(track_id))
            track.state = TrackState.FAILED
            track.last_error = str(exc)
            db.commit()
    finally:
        db.close()
