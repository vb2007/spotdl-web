"""Download dedup ledger (`downloaded_tracks`) and startup disk reconciliation."""

import logging
from pathlib import Path

from app.config import get_settings
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

        # Guard against a mount-not-there-yet false positive (v12): DOWNLOAD_OUTPUT_DIR
        # switched from a Docker-managed named volume to a host bind mount in this
        # version. If that host directory is missing or genuinely empty while the ledger
        # already holds rows, every file below would look "not there" and this would
        # prune the *entire* dedup ledger on the very first boot against the new mount —
        # e.g. a typo'd DOWNLOADS_DIR, a bind source that hasn't been created yet, or the
        # one-time named-volume-to-host-dir copy (see docs/DEPLOYMENT.md) not having run
        # yet. Refuse to prune in that case rather than silently forgetting every
        # previously-downloaded track and re-downloading all of them.
        root = Path(get_settings().download_output_dir)
        if rows and (not root.is_dir() or not any(root.iterdir())):
            logger.error(
                "reconcile_disk: %s is missing or empty but %d ledger rows exist — "
                "refusing to prune (mount not attached yet?)",
                root,
                len(rows),
            )
            return

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
