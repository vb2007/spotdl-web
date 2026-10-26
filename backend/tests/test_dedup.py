import logging
from pathlib import Path

import pytest

from app.models import DownloadedTrack
from app.services import app_settings, dedup


@pytest.fixture(autouse=True)
def _roots_stay_in_tmp(db_session, tmp_path, monkeypatch):
    """CI runs this suite on the production host, where /mnt/raid1/media/music (the default
    library root) is the real library: reconcile_disk creates sentinels, so no test here may
    leave a managed root outside tmp_path. Every test starts with unused downloads and library
    roots under tmp_path (a test's own get_settings patch replaces the first), and the guard
    below fails one that ends up managing a root anywhere else."""
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(tmp_path / "downloads-unused")))
    _set_library(db_session, tmp_path / "library-unused")
    real_managed_roots = dedup.managed_roots

    def _checked(db):
        roots = real_managed_roots(db)
        for root in roots:
            assert root.is_relative_to(tmp_path), f"test manages a root outside tmp_path: {root}"
        return roots

    monkeypatch.setattr(dedup, "managed_roots", _checked)


def _set_library(db_session, library_dir, *, earlier=()):
    """library_target_dir and its known roots, set on the row directly: update_library_settings
    would keep the default root (the host's real library) as a known one."""
    row = app_settings.get_library_settings(db_session)
    row.library_target_dir = str(library_dir)
    row.library_known_roots = [str(library_dir), *(str(root) for root in earlier)]
    db_session.commit()


def _mount(root: Path) -> Path:
    """`root` as a mounted volume: the directory and its sentinel."""
    root.mkdir(parents=True, exist_ok=True)
    (root / dedup.SENTINEL_NAME).write_text("sentinel")
    return root


class _NonClosingSession:
    """Wraps db_session so dedup's db.close() doesn't detach objects the test still
    needs to assert against — the fixture handles real teardown instead."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


def test_is_already_downloaded_returns_none_when_missing(db_session, monkeypatch):
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))

    assert dedup.is_already_downloaded("missing-id") is None


def test_is_already_downloaded_returns_path_when_present(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))

    file_path = tmp_path / "song.mp3"
    file_path.write_bytes(b"fake audio bytes")
    db_session.add(
        DownloadedTrack(spotify_track_id="abc123", file_path=str(file_path), format="mp3", bitrate="320k")
    )
    db_session.commit()

    assert dedup.is_already_downloaded("abc123") == file_path


def test_is_already_downloaded_returns_none_for_a_stale_ledger_row(db_session, monkeypatch, tmp_path):
    """v31: a ledger row whose file is genuinely gone must read as "not already
    downloaded," not as a false SKIPPED_DUPLICATE that never attempts a real download."""
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))

    file_path = tmp_path / "song.mp3"  # never written
    db_session.add(
        DownloadedTrack(spotify_track_id="abc123", file_path=str(file_path), format="mp3", bitrate="320k")
    )
    db_session.commit()

    assert dedup.is_already_downloaded("abc123") is None
    # v57 (L5): a path under no managed root can't be confirmed either way; it's a miss, and
    # the row goes.
    assert db_session.get(DownloadedTrack, "abc123") is None


class _FakeSettings:
    def __init__(self, download_output_dir):
        self.download_output_dir = download_output_dir


def _library_with_row(db_session, monkeypatch, tmp_path, *, library_dir, write_file, earlier=()):
    """A mounted downloads root, `library_dir` as library_target_dir (`earlier` as the roots it
    replaced), and one in-library ledger row pointing into it (its file written only if
    `write_file`)."""
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads_dir = _mount(tmp_path / "downloads")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads_dir)))
    _set_library(db_session, library_dir, earlier=earlier)
    file_path = library_dir / "Artist - Album - (2020)" / "01 - Artist - Song.mp3"
    if write_file:
        file_path.parent.mkdir(parents=True)
        file_path.write_bytes(b"moved audio")
    db_session.add(
        DownloadedTrack(
            spotify_track_id="moved-id",
            file_path=str(file_path),
            format="mp3",
            bitrate="320k",
            in_library=True,
        )
    )
    db_session.commit()
    return file_path


def test_is_already_downloaded_returns_the_library_path_for_a_moved_file(
    db_session, monkeypatch, tmp_path
):
    """v38: the library sort repoints the ledger row; the moved file is the duplicate."""
    file_path = _library_with_row(
        db_session, monkeypatch, tmp_path, library_dir=tmp_path / "library", write_file=True
    )

    assert dedup.is_already_downloaded("moved-id") == file_path


def test_is_already_downloaded_raises_when_the_library_root_is_not_mounted(
    db_session, monkeypatch, tmp_path
):
    """v38: worker-dl without the library mount saw every moved file as gone and downloaded
    it again. A missing root must never read as "not downloaded"."""
    library_dir = tmp_path / "library-not-mounted"
    _library_with_row(db_session, monkeypatch, tmp_path, library_dir=library_dir, write_file=False)

    with pytest.raises(dedup.LedgerRootUnavailable) as exc_info:
        dedup.is_already_downloaded("moved-id")
    assert exc_info.value.root == library_dir


def test_is_already_downloaded_raises_when_the_library_root_has_no_sentinel(
    db_session, monkeypatch, tmp_path
):
    """v57 (L4): a mount point without its sentinel (bind source not attached yet) is the same
    "can't tell" case, even with something in it (it used to take any file as "mounted")."""
    library_dir = tmp_path / "library-unmounted"
    (library_dir / "Someone Else - Album - (1999)").mkdir(parents=True)
    _library_with_row(db_session, monkeypatch, tmp_path, library_dir=library_dir, write_file=False)

    with pytest.raises(dedup.LedgerRootUnavailable):
        dedup.is_already_downloaded("moved-id")
    assert db_session.get(DownloadedTrack, "moved-id") is not None


def test_is_already_downloaded_drops_the_row_when_a_mounted_library_lost_the_file(
    db_session, monkeypatch, tmp_path
):
    """The guard is per root, like reconcile_disk's: a mounted library whose file is genuinely
    gone means "download it again", and (v57, L5) the stale row is dropped first."""
    library_dir = _mount(tmp_path / "library")
    _library_with_row(db_session, monkeypatch, tmp_path, library_dir=library_dir, write_file=False)

    assert dedup.is_already_downloaded("moved-id") is None
    assert db_session.get(DownloadedTrack, "moved-id") is None


def test_is_already_downloaded_drops_a_hand_deleted_file_in_an_empty_mounted_downloads_root(
    db_session, monkeypatch, tmp_path
):
    """v57 (L5): the held-forever case. `/downloads` emptied by a sweep, one row left on a file
    deleted by hand: with the root's sentinel there, it's a plain miss and a fresh download, no
    longer a hold on every ladder step."""
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads_dir = _mount(tmp_path / "downloads")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads_dir)))
    db_session.add(
        DownloadedTrack(
            spotify_track_id="deleted-id",
            file_path=str(downloads_dir / "deleted by hand.mp3"),
            format="mp3",
            bitrate="320k",
        )
    )
    db_session.commit()

    assert dedup.is_already_downloaded("deleted-id") is None
    assert db_session.get(DownloadedTrack, "deleted-id") is None


def test_is_already_downloaded_keeps_a_row_repointed_before_the_drop(db_session, monkeypatch, tmp_path):
    """The drop only takes the row while it still points at the missing file: a repoint (the
    sweep) or a fresh download landing first is left alone."""
    from sqlalchemy import update

    library_dir = _mount(tmp_path / "library")
    _library_with_row(db_session, monkeypatch, tmp_path, library_dir=library_dir, write_file=False)
    real_root_of = dedup.root_of

    def _repoint_lands_here(path, roots):
        db_session.execute(
            update(DownloadedTrack)
            .where(DownloadedTrack.spotify_track_id == "moved-id")
            .values(file_path="/elsewhere/song.mp3")
            .execution_options(synchronize_session=False)
        )
        return real_root_of(path, roots)

    monkeypatch.setattr(dedup, "root_of", _repoint_lands_here)

    assert dedup.is_already_downloaded("moved-id") is None
    db_session.expire_all()
    assert db_session.get(DownloadedTrack, "moved-id").file_path == "/elsewhere/song.mp3"


def test_is_already_downloaded_finds_a_file_under_an_earlier_library_root(
    db_session, monkeypatch, tmp_path
):
    """v57 (L6): after library_target_dir moves, a row under the old root is still a duplicate."""
    old_root = _mount(tmp_path / "library-old")
    file_path = _library_with_row(
        db_session, monkeypatch, tmp_path, library_dir=old_root, write_file=True
    )
    _set_library(db_session, _mount(tmp_path / "library-new"), earlier=[old_root])

    assert dedup.is_already_downloaded("moved-id") == file_path


def test_is_already_downloaded_holds_a_missing_file_under_an_unmounted_earlier_root(
    db_session, monkeypatch, tmp_path
):
    """v57 (L6): an earlier root is guarded like the current one. Before, a row under it fell
    outside every guard and read as gone, so an unmounted old root meant a re-download."""
    old_root = tmp_path / "library-old"
    _library_with_row(db_session, monkeypatch, tmp_path, library_dir=old_root, write_file=False)
    _set_library(db_session, _mount(tmp_path / "library-new"), earlier=[old_root])

    with pytest.raises(dedup.LedgerRootUnavailable) as exc_info:
        dedup.is_already_downloaded("moved-id")
    assert exc_info.value.root == old_root


def test_is_already_downloaded_follows_a_repoint_that_lands_mid_check(
    db_session, monkeypatch, tmp_path
):
    """v38: the sweep commits the repoint, then unlinks the source. A check that read the old
    /downloads path just before must find the moved file, not report a miss (a download)."""
    from sqlalchemy import update

    library_dir = tmp_path / "library"
    dest = library_dir / "Artist - Album - (2020)" / "01 - Artist - Song.mp3"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"moved audio")
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads_dir = _mount(tmp_path / "downloads")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads_dir)))
    _set_library(db_session, library_dir)
    source = downloads_dir / "01 - Artist - Song.mp3"
    db_session.add(
        DownloadedTrack(spotify_track_id="moving-id", file_path=str(source), format="mp3", bitrate="320k")
    )
    db_session.commit()

    class _SweepLandsHere(type(dedup.Path())):
        def exists(self):
            if str(self) == str(source):
                db_session.execute(
                    update(DownloadedTrack)
                    .where(DownloadedTrack.spotify_track_id == "moving-id")
                    .values(file_path=str(dest), in_library=True)
                    .execution_options(synchronize_session=False)
                )
                return False
            return super().exists()

    monkeypatch.setattr(dedup, "Path", _SweepLandsHere)

    assert dedup.is_already_downloaded("moving-id") == dest


def test_is_already_downloaded_is_a_miss_when_the_row_is_deleted_mid_check(
    db_session, monkeypatch, tmp_path
):
    """reconcile_disk() (worker-meta boot) can drop the row between the read and the
    re-read: that's no row at all, a plain miss, never a crash out of download_track."""
    from sqlalchemy import delete

    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    (downloads_dir / "other.mp3").write_text("audio")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads_dir)))
    gone = downloads_dir / "gone.mp3"
    db_session.add(
        DownloadedTrack(spotify_track_id="pruned-id", file_path=str(gone), format="mp3", bitrate="320k")
    )
    db_session.commit()

    class _ReconcileLandsHere(type(dedup.Path())):
        def exists(self):
            if str(self) == str(gone):
                db_session.execute(
                    delete(DownloadedTrack)
                    .where(DownloadedTrack.spotify_track_id == "pruned-id")
                    .execution_options(synchronize_session=False)
                )
            return super().exists()

    monkeypatch.setattr(dedup, "Path", _ReconcileLandsHere)

    assert dedup.is_already_downloaded("pruned-id") is None


def test_is_already_downloaded_raises_when_the_downloads_root_is_not_mounted(
    db_session, monkeypatch, tmp_path
):
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    not_mounted = tmp_path / "downloads-not-mounted"
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(not_mounted)))
    db_session.add(
        DownloadedTrack(
            spotify_track_id="abc123", file_path=str(not_mounted / "song.mp3"), format="mp3", bitrate="320k"
        )
    )
    db_session.commit()

    with pytest.raises(dedup.LedgerRootUnavailable) as exc_info:
        dedup.is_already_downloaded("abc123")
    assert exc_info.value.root == not_mounted


def test_reconcile_disk_drops_rows_for_missing_files(db_session, monkeypatch, tmp_path):
    """A root with no sentinel yet gets one when a ledger file under it is really there (it's
    the volume the ledger was written against), and is then reconciled (v57, L4)."""
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads_dir)))

    present = downloads_dir / "present.mp3"
    present.write_text("audio")
    missing = downloads_dir / "missing.mp3"

    db_session.add_all(
        [
            DownloadedTrack(spotify_track_id="present-id", file_path=str(present), format="mp3", bitrate="320k"),
            DownloadedTrack(spotify_track_id="missing-id", file_path=str(missing), format="mp3", bitrate="320k"),
        ]
    )
    db_session.commit()

    dedup.reconcile_disk()

    remaining = {row.spotify_track_id for row in db_session.query(DownloadedTrack).all()}
    assert remaining == {"present-id"}
    assert (downloads_dir / dedup.SENTINEL_NAME).is_file()


def test_reconcile_disk_refuses_to_prune_when_output_dir_missing(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    not_yet_mounted = tmp_path / "not-mounted-yet"
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(not_yet_mounted)))

    db_session.add(
        DownloadedTrack(
            spotify_track_id="abc123",
            file_path=str(not_yet_mounted / "song.mp3"),
            format="mp3",
            bitrate="320k",
        )
    )
    db_session.commit()

    dedup.reconcile_disk()

    remaining = {row.spotify_track_id for row in db_session.query(DownloadedTrack).all()}
    assert remaining == {"abc123"}


def test_reconcile_disk_skips_an_unmounted_root_with_a_log_line(db_session, monkeypatch, tmp_path, caplog):
    """v57 (L4): no sentinel, and every ledger file under the root missing, is what an
    unmounted volume looks like: no sentinel is created, the rows are kept, and it's logged.
    A stray file in the mount point doesn't make it "mounted" any more."""
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    unmounted = tmp_path / "empty-mount"
    unmounted.mkdir()
    (unmounted / "stray.txt").write_text("not the volume")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(unmounted)))

    db_session.add(
        DownloadedTrack(
            spotify_track_id="abc123", file_path=str(unmounted / "song.mp3"), format="mp3", bitrate="320k"
        )
    )
    db_session.commit()

    with caplog.at_level(logging.INFO, logger="app.services.dedup"):
        dedup.reconcile_disk()

    remaining = {row.spotify_track_id for row in db_session.query(DownloadedTrack).all()}
    assert remaining == {"abc123"}
    assert not (unmounted / dedup.SENTINEL_NAME).exists()
    assert f"reconcile_disk: {unmounted} has no .spotdl-volume (not mounted?); skipped 1 ledger rows under it" in caplog.messages


def test_reconcile_disk_prunes_a_stale_row_in_an_empty_mounted_root(db_session, monkeypatch, tmp_path, caplog):
    """v57 (L4): an empty but mounted `/downloads` (a sweep empties it) prunes its stale rows.
    Before, "empty" read as "unmounted", which is how GOTCHAS v48's 47 rows survived."""
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads_dir = _mount(tmp_path / "downloads")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads_dir)))
    db_session.add(
        DownloadedTrack(
            spotify_track_id="stale-id", file_path=str(downloads_dir / "gone.mp3"), format="mp3", bitrate="320k"
        )
    )
    db_session.commit()

    with caplog.at_level(logging.INFO, logger="app.services.dedup"):
        dedup.reconcile_disk()

    assert db_session.query(DownloadedTrack).count() == 0
    assert f"reconcile_disk: sentinel present in {downloads_dir}" in caplog.messages


def test_reconcile_disk_creates_a_sentinel_only_where_nothing_could_be_pruned(db_session, monkeypatch, tmp_path):
    """v57 (L4): a root no ledger row points into gets its sentinel (nothing to lose), and so
    does a root with at least one real ledger file; a missing root gets none."""
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads_dir)))
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    missing_root = tmp_path / "library-old-gone"
    _set_library(db_session, library_dir, earlier=[missing_root])

    dedup.reconcile_disk()

    assert (downloads_dir / dedup.SENTINEL_NAME).is_file()
    assert (library_dir / dedup.SENTINEL_NAME).is_file()
    assert not missing_root.exists()


def test_reconcile_disk_covers_an_earlier_library_root(db_session, monkeypatch, tmp_path):
    """v57 (L6): rows under a library root this install used before are reconciled under that
    root's own sentinel: pruned while it's mounted, kept while it isn't."""
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads_dir = _mount(tmp_path / "downloads")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads_dir)))
    mounted_old = _mount(tmp_path / "library-old-mounted")
    unmounted_old = tmp_path / "library-old-unmounted"
    unmounted_old.mkdir()
    _set_library(db_session, _mount(tmp_path / "library-new"), earlier=[mounted_old, unmounted_old])
    db_session.add_all(
        [
            DownloadedTrack(
                spotify_track_id="old-mounted-gone",
                file_path=str(mounted_old / "A" / "gone.mp3"),
                format="mp3",
                bitrate="320k",
                in_library=True,
            ),
            DownloadedTrack(
                spotify_track_id="old-unmounted",
                file_path=str(unmounted_old / "A" / "song.mp3"),
                format="mp3",
                bitrate="320k",
                in_library=True,
            ),
        ]
    )
    db_session.commit()

    dedup.reconcile_disk()

    remaining = {row.spotify_track_id for row in db_session.query(DownloadedTrack).all()}
    assert remaining == {"old-unmounted"}


def test_reconcile_disk_skips_only_library_rooted_rows_when_library_dir_missing(
    db_session, monkeypatch, tmp_path
):
    """v28: a moved track's file_path lives under library_target_dir instead of
    download_output_dir -- that root needs the exact same "don't prune if the mount
    looks unmounted" protection as the original v12 guard, scoped to just the rows that
    actually live under it so a healthy downloads root is still reconciled normally."""
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads_dir = _mount(tmp_path / "downloads")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads_dir)))

    library_dir = tmp_path / "library-not-mounted-yet"
    _set_library(db_session, library_dir)

    db_session.add_all(
        [
            # Downloads root is healthy -- this row's file is genuinely gone and must
            # still be pruned normally.
            DownloadedTrack(
                spotify_track_id="downloads-missing-file",
                file_path=str(downloads_dir / "gone.mp3"),
                format="mp3",
                bitrate="320k",
            ),
            # Library root looks unmounted -- this row must survive even though its
            # file "looks" missing, since that's indistinguishable from the mount
            # itself not being attached yet.
            DownloadedTrack(
                spotify_track_id="library-row",
                file_path=str(library_dir / "Artist - Album - (2020)" / "song.mp3"),
                format="mp3",
                bitrate="320k",
                in_library=True,
            ),
        ]
    )
    db_session.commit()

    dedup.reconcile_disk()

    remaining = {row.spotify_track_id for row in db_session.query(DownloadedTrack).all()}
    assert remaining == {"library-row"}


def test_reconcile_disk_prunes_downloads_root_normally_when_library_never_used(
    db_session, monkeypatch, tmp_path
):
    """A fresh install where v28's sort & move has never run yet has a genuinely empty
    (never-populated) library_target_dir by construction -- that must not permanently
    block the far more commonly needed downloads-root reconciliation."""
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    (downloads_dir / "present.mp3").write_text("audio")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads_dir)))
    # library_target_dir left never created (the autouse fixture's) -- exactly the
    # "nobody has ever run a sweep" state.

    db_session.add_all(
        [
            DownloadedTrack(
                spotify_track_id="present-id",
                file_path=str(downloads_dir / "present.mp3"),
                format="mp3",
                bitrate="320k",
            ),
            DownloadedTrack(
                spotify_track_id="missing-id",
                file_path=str(downloads_dir / "missing.mp3"),
                format="mp3",
                bitrate="320k",
            ),
        ]
    )
    db_session.commit()

    dedup.reconcile_disk()

    remaining = {row.spotify_track_id for row in db_session.query(DownloadedTrack).all()}
    assert remaining == {"present-id"}


def test_reconcile_disk_keeps_a_row_the_library_sweep_repoints_mid_check(
    db_session, monkeypatch, tmp_path
):
    """v34.1: the sweep (worker-expand) can run concurrently with reconcile_disk
    (worker-meta boot). It commits the repoint, *then* unlinks the source -- so a row
    whose file vanishes between reconcile reading its path and checking it has moved,
    not gone, and must survive."""
    from sqlalchemy import update

    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads_dir = _mount(tmp_path / "downloads")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads_dir)))
    library_dir = _mount(tmp_path / "library")
    (library_dir / "Artist").mkdir(parents=True)
    _set_library(db_session, library_dir)
    db_session.add(
        DownloadedTrack(
            spotify_track_id="moving-id",
            file_path=str(downloads_dir / "song.mp3"),  # already unlinked by the sweep
            format="mp3",
            bitrate="320k",
        )
    )
    db_session.commit()
    dest = library_dir / "Artist" / "song.mp3"
    dest.write_text("audio")

    real_path = dedup.Path

    class _SweepLandsHere(type(real_path())):
        def exists(self):
            if str(self) == str(downloads_dir / "song.mp3"):
                # The sweep's commit lands exactly between reconcile's read and check,
                # as another process would: no in-session sync of the loaded object.
                db_session.execute(
                    update(DownloadedTrack)
                    .where(DownloadedTrack.spotify_track_id == "moving-id")
                    .values(file_path=str(dest), in_library=True)
                    .execution_options(synchronize_session=False)
                )
                return False
            return super().exists()

    monkeypatch.setattr(dedup, "Path", _SweepLandsHere)

    dedup.reconcile_disk()

    row = db_session.get(DownloadedTrack, "moving-id")
    assert row is not None
    assert row.file_path == str(dest)


def test_reconcile_disk_recheck_respects_the_unmounted_root_guard(db_session, monkeypatch, tmp_path):
    """v34.1: a row repointed mid-check into a library root that looks unmounted on this
    worker must be skipped like any other row under that root, not pruned."""
    from sqlalchemy import update

    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads_dir = _mount(tmp_path / "downloads")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads_dir)))
    library_dir = tmp_path / "library-not-mounted"
    _set_library(db_session, library_dir)
    db_session.add(
        DownloadedTrack(
            spotify_track_id="moving-id",
            file_path=str(downloads_dir / "song.mp3"),
            format="mp3",
            bitrate="320k",
        )
    )
    db_session.commit()
    dest = library_dir / "Artist" / "song.mp3"

    class _SweepLandsHere(type(dedup.Path())):
        def exists(self):
            if str(self) == str(downloads_dir / "song.mp3"):
                db_session.execute(
                    update(DownloadedTrack)
                    .where(DownloadedTrack.spotify_track_id == "moving-id")
                    .values(file_path=str(dest), in_library=True)
                    .execution_options(synchronize_session=False)
                )
                return False
            return super().exists()

    monkeypatch.setattr(dedup, "Path", _SweepLandsHere)

    dedup.reconcile_disk()

    assert db_session.get(DownloadedTrack, "moving-id") is not None


def test_record_download_upserts_the_row_as_not_yet_filed(db_session, tmp_path):
    """worker-dl's upsert (v57, L3, moved here from download_track): in_library is reset, so a
    re-downloaded library file is swept again (v48)."""
    file_path = tmp_path / "song.mp3"
    file_path.write_bytes(b"audio")
    db_session.add(
        DownloadedTrack(
            spotify_track_id="abc123", file_path="/old/lib/song.mp3", format="mp3", bitrate="128k", in_library=True
        )
    )
    db_session.commit()

    dedup.record_download(db_session, "abc123", file_path, format="mp3", bitrate="320k")
    db_session.commit()

    row = db_session.get(DownloadedTrack, "abc123")
    db_session.refresh(row)
    assert (row.file_path, row.bitrate, row.in_library) == (str(file_path), "320k", False)


def test_record_download_refuses_a_file_that_moved_away(db_session, tmp_path):
    """The sweep moved the file while worker-dl waited on its lock: no row on a dead path."""
    with pytest.raises(dedup.LedgerFileMoved):
        dedup.record_download(db_session, "abc123", tmp_path / "moved.mp3", format="mp3", bitrate="320k")
    db_session.rollback()
    assert db_session.get(DownloadedTrack, "abc123") is None


def test_known_library_roots_leave_out_a_root_overlapping_the_downloads_dir(db_session, tmp_path, monkeypatch):
    """v57 (review round 1): an old root equal to, inside or around the downloads dir is never
    a library root (dedup, reconcile, file serving and the sweep all read this list)."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads)))
    _set_library(db_session, tmp_path / "library", earlier=[tmp_path, downloads, downloads / "lib", tmp_path / "old"])

    roots = dedup.known_library_roots(app_settings.get_library_settings(db_session))

    assert roots == [tmp_path / "library", tmp_path / "old"]


def test_the_file_lock_key_is_the_same_for_one_file_however_it_is_spelled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert dedup._file_lock_key(tmp_path / "a" / "song.mp3") == dedup._file_lock_key(Path("a/../a/./song.mp3"))
    assert dedup._file_lock_key(tmp_path / "a" / "song.mp3") != dedup._file_lock_key(tmp_path / "b" / "song.mp3")


def test_is_already_downloaded_follows_a_repoint_that_lands_before_the_drop(db_session, monkeypatch, tmp_path):
    """v57 (review round 2): the sweep repoints the row to a file that exists, between the
    re-read and the guarded delete: that file is the duplicate, not a re-download."""
    from sqlalchemy import update

    library_dir = _mount(tmp_path / "library")
    _library_with_row(db_session, monkeypatch, tmp_path, library_dir=library_dir, write_file=False)
    moved_to = library_dir / "Elsewhere" / "song.mp3"
    moved_to.parent.mkdir()
    moved_to.write_bytes(b"audio")
    real_root_of = dedup.root_of

    def _repoint_lands_here(path, roots):
        db_session.execute(
            update(DownloadedTrack)
            .where(DownloadedTrack.spotify_track_id == "moved-id")
            .values(file_path=str(moved_to))
            .execution_options(synchronize_session=False)
        )
        return real_root_of(path, roots)

    monkeypatch.setattr(dedup, "root_of", _repoint_lands_here)

    assert dedup.is_already_downloaded("moved-id") == moved_to


def test_record_download_gives_the_downloads_root_its_sentinel(db_session, tmp_path, monkeypatch):
    """Review round 4: a root whose rows were all stale at worker-meta's boot got no sentinel;
    the first real download proves the mount."""
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads)))
    file_path = downloads / "song.mp3"
    file_path.write_bytes(b"audio")

    dedup.record_download(db_session, "abc123", file_path, format="mp3", bitrate="320k")

    assert (downloads / dedup.SENTINEL_NAME).is_file()


def test_a_folder_root_inside_a_mounted_root_counts_as_mounted(db_session, monkeypatch, tmp_path):
    """Review round 4: every non-default library root is a folder inside the mount. One removed
    by hand is gone from a mounted volume, so its rows drop and reconcile prunes them, rather
    than holding the tracks forever."""
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads = _mount(tmp_path / "downloads")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads)))
    mount = _mount(tmp_path / "music")
    sorted_root = mount / "sorted"  # removed by hand: no folder, no sentinel of its own
    _set_library(db_session, mount, earlier=[sorted_root])
    db_session.add_all(
        [
            DownloadedTrack(spotify_track_id="a", file_path=str(sorted_root / "A" / "a.mp3"), format="mp3", bitrate="320k", in_library=True),
            DownloadedTrack(spotify_track_id="b", file_path=str(sorted_root / "B" / "b.mp3"), format="mp3", bitrate="320k", in_library=True),
        ]
    )
    db_session.commit()

    assert dedup.is_already_downloaded("a") is None
    assert db_session.get(DownloadedTrack, "a") is None
    dedup.reconcile_disk()
    assert db_session.get(DownloadedTrack, "b") is None
