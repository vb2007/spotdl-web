import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Track, TrackState, UserSession
from app.routers.auth import require_session
from app.services import events, retry
from app.services.serializers import track_to_dict

router = APIRouter(prefix="/api/tracks", tags=["tracks"])

_TERMINAL_TRACK_STATES = {TrackState.COMPLETED, TrackState.SKIPPED_DUPLICATE, TrackState.CANCELLED}
_RETRYABLE_TRACK_STATES = {TrackState.WAITING, TrackState.LOOKUP_FAILED, TrackState.FAILED}


def _get_track_or_404(db: Session, track_id: uuid.UUID) -> Track:
    track = db.get(Track, track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")
    return track


@router.get("")
def list_tracks(
    db: Session = Depends(get_db),
    _: UserSession = Depends(require_session),
) -> list[dict]:
    """All tracks across every job, in one query -- what the frontend's initial load and
    every SSE-reconnect resync actually need. Replaces what used to be N individual
    `GET /api/jobs/{id}/tracks` calls (one per job) fired concurrently via `Promise.all`
    on the frontend: harmless with a handful of jobs, but a real, felt bug once real
    usage accumulated 100+ historical jobs -- that many concurrent requests queues up
    behind the browser's/server's concurrent-stream limit, and any *other* request
    issued around the same time (e.g. a worker pause/resume click) gets stuck waiting
    behind the flood rather than being independently fast. Caught via a live report
    against the deployed production stack, not local testing (its shared dev database's
    job count was still small enough not to trigger it)."""
    tracks = db.query(Track).order_by(Track.created_at).all()
    return [track_to_dict(track) for track in tracks]


@router.delete("/{track_id}")
def cancel_track(
    track_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: UserSession = Depends(require_session),
) -> dict:
    """Same semantics as `DELETE /api/jobs/{id}` but for a single track — a track
    already `downloading` finishes but its result is discarded by `download_track`
    once it notices the state changed underneath it."""
    track = _get_track_or_404(db, track_id)
    if track.state not in _TERMINAL_TRACK_STATES:
        track.state = TrackState.CANCELLED
        track.scheduled_at = None
        db.commit()
        events.publish_track_event(track.id, track.job_id, track.state.value)
    return track_to_dict(track)


@router.post("/{track_id}/retry")
def retry_track(
    track_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: UserSession = Depends(require_session),
) -> dict:
    """Bypasses the per-track ladder wait by resetting `scheduled_at` to now, but still
    respects the global circuit breaker — a manual retry must not be able to defeat the
    pause that exists specifically to stop hammering a rate-limited provider. The
    response's `breaker_held` field tells the caller whether this will dispatch on the
    next beat tick or is deferred until the breaker clears."""
    track = _get_track_or_404(db, track_id)
    if track.state not in _RETRYABLE_TRACK_STATES:
        raise HTTPException(
            status_code=409, detail=f"Track is {track.state.value}, not retryable"
        )

    now = datetime.now(timezone.utc)
    track.state = TrackState.WAITING
    track.scheduled_at = now
    db.commit()
    events.publish_track_event(
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
