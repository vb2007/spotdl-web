import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import DownloadedTrack, Job, JobSourceType, Track, TrackAttempt, TrackState, User
from app.routers.auth import require_session
from app.services import events, retry, track_listing
from app.services.pagination import DEFAULT_LIMIT, InvalidCursor
from app.services.serializers import track_attempt_to_dict, track_song_meta, track_to_dict

router = APIRouter(prefix="/api/tracks", tags=["tracks"])

_TERMINAL_TRACK_STATES = {TrackState.COMPLETED, TrackState.SKIPPED_DUPLICATE, TrackState.CANCELLED}
_RETRYABLE_TRACK_STATES = {TrackState.WAITING, TrackState.LOOKUP_FAILED}


def _get_track_or_404(
    db: Session, track_id: uuid.UUID, user: User
) -> tuple[Track, uuid.UUID, datetime | None]:
    """Returns the track alongside its job's owner id and archived_at -- ownership lives
    on `jobs`, not `tracks` (v2's locked decision: no denormalized copy), so this always
    joins through `Track.job_id`. A non-admin's foreign track 404s exactly like a
    nonexistent one. `archived_at` is returned (not just owner id) so callers that must
    reject an action on an archived job's track (see `retry_track`) don't need a second
    query to find out."""
    query = (
        db.query(Track, Job.user_id, Job.archived_at)
        .join(Job, Track.job_id == Job.id)
        .filter(Track.id == track_id)
    )
    if not user.is_admin:
        query = query.filter(Job.user_id == user.id)
    row = query.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Track not found")
    return row


# The nginx `internal` location (frontend/nginx.conf) that aliases the downloads root --
# `X-Accel-Redirect` values must be prefixed with this, never the raw filesystem path.
_INTERNAL_DOWNLOADS_PREFIX = "/internal-downloads/"


def _resolve_track_file_path(db: Session, track: Track) -> Path | None:
    """The dedup ledger (`downloaded_tracks`, keyed by spotify_track_id) is the field v28's
    library move will repoint -- see CLAUDE.md's master-v3 invariants -- so it's consulted
    first and `Track.output_path` is only a fallback for the (expected-never) case where a
    completed/skipped-duplicate track has no matching ledger row. This is what lets this
    endpoint keep working unchanged once v28 starts moving files."""
    ledger_row = db.get(DownloadedTrack, track.spotify_track_id)
    raw_path = ledger_row.file_path if ledger_row is not None else track.output_path
    if raw_path is None:
        return None
    return Path(raw_path)


def _content_disposition(filename: str) -> str:
    """RFC 5987 `filename*` alongside a plain ASCII-sanitized `filename` fallback -- this
    library is full of non-ASCII artist/title names (v27's plan), and older clients that
    don't understand `filename*` still get a usable (if transliterated) name instead of a
    header encoding error.

    The fallback strips every non-printable-ASCII byte, not just non-ASCII ones -- a bare
    `encode("ascii", "ignore")` lets a literal CR/LF in `filename` straight through into a
    response header, which ASGI servers reject outright (a 500, not the clean 404/200 this
    endpoint is supposed to guarantee). `filename` is ultimately DB-sourced
    (`Track.output_path`/the ledger's `file_path`), so it gets the same not-actually-trusted
    treatment as the path-traversal check above rather than being assumed well-formed. The
    `filename*` branch below needs no equivalent guard -- `quote(..., safe="")` already
    percent-encodes every such byte."""
    ascii_only = filename.encode("ascii", "ignore").decode("ascii")
    ascii_fallback = "".join(ch for ch in ascii_only if 32 <= ord(ch) < 127 and ch != '"').strip()
    if not ascii_fallback:
        ascii_fallback = "track"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.get("")
def list_tracks(
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
    q: str | None = None,
    status: list[str] = Query(default=[]),
    state: list[str] = Query(default=[]),
    source_type: JobSourceType | None = None,
    include_archived: bool = False,
    sort: str = "created_at",
    dir: Literal["asc", "desc"] = "desc",
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    all_users: bool = False,
) -> dict:
    """Tracks across every job the caller can see, one page at a time, each with its
    parent job embedded -- the v18 replacement for the old "every track, unpaginated"
    shape (removed, not deprecated: that shape is exactly what made the UI unusable once
    real usage accumulated 100+ historical jobs, see git history on this endpoint for the
    original incident). Identical query to `GET /api/jobs?scope=track`; see
    `track_listing.list_tracks`."""
    try:
        return track_listing.list_tracks(
            db,
            user_id=user.id,
            is_admin=user.is_admin,
            all_users=all_users,
            q=q,
            job_status_tokens=status,
            track_states=state,
            source_type=source_type,
            include_archived=include_archived,
            sort=sort,
            dir=dir,
            limit=limit,
            cursor=cursor,
        )
    except (track_listing.InvalidListParams, InvalidCursor) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{track_id}")
def cancel_track(
    track_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """Same semantics as `DELETE /api/jobs/{id}` but for a single track — a track
    already `downloading` finishes but its result is discarded by `download_track`
    once it notices the state changed underneath it."""
    track, owner_id, _archived_at = _get_track_or_404(db, track_id, user)
    if track.state not in _TERMINAL_TRACK_STATES:
        track.state = TrackState.CANCELLED
        track.scheduled_at = None
        db.commit()
        events.publish_track_event(
            owner_id, track.id, track.job_id, track.state.value, **track_song_meta(track.song_json)
        )
    return track_to_dict(track)


@router.post("/{track_id}/retry")
def retry_track(
    track_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """Bypasses the per-track ladder wait by resetting `scheduled_at` to now, but still
    respects the global circuit breaker — a manual retry must not be able to defeat the
    pause that exists specifically to stop hammering a rate-limited provider. The
    response's `breaker_held` field tells the caller whether this will dispatch on the
    next beat tick or is deferred until the breaker clears.

    Rejects a track whose job is archived — archiving is only ever reachable once a job
    is `settled`/`failed`/`cancelled` (`archive._ARCHIVABLE_LIFECYCLES`), none of which
    can have a `waiting`/`lookup_failed` track that got there any way other than *this*
    endpoint reviving one — so this is the one place that gate actually needs to live to
    keep "archived means settled, not just hidden" true. An archived job must be
    unarchived first, exactly like a re-download would need it visible again anyway."""
    track, owner_id, archived_at = _get_track_or_404(db, track_id, user)
    if archived_at is not None:
        raise HTTPException(status_code=409, detail="Job is archived; unarchive it first")
    if track.state not in _RETRYABLE_TRACK_STATES:
        raise HTTPException(
            status_code=409, detail=f"Track is {track.state.value}, not retryable"
        )

    now = datetime.now(timezone.utc)
    track.state = TrackState.WAITING
    track.scheduled_at = now
    db.commit()
    events.publish_track_event(
        owner_id,
        track.id,
        track.job_id,
        track.state.value,
        scheduled_at=track.scheduled_at,
        attempt_count=track.attempt_count,
        **track_song_meta(track.song_json),
    )

    worker_state = retry.get_worker_state(db)
    db.commit()
    breaker_held = retry.breaker_active(worker_state, now)

    body = track_to_dict(track)
    body["breaker_held"] = breaker_held
    return body


@router.get("/{track_id}/attempts")
def list_track_attempts(
    track_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> list[dict]:
    """Per-attempt download history (v24) -- what each attempt tried (direct vs. which
    proxy) and what happened, oldest first. Same owner-scoped 404-not-403 gate as every
    other direct-id track endpoint."""
    _track, _owner_id, _archived_at = _get_track_or_404(db, track_id, user)
    rows = (
        db.query(TrackAttempt)
        .filter(TrackAttempt.track_id == track_id)
        .order_by(TrackAttempt.attempt_number, TrackAttempt.started_at)
        .all()
    )
    return [track_attempt_to_dict(row) for row in rows]


@router.get("/{track_id}/file")
def download_track_file(
    track_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> Response:
    """Streams a completed track's audio file via nginx `X-Accel-Redirect` (v27) -- no
    audio bytes pass through this process; FastAPI only decides *whether* nginx may serve
    the file and *which* one. Same owner-scoped 404-not-403 gate as every other direct-id
    track endpoint; availability is keyed on the file existing at its recorded path, never
    on the job's `archived_at` (a retention-archived job's track stays downloadable)."""
    track, _owner_id, _archived_at = _get_track_or_404(db, track_id, user)

    raw_path = _resolve_track_file_path(db, track)
    if raw_path is None:
        raise HTTPException(status_code=404, detail="File not found")

    # `output_path`/the ledger's `file_path` are app-generated today, but this endpoint
    # turns them into an authorization boundary -- confirm the resolved path is actually
    # inside the allowed downloads root before ever handing it to nginx, rather than
    # trusting it as already-safe input (v27's plan, path-traversal guard). `.resolve()`
    # on an absolute, possibly-nonexistent path is purely lexical (no filesystem access
    # required), so this needs no volume mount into this container.
    root = Path(get_settings().download_output_dir).resolve()
    resolved = raw_path if raw_path.is_absolute() else (root / raw_path)
    resolved = resolved.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise HTTPException(status_code=404, detail="File not found")

    accel_uri = _INTERNAL_DOWNLOADS_PREFIX + "/".join(
        quote(part, safe="") for part in resolved.relative_to(root).parts
    )
    headers = {
        "X-Accel-Redirect": accel_uri,
        "Content-Disposition": _content_disposition(resolved.name),
    }
    return Response(status_code=200, headers=headers)
