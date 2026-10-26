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
import os
import re
import shutil
import uuid
from pathlib import Path

from app.services import app_settings, tagging

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
    is never removed: "nothing is ever deleted on the target library filesystem, not
    once, not under any flag" (the plan's own words) means even a copy this function
    itself just wrote a moment ago. It is, however, renamed *off* `dest`'s exact path --
    a later sweep's "already exists" check is folder+filename only (deliberately
    content-blind, per the plan's dedup rule), so a corrupt partial file left sitting at
    the real expected filename would be silently adopted as "the file already exists"
    next time, causing that later sweep to quarantine or delete a perfectly good source
    over it instead of retrying the copy. Renaming (not deleting) keeps the bytes
    available for manual inspection while freeing the real filename for a real retry.

    v57 (L7): nothing unverified ever sits at `dest`. The copy goes to a staging name beside it
    (`.spotdl-copying-<hex>`) and is placed at `dest` only once it verifies. On a full disk
    `copy2` raised ENOSPC with a truncated file already at `dest` (reproduced on a 2 MiB tmpfs:
    2 MiB of an 8.6 MB source) before any checksum was taken, and a worker killed mid-copy (an
    OOM kill, a deploy) left the same; the next sweep then adopted the partial file as "already
    exists". Now a failed copy is renamed to `.spotdl-copy-failed-<hex>` (a rename needs no free
    space) and the error raised on, and a killed one stays at its staging name: neither is ever
    at the real filename (review round 4: no longer `<name>.…`, which a long name can't take). A copy whose data verified but whose copystat failed (a mount that
    refuses times or mode) is a good copy. If `dest` appeared meanwhile, the copy is left at its
    staging name rather than overwrite anything in the library."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Short, fixed names (review round 4): a suffix on a long filename could pass the 255-byte
    # limit and fail every copy of that file. Hidden, so a media scanner skips them.
    tag = uuid.uuid4().hex[:8]
    staging = dest.with_name(f".spotdl-copying-{tag}")
    try:
        shutil.copy2(source, staging)
    except OSError:
        if not (staging.exists() and files_match(source, staging)):
            if staging.exists():
                staging.rename(dest.with_name(f".spotdl-copy-failed-{tag}"))
            raise
    if not files_match(source, staging):
        staging.rename(dest.with_name(f".spotdl-verify-failed-{tag}"))
        return False
    _place(staging, dest)
    return True


def _place(staging: Path, dest: Path) -> None:
    """Puts the verified copy at `dest` without ever replacing a file there (v57, review round
    3): a hard link fails with EEXIST where a rename would silently overwrite, and only then is
    the staging name dropped (the data stays, under `dest`). A filesystem without hard links
    falls back to a check and a rename."""
    try:
        os.link(staging, dest)
    except FileExistsError:
        raise FileExistsError(f"{dest} appeared during the copy; the verified copy is left at {staging}") from None
    except OSError:
        if dest.exists():
            raise FileExistsError(f"{dest} appeared during the copy; the verified copy is left at {staging}") from None
        staging.rename(dest)
        return
    staging.unlink()


def library_mount() -> Path:
    """Where the library volume is mounted in every container, and the one directory nginx's
    /internal-library/ serves (compose binds LIBRARY_DIR there). The library dir must be this or
    a folder inside it (owner decision, 2026-10-26): anywhere else is the container's own
    writable layer, which the other workers can't see and a recreate discards."""
    return Path(app_settings.DEFAULT_LIBRARY_TARGET_DIR)


def outside_library_mount(library_dir: Path) -> bool:
    mount = library_mount().resolve()
    return not library_dir.resolve().is_relative_to(mount)


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


def path_relation(a: Path, b: Path) -> str | None:
    """How directory `a` sits relative to directory `b` once both are resolved (v57, L2):
    "equal", "inside" (a is under b), "contains" (b is under a), or None when they're apart.
    `resolve()` follows a symlink that exists and is lexical past one that doesn't, so an alias
    of the same directory compares equal and the api container (which mounts no root) can
    still answer."""
    a, b = a.resolve(), b.resolve()
    if a == b:
        return "equal"
    if a.is_relative_to(b):
        return "inside"
    if b.is_relative_to(a):
        return "contains"
    return None


def path_conflicts(downloads_dir: Path, library_dir: Path, quarantine_dir: Path) -> list[dict]:
    """Every way the three sweep directories overlap that would let a sweep act on its own
    output (v57, L2), as {"field", "other", "relation"} (`relation` is `field`'s position
    relative to `other`). The library may not equal, sit inside or contain the downloads dir;
    the quarantine dir may not equal, sit inside or contain the library, nor equal or contain
    the downloads dir. A quarantine dir *inside* the downloads dir is allowed (owner decision,
    2026-10-26): it's the shipped default, `/downloads/quarantine`, production mounts nowhere
    else it could go, and the sweep walks ledger rows, never the downloads tree."""
    conflicts = []
    relation = path_relation(library_dir, downloads_dir)
    if relation is not None:
        conflicts.append(
            {"field": "library_target_dir", "other": "download_output_dir", "relation": relation}
        )
    relation = path_relation(quarantine_dir, library_dir)
    if relation is not None:
        conflicts.append(
            {"field": "library_quarantine_dir", "other": "library_target_dir", "relation": relation}
        )
    relation = path_relation(quarantine_dir, downloads_dir)
    if relation in ("equal", "contains"):
        conflicts.append(
            {"field": "library_quarantine_dir", "other": "download_output_dir", "relation": relation}
        )
    return conflicts
