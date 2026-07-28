from pathlib import Path

from app.models import DownloadedTrack
from app.services import dedup


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
    db_session.add(
        DownloadedTrack(spotify_track_id="abc123", file_path=str(file_path), format="mp3", bitrate="320k")
    )
    db_session.commit()

    assert dedup.is_already_downloaded("abc123") == file_path


def test_reconcile_disk_drops_rows_for_missing_files(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(dedup, "SessionLocal", lambda: _NonClosingSession(db_session))

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
