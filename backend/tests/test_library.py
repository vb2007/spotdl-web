import errno
from pathlib import Path

import pytest

from app.services import library


def test_render_folder_name_substitutes_all_placeholders():
    tags = {"artists": ["Daft Punk"], "album_name": "Discovery", "year": 2001}

    name = library.render_folder_name("{artist} - {album} - ({year})", tags)

    assert name == "Daft Punk - Discovery - (2001)"


def test_render_folder_name_falls_back_for_missing_tags():
    name = library.render_folder_name("{artist} - {album} - ({year})", {})

    assert name == "Unknown Artist - Unknown Album - (Unknown Year)"


def test_render_folder_name_sanitizes_path_separators_in_tag_values():
    tags = {"artists": ["AC/DC"], "album_name": "Back In Black", "year": 1980}

    name = library.render_folder_name("{artist} - {album}", tags)

    assert "/" not in name
    assert name == "AC-DC - Back In Black"


def test_destination_path_rebuilds_folder_but_keeps_source_filename(tmp_path):
    target_dir = tmp_path / "library"
    source = tmp_path / "downloads" / "01 - Daft Punk - One More Time.mp3"
    tags = {"artists": ["Daft Punk"], "album_name": "Discovery", "year": 2001}

    dest = library.destination_path(target_dir, "{artist} - {album} - ({year})", tags, source)

    assert dest == target_dir / "Daft Punk - Discovery - (2001)" / source.name


def test_files_match_true_for_identical_content(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"identical content")
    b.write_bytes(b"identical content")

    assert library.files_match(a, b) is True


def test_files_match_false_for_different_size(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"short")
    b.write_bytes(b"much much longer content")

    assert library.files_match(a, b) is False


def test_files_match_false_for_same_size_different_content(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"AAAAA")
    b.write_bytes(b"BBBBB")

    assert library.files_match(a, b) is False


def test_copy_verify_succeeds_and_leaves_source_untouched(tmp_path):
    source = tmp_path / "downloads" / "track.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"the audio bytes")
    dest = tmp_path / "library" / "Artist - Album" / "track.mp3"

    ok = library.copy_verify(source, dest)

    assert ok is True
    assert dest.exists()
    assert dest.read_bytes() == b"the audio bytes"
    assert source.exists()  # copy_verify never deletes the source -- the caller decides


def test_copy_verify_failure_leaves_both_files_in_place(tmp_path, monkeypatch):
    source = tmp_path / "downloads" / "track.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"the audio bytes")
    dest = tmp_path / "library" / "Artist - Album" / "track.mp3"

    monkeypatch.setattr(library, "files_match", lambda a, b: False)

    ok = library.copy_verify(source, dest)

    assert ok is False
    # v31: never deleted, per the plan's "nothing is ever deleted on the target
    # filesystem, not once, not under any flag" -- not even a copy this function itself
    # just wrote. But also never left at the exact expected filename, or a later sweep's
    # content-blind "already exists" check would silently adopt this corrupt copy as the
    # real file and quarantine/delete a good source over it.
    assert not dest.exists()
    siblings = list(dest.parent.iterdir())
    assert len(siblings) == 1
    assert siblings[0].name.startswith(f"{dest.name}.verify-failed-")
    assert siblings[0].read_bytes() == b"the audio bytes"
    assert source.exists()


def test_quarantine_moves_source_and_returns_new_path(tmp_path):
    source = tmp_path / "downloads" / "track.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"quarantine me")
    quarantine_dir = tmp_path / "quarantine"

    dest = library.quarantine(source, quarantine_dir)

    assert dest == quarantine_dir / "track.mp3"
    assert dest.read_bytes() == b"quarantine me"
    assert not source.exists()


def test_quarantine_disambiguates_a_name_collision(tmp_path):
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()
    (quarantine_dir / "track.mp3").write_bytes(b"already quarantined earlier")

    source = tmp_path / "downloads" / "track.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"a second, different file with the same name")

    dest = library.quarantine(source, quarantine_dir)

    assert dest != quarantine_dir / "track.mp3"
    assert dest.parent == quarantine_dir
    assert dest.read_bytes() == b"a second, different file with the same name"
    # The earlier quarantined file was never touched.
    assert (quarantine_dir / "track.mp3").read_bytes() == b"already quarantined earlier"


def test_read_sort_tags_returns_none_for_unsupported_format(tmp_path):
    source = tmp_path / "track.wav"
    source.write_bytes(b"not a real wav file")

    assert library.read_sort_tags(source) is None


def _disk_full_copy(source, dest):
    """shutil.copy2 on a full disk: part of the file written, then ENOSPC (as on a 2 MiB tmpfs)."""
    Path(dest).write_bytes(Path(source).read_bytes()[:4])
    raise OSError(28, "No space left on device")


def test_copy_verify_renames_a_partial_copy_off_the_destination_when_the_disk_fills(tmp_path, monkeypatch):
    """v57 (L7): the copy raises before any checksum. The partial file must not stay at the
    destination's exact name, where the next sweep's folder+filename check would adopt it."""

    source = tmp_path / "source.mp3"
    source.write_bytes(b"the whole real audio")
    dest = tmp_path / "library" / "Album" / "source.mp3"
    monkeypatch.setattr(library.shutil, "copy2", _disk_full_copy)

    with pytest.raises(OSError) as exc_info:
        library.copy_verify(source, dest)

    assert exc_info.value.errno == errno.ENOSPC
    assert not dest.exists()
    leftovers = list(dest.parent.iterdir())
    assert len(leftovers) == 1 and leftovers[0].name.startswith("source.mp3.copy-failed-"), leftovers
    assert leftovers[0].read_bytes() == b"the "  # kept, never deleted
    assert source.read_bytes() == b"the whole real audio"


def test_path_relation_resolves_before_comparing(tmp_path):
    """v57 (L2): `..` and a symlinked alias compare as the directory they name."""
    (tmp_path / "downloads").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "downloads")

    assert library.path_relation(tmp_path / "alias", tmp_path / "downloads") == "equal"
    assert library.path_relation(tmp_path / "downloads" / ".." / "downloads" / "x", tmp_path / "downloads") == "inside"
    assert library.path_relation(tmp_path, tmp_path / "downloads") == "contains"
    assert library.path_relation(tmp_path / "library", tmp_path / "downloads") is None


def test_copy_verify_keeps_a_complete_copy_whose_metadata_copy_failed(tmp_path, monkeypatch):
    """v57 (review round 1): copy2 can raise in copystat after every byte landed (a mount that
    refuses times or mode). That copy verifies, so it's a success, not a renamed full-size
    leftover on the library filesystem every sweep."""
    source = tmp_path / "source.mp3"
    source.write_bytes(b"the whole real audio")
    dest = tmp_path / "library" / "Album" / "source.mp3"

    def _copystat_fails(src, dst):
        Path(dst).write_bytes(Path(src).read_bytes())
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(library.shutil, "copy2", _copystat_fails)

    assert library.copy_verify(source, dest) is True
    assert dest.read_bytes() == b"the whole real audio"
    assert [p.name for p in dest.parent.iterdir()] == ["source.mp3"]


def test_copy_verify_never_leaves_an_unverified_file_at_the_destination(tmp_path, monkeypatch):
    """v57 (review round 2): a worker killed mid-copy (OOM, a deploy) leaves its partial file at
    the staging name, never the real one the next sweep's "already exists" check reads."""
    source = tmp_path / "source.mp3"
    source.write_bytes(b"the whole real audio")
    dest = tmp_path / "library" / "Album" / "source.mp3"

    class _Killed(BaseException):
        pass

    def _killed_mid_copy(src, dst):
        Path(dst).write_bytes(b"the wh")
        raise _Killed

    monkeypatch.setattr(library.shutil, "copy2", _killed_mid_copy)

    with pytest.raises(_Killed):
        library.copy_verify(source, dest)

    assert not dest.exists()
    assert [p.name.split("-")[0] for p in dest.parent.iterdir()] == ["source.mp3.copying"]


def test_copy_verify_never_overwrites_a_destination_that_appeared_meanwhile(tmp_path, monkeypatch):
    source = tmp_path / "source.mp3"
    source.write_bytes(b"the whole real audio")
    dest = tmp_path / "library" / "Album" / "source.mp3"
    real_copy2 = library.shutil.copy2

    def _someone_else_wrote_dest(src, dst):
        real_copy2(src, dst)
        dest.write_bytes(b"another file")

    monkeypatch.setattr(library.shutil, "copy2", _someone_else_wrote_dest)

    with pytest.raises(FileExistsError):
        library.copy_verify(source, dest)
    assert dest.read_bytes() == b"another file"
