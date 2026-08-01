import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Job, JobSourceType, JobState, Track, TrackState, UserSession
from app.routers.auth import require_session
from app.services import events
from app.services.serializers import job_to_dict, track_to_dict
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
    _: UserSession = Depends(require_session),
) -> dict:
    job = Job(source_url=payload.url, source_type=_classify_source_type(payload.url))
    db.add(job)
    db.commit()
    expand_job.delay(str(job.id))
    return job_to_dict(db, job)


@router.get("")
def list_jobs(
    db: Session = Depends(get_db),
    _: UserSession = Depends(require_session),
) -> list[dict]:
    jobs = db.query(Job).order_by(Job.created_at.desc()).all()
    return [job_to_dict(db, job) for job in jobs]


def _get_job_or_404(db: Session, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}")
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: UserSession = Depends(require_session),
) -> dict:
    job = _get_job_or_404(db, job_id)
    return job_to_dict(db, job)


@router.get("/{job_id}/tracks")
def list_job_tracks(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: UserSession = Depends(require_session),
) -> list[dict]:
    _get_job_or_404(db, job_id)
    tracks = db.query(Track).filter(Track.job_id == job_id).order_by(Track.created_at).all()
    return [track_to_dict(track) for track in tracks]


@router.delete("/{job_id}")
def cancel_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: UserSession = Depends(require_session),
) -> dict:
    """Cancels the job and every non-terminal track under it. A track already
    `downloading` isn't interrupted (spotdl's call is synchronous, not cleanly
    interruptible) — it's marked `cancelled` here and `download_track` discards its
    result once the blocking call returns, rather than trying to stop it mid-flight."""
    job = _get_job_or_404(db, job_id)
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
    for track in tracks:
        events.publish_track_event(track.id, track.job_id, track.state.value)
    events.publish_job_event(job.id, job.state.value)
    return job_to_dict(db, job)
