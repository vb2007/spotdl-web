import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Job, JobSourceType, Track, TrackState, User
from app.routers.auth import require_session
from app.services import events, retry, track_listing
from app.services.pagination import DEFAULT_LIMIT, InvalidCursor
from app.services.serializers import track_to_dict

router = APIRouter(prefix="/api/tracks", tags=["tracks"])

_TERMINAL_TRACK_STATES = {TrackState.COMPLETED, TrackState.SKIPPED_DUPLICATE, TrackState.CANCELLED}
_RETRYABLE_TRACK_STATES = {TrackState.WAITING, TrackState.LOOKUP_FAILED}


def _get_track_or_404(db: Session, track_id: uuid.UUID, user: User) -> tuple[Track, uuid.UUID]:
    """Returns the track alongside its job's owner id -- ownership lives on `jobs`, not
    `tracks` (v2's locked decision: no denormalized copy), so this always joins through
    `Track.job_id`. A non-admin's foreign track 404s exactly like a nonexistent one."""
    query = db.query(Track, Job.user_id).join(Job, Track.job_id == Job.id).filter(Track.id == track_id)
    if not user.is_admin:
        query = query.filter(Job.user_id == user.id)
    row = query.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Track not found")
    return row


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
    track, owner_id = _get_track_or_404(db, track_id, user)
    if track.state not in _TERMINAL_TRACK_STATES:
        track.state = TrackState.CANCELLED
        track.scheduled_at = None
        db.commit()
        events.publish_track_event(owner_id, track.id, track.job_id, track.state.value)
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
    next beat tick or is deferred until the breaker clears."""
    track, owner_id = _get_track_or_404(db, track_id, user)
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
    )

    worker_state = retry.get_worker_state(db)
    db.commit()
    breaker_held = retry.breaker_active(worker_state, now)

    body = track_to_dict(track)
    body["breaker_held"] = breaker_held
    return body
