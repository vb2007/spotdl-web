import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Job, JobSourceType, JobState, Track, TrackState, User
from app.routers.auth import require_session
from app.services import events
from app.services.serializers import job_to_dict, track_counts, track_counts_by_job, track_to_dict
from app.tasks.expand import expand_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# Every track state a cancel should touch — anything not already a terminal outcome.
_CANCELLABLE_TRACK_STATES = [
    state
    for state in TrackState
    if state not in (TrackState.COMPLETED, TrackState.SKIPPED_DUPLICATE, TrackState.CANCELLED)
]


class CreateJobRequest(BaseModel):
    url: str


class SetPriorityRequest(BaseModel):
    priority: int


def _classify_source_type(url: str) -> JobSourceType:
    if "open.spotify.com" in url:
        if "/track/" in url:
            return JobSourceType.TRACK
        if "/album/" in url:
            return JobSourceType.ALBUM
        if "/playlist/" in url:
            return JobSourceType.PLAYLIST
        if "/artist/" in url:
            return JobSourceType.ARTIST
    return JobSourceType.SEARCH


@router.post("", status_code=201)
def create_job(
    payload: CreateJobRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    job = Job(source_url=payload.url, source_type=_classify_source_type(payload.url), user_id=user.id)
    db.add(job)
    db.commit()
    expand_job.delay(str(job.id))
    return job_to_dict(job, track_counts(db, job.id), user.email)


@router.get("")
def list_jobs(
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
    all_users: bool = False,
) -> list[dict]:
    # all_users is honored only for an admin session -- a non-admin passing it is
    # silently treated exactly as if they hadn't (v17's threat model: never trust a
    # client-supplied scope flag).
    query = db.query(Job, User.email).join(User, Job.user_id == User.id)
    if not (all_users and user.is_admin):
        query = query.filter(Job.user_id == user.id)
    rows = query.order_by(Job.created_at.desc()).all()

    # One aggregate for the whole page rather than one per job (v15's N+1 fix). Jobs with
    # no tracks are absent from `counts` and fall through to `{}` via job_to_dict's
    # required `counts` argument, matching what the old per-job query returned for them.
    # This does trade N queries for one query carrying N bind parameters -- fine at the
    # scale `list_jobs` runs at today (no LIMIT yet, so it's already every job), and
    # bounded permanently once v18 adds pagination.
    counts = track_counts_by_job(db, [job.id for job, _ in rows])
    return [job_to_dict(job, counts.get(job.id, {}), owner_email) for job, owner_email in rows]


def _get_job_or_404(db: Session, job_id: uuid.UUID, user: User) -> tuple[Job, str]:
    """Returns the job alongside its owner's email in one join -- and, for a non-admin,
    filters by ownership in the same query rather than loading the row and checking
    after, so a foreign job is indistinguishable from a nonexistent one (404, never 403,
    per the threat model: an id's existence must never be confirmed to a non-owner)."""
    query = db.query(Job, User.email).join(User, Job.user_id == User.id).filter(Job.id == job_id)
    if not user.is_admin:
        query = query.filter(Job.user_id == user.id)
    row = query.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return row


@router.get("/{job_id}")
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    job, owner_email = _get_job_or_404(db, job_id, user)
    return job_to_dict(job, track_counts(db, job.id), owner_email)


@router.get("/{job_id}/tracks")
def list_job_tracks(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> list[dict]:
    _get_job_or_404(db, job_id, user)
    tracks = db.query(Track).filter(Track.job_id == job_id).order_by(Track.created_at).all()
    return [track_to_dict(track) for track in tracks]


@router.delete("/{job_id}")
def cancel_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """Cancels the job and every non-terminal track under it. A track already
    `downloading` isn't interrupted (spotdl's call is synchronous, not cleanly
    interruptible) — it's marked `cancelled` here and `download_track` discards its
    result once the blocking call returns, rather than trying to stop it mid-flight."""
    job, owner_email = _get_job_or_404(db, job_id, user)
    tracks = (
        db.query(Track)
        .filter(Track.job_id == job_id, Track.state.in_(_CANCELLABLE_TRACK_STATES))
        .all()
    )
    for track in tracks:
        track.state = TrackState.CANCELLED
        track.scheduled_at = None
    job.state = JobState.CANCELLED
    db.commit()
    # Published to the job's *owner*, not the acting session -- an admin cancelling a
    # foreign job must update that owner's live view, not the admin's own channel.
    for track in tracks:
        events.publish_track_event(job.user_id, track.id, track.job_id, track.state.value)
    events.publish_job_event(job.user_id, job.id, job.state.value)
    # Read after the cancel commit above, not before -- counts must reflect the just
    # -cancelled tracks.
    return job_to_dict(job, track_counts(db, job.id), owner_email)


@router.patch("/{job_id}/priority")
def set_job_priority(
    job_id: uuid.UUID,
    payload: SetPriorityRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    job, owner_email = _get_job_or_404(db, job_id, user)
    job.priority = payload.priority
    db.commit()
    return job_to_dict(job, track_counts(db, job.id), owner_email)


@router.post("/{job_id}/bump")
def bump_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """Moves this job to the front of the dispatch order — sets its priority one above
    the current highest, which is the only "move to front" interaction actually needed
    day-to-day (per the v11 plan) rather than a full manual ranking scheme. The max is
    global, not scoped to the caller: queue fairness is a locked, global decision for
    v2 (no per-user slots), so "front" means front of everyone's queue."""
    job, owner_email = _get_job_or_404(db, job_id, user)
    max_priority = db.query(func.max(Job.priority)).scalar() or 0
    job.priority = max_priority + 1
    db.commit()
    return job_to_dict(job, track_counts(db, job.id), owner_email)
