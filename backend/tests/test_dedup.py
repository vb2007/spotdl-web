from pathlib import Path

from app.models import DownloadedTrack
from app.services import app_settings, dedup


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


class _FakeSettings:
    def __init__(self, download_output_dir):
        self.download_output_dir = download_output_dir


def test_reconcile_disk_drops_rows_for_missing_files(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    # download_output_dir must point at a real, non-empty directory here -- "present.mp3"
    # itself makes it non-empty -- or the new v12 empty-mount guard would refuse to prune.
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(tmp_path)))

    present = tmp_path / "present.mp3"
    present.write_text("audio")
    missing = tmp_path / "missing.mp3"

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


def test_reconcile_disk_refuses_to_prune_when_output_dir_empty(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    empty_dir = tmp_path / "empty-mount"
    empty_dir.mkdir()
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(empty_dir)))

    db_session.add(
        DownloadedTrack(
            spotify_track_id="abc123", file_path=str(empty_dir / "song.mp3"), format="mp3", bitrate="320k"
        )
    )
    db_session.commit()

    dedup.reconcile_disk()

    remaining = {row.spotify_track_id for row in db_session.query(DownloadedTrack).all()}
    assert remaining == {"abc123"}


def test_reconcile_disk_skips_only_library_rooted_rows_when_library_dir_missing(
    db_session, monkeypatch, tmp_path
):
    """v28: a moved track's file_path lives under library_target_dir instead of
    download_output_dir -- that root needs the exact same "don't prune if the mount
    looks unmounted" protection as the original v12 guard, scoped to just the rows that
    actually live under it so a healthy downloads root is still reconciled normally."""
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    (downloads_dir / "present.mp3").write_text("audio")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads_dir)))

    library_dir = tmp_path / "library-not-mounted-yet"
    app_settings.update_library_settings(db_session, library_target_dir=str(library_dir))
    db_session.commit()

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
    # library_target_dir left at its default and never created -- exactly the
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
    downloads_dir = tmp_path / "downloads"
    downloads_dir.mkdir()
    (downloads_dir / "other.mp3").write_text("audio")
    monkeypatch.setattr(dedup, "get_settings", lambda: _FakeSettings(str(downloads_dir)))
    library_dir = tmp_path / "library"
    (library_dir / "Artist").mkdir(parents=True)
    app_settings.update_library_settings(db_session, library_target_dir=str(library_dir))
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
