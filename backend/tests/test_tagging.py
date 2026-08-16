import shutil
from pathlib import Path

import pytest
from spotdl.types.song import Song

from app.services import tagging

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


@pytest.mark.parametrize("filename", ["silence.mp3", "silence.flac"])
def test_verify_tags_reports_everything_missing_on_untagged_file(tmp_path, filename):
    path = _copy_fixture(tmp_path, filename)

    missing = tagging.verify_tags(path)

    assert missing == {"name", "artists", "album_name", "track_number", "year", "cover_art"}


@pytest.mark.parametrize("filename", ["silence.mp3", "silence.flac"])
def test_repair_tags_fills_basic_fields_from_song(tmp_path, filename):
    path = _copy_fixture(tmp_path, filename)
    song = _make_song()
    missing = tagging.verify_tags(path) - {"cover_art"}

    warning = tagging.repair_tags(path, song, missing)

    assert warning is None
    # cover_art was deliberately excluded from `missing` above, so repair_tags never
    # touched it (skip_album_art=True) -- proves repair only acts on what it's told to.
    assert tagging.verify_tags(path) == {"cover_art"}


@pytest.mark.parametrize("filename", ["silence.mp3", "silence.flac"])
def test_repair_tags_warns_when_cover_art_unavailable(tmp_path, filename):
    path = _copy_fixture(tmp_path, filename)
    song = _make_song(cover_url=None)

    warning = tagging.repair_tags(path, song, {"cover_art"})

    assert warning is not None
    assert "cover art" in warning.lower()
    assert tagging.verify_tags(path) == {"cover_art"}


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
