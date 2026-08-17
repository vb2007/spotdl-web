"""Library sort & move (v28) -- destination-path building from tags, conflict detection,
copy/verify/delete, quarantine. Pure filesystem + metadata logic, no Celery/DB access,
so it's testable directly; app/tasks/library.py wraps this with the ledger/job
bookkeeping and progress reporting.

See plan/master-v3/v28-library-sort-move.md's "Non-negotiable safety rules" -- every
function here is written to hold those, not just the task that calls them:
nothing is ever deleted at a destination path, "already exists" is folder+filename only
(never content), and a move is copy -> verify -> delete source, in that order.
"""

import hashlib
import logging
import re
import shutil
import uuid
from pathlib import Path

from app.services import tagging

logger = logging.getLogger(__name__)

# Folder-name components come from tag values, not literal path input, but they're
# still not-actually-trusted the moment they're used to build a filesystem path (same
# treatment v27's Content-Disposition guard gives DB-sourced text) -- strip the only two
# bytes Linux forbids in a filename (`/`, NUL) rather than assume a tag is well-formed.
_INVALID_PATH_CHARS = re.compile(r"[/\x00]")

_COPY_CHUNK_SIZE = 1024 * 1024


def _sanitize_path_segment(value: str) -> str:
    cleaned = _INVALID_PATH_CHARS.sub("-", value).strip()
    return cleaned or "Unknown"


def read_sort_tags(path: Path) -> dict | None:
    """Tags needed to build a destination path -- artist/album/year, read straight off
    the file via v26's tagging service (tagging.read_tags), not song_json -- this is
    what lets a file that never went through this app's own download path (an old
    library import, a manually placed file) still sort correctly. None for an
    unsupported/unreadable format; the caller records that as a per-file error."""
    try:
        return tagging.read_tags(path)
    except Exception:
        logger.exception("library: failed reading tags from %s", path)
        return None


def render_folder_name(template: str, tags: dict) -> str:
    """Only the placeholders the plan's own folder template actually uses --
    {artist}/{album}/{year} -- resolved from a tag-reader dict (get_file_metadata's
    shape: "artists" is a list, so {artist} is its first/primary entry, matching how
    spotdl's own Song.artist is the primary artist alongside the Song.artists list)."""
    artists = tags.get("artists") or None
    values = {
        "artist": artists[0] if artists else "Unknown Artist",
        "album": tags.get("album_name") or "Unknown Album",
        "year": str(tags["year"]) if tags.get("year") else "Unknown Year",
    }
    name = template
    for key, value in values.items():
        name = name.replace("{" + key + "}", str(value))
    return _sanitize_path_segment(name)


def destination_path(target_dir: Path, folder_template: str, tags: dict, source: Path) -> Path:
    """Folder is rebuilt from tags; the filename itself is left exactly as the source
    file's own basename -- v28's own new output template already sorts newly downloaded
    filenames the way the real library expects, and re-deriving a filename here for
    files that predate that template (or never went through this app) is unnecessary:
    "already exists" is decided by folder+filename match, not by re-generating a name."""
    folder = render_folder_name(folder_template, tags)
    return target_dir / folder / source.name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_COPY_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_match(a: Path, b: Path) -> bool:
    """Size first (cheap), checksum second -- used only to verify a just-performed copy
    landed intact, never for "already exists" conflict detection (folder+filename alone
    decides that, deliberately content-blind -- see the plan's dedup rule)."""
    if a.stat().st_size != b.stat().st_size:
        return False
    return _sha256(a) == _sha256(b)


def copy_verify(source: Path, dest: Path) -> bool:
    """Copies source to dest (creating parent directories), verifies by size+checksum.
    Returns whether verification passed -- the source is never touched here; the caller
    decides whether it's now safe to delete it. A failed verification's now-suspect copy
    at `dest` is deliberately left in place, never removed: "nothing is ever deleted on
    the target library filesystem, not once, not under any flag" (the plan's own words)
    means even a copy this function itself just wrote a moment ago."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return files_match(source, dest)


def _quarantine_destination(quarantine_dir: Path, source: Path) -> Path:
    """Preserves the source's own basename under quarantine_dir, disambiguated with a
    short suffix if an earlier sweep already quarantined a same-named file -- this
    directory is a permanent recovery area, not a scratch buffer, so silently clobbering
    an earlier quarantined file there would defeat the point of quarantining at all."""
    candidate = quarantine_dir / source.name
    if not candidate.exists():
        return candidate
    return quarantine_dir / f"{source.stem}.{uuid.uuid4().hex[:8]}{source.suffix}"


def quarantine(source: Path, quarantine_dir: Path) -> Path:
    """Moves source into quarantine_dir instead of deleting it -- the conflict-with-
    quarantine-on branch. Never touches whatever already exists at the real destination;
    only ever acts on the source (downloads-volume) copy."""
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    dest = _quarantine_destination(quarantine_dir, source)
    shutil.move(str(source), str(dest))
    return dest
