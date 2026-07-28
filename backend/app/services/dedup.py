"""Download dedup ledger (`downloaded_tracks`) and startup disk reconciliation."""

import logging
from pathlib import Path

from app.db import SessionLocal
from app.models import DownloadedTrack

logger = logging.getLogger(__name__)


def is_already_downloaded(spotify_track_id: str) -> Path | None:
    db = SessionLocal()
    try:
        row = db.get(DownloadedTrack, spotify_track_id)
        return Path(row.file_path) if row is not None else None
    finally:
        db.close()


def reconcile_disk() -> None:
    """Drops ledger rows whose file no longer exists on disk, so a manually-deleted
    track gets re-downloaded on the next submission. Run once on worker-meta boot."""

    db = SessionLocal()
    try:
        rows = db.query(DownloadedTrack).all()
        removed = 0
        for row in rows:
            if not Path(row.file_path).exists():
                db.delete(row)
                removed += 1
        db.commit()
        logger.info(
            "reconcile_disk: checked %d ledger rows, removed %d with missing files",
            len(rows),
            removed,
        )
    finally:
        db.close()
