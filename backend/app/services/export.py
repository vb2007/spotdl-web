"""A job's files as one streamed zip, and its tracks as an extended M3U (v64).

Membership is v27/v38's file-availability rule: a track is in the export only if it's
`completed`/`skipped_duplicate` and its file exists at its recorded path (the ledger's
`file_path` first, `Track.output_path` as the fallback, inside the downloads root or the
library mount). Never keyed on `archived_at`, so a retention-archived job stays exportable.
Every other track is listed in the zip's `MISSING.txt`, with the reason.

`plan_export` does every database read up front and returns plain data, so the caller can
end the transaction before a byte is streamed (v31's idle-in-transaction lesson): nothing
here touches the session once the plan exists.
"""

import logging
import math
import os
import re
import stat as stat_module
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from zipstream import ZIP_STORED, ZipStream

from app.db import SessionLocal
from app.models import DownloadedTrack, Track, TrackState
from app.routers.tracks import _INTERNAL_LIBRARY_PREFIX, allowed_file_location

logger = logging.getLogger(__name__)

MISSING_NAME = "MISSING.txt"

# The states whose file a track has (or had): every other state never produced one.
_FILE_STATES = frozenset({TrackState.COMPLETED, TrackState.SKIPPED_DUPLICATE})

# Larger than zipstream's own 64 KiB reads, so a multi-gigabyte stream isn't tens of
# thousands of threadpool hops (Starlette iterates a sync iterator in its threadpool).
_CHUNK_BYTES = 1024 * 1024

# Characters a zip entry or download name can't safely carry: path separators (a
# backslash is one to Windows extractors, so a name with `..\` could escape the folder),
# the ones Windows refuses, and control characters.
# C1 controls and the Unicode line/paragraph separators too: Python's splitlines() (and
# some players) treat U+0085, U+2028 and U+2029 as line breaks.
# And the bidi controls, which make `exe.OPUS` display for `SUPO.exe`.
_UNSAFE_NAME = re.compile(
    r'[\\/:*?"<>|\x00-\x1f\x7f-\x9f\u2028\u2029\u200e\u200f\u202a-\u202e\u2066-\u2069]'
)
# In UTF-8 bytes, under the common 255-byte filename limit with room left for a ` (N)`
# duplicate suffix: a Hungarian name's accented letters take two bytes each.
_MAX_NAME_BYTES = 200
# What counts as a file's extension when a name is cut or numbered: a short dot-suffix with no
# space, so "No. 3" or "feat. X" in a title is never mistaken for one.
_EXTENSION = re.compile(r"\.[^.\s]{1,10}$")


@dataclass(frozen=True)
class ExportFile:
    arcname: str
    path: Path
    size: int
    # The ledger key, to find the file again if a library sweep moves it mid-stream.
    spotify_track_id: str
    # The file the plan stat'ed (st_dev, st_ino): the stream opens that file or none.
    identity: tuple[int, int]
    duration: int | None
    label: str
    # Under the library mount (not still on the downloads volume): `?paths=library` lists only these.
    in_library: bool


@dataclass(frozen=True)
class ExportPlan:
    title: str
    files: list[ExportFile]
    # (label, reason) for every track that isn't in the zip.
    missing: list[tuple[str, str]]
    total_tracks: int

    @property
    def total_bytes(self) -> int:
        return sum(entry.size for entry in self.files)

    @property
    def playlist_name(self) -> str:
        return f"{safe_name(self.title)}.m3u8"

    @property
    def archive_name(self) -> str:
        return f"{safe_name(self.title)}.zip"


# Names Windows refuses as a file whatever their extension (`NUL.opus` included).
_WINDOWS_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{n}" for n in range(1, 10)} | {f"LPT{n}" for n in range(1, 10)}
)


def _split_extension(name: str) -> tuple[str, str]:
    match = _EXTENSION.search(name)
    if match is None or match.start() == 0:
        return name, ""
    return name[: match.start()], match.group()


def safe_name(name: str, fallback: str = "export", *, keep_extension: bool = False) -> str:
    """A name usable as one path component on any common filesystem: unsafe characters
    become `_`, and a name that ends up empty (or only dots) is the fallback. A long name is
    cut to _MAX_NAME_BYTES; with `keep_extension` (a file's name) the cut is taken from the
    stem, so `....opus` never becomes `....op`, and a name that is only an extension
    (`.opus`, a hidden file once extracted) gets the fallback stem."""
    # A filesystem name that isn't valid UTF-8 reaches Python with surrogate escapes, which
    # can't be encoded into a zip entry, a header or a byte count: each bad byte becomes U+FFFD.
    cleaned = name.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    # NFC: macOS hands out decomposed names (NFD), and two spellings of one name would land on
    # one file once extracted there. Leading dots go too, or the file extracts hidden.
    cleaned = unicodedata.normalize("NFC", cleaned)
    cleaned = _UNSAFE_NAME.sub("_", cleaned).strip().rstrip(".").strip()
    stem, ext = cleaned, ""
    if keep_extension:
        match = _EXTENSION.search(cleaned)
        if match is not None:
            stem, ext = cleaned[: match.start()], match.group()
    stem = stem.lstrip(".").lstrip()
    if len((stem + ext).encode("utf-8")) > _MAX_NAME_BYTES:
        budget = _MAX_NAME_BYTES - len(ext.encode("utf-8"))
        stem = stem.encode("utf-8")[:budget].decode("utf-8", "ignore").rstrip().rstrip(".").rstrip()
    if not stem.strip("."):
        return f"{fallback}{ext}"
    if stem.split(".")[0].upper() in _WINDOWS_DEVICES:
        stem = f"_{stem}"
    return f"{stem}{ext}"


def _track_label(song_json: dict) -> str:
    name = song_json.get("name") or song_json.get("song_id") or "Unknown track"
    # Shaped as spotdl writes it (a list of names), but read defensively: a bare string or a
    # stray non-string must not come out as "S, o, l, o" or "None".
    artists = song_json.get("artists")
    if isinstance(artists, str):
        artists = [artists]
    if not isinstance(artists, list):
        artists = [song_json.get("artist")]
    names = [artist for artist in artists if isinstance(artist, str) and artist]
    if names:
        return f"{', '.join(names)} - {name}"
    return str(name)


# A day: past it, a duration is a corrupt value, not a track.
_MAX_DURATION = 24 * 3600


def _duration(song_json: dict) -> int | None:
    value = song_json.get("duration")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    # Compared before anything else: exact for a huge int (math.isfinite would overflow on
    # one), and false for NaN and infinity.
    if 0 < value <= _MAX_DURATION:
        return int(round(value))
    return None


def _order_key(row) -> tuple:
    """Play order. One expansion inserts every track in one transaction, so their
    `created_at` ties (it only orders separate expansions); within one, a playlist's
    `list_position` decides, and otherwise (an album, or an artist's whole discography, where
    spotdl sets no list position) album by album, oldest first, then disc and track number."""
    song = row.song_json if isinstance(row.song_json, dict) else {}

    def number(key: str) -> float:
        value = song.get(key)
        return value if isinstance(value, (int, float)) else math.inf

    def text(key: str) -> str:
        value = song.get(key)
        return value if isinstance(value, str) else ""

    created_at: datetime = row.created_at
    return (
        created_at,
        number("list_position"),
        text("date"),
        text("album_id") or text("album_name"),
        number("disc_number"),
        number("track_number"),
        str(row.id),
    )


def _dedupe(name: str, taken: set[str]) -> str:
    """`name`, or `name (2)`, `name (3)`... before its extension, compared case-insensitively
    (an archive extracted on Windows or macOS would fold two cases into one file)."""
    stem, ext = _split_extension(name)
    candidate, counter = name, 1
    while candidate.casefold() in taken:
        counter += 1
        candidate = f"{stem} ({counter}){ext}"
    taken.add(candidate.casefold())
    return candidate


def plan_export(db: Session, job_id: uuid.UUID, title: str) -> ExportPlan:
    """load_rows and plan_from_rows in one step, for a caller that holds no transaction open
    on purpose (tests, scripts)."""
    return plan_from_rows(load_rows(db, job_id), title)


def load_rows(db: Session, job_id: uuid.UUID) -> list:
    """Every track of the job with its ledger path: the export's one query. Plain rows, so
    the caller can end its transaction before plan_from_rows touches the filesystem (a stat
    per track on a spun-down disk is no reason to sit idle in transaction)."""
    return db.execute(
        select(
            Track.id,
            Track.spotify_track_id,
            Track.state,
            Track.song_json,
            Track.output_path,
            Track.created_at,
            DownloadedTrack.file_path,
        )
        .outerjoin(DownloadedTrack, DownloadedTrack.spotify_track_id == Track.spotify_track_id)
        .where(Track.job_id == job_id)
    ).all()


_NOT_FOUND = "file not found at its recorded path"
_UNREADABLE = "file can't be read (permissions)"


def _locate(raw_path: str) -> tuple[Path, str, os.stat_result] | str:
    """The file at `raw_path`: its resolved path, its root's nginx prefix and its stat, or
    the reason it isn't in the export."""
    try:
        location = allowed_file_location(Path(raw_path))
    except (OSError, RuntimeError):
        # Python 3.12's resolve() raises RuntimeError on a symlink loop, even non-strict: one
        # bad row must not fail the whole job's export.
        return "recorded path can't be resolved (a symlink loop?)"
    if location is None:
        return "recorded path is outside the download and library folders"
    resolved, _root, prefix = location
    try:
        stat = resolved.stat()
    except PermissionError:
        return _UNREADABLE
    except OSError:
        return _NOT_FOUND
    # The type from the same stat (a second look could raise, or see another file).
    if not stat_module.S_ISREG(stat.st_mode):
        return _NOT_FOUND
    # Checked here, not met mid-stream: an unreadable file would break every download of the
    # zip partway, where the probe had said it was fine.
    if not os.access(resolved, os.R_OK):
        return _UNREADABLE
    return resolved, prefix, stat


def plan_from_rows(rows: list, title: str) -> ExportPlan:
    """Every track, sorted into the zip or MISSING.txt: filesystem checks, plus one batched
    ledger re-read only if a file wasn't where its row said (see below)."""
    rows = sorted(rows, key=_order_key)

    # The ledger's path first (a library move repoints it), as the single-track download
    # does (routers/tracks.py's _resolve_track_file_path).
    found: dict[int, tuple[Path, str, int] | str] = {}
    for index, row in enumerate(rows):
        if row.state not in _FILE_STATES:
            found[index] = f"not downloaded ({row.state.value.replace('_', ' ')})"
            continue
        raw_path = row.file_path if row.file_path is not None else row.output_path
        found[index] = "no file recorded" if raw_path is None else _locate(raw_path)
    # A library sweep may have moved a file between the rows' read and its stat (it commits
    # the ledger's new path before unlinking the source): one read of those rows' current
    # paths, as the stream does for a file that moves later (_open).
    # A playlist can list one song twice, so an id may stand for more than one row.
    misses: dict[str, list[int]] = {}
    for index, result in found.items():
        if result == _NOT_FOUND:
            misses.setdefault(rows[index].spotify_track_id, []).append(index)
    if misses:
        for spotify_track_id, file_path in _current_paths(list(misses)).items():
            for index in misses[spotify_track_id]:
                if file_path != rows[index].file_path:
                    found[index] = _locate(file_path)

    playlist_name = f"{safe_name(title)}.m3u8"
    taken = {MISSING_NAME.casefold(), playlist_name.casefold()}
    files: list[ExportFile] = []
    missing: list[tuple[str, str]] = []
    for index, row in enumerate(rows):
        song = row.song_json if isinstance(row.song_json, dict) else {}
        label = _track_label(song)
        result = found[index]
        if isinstance(result, str):
            missing.append((label, result))
            continue
        resolved, prefix, stat = result
        files.append(
            ExportFile(
                arcname=_dedupe(safe_name(resolved.name, "track", keep_extension=True), taken),
                path=resolved,
                size=stat.st_size,
                identity=(stat.st_dev, stat.st_ino),
                spotify_track_id=row.spotify_track_id,
                duration=_duration(song),
                label=label,
                in_library=prefix == _INTERNAL_LIBRARY_PREFIX,
            )
        )
    return ExportPlan(title=title, files=files, missing=missing, total_tracks=len(rows))


def _is_utf8(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _m3u_label(label: str) -> str:
    # One line per entry: a newline in a title would end the #EXTINF line early.
    return " ".join(label.splitlines())


def m3u_text(plan: ExportPlan, *, absolute: bool = False) -> str:
    """UTF-8 extended M3U. Relative entries are the zip's own names (the playlist sits next
    to them in the archive); a name starting with `#` gets `./`, or a player would read the
    line as a comment and drop the track. `absolute` lists the files already in the library at
    their path there, for a media server pointed at it; a file still on the downloads volume
    has no such path yet, so it's a comment line naming the track instead."""
    lines = ["#EXTM3U"]
    for entry in plan.files:
        if absolute and not entry.in_library:
            lines.append(f"# not in the library yet: {_m3u_label(entry.label)}")
            continue
        duration = entry.duration if entry.duration is not None else -1
        lines.append(f"#EXTINF:{duration},{_m3u_label(entry.label)}")
        if absolute:
            # A line break in a path would end the entry early and start another one.
            path = str(entry.path)
            # Any line break a player might split on (`splitlines()`'s set, U+2028 included), or
            # bytes that aren't UTF-8 (surrogate escapes): neither can be a playlist line.
            if len(path.splitlines()) != 1 or not _is_utf8(path):
                path = f"# unlistable path: {_m3u_label(entry.label)}"
            lines.append(path)
        else:
            lines.append(f"./{entry.arcname}" if entry.arcname.startswith("#") else entry.arcname)
    return "\n".join(lines) + "\n"


def missing_text(plan: ExportPlan) -> str:
    lines = [
        f"{_m3u_label(plan.title)}: {len(plan.missing)} of {plan.total_tracks} tracks are not in this archive.",
        "",
    ]
    lines.extend(f"{_m3u_label(label)} -- {reason}" for label, reason in plan.missing)
    return "\n".join(lines) + "\n"


class ExportFileChanged(Exception):
    """A file can't be streamed as planned: gone, or no longer the size the Content-Length
    promised. The response is already under way, so the stream ends there."""


_IDS_PER_QUERY = 10_000


def _current_paths(spotify_track_ids: list[str]) -> dict[str, str]:
    """Where the ledger says these files are now. One short read on a session of its own,
    ended at once: the request or stream around it may run for hours, and it must not hold a
    transaction meanwhile (v31)."""
    session = SessionLocal()
    rows = []
    try:
        # In chunks: Postgres takes at most 65,535 bound parameters in one statement.
        for start in range(0, len(spotify_track_ids), _IDS_PER_QUERY):
            chunk = spotify_track_ids[start : start + _IDS_PER_QUERY]
            rows.extend(
                session.execute(
                    select(DownloadedTrack.spotify_track_id, DownloadedTrack.file_path).where(
                        DownloadedTrack.spotify_track_id.in_(chunk)
                    )
                ).all()
            )
        session.rollback()
    finally:
        session.close()
    return {row.spotify_track_id: row.file_path for row in rows}


def _current_path(spotify_track_id: str) -> Path | None:
    """Where the ledger says one file is now, inside an allowed root (the stream's re-read)."""
    file_path = _current_paths([spotify_track_id]).get(spotify_track_id)
    if file_path is None:
        return None
    try:
        location = allowed_file_location(Path(file_path))
    except (OSError, RuntimeError):
        return None
    return location[0] if location is not None else None


def _open_regular(path: Path, identity: tuple[int, int] | None = None):
    """`path` opened for reading only if it is a regular file inside an allowed root, and (with
    `identity`) the very file the plan stat'ed.

    Non-blocking, so a FIFO swapped in can't hang a threadpool thread (an uncancellable read:
    40 of them stalled the whole API in a live review), and without following a symlink in the
    last component. A folder swapped for a link out of the roots is caught by the opened file's
    own path (`/proc/self/fd`), checked against the roots after the open: a check made before
    it (the plan's, or the ledger re-read's) can race the swap, the opened file can't. The
    identity check can't tell a same-size file written over a freed inode in place, but that
    one is inside a root anyway."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_NOCTTY | os.O_CLOEXEC)
    try:
        stat = os.fstat(fd)
        if not stat_module.S_ISREG(stat.st_mode):
            raise ExportFileChanged(f"{path}: not a regular file any more")
        if identity is not None and (stat.st_dev, stat.st_ino) != identity:
            raise ExportFileChanged(f"{path}: replaced by another file since the plan")
        opened = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if allowed_file_location(opened, follow_symlinks=False) is None:
            raise ExportFileChanged(f"{path}: opened outside the download and library folders")
        os.set_blocking(fd, True)
    except BaseException:
        os.close(fd)
        raise
    # Outside the try: fdopen closes the fd itself if it fails, and a second close could hit a
    # number another thread has been given meanwhile.
    return os.fdopen(fd, "rb")


def _open(entry: ExportFile):
    """The entry's file, opened as the stream reaches it, and only if it is still the file the
    plan counted (_open_regular). Anything else at the planned path (gone, swapped, a library
    sweep's move: the sweep commits the ledger's new path before it removes the source,
    tasks/library.py) is re-resolved once through the ledger (owner's decision, 2026-10-30),
    inside an allowed root, a regular file of the planned size. Otherwise the stream ends the
    documented way (ExportFileChanged)."""
    try:
        return _open_regular(entry.path, entry.identity)
    except (OSError, ExportFileChanged) as exc:
        first = exc
    try:
        moved = _current_path(entry.spotify_track_id)
    except Exception as exc:
        raise ExportFileChanged(f"{entry.arcname}: unreadable, and the ledger couldn't be read ({exc})") from None
    if moved is None or moved == entry.path:
        reason = first.strerror if isinstance(first, OSError) and first.strerror else str(first)
        raise ExportFileChanged(f"{entry.arcname}: can't be read as planned ({reason})")
    try:
        handle = _open_regular(moved)
    except ExportFileChanged:
        raise
    except OSError as exc:
        raise ExportFileChanged(f"{entry.arcname}: can't be read at {moved} ({exc.strerror or exc})") from None
    if os.fstat(handle.fileno()).st_size != entry.size:
        handle.close()
        raise ExportFileChanged(f"{entry.arcname}: moved to {moved} with another size")
    logger.info("export: %s moved during the stream, reading it from %s", entry.arcname, moved)
    return handle


def _file_bytes(entry: ExportFile):
    """The entry's bytes, in chunks, opened only when the stream reaches it (so an export of
    thousands of files never holds more than one open). Exactly `entry.size` of them, or the
    stream ends: a sized archive's entries can't change length."""
    with _open(entry) as handle:
        sent = 0
        while chunk := handle.read(_CHUNK_BYTES):
            sent += len(chunk)
            if sent > entry.size:
                raise ExportFileChanged(f"{entry.arcname}: grew during the stream")
            yield chunk
        if sent != entry.size:
            raise ExportFileChanged(f"{entry.arcname}: shrank during the stream")


class _ExportZip(ZipStream):
    """zipstream-ng (pinned 1.9.3) gives an entry added from bytes or an iterable the mode
    `0600`, which Info-ZIP's unzip restores as is: a media server reading the extracted folder
    as another user couldn't open a file. Every file entry is `0644` in the central directory,
    written last, so it's set just before."""

    def _gen_archive_footer(self):
        for zinfo in self._filelist:
            if not zinfo.is_dir():
                zinfo.external_attr = (stat_module.S_IFREG | 0o644) << 16
        yield from super()._gen_archive_footer()


def build_zip(plan: ExportPlan) -> ZipStream:
    """A STORED (uncompressed) archive with its size known before the first byte: audio
    doesn't compress, and a known size is what lets the response carry a Content-Length
    (and the browser show real progress). Nothing is written to disk or held in memory:
    each file is read in chunks while the response streams. An entry is added as sized
    bytes rather than a path, so a file moved mid-stream can be found again (_open); the
    cost is that its timestamp in the archive is the export's, not the file's."""
    archive = _ExportZip(compress_type=ZIP_STORED, sized=True)
    for entry in plan.files:
        archive.add(_file_bytes(entry), entry.arcname, size=entry.size)
    archive.add(m3u_text(plan).encode("utf-8"), plan.playlist_name)
    if plan.missing:
        archive.add(missing_text(plan).encode("utf-8"), MISSING_NAME)
    return archive


def iter_chunks(archive: ZipStream):
    """The archive's bytes in ~1 MiB pieces (see _CHUNK_BYTES). Closing it closes the
    archive's own generator, and with it the file being read."""
    pending: list[bytes] = []
    size = 0
    stream = iter(archive)
    try:
        for chunk in stream:
            pending.append(chunk)
            size += len(chunk)
            if size >= _CHUNK_BYTES:
                yield b"".join(pending)
                pending, size = [], 0
        if pending:
            yield b"".join(pending)
    finally:
        stream.close()
