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

import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from zipstream import ZIP_STORED, ZipStream

from app.models import DownloadedTrack, Track, TrackState
from app.routers.tracks import allowed_file_location

MISSING_NAME = "MISSING.txt"

# The states whose file a track has (or had): every other state never produced one.
_FILE_STATES = frozenset({TrackState.COMPLETED, TrackState.SKIPPED_DUPLICATE})

# Larger than zipstream's own 64 KiB reads, so a multi-gigabyte stream isn't tens of
# thousands of threadpool hops (Starlette iterates a sync iterator in its threadpool).
_CHUNK_BYTES = 1024 * 1024

# Characters a zip entry or download name can't safely carry: path separators (a
# backslash is one to Windows extractors, so a name with `..\` could escape the folder),
# the ones Windows refuses, and control characters.
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_MAX_NAME_CHARS = 150


@dataclass(frozen=True)
class ExportFile:
    arcname: str
    path: Path
    size: int
    duration: int | None
    label: str


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


def safe_name(name: str, fallback: str = "export") -> str:
    """A name usable as one path component on any common filesystem: unsafe characters
    become `_`, and a name that ends up empty (or only dots) is the fallback."""
    cleaned = _UNSAFE_NAME.sub("_", name).strip().rstrip(".").strip()
    if len(cleaned) > _MAX_NAME_CHARS:
        cleaned = cleaned[:_MAX_NAME_CHARS].rstrip()
    if not cleaned.strip("."):
        return fallback
    return cleaned


def _track_label(song_json: dict) -> str:
    name = song_json.get("name") or song_json.get("song_id") or "Unknown track"
    artists = song_json.get("artists") or ([song_json["artist"]] if song_json.get("artist") else [])
    if artists:
        return f"{', '.join(str(artist) for artist in artists)} - {name}"
    return str(name)


def _duration(song_json: dict) -> int | None:
    value = song_json.get("duration")
    if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
        return int(round(value))
    return None


def _order_key(row) -> tuple:
    """The job's own order: insertion first (what the track list shows), then the source's
    position. One expansion inserts every track in one transaction, so their `created_at`
    ties, and the album or playlist position keeps the M3U in play order."""
    song = row.song_json or {}

    def number(key: str) -> float:
        value = song.get(key)
        return value if isinstance(value, (int, float)) else math.inf

    created_at: datetime = row.created_at
    return (
        created_at,
        number("list_position"),
        number("disc_number"),
        number("track_number"),
        str(row.id),
    )


def _dedupe(name: str, taken: set[str]) -> str:
    """`name`, or `name (2)`, `name (3)`... before its extension, compared case-insensitively
    (an archive extracted on Windows or macOS would fold two cases into one file)."""
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext = name, ""
    candidate, counter = name, 1
    while candidate.casefold() in taken:
        counter += 1
        candidate = f"{stem} ({counter}).{ext}" if ext else f"{stem} ({counter})"
    taken.add(candidate.casefold())
    return candidate


def plan_export(db: Session, job_id: uuid.UUID, title: str) -> ExportPlan:
    """Every track of the job, sorted into the zip or MISSING.txt. One query (the ledger
    joined in), then filesystem checks only."""
    rows = db.execute(
        select(
            Track.id,
            Track.state,
            Track.song_json,
            Track.output_path,
            Track.created_at,
            DownloadedTrack.file_path,
        )
        .outerjoin(DownloadedTrack, DownloadedTrack.spotify_track_id == Track.spotify_track_id)
        .where(Track.job_id == job_id)
    ).all()
    rows.sort(key=_order_key)

    playlist_name = f"{safe_name(title)}.m3u8"
    taken = {MISSING_NAME.casefold(), playlist_name.casefold()}
    files: list[ExportFile] = []
    missing: list[tuple[str, str]] = []
    for row in rows:
        song = row.song_json or {}
        label = _track_label(song)
        if row.state not in _FILE_STATES:
            missing.append((label, f"not downloaded ({row.state.value.replace('_', ' ')})"))
            continue
        # The ledger's path first (a library move repoints it), as the single-track
        # download does (routers/tracks.py's _resolve_track_file_path).
        raw_path = row.file_path if row.file_path is not None else row.output_path
        if raw_path is None:
            missing.append((label, "no file recorded"))
            continue
        location = allowed_file_location(Path(raw_path))
        if location is None:
            missing.append((label, "recorded path is outside the download and library folders"))
            continue
        resolved = location[0]
        try:
            stat = resolved.stat()
        except OSError:
            missing.append((label, "file not found at its recorded path"))
            continue
        if not resolved.is_file():
            missing.append((label, "file not found at its recorded path"))
            continue
        files.append(
            ExportFile(
                arcname=_dedupe(safe_name(resolved.name, "track"), taken),
                path=resolved,
                size=stat.st_size,
                duration=_duration(song),
                label=label,
            )
        )
    return ExportPlan(title=title, files=files, missing=missing, total_tracks=len(rows))


def _m3u_label(label: str) -> str:
    # One line per entry: a newline in a title would end the #EXTINF line early.
    return " ".join(label.splitlines())


def m3u_text(plan: ExportPlan, *, absolute: bool = False) -> str:
    """UTF-8 extended M3U. Relative entries are the zip's own names (the playlist sits next
    to them in the archive); `absolute` lists each file at its path on disk instead."""
    lines = ["#EXTM3U"]
    for entry in plan.files:
        duration = entry.duration if entry.duration is not None else -1
        lines.append(f"#EXTINF:{duration},{_m3u_label(entry.label)}")
        lines.append(str(entry.path) if absolute else entry.arcname)
    return "\n".join(lines) + "\n"


def missing_text(plan: ExportPlan) -> str:
    lines = [
        f"{plan.title}: {len(plan.missing)} of {plan.total_tracks} tracks are not in this archive.",
        "",
    ]
    lines.extend(f"{_m3u_label(label)} -- {reason}" for label, reason in plan.missing)
    return "\n".join(lines) + "\n"


def build_zip(plan: ExportPlan) -> ZipStream:
    """A STORED (uncompressed) archive with its size known before the first byte: audio
    doesn't compress, and a known size is what lets the response carry a Content-Length
    (and the browser show real progress). Nothing is written to disk or held in memory:
    each file is read in chunks while the response streams."""
    archive = ZipStream(compress_type=ZIP_STORED, sized=True)
    for entry in plan.files:
        archive.add_path(str(entry.path), entry.arcname)
    archive.add(m3u_text(plan).encode("utf-8"), plan.playlist_name)
    if plan.missing:
        archive.add(missing_text(plan).encode("utf-8"), MISSING_NAME)
    return archive


def iter_chunks(archive: ZipStream):
    """The archive's bytes in ~1 MiB pieces (see _CHUNK_BYTES)."""
    pending: list[bytes] = []
    size = 0
    for chunk in archive:
        pending.append(chunk)
        size += len(chunk)
        if size >= _CHUNK_BYTES:
            yield b"".join(pending)
            pending, size = [], 0
    if pending:
        yield b"".join(pending)
