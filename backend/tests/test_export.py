"""v64: a job's export, `GET /api/jobs/{id}/export.zip` and `/playlist.m3u8`.

Real files in a temporary downloads root and library mount (both patched in, since the
container's own /downloads is mounted read-only). Ownership cases live in
test_ownership.py beside the other direct-id endpoints."""

import hashlib
import io
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config import get_settings
from app.models import AppSettings, DownloadedTrack, Job, JobSourceType, JobState, Track, TrackState
from app.services import app_settings, export


class _NonClosingSession:
    """db_session for the stream's own short read: its close() would detach the test's rows."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _ledger_reads_on_the_test_session(db_session, monkeypatch):
    """The export's own short ledger reads (a file that moved before its stat or mid-stream)
    go through db_session, never a connection of their own."""
    monkeypatch.setattr(export, "SessionLocal", lambda: _NonClosingSession(db_session))


@pytest.fixture()
def roots(tmp_path, monkeypatch):
    downloads = tmp_path / "downloads"
    library = tmp_path / "library"
    downloads.mkdir()
    library.mkdir()
    monkeypatch.setattr(get_settings(), "download_output_dir", str(downloads))
    monkeypatch.setattr(app_settings, "DEFAULT_LIBRARY_TARGET_DIR", str(library))
    return downloads, library


def _job(db_session, user, *, archived=False) -> Job:
    job = Job(
        source_url="https://open.spotify.com/album/x",
        source_type=JobSourceType.ALBUM,
        state=JobState.EXPANDED,
        user_id=user.id,
        archived_at=datetime.now(timezone.utc) if archived else None,
    )
    db_session.add(job)
    db_session.commit()
    return job


def _track(db_session, job, number, *, path=None, state=TrackState.COMPLETED, name=None, ledger=None, **song):
    track = Track(
        job_id=job.id,
        spotify_track_id=f"{job.id}-{number}",
        song_json={
            "name": name or f"Song {number}",
            "artists": ["Artist A", "Artist B"],
            "list_name": "The Album",
            "track_number": number,
            "duration": 200 + number,
            **song,
        },
        state=state,
        output_path=str(path) if path is not None else None,
    )
    db_session.add(track)
    if ledger is not None:
        db_session.add(DownloadedTrack(spotify_track_id=track.spotify_track_id, file_path=str(ledger), format="opus"))
    db_session.commit()
    return track


def _file(root: Path, name: str, size: int = 4096) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))
    return path


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip(response) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(response.content))


def test_every_present_file_is_in_the_zip_byte_for_byte_with_an_m3u8(authenticated_client, db_session, owner, roots):
    downloads, library = roots
    job = _job(db_session, owner)
    # Inserted out of album order: the archive's playlist follows track_number.
    files = {3: _file(downloads, "03 - c.opus"), 1: _file(library, "Artist/Album/01 - a.opus"), 2: _file(downloads, "02 - b.opus")}
    for number in (3, 1, 2):
        _track(db_session, job, number, path=files[number])

    response = authenticated_client.get(f"/api/jobs/{job.id}/export.zip")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert int(response.headers["content-length"]) == len(response.content)
    archive = _zip(response)
    assert archive.testzip() is None
    names = archive.namelist()
    assert sorted(names) == sorted(["01 - a.opus", "02 - b.opus", "03 - c.opus", "The Album.m3u8"])
    for number, path in files.items():
        info = archive.getinfo(path.name)
        assert info.compress_type == zipfile.ZIP_STORED
        assert _sha(archive.read(path.name)) == _sha(path.read_bytes())
    assert "MISSING.txt" not in names
    assert archive.read("The Album.m3u8").decode("utf-8") == (
        "#EXTM3U\n"
        "#EXTINF:201,Artist A, Artist B - Song 1\n01 - a.opus\n"
        "#EXTINF:202,Artist A, Artist B - Song 2\n02 - b.opus\n"
        "#EXTINF:203,Artist A, Artist B - Song 3\n03 - c.opus\n"
    )


def test_extracted_entries_are_readable_by_other_users(authenticated_client, db_session, owner, roots):
    """0644, not zipstream-ng's 0600 for an added iterable: Info-ZIP restores the mode as is."""
    downloads, _library = roots
    job = _job(db_session, owner)
    _track(db_session, job, 1, path=_file(downloads, "01 - a.opus"))
    _track(db_session, job, 2, state=TrackState.WAITING)

    archive = _zip(authenticated_client.get(f"/api/jobs/{job.id}/export.zip"))

    for info in archive.infolist():
        assert info.external_attr >> 16 == 0o100644, info.filename


def test_an_artist_job_plays_album_by_album_oldest_first(authenticated_client, db_session, owner, roots):
    """spotdl sets no list position on an artist's album tracks, and one expansion's tracks
    share a created_at: without an album key the M3U interleaved the albums."""
    downloads, _library = roots
    job = _job(db_session, owner)
    for album, date in (("B", "2010-01-01"), ("A", "2005-01-01")):
        for number in (2, 1):
            _track(
                db_session,
                job,
                number + (10 if album == "B" else 0),
                path=_file(downloads, f"{album}{number}.opus"),
                list_name=None,
                track_number=number,
                album_name=album,
                album_id=f"id-{album}",
                date=date,
            )
    # One expansion: the same created_at for every track.
    db_session.query(Track).filter(Track.job_id == job.id).update({Track.created_at: datetime(2026, 1, 1, tzinfo=timezone.utc)})
    db_session.commit()

    playlist = authenticated_client.get(f"/api/jobs/{job.id}/playlist.m3u8").text

    assert [line for line in playlist.splitlines() if not line.startswith("#")] == [
        "A1.opus",
        "A2.opus",
        "B1.opus",
        "B2.opus",
    ]


def test_the_ledger_path_wins_over_output_path(authenticated_client, db_session, owner, roots):
    """A library move repoints the ledger's file_path (master-v3 invariant), not the track."""
    downloads, library = roots
    job = _job(db_session, owner)
    moved = _file(library, "Moved/01 - a.opus")
    _track(db_session, job, 1, path=downloads / "01 - a.opus", ledger=moved)

    archive = _zip(authenticated_client.get(f"/api/jobs/{job.id}/export.zip"))

    assert _sha(archive.read("01 - a.opus")) == _sha(moved.read_bytes())


def test_deleted_files_are_listed_in_missing_txt_and_the_rest_are_intact(authenticated_client, db_session, owner, roots):
    downloads, _library = roots
    job = _job(db_session, owner)
    kept = [_file(downloads, f"0{n} - kept.opus") for n in (1, 2)]
    gone = [_file(downloads, f"0{n} - gone.opus") for n in (3, 4)]
    for number, path in enumerate(kept + gone, start=1):
        _track(db_session, job, number, path=path, name=f"Track {number}")
    _track(db_session, job, 5, state=TrackState.LOOKUP_FAILED, name="Track 5")
    _track(db_session, job, 6, state=TrackState.WAITING, name="Track 6")
    for path in gone:
        path.unlink()

    archive = _zip(authenticated_client.get(f"/api/jobs/{job.id}/export.zip"))

    assert sorted(archive.namelist()) == sorted([p.name for p in kept] + ["The Album.m3u8", "MISSING.txt"])
    for path in kept:
        assert _sha(archive.read(path.name)) == _sha(path.read_bytes())
    missing = archive.read("MISSING.txt").decode("utf-8")
    assert missing.startswith("The Album: 4 of 6 tracks are not in this archive.")
    assert "Artist A, Artist B - Track 3 -- file not found at its recorded path" in missing
    assert "Artist A, Artist B - Track 4 -- file not found at its recorded path" in missing
    assert "Artist A, Artist B - Track 5 -- not downloaded (lookup failed)" in missing
    assert "Artist A, Artist B - Track 6 -- not downloaded (waiting)" in missing
    assert "Track 1" not in missing and "Track 2" not in missing
    playlist = archive.read("The Album.m3u8").decode("utf-8")
    assert "01 - kept.opus" in playlist and "gone" not in playlist


def test_a_retention_archived_job_is_still_exportable(authenticated_client, db_session, owner, roots):
    downloads, _library = roots
    job = _job(db_session, owner, archived=True)
    path = _file(downloads, "01 - a.opus")
    _track(db_session, job, 1, path=path)

    zipped = authenticated_client.get(f"/api/jobs/{job.id}/export.zip")
    playlist = authenticated_client.get(f"/api/jobs/{job.id}/playlist.m3u8")

    assert zipped.status_code == 200
    assert _sha(_zip(zipped).read("01 - a.opus")) == _sha(path.read_bytes())
    assert playlist.status_code == 200 and "01 - a.opus" in playlist.text


@pytest.mark.parametrize(
    "bad_path",
    [
        "/etc/hostname",  # exists, outside both roots
        "{downloads}/../outside.opus",  # `..` out of the downloads root
        "{downloads}",  # the root itself
        "{downloads}/link.opus",  # a symlink pointing out of the root
    ],
)
def test_a_path_outside_the_roots_is_excluded_and_listed_as_missing(
    bad_path, authenticated_client, db_session, owner, roots, tmp_path
):
    downloads, _library = roots
    outside = _file(tmp_path, "outside.opus")
    (downloads / "link.opus").symlink_to(outside)
    job = _job(db_session, owner)
    _track(db_session, job, 1, path=_file(downloads, "01 - ok.opus"))
    _track(db_session, job, 2, path=bad_path.format(downloads=downloads), name="Corrupted")

    archive = _zip(authenticated_client.get(f"/api/jobs/{job.id}/export.zip"))

    assert sorted(archive.namelist()) == ["01 - ok.opus", "MISSING.txt", "The Album.m3u8"]
    assert "Corrupted -- recorded path is outside the download and library folders" in archive.read(
        "MISSING.txt"
    ).decode("utf-8")


def test_same_basenames_are_deduplicated_with_a_numbered_suffix(authenticated_client, db_session, owner, roots):
    downloads, library = roots
    job = _job(db_session, owner)
    first = _file(downloads, "a/Intro.opus")
    second = _file(downloads, "b/Intro.opus")
    third = _file(library, "c/intro.OPUS")
    for number, path in enumerate((first, second, third), start=1):
        _track(db_session, job, number, path=path)

    archive = _zip(authenticated_client.get(f"/api/jobs/{job.id}/export.zip"))

    assert sorted(archive.namelist()) == sorted(["Intro.opus", "Intro (2).opus", "intro (3).OPUS", "The Album.m3u8"])
    assert _sha(archive.read("Intro (2).opus")) == _sha(second.read_bytes())
    assert "Intro (2).opus\n" in archive.read("The Album.m3u8").decode("utf-8")


def test_a_track_file_named_like_the_playlist_or_missing_txt_is_renamed(authenticated_client, db_session, owner, roots):
    downloads, _library = roots
    job = _job(db_session, owner)
    _track(db_session, job, 1, path=_file(downloads, "MISSING.txt"))
    _track(db_session, job, 2, path=_file(downloads, "The Album.m3u8"))
    _track(db_session, job, 3, state=TrackState.WAITING)

    archive = _zip(authenticated_client.get(f"/api/jobs/{job.id}/export.zip"))

    assert sorted(archive.namelist()) == sorted(["MISSING (2).txt", "The Album (2).m3u8", "The Album.m3u8", "MISSING.txt"])


def test_a_non_ascii_title_names_the_archive_rfc_5987(authenticated_client, db_session, owner, roots):
    downloads, _library = roots
    job = _job(db_session, owner)
    _track(db_session, job, 1, path=_file(downloads, "a.opus"), list_name="Björk: Homogénic / Ünïcode")

    head = authenticated_client.head(f"/api/jobs/{job.id}/export.zip")
    playlist = authenticated_client.get(f"/api/jobs/{job.id}/playlist.m3u8")

    disposition = head.headers["content-disposition"]
    assert 'filename="Bjrk_ Homognic _ ncode.zip"' in disposition
    assert "filename*=UTF-8''Bj%C3%B6rk_%20Homog%C3%A9nic%20_%20%C3%9Cn%C3%AFcode.zip" in disposition
    assert "filename*=UTF-8''Bj%C3%B6rk_%20Homog%C3%A9nic%20_%20%C3%9Cn%C3%AFcode.m3u8" in playlist.headers[
        "content-disposition"
    ]


def test_head_answers_the_same_headers_without_a_body(authenticated_client, db_session, owner, roots):
    downloads, _library = roots
    job = _job(db_session, owner)
    _track(db_session, job, 1, path=_file(downloads, "a.opus", size=10_000))

    head = authenticated_client.head(f"/api/jobs/{job.id}/export.zip")
    get = authenticated_client.get(f"/api/jobs/{job.id}/export.zip")

    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == get.headers["content-length"] == str(len(get.content))
    assert head.headers["content-disposition"] == get.headers["content-disposition"]


def test_over_the_file_limit_is_a_413_and_the_playlist_still_works(authenticated_client, db_session, owner, roots, monkeypatch):
    downloads, _library = roots
    monkeypatch.setattr(get_settings(), "export_max_files", 2)
    job = _job(db_session, owner)
    for number in (1, 2, 3):
        _track(db_session, job, number, path=_file(downloads, f"{number}.opus"))

    zipped = authenticated_client.get(f"/api/jobs/{job.id}/export.zip")
    head = authenticated_client.head(f"/api/jobs/{job.id}/export.zip")
    playlist = authenticated_client.get(f"/api/jobs/{job.id}/playlist.m3u8")

    assert zipped.status_code == 413
    assert zipped.json()["code"] == "export_too_large"
    assert zipped.json()["params"]["files"] == 3
    assert zipped.json()["params"]["max_files"] == 2
    assert head.status_code == 413
    assert playlist.status_code == 200 and playlist.text.count("#EXTINF") == 3


def test_the_zip_says_how_many_tracks_have_a_file_on_disk(authenticated_client, db_session, owner, roots, monkeypatch):
    """The open job's strip reads these (one HEAD), so a deleted file isn't counted, also
    on a 413 (the playlist stays offered)."""
    downloads, _library = roots
    job = _job(db_session, owner)
    _track(db_session, job, 1, path=_file(downloads, "1.opus"))
    gone = _file(downloads, "2.opus")
    _track(db_session, job, 2, path=gone)
    _track(db_session, job, 3, state=TrackState.WAITING)
    gone.unlink()

    head = authenticated_client.head(f"/api/jobs/{job.id}/export.zip")
    monkeypatch.setattr(app_settings, "export_limits", lambda db: (0, 10**9))
    over = authenticated_client.head(f"/api/jobs/{job.id}/export.zip")

    assert (head.headers["x-export-files"], head.headers["x-export-tracks"]) == ("1", "3")
    assert over.status_code == 413
    assert (over.headers["x-export-files"], over.headers["x-export-tracks"]) == ("1", "3")


def test_closing_the_stream_closes_the_file_being_read(db_session, make_user, roots):
    """An aborted download: the response closes its iterator, and the file goes with it,
    not whenever the garbage collector gets to it."""
    downloads, _library = roots
    job = _job(db_session, make_user("owner@example.com"))
    _track(db_session, job, 1, path=_file(downloads, "big.opus", size=4 * 1024 * 1024))
    plan = export.plan_export(db_session, job.id, "The Album")
    chunks = export.iter_chunks(export.build_zip(plan))
    next(chunks)
    fd_dir = Path(f"/proc/{os.getpid()}/fd")
    open_now = lambda: sum(1 for fd in fd_dir.iterdir() if fd.resolve() == downloads / "big.opus")  # noqa: E731
    assert open_now() == 1

    chunks.close()

    assert open_now() == 0


def test_a_title_with_a_line_break_stays_on_one_line_in_missing_txt(authenticated_client, db_session, owner, roots):
    downloads, _library = roots
    job = _job(db_session, owner)
    _track(db_session, job, 1, path=_file(downloads, "1.opus"), list_name="Evil\nX-Injected: 1")
    _track(db_session, job, 2, state=TrackState.WAITING, list_name="Evil\nX-Injected: 1")

    missing = _zip(authenticated_client.get(f"/api/jobs/{job.id}/export.zip")).read("MISSING.txt").decode()

    assert missing.splitlines()[0] == "Evil X-Injected: 1: 1 of 2 tracks are not in this archive."


def test_over_the_size_limit_is_a_413(authenticated_client, db_session, owner, roots, monkeypatch):
    downloads, _library = roots
    monkeypatch.setattr(app_settings, "export_limits", lambda db: (2000, 5000))
    job = _job(db_session, owner)
    _track(db_session, job, 1, path=_file(downloads, "1.opus", size=3000))
    _track(db_session, job, 2, path=_file(downloads, "2.opus", size=3000))

    response = authenticated_client.get(f"/api/jobs/{job.id}/export.zip")

    assert response.status_code == 413
    assert response.json()["params"] == {"files": 2, "bytes": 6000, "max_files": 2000, "max_bytes": 5000}


def test_the_limits_are_the_env_defaults_until_an_admin_overrides_them(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "export_max_files", 2000)
    monkeypatch.setattr(get_settings(), "export_max_gb", 20)
    # GB as the page and the env say it: 10^9 bytes.
    assert app_settings.export_limits(db_session) == (2000, 20 * 10**9)

    app_settings.update_export_settings(db_session, export_max_files=10, export_max_gb=1)
    assert app_settings.export_limits(db_session) == (10, 10**9)

    app_settings.update_export_settings(db_session, export_max_files=None)
    assert app_settings.export_limits(db_session) == (2000, 10**9)


def test_admin_reads_and_overrides_the_export_settings(admin_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "export_max_files", 2000)
    monkeypatch.setattr(get_settings(), "export_max_gb", 20)

    initial = admin_client.get("/api/settings/export")
    pinned = admin_client.patch("/api/settings/export", json={"export_max_files": 50, "export_max_gb": 3})
    cleared = admin_client.patch("/api/settings/export", json={"export_max_gb": None})
    untouched = admin_client.patch("/api/settings/export", json={})

    assert initial.json() == {"export_max_files": None, "export_max_gb": None, "default_max_files": 2000, "default_max_gb": 20}
    assert pinned.json()["export_max_files"] == 50 and pinned.json()["export_max_gb"] == 3
    assert cleared.json()["export_max_files"] == 50 and cleared.json()["export_max_gb"] is None
    assert untouched.json() == cleared.json()


@pytest.mark.parametrize(
    "field, value", [("export_max_files", 0), ("export_max_files", 65_001), ("export_max_gb", 0), ("export_max_gb", 10_001)]
)
def test_export_settings_out_of_range_are_refused(field, value, admin_client, db_session):
    response = admin_client.patch("/api/settings/export", json={field: value})

    assert response.status_code == 400
    assert response.json()["code"] == "setting_out_of_range"
    assert db_session.get(AppSettings, 1) is None or getattr(db_session.get(AppSettings, 1), field) is None


def test_a_job_with_no_files_still_exports_its_missing_list(authenticated_client, db_session, owner, roots):
    job = _job(db_session, owner)
    _track(db_session, job, 1, state=TrackState.WAITING)

    archive = _zip(authenticated_client.get(f"/api/jobs/{job.id}/export.zip"))

    assert sorted(archive.namelist()) == ["MISSING.txt", "The Album.m3u8"]
    assert archive.read("The Album.m3u8").decode("utf-8") == "#EXTM3U\n"


def test_export_needs_a_session(client, db_session, make_user, roots):
    job = _job(db_session, make_user("owner@example.com"))

    assert client.get(f"/api/jobs/{job.id}/export.zip").status_code == 401
    assert client.get(f"/api/jobs/{job.id}/playlist.m3u8").status_code == 401


def test_unknown_job_is_a_404(authenticated_client, roots):
    response = authenticated_client.get("/api/jobs/00000000-0000-0000-0000-000000000000/export.zip")

    assert response.status_code == 404
    assert response.json()["code"] == "job_not_found"


def test_a_long_file_name_keeps_its_extension_and_numbers_before_it(authenticated_client, db_session, owner, roots):
    """Classical and multi-artist names run long: the stem is cut (to 200 UTF-8 bytes), never the
    extension, and a dot inside the title ("No. 3") isn't taken for one."""
    downloads, library = roots
    job = _job(db_session, owner)
    name = "Ádám Fischer, Karl Böhm, " * 7 + "Brandenburg Concerto No. 3, BWV 1048_ I. Allegro.opus"
    assert 230 < len(name.encode("utf-8")) <= 255
    _track(db_session, job, 1, path=_file(downloads / "a", name))
    _track(db_session, job, 2, path=_file(library / "b", name))

    names = sorted(_zip(authenticated_client.get(f"/api/jobs/{job.id}/export.zip")).namelist())

    audio = [n for n in names if n.endswith(".opus")]
    assert len(audio) == 2
    first = min(audio, key=len)
    assert len(first.encode("utf-8")) <= 200
    assert first.startswith("Ádám Fischer, Karl Böhm, ")
    assert first.removesuffix(".opus") + " (2).opus" in audio


def test_a_file_name_starting_with_hash_is_not_a_comment_in_the_playlist(authenticated_client, db_session, owner, roots):
    downloads, _library = roots
    job = _job(db_session, owner)
    _track(db_session, job, 1, path=_file(downloads, "#1 Crush.opus"))

    archive = _zip(authenticated_client.get(f"/api/jobs/{job.id}/export.zip"))

    assert "#1 Crush.opus" in archive.namelist()
    assert archive.read("The Album.m3u8").decode("utf-8").splitlines()[-1] == "./#1 Crush.opus"


def test_library_paths_list_only_library_files_and_name_the_rest(admin_client, db_session, admin_user, roots):
    downloads, library = roots
    job = _job(db_session, admin_user)
    _track(db_session, job, 1, path=_file(library, "Artist/01 - a.opus"))
    _track(db_session, job, 2, path=_file(downloads, "02 - b.opus"))

    response = admin_client.get(f"/api/jobs/{job.id}/playlist.m3u8?paths=library")

    assert response.status_code == 200
    assert response.text == (
        "#EXTM3U\n"
        f"#EXTINF:201,Artist A, Artist B - Song 1\n{library / 'Artist' / '01 - a.opus'}\n"
        "# not in the library yet: Artist A, Artist B - Song 2\n"
    )


def _stream_after(plan, before_stream):
    """The zip's bytes, with `before_stream` run once the plan exists (and the
    Content-Length is fixed) but before any file is read."""
    archive = export.build_zip(plan)
    length = len(archive)
    before_stream()
    return length, b"".join(export.iter_chunks(archive))


def test_a_file_a_sweep_moves_mid_stream_is_read_from_its_new_path(db_session, make_user, roots, monkeypatch):
    """Owner's decision (2026-10-30): the sweep commits the ledger's new path before it removes
    the source, so the stream finds the file there, at the size the plan counted."""
    downloads, library = roots
    job = _job(db_session, make_user("owner@example.com"))
    source = _file(downloads, "01 - a.opus")
    track = _track(db_session, job, 1, path=source, ledger=source)
    data = source.read_bytes()
    plan = export.plan_export(db_session, job.id, "The Album")

    def sweep():
        dest = library / "Artist" / "01 - a.opus"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(data)
        db_session.get(DownloadedTrack, track.spotify_track_id).file_path = str(dest)
        db_session.commit()
        source.unlink()

    length, body = _stream_after(plan, sweep)

    assert len(body) == length
    archive = zipfile.ZipFile(io.BytesIO(body))
    assert archive.testzip() is None
    assert _sha(archive.read("01 - a.opus")) == _sha(data)


@pytest.mark.parametrize("case", ["gone", "other size", "grew"])
def test_a_file_that_cant_be_streamed_as_planned_ends_the_stream(case, db_session, make_user, roots, monkeypatch):
    downloads, library = roots
    job = _job(db_session, make_user("owner@example.com"))
    source = _file(downloads, "01 - a.opus")
    track = _track(db_session, job, 1, path=source, ledger=source)
    plan = export.plan_export(db_session, job.id, "The Album")

    def change():
        if case == "grew":
            with source.open("ab") as handle:
                handle.write(b"more")
            return
        if case == "other size":
            dest = _file(library, "01 - a.opus", size=100)
            db_session.get(DownloadedTrack, track.spotify_track_id).file_path = str(dest)
            db_session.commit()
        source.unlink()

    with pytest.raises(export.ExportFileChanged):
        _stream_after(plan, change)


def test_a_file_moved_before_its_stat_is_found_through_the_ledger(db_session, make_user, roots):
    """A sweep that commits the ledger's new path between the plan's read and its stat:
    one batched re-read finds it, instead of listing it as missing."""
    downloads, library = roots
    job = _job(db_session, make_user("owner@example.com"))
    source = _file(downloads, "01 - a.opus")
    track = _track(db_session, job, 1, path=source, ledger=source)
    rows = export.load_rows(db_session, job.id)
    dest = library / "Artist" / "01 - a.opus"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(source.read_bytes())
    db_session.get(DownloadedTrack, track.spotify_track_id).file_path = str(dest)
    db_session.commit()
    source.unlink()

    plan = export.plan_from_rows(rows, "The Album")

    assert [(f.arcname, f.path, f.in_library) for f in plan.files] == [("01 - a.opus", dest, True)]
    assert plan.missing == []


def test_a_zip_over_4_gib_has_the_length_it_declares(db_session, make_user, roots):
    """Past 4 GiB zipstream-ng writes zip64 records: the length counted up front must still
    be the bytes streamed (sparse files, so the test writes nothing real)."""
    downloads, _library = roots
    job = _job(db_session, make_user("owner@example.com"))
    for number in (1, 2):
        path = downloads / f"{number}.opus"
        with path.open("wb") as handle:
            handle.truncate(2_300 * 1024 * 1024)
        _track(db_session, job, number, path=path)
    _track(db_session, job, 3, state=TrackState.WAITING)
    archive = export.build_zip(export.plan_export(db_session, job.id, "The Album"))
    declared = len(archive)
    assert declared > 4 * 1024**3

    streamed = sum(len(chunk) for chunk in export.iter_chunks(archive))

    assert streamed == declared


def test_the_response_closes_its_stream_when_the_client_is_gone(db_session, make_user, roots):
    """On a disconnect Starlette's send() raises and nothing closes the body: the response
    does, so the file being read is closed at once, not by the garbage collector."""
    import asyncio

    from starlette.requests import ClientDisconnect

    from app.routers import export as export_router

    downloads, _library = roots
    job = _job(db_session, make_user("owner@example.com"))
    _track(db_session, job, 1, path=_file(downloads, "big.opus", size=4 * 1024 * 1024))
    archive = export.build_zip(export.plan_export(db_session, job.id, "The Album"))
    response = export_router._ClosingStreamingResponse(export_router._stream(archive), media_type="application/zip")
    fd_dir = Path(f"/proc/{os.getpid()}/fd")
    open_now = lambda: sum(1 for fd in fd_dir.iterdir() if fd.resolve() == downloads / "big.opus")  # noqa: E731
    sent = []

    async def send(message):
        sent.append(message)
        if len(sent) > 2:
            raise OSError("client went away")

    async def receive():
        await asyncio.sleep(3600)

    # Starlette reports the failed send as a ClientDisconnect.
    with pytest.raises((OSError, ClientDisconnect)):
        asyncio.run(response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send))

    assert len(sent) > 2
    assert open_now() == 0


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Björk", "Björk"),
        ("line\u2028sep\x85", "line_sep_"),
        ("AC/DC: Live", "AC_DC_ Live"),
        ("..\\..\\evil", "_.._evil"),
        ("...", "export"),
        ("  ", "export"),
        ("line\nbreak", "line_break"),
        ("x" * 300, "x" * 200),
        ("é" * 150, "é" * 100),
    ],
)
def test_safe_name(name, expected):
    assert export.safe_name(name) == expected


@pytest.mark.parametrize(
    "name, expected",
    [
        ("a.opus", "a.opus"),
        ("x" * 300 + ".opus", "x" * 195 + ".opus"),
        ("Concerto No. 3", "Concerto No. 3"),
        (".opus", "track.opus"),
        (".hidden.opus", "hidden.opus"),
        ("NUL.opus", "_NUL.opus"),
        ("com1.opus", "_com1.opus"),
        ("Console.opus", "Console.opus"),
        ("Bjo\u0308rk.opus", "Bj\u00f6rk.opus"),
    ],
)
def test_safe_name_keeps_a_file_extension(name, expected):
    assert export.safe_name(name, "track", keep_extension=True) == expected
