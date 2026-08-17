"""ID3/tag integrity verification and repair (v26).

spotdl embeds tags at download time via `spotdl.utils.metadata.embed_metadata`, but
nothing previously checked that it actually happened -- a partial write (interrupted
process, a format spotdl's embedder mishandles) would ship a file with holes in its
metadata and nothing would notice. The **file** is the source of truth: verification
reads tags back off the file with the same library that wrote them, rather than
trusting `song_json`. `song_json` is used only as the repair source. Pure functions
over a file path, no DB access -- reusable by v28's library sorter, which also reads
tags off files.
"""

import logging
from pathlib import Path

from mutagen import File as MutagenFile
from spotdl.types.song import Song
from spotdl.utils.metadata import embed_metadata, get_file_metadata

# spotdl's own embed_metadata (verified by reading its source, not assumed) never writes
# a distinct "year" tag for these three containers -- only "date" (the full ISO date
# string), via a shared generic tag_preset that has no year-specific branch the way its
# mp3 path (an explicit TYER frame) and m4a path (year shares m4a's own \xa9day atom with
# date) both do. Left unpatched, "year" would show up missing on every flac/ogg/opus
# file forever, no matter how many times repair_tags runs. See docs/GOTCHAS.md's v26
# entry.
_YEAR_TAG_GAP_FORMATS = {"flac", "ogg", "opus"}

logger = logging.getLogger(__name__)

# The six fields the plan requires (album cover art is checked separately below,
# since get_file_metadata reports it under "album_art" rather than as one of these).
REQUIRED_FIELDS = {"name", "artists", "album_name", "track_number", "year"}

# What get_file_metadata/embed_metadata actually round-trip correctly. spotdl's own
# get_supported_output_options (app.services.downloads) reports every format the
# --format flag accepts, including "wav" -- but get_file_metadata's read-back path
# for "wav" reuses the generic Vorbis-comment-style key lookup (audio_file.get("title")
# etc.), which never matches WAVE's real ID3 frame ids (TIT2, TPE1, ...) and so reports
# every field missing on a WAV file regardless of what embed_wav_file actually wrote.
# Verified by reading spotdl 4.5.2's get_file_metadata source rather than assumed --
# see docs/GOTCHAS.md's v26 entry. Excluding it here is what "skip cleanly for any
# format the tag library can't handle" means in practice for this version.
SUPPORTED_FORMATS = {"mp3", "flac", "ogg", "opus", "m4a"}


def is_supported_format(path: Path) -> bool:
    return path.suffix.lstrip(".").lower() in SUPPORTED_FORMATS


def read_tags(path: Path) -> dict | None:
    """Raw tag dict for library sort/move (v28) -- unlike verify_tags below (which only
    reports *which* of REQUIRED_FIELDS are missing), the sorter needs the actual values
    to build a destination path from a file that may never have gone through this app's
    own download path at all. Same is_supported_format gate as everything else in this
    module; None for anything outside it (the caller records that as a per-file error,
    never a crash)."""
    if not is_supported_format(path):
        return None
    return get_file_metadata(path)


def verify_tags(path: Path) -> set[str]:
    """Returns the set of required field names missing or empty on the file. Caller
    must have already checked is_supported_format(path)."""
    meta = get_file_metadata(path) or {}
    missing = {field for field in REQUIRED_FIELDS if not meta.get(field)}
    if not meta.get("album_art"):
        missing.add("cover_art")
    return missing


def repair_tags(path: Path, song: Song, missing: set[str]) -> str | None:
    """Re-embeds whatever's missing from `song`. Cover art is only (re-)fetched when
    it's actually in `missing`, since embed_cover always re-downloads from Spotify's
    cover_url -- doing that unconditionally would cost a network round trip on every
    already-correctly-tagged file. Returns a warning message if cover art still isn't
    present after the repair attempt (network failure fetching it, or no cover_url on
    the song at all); returns None otherwise, including when nothing was missing."""
    if not missing:
        return None

    needs_cover = "cover_art" in missing
    embed_metadata(path, song, skip_album_art=not needs_cover)

    encoding = path.suffix.lstrip(".").lower()
    if "year" in missing and encoding in _YEAR_TAG_GAP_FORMATS and song.year is not None:
        audio_file = MutagenFile(str(path))
        audio_file["year"] = str(song.year)
        audio_file.save()

    if needs_cover:
        after = get_file_metadata(path) or {}
        if not after.get("album_art"):
            logger.warning(
                "tagging: cover art still missing for %s after repair (fetch failed "
                "or song has no cover_url)",
                path,
            )
            return "cover art missing: fetch from Spotify failed or no cover art available"

    return None
