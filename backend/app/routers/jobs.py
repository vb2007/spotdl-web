import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Job, JobSourceType, JobState, Track, TrackState, User
from app.routers.auth import require_session
from app.services import archive, events, job_listing, rollup, track_listing
from app.services.pagination import DEFAULT_LIMIT, InvalidCursor
from app.services.serializers import job_to_dict, track_counts, track_song_meta
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


class ArchiveJobsRequest(BaseModel):
    job_ids: list[uuid.UUID] | None = None
    all_settled: bool = False


class UnarchiveJobsRequest(BaseModel):
    job_ids: list[uuid.UUID]


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
    return job_to_dict(job, track_counts(db, job.id), user.email, rollup.job_title(db, job))


@router.get("")
def list_jobs(
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
    scope: Literal["job", "track"] = "job",
    q: str | None = None,
    status: list[str] = Query(default=[]),
    state: list[str] = Query(default=[]),
    source_type: JobSourceType | None = None,
    include_archived: bool = False,
    sort: str | None = None,
    dir: Literal["asc", "desc"] | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    all_users: bool = False,
) -> dict:
    """`scope=track` (the master plan's job/track toggle, "Tracks" position) delegates to
    exactly the same query `GET /api/tracks` runs, sharing `track_listing.list_tracks` --
    both URLs are equally "correct" for a track-scoped result; which one the frontend
    calls is purely its own choice, not a distinction this API enforces."""
    try:
        if scope == "track":
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
                sort=sort or "created_at",
                dir=dir or "desc",
                limit=limit,
                cursor=cursor,
            )
        return job_listing.list_jobs(
            db,
            user_id=user.id,
            is_admin=user.is_admin,
            all_users=all_users,
            q=q,
            status_tokens=status,
            source_type=source_type,
            include_archived=include_archived,
            sort=sort or "created_at",
            dir=dir or "desc",
            limit=limit,
            cursor=cursor,
        )
    except (job_listing.InvalidListParams, track_listing.InvalidListParams, InvalidCursor) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/archive")
def archive_jobs(
    payload: ArchiveJobsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """"Clear log": archives the caller's own settled/failed/cancelled jobs, never an
    in-flight or another user's job -- `archive.archive_jobs` re-derives eligibility from
    the real track states rather than trusting `job_ids`. `all_settled=true` archives
    every eligible job for this user with no age restriction; otherwise exactly the given
    `job_ids` that turn out to be eligible."""
    if not payload.all_settled and not payload.job_ids:
        raise HTTPException(status_code=400, detail="Provide job_ids or set all_settled=true")
    job_ids = None if payload.all_settled else payload.job_ids
    jobs = archive.archive_jobs(db, user.id, job_ids=job_ids)
    for job in jobs:
        events.publish_job_event(user.id, job.id, job.state.value, archived=True)
    return {"archived_ids": [str(job.id) for job in jobs]}


@router.post("/unarchive")
def unarchive_jobs(
    payload: UnarchiveJobsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    jobs = archive.unarchive_jobs(db, user.id, payload.job_ids)
    for job in jobs:
        events.publish_job_event(user.id, job.id, job.state.value, archived=False)
    return {"unarchived_ids": [str(job.id) for job in jobs]}


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
    return job_to_dict(job, track_counts(db, job.id), owner_email, rollup.job_title(db, job))


@router.get("/{job_id}/tracks")
def list_job_tracks(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
    q: str | None = None,
    state: list[str] = Query(default=[]),
    sort: str = "created_at",
    dir: Literal["asc", "desc"] = "asc",
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> dict:
    _get_job_or_404(db, job_id, user)
    try:
        result = track_listing.list_tracks(
            db,
            user_id=user.id,
            is_admin=user.is_admin,
            # Ownership of `job_id` is already checked above by `_get_job_or_404` (which
            # itself only bypasses the owner filter for an admin) -- passing
            # `all_users=is_admin` here reproduces that exact same bypass for the track
            # query rather than introducing a second, differently-shaped ownership rule.
            all_users=user.is_admin,
            q=q,
            job_status_tokens=[],
            track_states=state,
            source_type=None,
            include_archived=True,  # this job's own archived state is irrelevant to listing *its* tracks
            sort=sort,
            dir=dir,
            limit=limit,
            cursor=cursor,
            job_id=job_id,
        )
    except (track_listing.InvalidListParams, InvalidCursor) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # counts_by_state ignores this request's own `state` filter (so switching tabs keeps
    # every tab's count visible) but, deliberately, not `q` either -- unlike the job
    # listing's counts_by_status, this is the simple full per-job breakdown already
    # computed by `track_counts`, reused as-is rather than adding a second q-aware query
    # for a per-job tab count nobody has asked to search live.
    result["counts_by_state"] = track_counts(db, job_id)
    return result


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
        events.publish_track_event(
            job.user_id, track.id, track.job_id, track.state.value, **track_song_meta(track.song_json)
        )
    events.publish_job_event(job.user_id, job.id, job.state.value)
    # Read after the cancel commit above, not before -- counts must reflect the just
    # -cancelled tracks.
    return job_to_dict(job, track_counts(db, job.id), owner_email, rollup.job_title(db, job))


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
    return job_to_dict(job, track_counts(db, job.id), owner_email, rollup.job_title(db, job))


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
    return job_to_dict(job, track_counts(db, job.id), owner_email, rollup.job_title(db, job))
