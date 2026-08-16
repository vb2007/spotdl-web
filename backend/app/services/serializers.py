"""Shared REST projections for Job/Track — deliberate projections rather than exposing
the ORM row directly (see v09's CLAUDE.md gotcha), used by both the jobs and tracks
routers."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Job, Track, TrackAttempt
from app.services.rollup import derive_rollup


def track_counts_by_job(
    db: Session, job_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    """One grouped aggregate covering every requested job -- replaces the per-job query
    job_to_dict used to run in a loop (list_jobs's N+1, see v15). Jobs with no tracks are
    simply absent from the result rather than mapped to {}; callers use .get(job_id, {}),
    which reproduces exactly what the old per-job query returned for an empty job."""
    if not job_ids:
        return {}
    rows = (
        db.query(Track.job_id, Track.state, func.count(Track.id))
        .filter(Track.job_id.in_(job_ids))
        .group_by(Track.job_id, Track.state)
        .all()
    )
    counts: dict[uuid.UUID, dict[str, int]] = {}
    for job_id, state, count in rows:
        counts.setdefault(job_id, {})[state.value] = count
    return counts


def track_counts(db: Session, job_id: uuid.UUID) -> dict[str, int]:
    """Single-job convenience over the bulk query -- for endpoints that serialize exactly
    one job and so can't loop into an N+1 by construction."""
    return track_counts_by_job(db, [job_id]).get(job_id, {})


def job_to_dict(job: Job, counts: dict[str, int], owner_email: str, title: str) -> dict:
    """counts is passed in, not queried -- dropping the Session parameter is what makes
    list_jobs's N+1 impossible to reintroduce by accident: this function has nothing left
    to query with, so the caller must decide up front how many jobs' counts to fetch.
    counts, owner_email, and title are all required (no default) so a caller that forgets
    any of them fails loudly at the call site instead of silently serializing empty/
    missing data -- owner_email specifically so an admin's all-users view can actually
    tell whose job is whose (v17), title because `Job` has no title column of its own
    (see `rollup.derive_job_title`/`rollup.job_title`) and every caller must decide how to
    get one rather than this function silently querying for it.

    `status` (v18) is derived from `counts` and `job.state`, never stored -- see
    `rollup.derive_rollup`."""
    rollup = derive_rollup(job.state, counts)
    return {
        "id": str(job.id),
        "source_url": job.source_url,
        "source_type": job.source_type.value,
        "state": job.state.value,
        "priority": job.priority,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "archived_at": job.archived_at.isoformat() if job.archived_at is not None else None,
        "track_counts": counts,
        "owner_email": owner_email,
        "title": title,
        "status": {"lifecycle": rollup.lifecycle, "outcome": rollup.outcome},
    }


def track_song_meta(song_json: dict) -> dict:
    """title/artists/album straight from a track's `song_json` -- the single field
    mapping both the REST projection (track_to_dict, below) and every live SSE
    `track.state` event (events.publish_track_event call sites, v23) read from, so the
    two can never drift into disagreeing about what a track is called. Takes the raw
    dict rather than a `Track` so a bulk-update's `RETURNING` projection (no full ORM
    object) can use it too, not just a loaded `Track` instance."""
    return {
        "title": song_json.get("name"),
        "artists": song_json.get("artists"),
        "album": song_json.get("album_name"),
    }


def track_to_dict(track: Track) -> dict:
    return {
        "id": str(track.id),
        "job_id": str(track.job_id),
        "state": track.state.value,
        **track_song_meta(track.song_json),
        "spotify_track_id": track.spotify_track_id,
        "attempt_count": track.attempt_count,
        "scheduled_at": track.scheduled_at.isoformat() if track.scheduled_at is not None else None,
        "last_error": track.last_error,
        "last_error_type": track.last_error_type.value if track.last_error_type is not None else None,
    }


def track_attempt_to_dict(attempt: TrackAttempt) -> dict:
    return {
        "id": str(attempt.id),
        "attempt_number": attempt.attempt_number,
        "started_at": attempt.started_at.isoformat(),
        "finished_at": attempt.finished_at.isoformat(),
        "outcome": attempt.outcome.value,
        "error_type": attempt.error_type.value if attempt.error_type is not None else None,
        "error_message": attempt.error_message,
        "proxy_id": str(attempt.proxy_id) if attempt.proxy_id is not None else None,
    }
