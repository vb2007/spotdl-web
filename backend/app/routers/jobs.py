import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import DownloadedTrack, Job, JobSourceType, JobState, Track, TrackState, User
from app.routers.auth import Principal, require_admin_hidden, require_session, require_session_or_api_key
from app.services import archive, events, job_listing, rate_limit, rollup, spotify_urls, track_listing
from app.services.pagination import DEFAULT_LIMIT, InvalidCursor
from app.services.serializers import job_to_dict, track_counts, track_song_meta
from app.services.track_states import CANCELLABLE_TRACK_STATES
from app.services.view_scope import View, resolve_view
from app.tasks.expand import expand_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

class CreateJobRequest(BaseModel):
    url: str
    # v53: queue the link's album or artist instead (spotify_urls.resolve_cascade).
    # Any JSON value, checked in the handler, so a bad one answers with a stable code (v46).
    cascade: Any = None


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


# v53: the header the browser extension sends (`extension/<version>`). It's a non-simple
# header, so a web page can't send it cross-origin without a CORS preflight the API refuses.
CLIENT_HEADER = "X-Spotdl-Client"


def _resolve_cascade(ref: spotify_urls.SpotifyRef, cascade: str) -> spotify_urls.SpotifyRef:
    try:
        return spotify_urls.resolve_cascade(ref, cascade)
    except spotify_urls.CascadeInvalid as exc:
        raise ApiError(
            422,
            "cascade_invalid",
            f"{'An' if ref.type in ('album', 'artist') else 'A'} {ref.type} link has no {cascade} to queue",
            {"cascade": cascade, "type": ref.type, "reason": exc.reason},
        ) from None
    except spotify_urls.CascadeNotFound:
        raise ApiError(422, "cascade_not_found", "Spotify doesn't know this link") from None
    except spotify_urls.CascadeUnavailable as exc:
        raise ApiError(
            503,
            "cascade_unavailable",
            "Spotify's metadata couldn't be read; try again",
            {"reason": exc.reason},
        ) from None
    except spotify_urls.CascadeAmbiguous as exc:
        raise ApiError(
            409,
            "cascade_ambiguous",
            "This has more than one artist; choose one",
            {"candidates": exc.candidates},
        ) from None


# The longest link or search text a job may be created from (a Spotify link is under 100).
MAX_SUBMIT_LENGTH = 2048

# How long a job may sit in `expanding` and still count as queued. Nothing recovers a job
# whose expansion was lost (a broker error after its row committed), and a key can't cancel
# one: past this, a re-submit creates a fresh job instead of answering with the dead one. A
# discography expands in about two minutes; the margin covers a backed-up expand queue.
ALREADY_QUEUED_EXPANDING_FOR = timedelta(hours=1)


def _unfinished_job(db: Session, user_id: uuid.UUID, source_url: str) -> Job | None:
    """The caller's newest job for `source_url` that is still expanding (recently) or still
    has a track to download (rollup's `active` or `waiting`), if any."""
    unfinished_track = (
        db.query(Track.id)
        .filter(
            Track.job_id == Job.id,
            Track.state.in_(
                (TrackState.PENDING, TrackState.QUEUED, TrackState.DOWNLOADING, TrackState.WAITING)
            ),
        )
        .exists()
    )
    expanding_since = datetime.now(timezone.utc) - ALREADY_QUEUED_EXPANDING_FOR
    return (
        db.query(Job)
        .filter(
            Job.user_id == user_id,
            Job.source_url == source_url,
            Job.archived_at.is_(None),
            ((Job.state == JobState.EXPANDING) & (Job.created_at > expanding_since))
            | ((Job.state == JobState.EXPANDED) & unfinished_track),
        )
        .order_by(Job.created_at.desc())
        .first()
    )


@router.post("", status_code=201)
def create_job(
    payload: CreateJobRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_session_or_api_key),
) -> dict:
    """v53: the session cookie or an API key. A key-authenticated or extension-origin
    request (`X-Spotdl-Client`) may submit only an open.spotify.com track/album/artist/
    playlist link (422 `url_not_spotify` otherwise); the web UI's cookie requests keep
    submitting anything, search text included. A Spotify link is stored in its canonical
    form either way.

    `hint` in the answer: `already_queued` when the caller already has an unfinished job for
    the same link (that job is returned, 200, and nothing is created), `in_library` when a
    track link's track is already in the ledger (the job is still created, and resolves as a
    duplicate)."""
    user = principal.user
    rate_limit.hit_job_create(user.id, principal.api_key.id if principal.api_key else None)
    if payload.cascade is not None and (
        not isinstance(payload.cascade, str) or payload.cascade not in spotify_urls.CASCADE_SOURCES
    ):
        raise ApiError(
            422,
            "cascade_invalid",
            "A cascade is \"album\" or \"artist\"",
            # Echoed only when it can be: a lone surrogate would fail the response's encoding.
            {
                "cascade": payload.cascade[:40]
                if isinstance(payload.cascade, str) and spotify_urls.storable(payload.cascade)
                else None,
                "reason": "unknown",
            },
        )
    if len(payload.url) > MAX_SUBMIT_LENGTH:
        # The web UI's search text has no other bound, and a 20 MB "search" was stored, searched
        # and echoed into every listing of that user's jobs.
        raise ApiError(
            422,
            "submit_too_long",
            f"A link or search is at most {MAX_SUBMIT_LENGTH} characters",
            {"max": MAX_SUBMIT_LENGTH},
        )
    if not spotify_urls.storable(payload.url):
        # A NUL or a lone surrogate: Postgres can't take it, so the query would be a 500.
        raise ApiError(422, "request_invalid", "The link holds a character that can't be stored")

    restricted = principal.api_key is not None or CLIENT_HEADER.lower() in request.headers
    ref = spotify_urls.parse(payload.url)
    if ref is None and (restricted or payload.cascade is not None):
        raise ApiError(
            422, "url_not_spotify", "Only open.spotify.com track, album, artist or playlist links"
        )
    if ref is not None and payload.cascade is not None:
        # The metadata call can take seconds: never with a transaction idling open across it
        # (v31's idle-in-transaction lesson). The user row reloads after it.
        db.commit()
        ref = _resolve_cascade(ref, payload.cascade)

    if ref is not None:
        source_url, source_type = ref.url, ref.source_type
    else:
        source_url, source_type = payload.url, _classify_source_type(payload.url)

    # Two identical submits at once (an extension's double send) would both find nothing and
    # both create: the user's row serializes them, held until this request commits.
    # NO KEY UPDATE: it doesn't block the KEY SHARE locks a concurrent insert referencing the
    # user takes (a login's session row).
    db.query(User.id).filter(User.id == user.id).with_for_update(key_share=True).one()
    existing = _unfinished_job(db, user.id, source_url)
    if existing is not None:
        # Nothing to write: let the lock go before building the answer.
        db.commit()
        response.status_code = 200
        return {
            **job_to_dict(
                existing, track_counts(db, existing.id), user.email, user.username, rollup.job_title(db, existing)
            ),
            "hint": "already_queued",
        }

    hint = None
    if ref is not None and ref.type == "track" and db.get(DownloadedTrack, ref.id) is not None:
        hint = "in_library"
    job = Job(source_url=source_url, source_type=source_type, user_id=user.id)
    db.add(job)
    db.commit()
    try:
        expand_job.delay(str(job.id))
    except Exception as exc:
        # The broker (Redis) is down: the committed job would never expand, and the hint would
        # hand it back to every re-submit as "already queued". It fails instead, so the next
        # submit starts over (v53, live review).
        # Archived at once too: it was never really queued, and an unarchived failed job would
        # sit in the dashboard's incoming panel reading as an unreadable link.
        job.state = JobState.FAILED
        job.error = "Couldn't be queued for expansion; submit it again"
        job.archived_at = datetime.now(timezone.utc)
        db.commit()
        logger.warning("create_job: expansion not enqueued for %s: %s", job.id, type(exc).__name__)
        raise ApiError(503, "queue_unavailable", "The queue is unavailable; try again shortly") from None
    return {
        **job_to_dict(job, track_counts(db, job.id), user.email, user.username, rollup.job_title(db, job)),
        "hint": hint,
    }


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
    view: View | None = None,
    all_users: bool | None = None,
) -> dict:
    """`scope=track` (the master plan's job/track toggle, "Tracks" position) delegates to
    exactly the same query `GET /api/tracks` runs, sharing `track_listing.list_tracks` --
    both URLs are equally "correct" for a track-scoped result; which one the frontend
    calls is purely its own choice, not a distinction this API enforces.

    `view` (v54) is the admin's mine/all/others scope; `all_users=true` is its alias for
    `all`. A non-admin always gets `mine`."""
    view = resolve_view(view, all_users, is_admin=user.is_admin)
    try:
        if scope == "track":
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
                sort=sort or "created_at",
                dir=dir or "desc",
                limit=limit,
                cursor=cursor,
                include_state_counts=True,
            )
        return job_listing.list_jobs(
            db,
            user_id=user.id,
            is_admin=user.is_admin,
            view=view,
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
        raise ApiError(400, "invalid_list_params", str(exc), {"reason": str(exc)}) from exc


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
        raise ApiError(400, "archive_nothing_selected", "Provide job_ids or set all_settled=true")
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


def _get_job_or_404(
    db: Session, job_id: uuid.UUID, user: User, *, owner_only: bool = False
) -> tuple[Job, str, str | None]:
    """Returns the job alongside its owner's email and username in one join -- and, for a
    non-admin, filters by ownership in the same query rather than loading the row and
    checking after, so a foreign job is indistinguishable from a nonexistent one (404,
    never 403, per the threat model: an id's existence must never be confirmed to a
    non-owner)."""
    query = (
        db.query(Job, User.email, User.username)
        .join(User, Job.user_id == User.id)
        .filter(Job.id == job_id)
    )
    if owner_only or not user.is_admin:
        query = query.filter(Job.user_id == user.id)
    row = query.one_or_none()
    if row is None:
        raise ApiError(404, "job_not_found", "Job not found")
    return row


@router.get("/{job_id}")
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_session_or_api_key),
) -> dict:
    """v53 (owner's decision): an API key may read its own user's jobs here, the extension's
    "how is my submission doing", and nothing else of the job API. Through a key it's always
    the user's own jobs, even an admin's key (404 for anyone else's, like a non-owner)."""
    job, owner_email, owner_username = _get_job_or_404(
        db, job_id, principal.user, owner_only=principal.api_key is not None
    )
    return job_to_dict(
        job, track_counts(db, job.id), owner_email, owner_username, rollup.job_title(db, job)
    )


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
            # `view="all"` here reproduces that exact same bypass for the track query (the
            # service narrows a non-admin back to `mine`) rather than introducing a second,
            # differently-shaped ownership rule.
            view="all",
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
        raise ApiError(400, "invalid_list_params", str(exc), {"reason": str(exc)}) from exc
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
    result once the blocking call returns, rather than trying to stop it mid-flight.

    v56 (A1): only a job still in flight (`expanding`, `active` or `waiting`) can be
    cancelled, plus a `failed` one (owner's decision, 2026-10-26): it has no tracks, and
    cancelling it is how the incoming overlay's "dismiss" clears it. Any other (settled, or
    already cancelled) answers 409 `job_not_cancellable` with its rollup status and is left
    exactly as it was: before v56 a finished job was relabelled `cancelled`."""
    job, owner_email, owner_username = _get_job_or_404(db, job_id, user)
    # v34.1: row-lock the job before touching its tracks. expand_job commits EXPANDED and
    # the new tracks in one transaction via a conditional UPDATE on this same row, so with
    # the lock the two serialize: either that commit lands first (the UPDATE below then
    # sees and cancels the new tracks) or this cancel does (its UPDATE then matches no
    # row and it cancels its own tracks). Without it, a commit landing between the query
    # and the commit below left a `cancelled` job whose tracks still downloaded.
    db.refresh(job, with_for_update=True)
    cancelled_tracks = []
    if job.state in (JobState.EXPANDING, JobState.EXPANDED):
        # One conditional UPDATE, not loaded rows written back: Postgres re-checks the
        # state of a row another transaction held, so a last track completing meanwhile is
        # never relabelled `cancelled` (and then leaves nothing here to cancel).
        cancelled_tracks = db.execute(
            update(Track)
            .where(Track.job_id == job_id, Track.state.in_(CANCELLABLE_TRACK_STATES))
            .values(state=TrackState.CANCELLED, scheduled_at=None)
            .returning(Track.id, Track.song_json)
        ).all()
    # An expanded job with no track left in flight is settled: nothing to cancel. (Its
    # cancellable tracks are exactly what makes a job `active`/`waiting`, rollup.py.)
    if job.state not in (JobState.EXPANDING, JobState.FAILED) and not cancelled_tracks:
        db.rollback()
        status = rollup.derive_rollup(job.state, track_counts(db, job.id))
        raise ApiError(
            409,
            "job_not_cancellable",
            f"Job is {status.key}, not cancellable",
            {"lifecycle": status.lifecycle, "outcome": status.outcome},
        )
    job.state = JobState.CANCELLED
    db.commit()
    # Published to the job's *owner*, not the acting session -- an admin cancelling a
    # foreign job must update that owner's live view, not the admin's own channel.
    for track_id, song_json in cancelled_tracks:
        events.publish_track_event(
            job.user_id, track_id, job.id, TrackState.CANCELLED.value, **track_song_meta(song_json)
        )
    events.publish_job_event(job.user_id, job.id, job.state.value)
    # Read after the cancel commit above, not before -- counts must reflect the just
    # -cancelled tracks.
    return job_to_dict(
        job, track_counts(db, job.id), owner_email, owner_username, rollup.job_title(db, job)
    )


@router.patch("/{job_id}/priority")
def set_job_priority(
    job_id: uuid.UUID,
    payload: SetPriorityRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_hidden),
) -> dict:
    """Admin-only (v48, owner decision): priority reorders everyone's queue, so it is an
    operator control, not a job owner's. A non-admin gets require_admin_hidden's 404
    (v56, A6) before the job is looked up, the same answer for any id."""
    job, owner_email, owner_username = _get_job_or_404(db, job_id, user)
    job.priority = payload.priority
    db.commit()
    return job_to_dict(
        job, track_counts(db, job.id), owner_email, owner_username, rollup.job_title(db, job)
    )


@router.post("/{job_id}/bump")
def bump_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin_hidden),
) -> dict:
    """Moves this job to the front of the dispatch order — sets its priority one above
    the current highest, which is the only "move to front" interaction actually needed
    day-to-day (per the v11 plan) rather than a full manual ranking scheme. The max is
    global, not scoped to the caller: queue fairness is a locked, global decision for
    v2 (no per-user slots), so "front" means front of everyone's queue -- which is why
    it is admin-only, like set_job_priority (v48)."""
    job, owner_email, owner_username = _get_job_or_404(db, job_id, user)
    max_priority = db.query(func.max(Job.priority)).scalar() or 0
    job.priority = max_priority + 1
    db.commit()
    return job_to_dict(
        job, track_counts(db, job.id), owner_email, owner_username, rollup.job_title(db, job)
    )
