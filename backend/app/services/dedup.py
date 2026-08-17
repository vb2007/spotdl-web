"""Download dedup ledger (`downloaded_tracks`) and startup disk reconciliation."""

import logging
from pathlib import Path

from app.config import get_settings
from app.db import SessionLocal
from app.models import DownloadedTrack
from app.services import app_settings

logger = logging.getLogger(__name__)


def is_already_downloaded(spotify_track_id: str) -> Path | None:
    db = SessionLocal()
    try:
        row = db.get(DownloadedTrack, spotify_track_id)
        return Path(row.file_path) if row is not None else None
    finally:
        db.close()


def _mount_looks_missing(root: Path) -> bool:
    return not root.is_dir() or not any(root.iterdir())


def reconcile_disk() -> None:
    """Drops ledger rows whose file no longer exists on disk, so a manually-deleted
    track gets re-downloaded on the next submission. Run once on worker-meta boot."""

    db = SessionLocal()
    try:
        rows = db.query(DownloadedTrack).all()

        # Guard against a mount-not-there-yet false positive (v12): DOWNLOAD_OUTPUT_DIR
        # switched from a Docker-managed named volume to a host bind mount in that
        # version. If that host directory is missing or genuinely empty while the ledger
        # already holds rows, every file below would look "not there" and this would
        # prune the *entire* dedup ledger on the very first boot against the new mount —
        # e.g. a typo'd DOWNLOADS_DIR, a bind source that hasn't been created yet, or the
        # one-time named-volume-to-host-dir copy (see docs/DEPLOYMENT.md) not having run
        # yet. Refuse to prune in that case rather than silently forgetting every
        # previously-downloaded track and re-downloading all of them.
        #
        # v28 extends this per-root rather than as a second blanket check: a moved
        # track's file_path now lives under library_target_dir instead, and that mount
        # needs the exact same protection (this is what CLAUDE.md's "reconcile_disk()
        # must be able to see the library mount" invariant is guarding against) — but a
        # library root that's simply *unused* (no sweep has ever moved anything there
        # yet, so it's legitimately empty) must not block pruning real, missing
        # downloads-root rows the way a single blanket "refuse everything" check would.
        # Skipping only the rows that actually live under whichever specific root looks
        # unmounted keeps both guarantees.
        downloads_root = Path(get_settings().download_output_dir)
        library_root = Path(app_settings.get_library_settings(db).library_target_dir)
        db.commit()

        downloads_missing = bool(rows) and _mount_looks_missing(downloads_root)
        library_missing = bool(rows) and _mount_looks_missing(library_root)
        if downloads_missing:
            logger.error(
                "reconcile_disk: %s is missing or empty but %d ledger rows exist — "
                "refusing to prune rows under it (mount not attached yet?)",
                downloads_root,
                len(rows),
            )
        if library_missing:
            logger.error(
                "reconcile_disk: %s is missing or empty but %d ledger rows exist — "
                "refusing to prune rows under it (mount not attached yet?)",
                library_root,
                len(rows),
            )

        removed = 0
        skipped = 0
        for row in rows:
            path = Path(row.file_path)
            if downloads_missing and path.is_relative_to(downloads_root):
                skipped += 1
                continue
            if library_missing and path.is_relative_to(library_root):
                skipped += 1
                continue
            if not path.exists():
                db.delete(row)
                removed += 1
        db.commit()
        logger.info(
            "reconcile_disk: checked %d ledger rows, removed %d with missing files%s",
            len(rows),
            removed,
            f" ({skipped} skipped, root looked unmounted)" if skipped else "",
        )
    finally:
        db.close()
