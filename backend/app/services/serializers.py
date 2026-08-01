"""Shared REST projections for Job/Track — deliberate projections rather than exposing
the ORM row directly (see v09's CLAUDE.md gotcha), used by both the jobs and tracks
routers."""

import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Job, Track


def track_counts(db: Session, job_id: uuid.UUID) -> dict[str, int]:
    rows = (
        db.query(Track.state, func.count(Track.id))
        .filter(Track.job_id == job_id)
        .group_by(Track.state)
        .all()
    )
    return {state.value: count for state, count in rows}


def job_to_dict(db: Session, job: Job) -> dict:
    return {
        "id": str(job.id),
        "source_url": job.source_url,
        "source_type": job.source_type.value,
        "state": job.state.value,
        "priority": job.priority,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "track_counts": track_counts(db, job.id),
    }


def track_to_dict(track: Track) -> dict:
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
