import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Job, JobSourceType, Track, UserSession
from app.routers.auth import require_session
from app.tasks.expand import expand_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


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


def _track_counts(db: Session, job_id: uuid.UUID) -> dict[str, int]:
    rows = (
        db.query(Track.state, func.count(Track.id))
        .filter(Track.job_id == job_id)
        .group_by(Track.state)
        .all()
    )
    return {state.value: count for state, count in rows}


def _job_to_dict(db: Session, job: Job) -> dict:
    return {
        "id": str(job.id),
        "source_url": job.source_url,
        "source_type": job.source_type.value,
        "state": job.state.value,
        "priority": job.priority,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "track_counts": _track_counts(db, job.id),
    }


def _track_to_dict(track: Track) -> dict:
    song = track.song_json
    return {
        "id": str(track.id),
        "job_id": str(track.job_id),
        "state": track.state.value,
        "title": song.get("name"),
        "artists": song.get("artists"),
        "album": song.get("album_name"),
        "spotify_track_id": track.spotify_track_id,
        "attempt_count": track.attempt_count,
        "scheduled_at": track.scheduled_at.isoformat() if track.scheduled_at is not None else None,
        "last_error": track.last_error,
        "last_error_type": track.last_error_type.value if track.last_error_type is not None else None,
    }


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
    return _job_to_dict(db, job)


@router.get("")
def list_jobs(
    db: Session = Depends(get_db),
    _: UserSession = Depends(require_session),
) -> list[dict]:
    jobs = db.query(Job).order_by(Job.created_at.desc()).all()
    return [_job_to_dict(db, job) for job in jobs]


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
    return _job_to_dict(db, job)


@router.get("/{job_id}/tracks")
def list_job_tracks(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: UserSession = Depends(require_session),
) -> list[dict]:
    _get_job_or_404(db, job_id)
    tracks = db.query(Track).filter(Track.job_id == job_id).order_by(Track.created_at).all()
    return [_track_to_dict(track) for track in tracks]
