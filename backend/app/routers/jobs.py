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
from app.models import DownloadedTrack, Job, JobSourceType, JobState, Track, TrackAttemptOutcome, TrackState, User
from app.routers.auth import Principal, require_admin_hidden, require_session, require_session_or_api_key
from app.services import archive, attempts, events, job_listing, job_status, rate_limit, retry, rollup, spotify_urls, track_listing, watch
from app.services.pagination import DEFAULT_LIMIT, InvalidCursor
from app.services.serializers import job_to_dict, track_counts, track_song_meta
from app.services.track_states import CANCELLABLE_TRACK_STATES, cancelled_used_proxy_id
from app.services.view_scope import View, resolve_view
from app.tasks.expand import expand_job
# After expand: importing tasks.download first is a circular import (celery_app imports expand).
from app.tasks.download import download_track  # noqa: E402

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

class CreateJobRequest(BaseModel):
    url: str
    # v53: queue the link's album or artist instead (spotify_urls.resolve_cascade).
    # Any JSON value, checked in the handler, so a bad one answers with a stable code (v46).
    cascade: Any = None


class SetPriorityRequest(BaseModel):
    priority: int


class SetWatchRequest(BaseModel):
    # Any JSON value, checked in the handler, so a bad one answers with a stable code (v46).
    interval_hours: Any = None


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
                existing,
                track_counts(db, existing.id),
                user.email,
                user.username,
                rollup.job_title(db, existing),
                new_tracks=watch.new_tracks(db, existing.id),
            ),
            "hint": "already_queued",
        }

    hint = None
    if ref is not None and ref.type == "track" and db.get(DownloadedTrack, ref.id) is not None:
        hint = "in_library"
    job = Job(source_url=source_url, source_type=source_type, user_id=user.id)
    db.add(job)
    db.commit()
    # v62 (F1): its first status (`expanding`, from none), so the dashboard counts it at once.
    job_status.publish_change(db, job.id, created=True)
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
        job_status.publish_change(db, job.id)
        logger.warning("create_job: expansion not enqueued for %s: %s", job.id, type(exc).__name__)
        raise ApiError(503, "queue_unavailable", "The queue is unavailable; try again shortly") from None
    return {
        **job_to_dict(
            job, track_counts(db, job.id), user.email, user.username, rollup.job_title(db, job), new_tracks=0
        ),
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


def _job_answer(db: Session, job: Job, owner_email: str, owner_username: str | None) -> dict:
    """One job's REST answer, read now (its counts after the caller's commit)."""
    return job_to_dict(
        job,
        track_counts(db, job.id),
        owner_email,
        owner_username,
        rollup.job_title(db, job),
        new_tracks=watch.new_tracks(db, job.id),
    )


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
    return _job_answer(db, job, owner_email, owner_username)


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
            .values(state=TrackState.CANCELLED, scheduled_at=None, used_proxy_id=cancelled_used_proxy_id())
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
    job_status.publish_change(db, job.id)
    # Read after the cancel commit above, not before -- counts must reflect the just
    # -cancelled tracks.
    return _job_answer(db, job, owner_email, owner_username)


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
    return _job_answer(db, job, owner_email, owner_username)


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
    return _job_answer(db, job, owner_email, owner_username)


# v63: watched jobs, "check now" and "retry failed".


@router.put("/{job_id}/watch")
def set_job_watch(
    job_id: uuid.UUID,
    payload: SetWatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """Watches a playlist or artist job (`interval_hours`, at least a day), or stops watching
    it (`null`). Its owner's, or an admin's on any job; anyone else's is a 404. A watched job
    is re-expanded every interval from now on (services/watch.py); the first check is one
    interval away, and an unchanged interval keeps the check already scheduled."""
    job, owner_email, owner_username = _get_job_or_404(db, job_id, user)
    interval = payload.interval_hours
    if interval is not None and (
        not isinstance(interval, int)
        or isinstance(interval, bool)
        or not watch.MIN_WATCH_INTERVAL_HOURS <= interval <= watch.MAX_WATCH_INTERVAL_HOURS
    ):
        raise ApiError(
            422,
            "watch_interval_invalid",
            f"A watch interval is a whole number of hours from {watch.MIN_WATCH_INTERVAL_HOURS}"
            f" to {watch.MAX_WATCH_INTERVAL_HOURS}",
            {"min": watch.MIN_WATCH_INTERVAL_HOURS, "max": watch.MAX_WATCH_INTERVAL_HOURS},
        )
    db.refresh(job, with_for_update=True)
    if interval is None:
        job.watch_interval_hours = None
        job.next_expand_at = None
    elif interval != job.watch_interval_hours:
        if not watch.is_watchable(job):
            raise ApiError(
                409,
                "job_not_watchable",
                "Only a playlist or an artist can be watched",
                {"reason": "source_type", "source_type": job.source_type.value},
            )
        if job.state != JobState.EXPANDED or job.archived_at is not None:
            raise ApiError(
                409,
                "job_not_watchable",
                "Only an expanded, unarchived job can be watched",
                {"reason": "archived" if job.archived_at is not None else "state", "state": job.state.value},
            )
        job.watch_interval_hours = interval
        job.next_expand_at = datetime.now(timezone.utc) + timedelta(hours=interval)
    db.commit()
    return _job_answer(db, job, owner_email, owner_username)


@router.post("/{job_id}/reexpand", status_code=202)
def reexpand_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """"Check now": re-expands the job at once, adding only the tracks new to it (any source
    type; the job must be expanded and unarchived). Its owner's, or an admin's on any job;
    anyone else's is a 404. One at a time per job: 409 `reexpand_running` while one is queued
    or running, a scheduled one included. Counts toward the hourly cap, never held by it (the
    cap paces beat's scheduled runs). A watched job's next scheduled run moves to an interval
    from now."""
    job, owner_email, owner_username = _get_job_or_404(db, job_id, user)
    db.refresh(job, with_for_update=True)
    if job.archived_at is not None:
        raise ApiError(409, "job_archived", "Job is archived; unarchive it first")
    if job.state != JobState.EXPANDED:
        raise ApiError(
            409,
            "job_not_reexpandable",
            f"Job is {job.state.value}, not expanded",
            {"state": job.state.value},
        )
    try:
        claimed = watch.claim_run(job.id)
    except watch.MarkerUnavailable:
        raise ApiError(503, "queue_unavailable", "The queue is unavailable; try again shortly") from None
    if not claimed:
        raise ApiError(409, "reexpand_running", "This job is already being checked")
    previous = (job.last_expanded_at, job.next_expand_at)
    now = datetime.now(timezone.utc)
    watch.mark_started(job, now)
    db.commit()
    try:
        expand_job.delay(str(job.id), reexpand=True)
    except Exception as exc:
        job.last_expanded_at, job.next_expand_at = previous
        db.commit()
        watch.release_run(job.id)
        logger.warning("reexpand_job: %s not enqueued: %s", job.id, type(exc).__name__)
        raise ApiError(503, "queue_unavailable", "The queue is unavailable; try again shortly") from None
    return _job_answer(db, job, owner_email, owner_username)


# Recorded on each not-found track an admin's "retry failed" puts back (raw worker-side text,
# untranslated like every attempt note).
MANUAL_OVERRIDE_NOTE = "Not found before; an admin queued it for one more attempt"


@router.post("/{job_id}/retry-failed")
def retry_failed_tracks(
    job_id: uuid.UUID,
    include_not_found: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """"Retry failed": every `waiting` track of the job is due now, by single retry's rules
    (routers/tracks.py's retry_track), applied per track: the breaker still holds them, and a
    non-admin's retry-now works once per ladder step (v56, A8), so a track already retried in
    its step is left to its slot (`cooldown` counts those). Its owner's, or an admin's on any
    job; anyone else's is a 404; an archived or cancelled job is a 409, as for one track.

    `include_not_found` (admin only, 403 otherwise): every `lookup_failed` track is put back
    `queued` for one more attempt, an explicit override of LookupError's terminal rule,
    recorded in its attempt history as `manual_override`."""
    job, owner_email, owner_username = _get_job_or_404(db, job_id, user)
    if include_not_found and not user.is_admin:
        raise ApiError(403, "admin_required", "Admin access required")
    # The job's row lock first, before the bulk UPDATEs of its tracks (cancel_job's order, so
    # the two serialize instead of deadlocking); a cancel committing meanwhile is seen.
    db.refresh(job, with_for_update=True)
    if job.archived_at is not None:
        raise ApiError(409, "job_archived", "Job is archived; unarchive it first")
    if job.state == JobState.CANCELLED:
        raise ApiError(409, "job_cancelled", "Job is cancelled; submit the link again")

    now = datetime.now(timezone.utc)
    waiting = (Track.job_id == job.id, Track.state == TrackState.WAITING)
    waiting_n = db.query(func.count(Track.id)).filter(*waiting).scalar()
    retry_now = update(Track).where(*waiting)
    if user.is_admin:
        retry_now = retry_now.values(scheduled_at=now)
    else:
        retry_now = retry_now.where(Track.retry_now_step.is_distinct_from(Track.attempt_count)).values(
            scheduled_at=now, retry_now_step=Track.attempt_count
        )
    retried = db.execute(
        retry_now.returning(Track.id, Track.song_json, Track.attempt_count).execution_options(
            synchronize_session=False
        )
    ).all()
    overridden = []
    if include_not_found:
        overridden = db.execute(
            update(Track)
            .where(Track.job_id == job.id, Track.state == TrackState.LOOKUP_FAILED)
            .values(state=TrackState.QUEUED, scheduled_at=None)
            .returning(Track.id, Track.song_json, Track.attempt_count)
            .execution_options(synchronize_session=False)
        ).all()
        for track_id, _song_json, _attempt_count in overridden:
            attempts.record_attempt(
                db,
                track_id,
                now,
                now,
                TrackAttemptOutcome.MANUAL_OVERRIDE,
                warning_message=MANUAL_OVERRIDE_NOTE,
            )
    db.commit()

    for track_id, song_json, attempt_count in retried:
        events.publish_track_event(
            job.user_id,
            track_id,
            job.id,
            TrackState.WAITING.value,
            scheduled_at=now,
            attempt_count=attempt_count,
            **track_song_meta(song_json),
        )
    for track_id, song_json, attempt_count in overridden:
        events.publish_track_event(
            job.user_id,
            track_id,
            job.id,
            TrackState.QUEUED.value,
            attempt_count=attempt_count,
            **track_song_meta(song_json),
        )
    job_status.publish_change(db, job.id)
    # Sent as beat sends a due track. One the broker refuses stays `queued`, and beat's stale
    # reclaim puts it back in the ladder.
    for track_id, _song_json, _attempt_count in overridden:
        try:
            download_track.delay(str(track_id))
        except Exception as exc:
            logger.warning("retry_failed_tracks: track %s not enqueued: %s", track_id, type(exc).__name__)
            break

    worker_state = retry.get_worker_state(db)
    db.commit()
    return {
        "job": _job_answer(db, job, owner_email, owner_username),
        "retried": len(retried),
        "cooldown": waiting_n - len(retried),
        "overridden": len(overridden),
        "breaker_held": retry.breaker_active(worker_state, now),
    }
