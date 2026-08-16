import shutil
from pathlib import Path

import pytest
from spotdl.types.song import Song
from spotdl.utils.metadata import get_file_metadata

from app.services import tagging

ALL_FORMATS = ["silence.mp3", "silence.flac", "silence.ogg", "silence.opus", "silence.m4a"]

# Tiny real (silent) audio fixtures generated once with ffmpeg, not at test time --
# CI's backend-tests job deliberately has no ffmpeg (docs/GOTCHAS.md v26 entry / ci.yml),
# so these pure-function tests exercise the real mutagen read/write path against real
# containers without needing it. Copied into tmp_path per test since repair_tags mutates
# the file in place.
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _copy_fixture(tmp_path: Path, name: str) -> Path:
    dest = tmp_path / name
    shutil.copyfile(FIXTURES_DIR / name, dest)
    return dest


def _make_song(**overrides) -> Song:
    base = dict(
        name="Test Title",
        artists=["Test Artist"],
        artist="Test Artist",
        genres=["test"],
        disc_number=1,
        disc_count=1,
        album_name="Test Album",
        album_artist="Test Artist",
        duration=200,
        year=2020,
        date="2020-01-01",
        track_number=1,
        tracks_count=10,
        song_id="testid1234567890123",
        explicit=False,
        publisher="Test Publisher",
        url="https://open.spotify.com/track/testid1234567890123",
        isrc="TEST00000000",
        cover_url=None,
        copyright_text=None,
        download_url=None,
    )
    base.update(overrides)
    return Song(**base)


def test_is_supported_format():
    assert tagging.is_supported_format(Path("song.mp3"))
    assert tagging.is_supported_format(Path("song.flac"))
    assert tagging.is_supported_format(Path("song.ogg"))
    assert tagging.is_supported_format(Path("song.opus"))
    assert tagging.is_supported_format(Path("song.m4a"))
    # spotdl's own get_file_metadata can't read WAV's ID3 frames back through its
    # generic Vorbis-comment-style key lookup -- see tagging.py's SUPPORTED_FORMATS
    # docstring and docs/GOTCHAS.md's v26 entry.
    assert not tagging.is_supported_format(Path("song.wav"))


@pytest.mark.parametrize("filename", ALL_FORMATS)
def test_verify_tags_reports_everything_missing_on_untagged_file(tmp_path, filename):
    path = _copy_fixture(tmp_path, filename)

    missing = tagging.verify_tags(path)

    assert missing == {"name", "artists", "album_name", "track_number", "year", "cover_art"}


@pytest.mark.parametrize("filename", ALL_FORMATS)
def test_repair_tags_fills_basic_fields_from_song(tmp_path, filename):
    path = _copy_fixture(tmp_path, filename)
    song = _make_song()
    missing = tagging.verify_tags(path) - {"cover_art"}

    warning = tagging.repair_tags(path, song, missing)

    assert warning is None
    # cover_art was deliberately excluded from `missing` above, so repair_tags never
    # touched it (skip_album_art=True) -- proves repair only acts on what it's told to.
    assert tagging.verify_tags(path) == {"cover_art"}


@pytest.mark.parametrize("filename", ALL_FORMATS)
def test_repair_tags_warns_when_cover_art_unavailable(tmp_path, filename):
    path = _copy_fixture(tmp_path, filename)
    song = _make_song(cover_url=None)
    # The full, realistic set -- matches what download_track actually passes (its own
    # call always comes from a fresh verify_tags(), never an artificially narrowed one).
    missing = tagging.verify_tags(path)

    warning = tagging.repair_tags(path, song, missing)

    assert warning is not None
    assert "cover art" in warning.lower()
    assert tagging.verify_tags(path) == {"cover_art"}


def test_repair_tags_does_not_clobber_correct_year_when_not_requested(tmp_path):
    """Regression: the flac/ogg/opus year-tag patch (tagging.py's _YEAR_TAG_GAP_FORMATS)
    must only fire when "year" is actually in `missing`. An earlier version ran it
    unconditionally whenever repair_tags was called at all, which would silently
    overwrite an already-correct year with stale data from a second, unrelated call
    (e.g. one that only asked for cover_art to be repaired)."""
    path = _copy_fixture(tmp_path, "silence.flac")
    song_first = _make_song(year=2020)
    tagging.repair_tags(path, song_first, tagging.verify_tags(path))
    assert str(get_file_metadata(path)["year"]) == "2020"

    song_second = _make_song(year=1999)
    tagging.repair_tags(path, song_second, {"cover_art"})

    assert str(get_file_metadata(path)["year"]) == "2020"


def test_repair_tags_skips_year_patch_when_song_year_is_none(tmp_path):
    """Regression: writing str(None) into the year tag would read back as a non-empty
    ("None") string forever -- verify_tags would then consider "year" permanently
    present and never flag it for repair again."""
    path = _copy_fixture(tmp_path, "silence.flac")
    song = _make_song(year=None)
    missing = tagging.verify_tags(path)

    tagging.repair_tags(path, song, missing)

    meta = get_file_metadata(path)
    assert meta.get("year") != "None"
    assert "year" in tagging.verify_tags(path)


def test_repair_tags_noop_when_nothing_missing(tmp_path):
    path = _copy_fixture(tmp_path, "silence.mp3")
    song = _make_song()

    assert tagging.repair_tags(path, song, set()) is None
    # A no-op repair must not have written anything -- still fully untagged.
    assert tagging.verify_tags(path) == {
        "name",
        "artists",
        "album_name",
        "track_number",
        "year",
        "cover_art",
    }
