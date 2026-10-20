"""Download dedup ledger (`downloaded_tracks`) and startup disk reconciliation."""

import logging
from pathlib import Path

from sqlalchemy.exc import InvalidRequestError

from app.config import get_settings
from app.db import SessionLocal
from app.models import DownloadedTrack
from app.services import app_settings

logger = logging.getLogger(__name__)


class LedgerRootUnavailable(Exception):
    """A ledger row's file is missing, but it lives under a root that looks unmounted in
    this process, so "missing" can't be told apart from "can't see it" (v38)."""

    def __init__(self, root: Path, path: Path) -> None:
        super().__init__(f"{path} is under {root}, which is missing or empty")
        self.root = root
        self.path = path


def is_already_downloaded(spotify_track_id: str) -> Path | None:
    """None means "attempt a real download" -- to the caller, a stale ledger row (file
    genuinely gone, see reconcile_disk()) must be indistinguishable from no row at all.
    v31: this used to trust `row.file_path` completely, the same gap `download_track`'s
    own success path had -- a track could be marked `SKIPPED_DUPLICATE` pointing at a
    ledger entry whose file doesn't exist, which is strictly worse than a false
    `COMPLETED` (it never even attempts a real download to fix itself). Doesn't touch or
    delete the stale row here -- that's reconcile_disk()'s job at boot, kept as the one
    place that mutates the ledger for "file is gone," so this function stays read-only.

    v38: a missing file under a root that looks unmounted here raises
    LedgerRootUnavailable instead of returning None -- reconcile_disk()'s own guard.
    worker-dl didn't mount the library before v38, so every file the library sort had
    moved read as gone and was downloaded again; a future mount mistake (or an admin
    repointing library_target_dir) must not repeat that silently. A miss also re-reads
    the row first, in case the library sweep moved the file mid-check."""
    db = SessionLocal()
    try:
        row = db.get(DownloadedTrack, spotify_track_id)
        if row is None:
            return None
        path = Path(row.file_path)
        if path.exists():
            return path
        # The library sweep (worker-expand) commits a row's repoint *before* unlinking the
        # source, so a file missing at the path read above may just have moved: re-read the
        # row and check its current path, as reconcile_disk() does (v34.1).
        try:
            db.refresh(row)
        except InvalidRequestError:
            return None  # reconcile_disk() dropped the row meanwhile: no row is a miss
        path = Path(row.file_path)
        if path.exists():
            return path
        roots = (
            Path(get_settings().download_output_dir),
            Path(app_settings.get_library_settings(db).library_target_dir),
        )
        db.commit()
        for root in roots:
            if path.is_relative_to(root) and _mount_looks_missing(root):
                raise LedgerRootUnavailable(root, path)
        return None
    finally:
        db.close()


def filed_copy(db, path: Path, library_root: Path) -> Path | None:
    """The library file a missing ledger path was already filed as, if exactly one can be
    told (v48, F34 repair). Before v48 a sweep moved a shared file (two ledger rows, e.g. a
    single and its album cut) for its first row and stranded the second on the deleted
    source path: an error on every later sweep, a track whose file can't be downloaded, and
    a row reconcile_disk would prune into a re-download. The sweep's destination keeps the
    source's basename, so that file is the one in-library ledger file with the same name.
    Two candidates, or one missing on disk or outside the library, is not "exactly one"."""
    candidates = {
        Path(candidate)
        for (candidate,) in db.query(DownloadedTrack.file_path)
        .filter(
            DownloadedTrack.in_library.is_(True),
            DownloadedTrack.file_path.endswith(f"/{path.name}", autoescape=True),
        )
        .distinct()
    }
    if len(candidates) != 1:
        return None
    (candidate,) = candidates
    if not candidate.is_relative_to(library_root) or not candidate.exists():
        return None
    return candidate


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
        relinked = 0
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
                # v34.1: the library sweep runs on worker-expand, concurrently with this
                # (worker-meta boot, e.g. a deploy recreating both mid-sweep). It commits
                # a row's repoint *before* unlinking the source, so a file missing at the
                # path read above may just have moved: re-read the row and check its
                # current path before deleting. Deleting on the stale path would drop a
                # freshly moved track's ledger row and re-download it (the v3 invariant).
                try:
                    db.refresh(row)
                except InvalidRequestError:
                    continue  # row already gone
                fresh = Path(row.file_path)
                if fresh.exists():
                    continue
                # The same unmounted-root guard as above, for the path it moved *to*.
                if (downloads_missing and fresh.is_relative_to(downloads_root)) or (
                    library_missing and fresh.is_relative_to(library_root)
                ):
                    skipped += 1
                    continue
                # v48: a row an earlier sweep stranded on its shared file's deleted source
                # follows the library copy that file became instead of being dropped.
                filed = None if library_missing else filed_copy(db, fresh, library_root)
                if filed is not None:
                    row.file_path = str(filed)
                    row.in_library = True
                    relinked += 1
                    continue
                db.delete(row)
                removed += 1
        db.commit()
        logger.info(
            "reconcile_disk: checked %d ledger rows, removed %d with missing files, "
            "relinked %d to their library copy%s",
            len(rows),
            removed,
            relinked,
            f" ({skipped} skipped, root looked unmounted)" if skipped else "",
        )
    finally:
        db.close()
