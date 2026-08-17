from pathlib import Path

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
    # Never deleted, per the plan's "nothing is ever deleted on the target filesystem,
    # not once, not under any flag" -- not even a copy this function itself just wrote.
    assert dest.exists()
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
