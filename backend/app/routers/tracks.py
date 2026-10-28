import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import DownloadedTrack, Job, JobSourceType, JobState, Proxy, Track, TrackAttempt, TrackState, User
from app.routers.auth import require_session
from app.services import app_settings, events, job_status, retry, rollup, track_listing
from app.services.track_states import CANCELLABLE_TRACK_STATES, RETRYABLE_TRACK_STATES, cancelled_used_proxy_id
from app.services.pagination import DEFAULT_LIMIT, InvalidCursor
from app.services.serializers import track_attempt_to_dict, track_song_meta, track_to_dict
from app.services.view_scope import View, resolve_view

router = APIRouter(prefix="/api/tracks", tags=["tracks"])

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
        raise ApiError(404, "track_not_found", "Track not found")
    return row


# The nginx `internal` locations (frontend/nginx.conf) that alias the downloads root and
# (v28) the sorted library root -- `X-Accel-Redirect` values must be prefixed with
# whichever one actually contains the resolved path, never the raw filesystem path.
_INTERNAL_DOWNLOADS_PREFIX = "/internal-downloads/"
_INTERNAL_LIBRARY_PREFIX = "/internal-library/"


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
    view: View | None = None,
    all_users: bool | None = None,
) -> dict:
    """Tracks across every job the caller can see, one page at a time, each with its
    parent job embedded -- the v18 replacement for the old "every track, unpaginated"
    shape (removed, not deprecated: that shape is exactly what made the UI unusable once
    real usage accumulated 100+ historical jobs, see git history on this endpoint for the
    original incident). Identical query to `GET /api/jobs?scope=track`; see
    `track_listing.list_tracks`. `view`/`all_users` as on `GET /api/jobs` (v54)."""
    view = resolve_view(view, all_users, is_admin=user.is_admin)
    try:
        return track_listing.list_tracks(
            db,
            user_id=user.id,
            is_admin=user.is_admin,
            view=view,
            q=q,
            job_status_tokens=status,
            track_states=state,
            source_type=source_type,
            include_archived=include_archived,
            sort=sort,
            dir=dir,
            limit=limit,
            cursor=cursor,
            include_state_counts=True,
        )
    except (track_listing.InvalidListParams, InvalidCursor) as exc:
        raise ApiError(400, "invalid_list_params", str(exc), {"reason": str(exc)}) from exc


@router.get("/{track_id}")
def get_track(
    track_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """v56 (A3): one track as the server has it now, with its job's summary embedded in the
    same shape as `GET /api/tracks`'s items. The track row's cancel used to re-read up to
    1000 tracks of the job to find this one. Same owner-scoped 404-not-403 gate as every
    other direct-id track endpoint; an admin reads anyone's."""
    track, _owner_id, _archived_at = _get_track_or_404(db, track_id, user)
    job, owner_email, owner_username = (
        db.query(Job, User.email, User.username)
        .join(User, Job.user_id == User.id)
        .filter(Job.id == track.job_id)
        .one()
    )
    body = track_to_dict(track)
    body["job"] = {
        "id": str(job.id),
        "source_url": job.source_url,
        "source_type": job.source_type.value,
        "owner_email": owner_email,
        "owner_username": owner_username,
        "title": rollup.job_title(db, job),
    }
    return body


@router.delete("/{track_id}")
def cancel_track(
    track_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """Same semantics as `DELETE /api/jobs/{id}` but for a single track — a track
    already `downloading` finishes but its result is discarded by `download_track`
    once it notices the state changed underneath it.

    v56 (A2): a track with nothing left in flight (`track_states.TERMINAL_TRACK_STATES`,
    `lookup_failed` included) answers 409 `track_not_cancellable` with its state, like a
    settled job's cancel, instead of a silent no-op. The state is re-checked by the UPDATE
    itself, so a track that settled since it was read is never relabelled `cancelled`."""
    track, owner_id, _archived_at = _get_track_or_404(db, track_id, user)
    cancelled = db.execute(
        update(Track)
        .where(Track.id == track.id, Track.state.in_(CANCELLABLE_TRACK_STATES))
        .values(state=TrackState.CANCELLED, scheduled_at=None, used_proxy_id=cancelled_used_proxy_id())
    ).rowcount
    db.commit()
    db.refresh(track)
    if not cancelled:
        raise ApiError(
            409,
            "track_not_cancellable",
            f"Track is {track.state.value}, not cancellable",
            {"state": track.state.value},
        )
    events.publish_track_event(
        owner_id, track.id, track.job_id, track.state.value, **track_song_meta(track.song_json)
    )
    job_status.publish_change(db, track.job_id)
    return track_to_dict(track)


def _seconds_until_tried(db: Session, track: Track, now: datetime) -> int:
    """When a `waiting` track is dispatched without anyone's help: its own slot, or the
    breaker's clear if that comes later (beat dispatches nothing while it holds). 0 when
    it's due and nothing holds it."""
    worker_state = retry.get_worker_state(db)
    times = [track.scheduled_at] if track.scheduled_at is not None else []
    if retry.breaker_tripped(worker_state, now):
        times.append(worker_state.breaker_tripped_until)
    return max([0] + [math.ceil((at - now).total_seconds()) for at in times])


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
    unarchived first, exactly like a re-download would need it visible again anyway.

    v56 (A8, #69): a non-admin may retry-now a `waiting` track once per ladder step
    (`attempt_count`). It dispatches on the next beat pass and leaves the step as it is, so
    the ladder keeps climbing; a second press in the same step answers 429 `retry_cooldown`
    with the seconds until the track is tried anyway. An admin's retry is unrestricted, and so
    is anyone's retry of a `lookup_failed` track (another search after a not-found)."""
    track, owner_id, archived_at = _get_track_or_404(db, track_id, user)
    # v56 (A2): a job cancel leaves its not-found tracks as they are, so one can sit under a
    # cancelled job; retrying it would download for a job that says "cancelled" and can no
    # longer be cancelled. The job is read under a share lock, so a cancel committing
    # meanwhile is seen (and a retry committing first is cancelled by it).
    job_state = db.execute(
        select(Job.state).where(Job.id == track.job_id).with_for_update(read=True)
    ).scalar_one()
    # Locked, so two presses at once can't both pass the per-step check below.
    db.refresh(track, with_for_update=True)
    if archived_at is not None:
        raise ApiError(409, "job_archived", "Job is archived; unarchive it first")
    if job_state == JobState.CANCELLED:
        raise ApiError(409, "job_cancelled", "Job is cancelled; submit the link again")
    if track.state not in RETRYABLE_TRACK_STATES:
        raise ApiError(
            409,
            "track_not_retryable",
            f"Track is {track.state.value}, not retryable",
            {"state": track.state.value},
        )

    now = datetime.now(timezone.utc)
    if track.state == TrackState.WAITING and not user.is_admin:
        if track.retry_now_step == track.attempt_count:
            retry_after = _seconds_until_tried(db, track, now)
            # A manual pause has no end time: nothing dispatches until someone resumes.
            paused = bool(retry.get_worker_state(db).paused)
            db.rollback()
            raise ApiError(
                429,
                "retry_cooldown",
                f"Retry now works once per wait; the next try is in {retry_after}s"
                + (" once downloads resume" if paused else ""),
                {"retry_after": retry_after, "paused": paused},
                headers={"Retry-After": str(retry_after)},
            )
        track.retry_now_step = track.attempt_count
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
    job_status.publish_change(db, track.job_id)

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
    other direct-id track endpoint. Each row carries its proxy's redacted label, stored
    with the row since v56 (A4) so it outlives the proxy. The proxy is still joined in (v35),
    in the same query, for a row with no stored label whose proxy exists: one an old worker
    wrote during the deploy, after the migration's backfill."""
    _track, _owner_id, _archived_at = _get_track_or_404(db, track_id, user)
    rows = (
        db.query(TrackAttempt, Proxy.url)
        .outerjoin(Proxy, TrackAttempt.proxy_id == Proxy.id)
        .filter(TrackAttempt.track_id == track_id)
        .order_by(TrackAttempt.attempt_number)
        .all()
    )
    return [track_attempt_to_dict(attempt, proxy_url) for attempt, proxy_url in rows]


# v35 (e): HEAD too. The frontend probes with it before handing the URL to a real browser
# download, so a missing file still shows the inline notice instead of navigating to a
# 404 page. Through nginx the X-Accel-Redirect is followed for HEAD as well, so the probe
# also catches a file deleted from disk (this container has no mount to check that).
@router.api_route("/{track_id}/file", methods=["GET", "HEAD"])
def download_track_file(
    track_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> Response:
    """Streams a completed track's audio file via nginx `X-Accel-Redirect` (v27) -- no
    audio bytes pass through this process; FastAPI only decides *whether* nginx may serve
    the file and *which* one. Same owner-scoped 404-not-403 gate as every other direct-id
    track endpoint; availability is keyed on the file existing at its recorded path, never
    on the job's `archived_at` (a retention-archived job's track stays downloadable).

    v28's library move repoints the ledger's `file_path` to the sorted library root
    instead of the downloads root -- this endpoint accepts either, resolving whichever
    one the path actually falls under, so a moved track stays downloadable exactly as
    the master plan requires (see CLAUDE.md's "Sort & move vs. file downloads")."""
    track, _owner_id, _archived_at = _get_track_or_404(db, track_id, user)

    raw_path = _resolve_track_file_path(db, track)
    if raw_path is None:
        raise ApiError(404, "file_not_found", "File not found")

    # `output_path`/the ledger's `file_path` are app-generated today, but this endpoint
    # turns them into an authorization boundary -- confirm the resolved path is actually
    # inside one of the two allowed roots before ever handing it to nginx, rather than
    # trusting it as already-safe input (v27's plan, path-traversal guard). `.resolve()`
    # on an absolute, possibly-nonexistent path is purely lexical (no filesystem access
    # required), so this needs no volume mount into this container.
    downloads_root = Path(get_settings().download_output_dir).resolve()
    # v57 (L6): the whole library mount, not only the current library_target_dir, so a track
    # left under an earlier root stays downloadable (the owner's mount rule keeps every library
    # root inside it). nginx's /internal-library/ aliases exactly that directory, so the path
    # nginx gets is relative to it.
    library_alias = Path(app_settings.DEFAULT_LIBRARY_TARGET_DIR).resolve()
    db.commit()

    resolved = raw_path if raw_path.is_absolute() else (downloads_root / raw_path)
    resolved = resolved.resolve()

    if resolved.is_relative_to(downloads_root) and resolved != downloads_root:
        root, prefix = downloads_root, _INTERNAL_DOWNLOADS_PREFIX
    elif resolved.is_relative_to(library_alias) and resolved != library_alias:
        root, prefix = library_alias, _INTERNAL_LIBRARY_PREFIX
    else:
        raise ApiError(404, "file_not_found", "File not found")

    accel_uri = prefix + "/".join(
        quote(part, safe="") for part in resolved.relative_to(root).parts
    )
    headers = {
        "X-Accel-Redirect": accel_uri,
        "Content-Disposition": _content_disposition(resolved.name),
    }
    return Response(status_code=200, headers=headers)
