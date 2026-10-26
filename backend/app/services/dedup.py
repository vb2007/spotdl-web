"""Download dedup ledger (`downloaded_tracks`) and startup disk reconciliation.

v57: a managed root (the downloads dir and every library root this install has used) counts as
mounted only while its mount sentinel, `.spotdl-volume`, is there (L4). Before, a root was
"unmounted" when it was empty, so an emptied-but-mounted `/downloads` kept its stale rows by
accident and an unmounted one with a stray file in it lost them. The sweep and worker-dl's
ledger upsert serialize per file on a Postgres advisory lock (L3).
"""

import hashlib
import logging
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, engine
from app.models import AppSettings, DownloadedTrack
from app.services import app_settings

logger = logging.getLogger(__name__)

SENTINEL_NAME = ".spotdl-volume"
_SENTINEL_TEXT = (
    "spotdl-web mount sentinel (v57). reconcile_disk prunes ledger rows whose file is gone from\n"
    "this directory only while this file is here; without it the directory reads as not mounted.\n"
    "Leave it in place.\n"
)


class LedgerRootUnavailable(Exception):
    """A ledger row's file is missing, but it lives under a root whose mount sentinel is
    missing in this process, so "missing" can't be told apart from "can't see it" (v38; the
    sentinel since v57)."""

    def __init__(self, root: Path, path: Path) -> None:
        super().__init__(f"{path} is under {root}, which has no {SENTINEL_NAME} (not mounted?)")
        self.root = root
        self.path = path


class LedgerFileMoved(Exception):
    """worker-dl's finished file left its path before the ledger could record it: the library
    sweep moved it while worker-dl waited on the file's lock (v57, L3). Recording it would
    leave a row on a path that no longer exists, so the attempt fails instead (an ordinary
    error: the ladder retries it, the breaker isn't fed)."""


def known_library_roots(settings_row: AppSettings) -> list[Path]:
    """The current library_target_dir first, then every earlier one (v57, L6). A root that
    overlaps the downloads dir (equal, inside or around it: a value saved before L2's check,
    or the migration's seed of one) is never a library root: it would make every download
    read as "already in the library", and the list can't be edited."""
    from app.services.library import path_relation  # library imports nothing from here

    downloads = Path(get_settings().download_output_dir)
    roots = [settings_row.library_target_dir, *settings_row.library_known_roots]
    return [
        Path(root)
        for root in dict.fromkeys(str(root) for root in roots)
        if path_relation(Path(root), downloads) is None
    ]


def managed_roots(db: Session) -> list[Path]:
    """Every root a ledger row may legitimately point into: the downloads dir and every known
    library root. Reads the settings row; the caller ends the transaction."""
    downloads = Path(get_settings().download_output_dir)
    return [downloads, *known_library_roots(app_settings.get_library_settings(db))]


def root_of(path: Path, roots: Sequence[Path]) -> Path | None:
    """The most specific of `roots` that `path` lies under, or None."""
    matches = [root for root in roots if path.is_relative_to(root)]
    return max(matches, key=lambda root: len(root.parts)) if matches else None


def sentinel_present(root: Path) -> bool:
    return (root / SENTINEL_NAME).is_file()


def covered(path: Path, roots: Sequence[Path]) -> bool:
    """Whether `path` lies under a managed root whose sentinel is there (v57, review round 4).
    Any enclosing root counts, not only the most specific: under the owner's mount rule every
    library root but the mount point itself is a folder inside it, so the mount point's sentinel
    proves the volume for all of them, a subfolder removed by hand included."""
    return any(sentinel_present(root) for root in roots if path.is_relative_to(root))


def ensure_sentinel(root: Path, ledger_paths: Sequence[Path], *, caller: str = "reconcile_disk") -> bool:
    """Whether `root` is mounted, creating its sentinel when that's safe to decide (v57, L4):
    `ledger_paths` are the ledger's files under this root. A root with no sentinel gets one only
    if it exists and either no ledger row points into it (nothing could be pruned there) or at
    least one of those files is really there (it's the volume the ledger was written against).
    A root whose every ledger file is missing is exactly what an unmounted volume looks like, so
    it gets none and its rows are skipped; an admin who has checked the mount creates the file
    by hand (docs/GOTCHAS.md, v57). A process that can't write the root (a read-only mount)
    leaves it to one that can."""
    sentinel = root / SENTINEL_NAME
    if sentinel.is_file():
        logger.info("%s: sentinel present in %s", caller, root)
        return True
    if not root.is_dir():
        # Known roots only grow (a library dir saved once by mistake stays known), so a missing
        # one nothing points into is only noted; one with ledger rows under it is the alarm.
        if ledger_paths:
            logger.error(
                "%s: %s doesn't exist here: not mounted (%d ledger rows under it)",
                caller,
                root,
                len(ledger_paths),
            )
        else:
            logger.info("%s: %s doesn't exist here; no ledger rows under it", caller, root)
        return False
    if ledger_paths and not any(path.exists() for path in ledger_paths):
        logger.error(
            "%s: %s has no %s and none of the %d ledger files under it exist: it "
            "looks unmounted, so no sentinel was created. If it is mounted and those files are "
            "really gone, create %s by hand",
            caller,
            root,
            SENTINEL_NAME,
            len(ledger_paths),
            sentinel,
        )
        return False
    try:
        sentinel.write_text(_SENTINEL_TEXT)
    except OSError as exc:
        logger.error("%s: couldn't create %s: %s", caller, sentinel, exc)
        return False
    logger.info("%s: sentinel created in %s", caller, root)
    return True


def _file_lock_key(path: Path) -> int:
    # A signed 64-bit key, namespaced so it can't meet another advisory lock's key. The path is
    # made absolute and normalized first, so "a/../b", "./b" and "b" lock the same file.
    normalized = os.path.normpath(os.path.abspath(path))
    digest = hashlib.sha256(f"spotdl-web:file:{normalized}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def lock_file_in(db: Session, path: Path) -> None:
    """The per-file advisory lock (v57, L3) in `db`'s own transaction, held until it ends."""
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _file_lock_key(path)})


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Holds the per-file advisory lock (v57, L3) for the block, on a connection of its own:
    the library sweep commits its repoint and only then deletes the source, so the lock must
    outlive the sweep session's commit. Released when the block ends, or with the connection
    if the process dies."""
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _file_lock_key(path)})
        yield


def record_download(
    db: Session, spotify_track_id: str, file_path: Path, *, format: str, bitrate: str
) -> None:
    """worker-dl's ledger upsert for a finished download (v57, L3). Takes the file's advisory
    lock in `db`'s transaction (held until the caller commits), so it can't land between the
    library sweep's re-read of the rows on this file and its delete of the file: the sweep then
    either sees this row and moves it with the file, or has moved the file before this runs,
    which the existence check under the lock catches (LedgerFileMoved).

    in_library is set, not left out: merge copies only the attributes given, so a row whose
    library file went missing and was downloaded again kept in_library=True on its new
    /downloads path, and no sweep (which reads only in_library=False) would ever file it (v48)."""
    lock_file_in(db, file_path)
    if not file_path.exists():
        raise LedgerFileMoved(f"{file_path} was moved by the library sweep before it was recorded")
    # A file worker-dl just wrote proves its downloads root is mounted (review round 4): a root
    # whose ledger rows were all stale at worker-meta's boot gets its sentinel here, at the next
    # real download, instead of waiting for someone to create it by hand.
    downloads = Path(get_settings().download_output_dir)
    if file_path.is_relative_to(downloads) and not sentinel_present(downloads):
        ensure_sentinel(downloads, [file_path], caller="worker-dl")
    db.merge(
        DownloadedTrack(
            spotify_track_id=spotify_track_id,
            file_path=str(file_path),
            format=format,
            bitrate=bitrate,
            in_library=False,
        )
    )


def is_already_downloaded(spotify_track_id: str) -> Path | None:
    """None means "attempt a real download" -- to the caller, a stale ledger row (file
    genuinely gone) must be indistinguishable from no row at all. v31: this used to trust
    `row.file_path` completely -- a track could be marked `SKIPPED_DUPLICATE` pointing at a
    ledger entry whose file doesn't exist, which is strictly worse than a false `COMPLETED` (it
    never even attempts a real download to fix itself).

    v38: a missing file under a root that can't be confirmed mounted raises
    LedgerRootUnavailable instead of returning None, and `download_track` holds the track.
    worker-dl didn't mount the library before v38, so every file the library sort had moved read
    as gone and was downloaded again; a future mount mistake must not repeat that silently. A
    miss also re-reads the row first, in case the library sweep moved the file mid-check.

    v57: "mounted" is the root's sentinel (L4), and the roots are every known library root, not
    only the current one (L6). A file missing under a mounted root is really gone, so its row is
    dropped here before the download (L5): it used to stay, and while `/downloads` was empty the
    track was held on every ladder step, forever."""
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
        roots = managed_roots(db)
        root = root_of(path, roots)
        db.commit()
        if root is not None and not covered(path, roots):
            raise LedgerRootUnavailable(root, path)
        # Only while the row still points where it was read: the sweep may have repointed it,
        # or worker-dl recorded a fresh download, since.
        dropped = (
            db.query(DownloadedTrack)
            .filter(
                DownloadedTrack.spotify_track_id == spotify_track_id,
                DownloadedTrack.file_path == str(path),
            )
            .delete(synchronize_session=False)
        )
        db.commit()
        if not dropped:
            # The sweep repointed the row, or worker-dl recorded a fresh download, between the
            # re-read and the delete: whatever the row says now decides.
            db.expire_all()
            row = db.get(DownloadedTrack, spotify_track_id)
            if row is not None and Path(row.file_path).exists():
                return Path(row.file_path)
        if dropped:
            logger.info(
                "dedup: %s's ledger file %s is gone from a mounted root; dropped the row and "
                "downloading it again",
                spotify_track_id,
                path,
            )
        return None
    finally:
        db.close()


def reconcile_disk() -> None:
    """Drops ledger rows whose file no longer exists on disk, so a manually-deleted
    track gets re-downloaded on the next submission. Run once on worker-meta boot.

    Only under a mounted root (v57, L4): every managed root (the downloads dir and every known
    library root) is checked for its sentinel first, created where that's safe
    (ensure_sentinel), and rows under a root without one are skipped. This replaced v12's
    "missing or empty means unmounted" guard (extended per root in v28): an empty but mounted
    `/downloads` (every sweep empties it) skipped its stale rows by accident (the 47 rows of
    GOTCHAS v48), while a mount that failed with any stray file in the mountpoint pruned every
    row under it into a re-download. A row under no managed root is pruned when its file is
    gone, as before."""

    db = SessionLocal()
    try:
        rows = db.query(DownloadedTrack).all()
        roots = managed_roots(db)
        db.commit()

        under: dict[Path, list[Path]] = {root: [] for root in roots}
        for row in rows:
            root = root_of(Path(row.file_path), roots)
            if root is not None:
                under[root].append(Path(row.file_path))
        # Outermost first: a root inside a mounted one is covered by its sentinel (covered()).
        mounted: dict[Path, bool] = {}
        for root in sorted(under, key=lambda r: len(r.parts)):
            enclosing = [r for r in mounted if root.is_relative_to(r)]
            mounted[root] = any(mounted[r] for r in enclosing) or ensure_sentinel(root, under[root])

        def unmounted_root(path: Path) -> Path | None:
            root = root_of(path, roots)
            return root if root is not None and not mounted[root] else None

        removed = 0
        skipped: dict[Path, int] = {}
        for row in rows:
            path = Path(row.file_path)
            root = unmounted_root(path)
            if root is not None:
                skipped[root] = skipped.get(root, 0) + 1
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
                root = unmounted_root(fresh)
                if root is not None:
                    skipped[root] = skipped.get(root, 0) + 1
                    continue
                db.delete(row)
                removed += 1
        db.commit()
        for root, count in skipped.items():
            logger.error(
                "reconcile_disk: %s has no %s (not mounted?); skipped %d ledger rows under it",
                root,
                SENTINEL_NAME,
                count,
            )
        logger.info(
            "reconcile_disk: checked %d ledger rows, removed %d with missing files%s",
            len(rows),
            removed,
            f" ({sum(skipped.values())} skipped, root not mounted)" if skipped else "",
        )
    finally:
        db.close()
