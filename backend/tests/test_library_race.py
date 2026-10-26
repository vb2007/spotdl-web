"""v57 (L3): the library sweep vs worker-dl's ledger upsert on the same file, on real Postgres
with committed sessions (tests/concurrency.py).

The window: the sweep re-reads every ledger row on a file, repoints them, commits, and only
then deletes the source. A row worker-dl commits on that file in between (spotdl's
skip-existing hands back the file already on disk, so a second Spotify id lands on it) is
neither repointed nor still backed by a file: stranded, and reconcile_disk prunes it into a
re-download. Both sides now take the file's advisory lock (dedup.file_lock / record_download).
"""

import uuid
from contextlib import nullcontext
from pathlib import Path

import pytest

from app.models import DownloadedTrack, LibrarySortRun, LibrarySortState
from app.services import alerts, app_settings, dedup, events
from app.services import library as library_service
from app.tasks import library as library_task
from concurrency import Gate, Thread, blocked_or_done

_FAKE_TAGS = {"artists": ["Daft Punk"], "album_name": "Discovery", "year": 2001}


def _record_as_worker_dl(factory, spotify_track_id: str, file_path: Path) -> None:
    db = factory()
    try:
        dedup.record_download(db, spotify_track_id, file_path, format="mp3", bitrate="320k")
        db.commit()
    finally:
        db.close()


@pytest.mark.parametrize(
    "locked",
    [
        True,
        pytest.param(
            False,
            marks=pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="without the advisory lock worker-dl's row lands between the sweep's "
                "repoint and its delete, and is stranded on a deleted file",
            ),
        ),
    ],
    ids=["with-lock", "without-lock"],
)
def test_worker_dl_upsert_vs_sweep_move_of_the_same_file(committed_db, tmp_path, monkeypatch, locked):
    if not locked:
        monkeypatch.setattr(dedup, "file_lock", lambda path: nullcontext())
        monkeypatch.setattr(dedup, "lock_file_in", lambda db, path: None)

    source = tmp_path / "downloads" / "01 - Daft Punk - One More Time.mp3"
    source.parent.mkdir()
    source.write_bytes(b"one more time")
    (tmp_path / "library").mkdir()
    setup = committed_db()
    app_settings.update_library_settings(
        setup,
        library_target_dir=str(tmp_path / "library"),
        library_quarantine_enabled=False,
        library_quarantine_dir=str(tmp_path / "quarantine"),
    )
    setup.add(DownloadedTrack(spotify_track_id="single", file_path=str(source), format="mp3", bitrate="320k"))
    setup.add(LibrarySortRun(id=1, state=LibrarySortState.RUNNING, errors=[]))  # as the endpoint leaves it
    setup.commit()
    setup.close()

    monkeypatch.setattr(library_service, "library_mount", lambda: tmp_path / "library")
    monkeypatch.setattr(library_task, "SessionLocal", committed_db)
    monkeypatch.setattr(library_service, "read_sort_tags", lambda path: dict(_FAKE_TAGS))
    monkeypatch.setattr(events, "publish_library_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(alerts, "enqueue", lambda *args, **kwargs: None)
    # The sweep stops after its repoint is committed, just before it deletes the source.
    gate = Gate("sweep between its repoint commit and its delete of the source")
    real_unlink = Path.unlink

    def _unlink(self, *args, **kwargs):
        if self == source:  # copy_verify also drops its staging name, before the lock
            gate()
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _unlink)

    sweep = Thread(library_task.sort_library, str(uuid.uuid4()), name="sweep")
    gate.wait_reached()
    worker_dl = Thread(_record_as_worker_dl, committed_db, "album-cut", source, name="worker-dl")
    outcome = blocked_or_done(worker_dl)
    if locked:
        assert outcome == "blocked"  # worker-dl waits on the sweep's lock on this file
    gate.open()
    sweep.join()
    if locked:
        # The sweep moved the file while worker-dl waited; recording it would strand the row.
        with pytest.raises(dedup.LedgerFileMoved):
            worker_dl.join()
    else:
        worker_dl.join()

    check = committed_db()
    try:
        rows = {row.spotify_track_id: row.file_path for row in check.query(DownloadedTrack).all()}
    finally:
        check.close()
    dest = tmp_path / "library" / "Daft Punk - Discovery - (2001)" / source.name
    assert rows["single"] == str(dest)
    assert dest.read_bytes() == b"one more time"
    stranded = {spotify_id: path for spotify_id, path in rows.items() if not Path(path).exists()}
    assert stranded == {}


def test_only_one_of_two_sweep_deliveries_runs(committed_db, tmp_path, monkeypatch):
    """Review round 7 (reproduced live): a redelivered sweep message and a new start both found
    the row running and swept at once, racing each other's files. The second waits on nothing: it
    can't take the sweep lock and is dropped."""
    source = tmp_path / "downloads" / "song.mp3"
    source.parent.mkdir()
    source.write_bytes(b"audio")
    (tmp_path / "library").mkdir()
    setup = committed_db()
    app_settings.update_library_settings(
        setup,
        library_target_dir=str(tmp_path / "library"),
        library_quarantine_enabled=False,
        library_quarantine_dir=str(tmp_path / "quarantine"),
    )
    setup.add(DownloadedTrack(spotify_track_id="one", file_path=str(source), format="mp3", bitrate="320k"))
    setup.add(LibrarySortRun(id=1, state=LibrarySortState.RUNNING, errors=[]))
    setup.commit()
    setup.close()
    monkeypatch.setattr(library_service, "library_mount", lambda: tmp_path / "library")
    monkeypatch.setattr(library_task, "SessionLocal", committed_db)
    monkeypatch.setattr(library_service, "read_sort_tags", lambda path: dict(_FAKE_TAGS))
    monkeypatch.setattr(events, "publish_library_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(alerts, "enqueue", lambda *args, **kwargs: None)
    gate = Gate("the first sweep, holding the sweep lock")
    monkeypatch.setattr(library_task, "_run_sweep", gate.wrap(library_task._run_sweep))

    first = Thread(library_task.sort_library, str(uuid.uuid4()), name="first delivery")
    gate.wait_reached()
    second = Thread(library_task.sort_library, str(uuid.uuid4()), name="second delivery")
    second.join()  # returns at once: dropped, not waiting
    gate.open()
    first.join()

    check = committed_db()
    try:
        run = check.get(LibrarySortRun, 1)
        assert (run.state, run.total, run.processed, run.moved) == (LibrarySortState.IDLE, 1, 1, 1)
    finally:
        check.close()
