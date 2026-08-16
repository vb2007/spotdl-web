"""Paginated/filtered/sorted/searchable track listing shared by `GET /api/tracks` and
`GET /api/jobs?scope=track` (v18) -- identical query, identical response shape, so
either URL works for the frontend's job/track scope toggle. See
`plan/master-v2/v18-job-centric-api.md`.

`status=` here filters by the *parent job's* rollup status (v18's `rollup` module);
`state=` filters by the track's own state. They're independent axes and both accepted.
"""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Job, JobSourceType, Track, TrackState, User
from app.services import pagination, rollup, search
from app.services.serializers import track_to_dict

_SORT_FIELDS = {"created_at", "title", "state"}


class InvalidListParams(ValueError):
    pass


def list_tracks(
    db: Session,
    *,
    user_id,
    is_admin: bool,
    all_users: bool,
    q: str | None,
    job_status_tokens: list[str],
    track_states: list[str],
    source_type: JobSourceType | None,
    include_archived: bool,
    sort: str,
    dir: str,
    limit: int,
    cursor: str | None,
    job_id=None,
) -> dict:
    if sort not in _SORT_FIELDS:
        raise InvalidListParams(f"invalid sort: {sort!r}, expected one of {sorted(_SORT_FIELDS)}")
    if dir not in ("asc", "desc"):
        raise InvalidListParams(f"invalid dir: {dir!r}, expected 'asc' or 'desc'")
    bad_status = set(job_status_tokens) - rollup.VALID_STATUS_TOKENS
    if bad_status:
        raise InvalidListParams(f"invalid status token(s): {sorted(bad_status)}")
    valid_states = {s.value for s in TrackState}
    bad_states = set(track_states) - valid_states
    if bad_states:
        raise InvalidListParams(f"invalid state token(s): {sorted(bad_states)}")

    limit = pagination.clamp_limit(limit)
    descending = dir == "desc"

    stmt = (
        select(
            Track,
            Job.id.label("job_id"),
            Job.source_url.label("job_source_url"),
            Job.source_type.label("job_source_type"),
            User.email.label("owner_email"),
            User.username.label("owner_username"),
            rollup.job_title_expr(Job.source_url, Job.id).label("job_title"),
        )
        .join(Job, Track.job_id == Job.id)
        .join(User, Job.user_id == User.id)
    )
    if job_id is not None:
        stmt = stmt.where(Track.job_id == job_id)
    # all_users is honored only for an admin session, same threat model as job listing.
    if not (all_users and is_admin):
        stmt = stmt.where(Job.user_id == user_id)
    if not include_archived:
        stmt = stmt.where(Job.archived_at.is_(None))
    if source_type is not None:
        stmt = stmt.where(Job.source_type == source_type)
    if track_states:
        stmt = stmt.where(Track.state.in_([TrackState(s) for s in track_states]))
    if q:
        stmt = stmt.where(or_(search.track_matches(q), Job.source_url.ilike(f"%{q}%")))

    if job_status_tokens:
        owner_jobs = select(Job.id, Job.state)
        if not (all_users and is_admin):
            owner_jobs = owner_jobs.where(Job.user_id == user_id)
        agg = rollup.aggregate_jobs(owner_jobs.subquery())
        lifecycle_expr = rollup.lifecycle_case(agg.c.state, agg.c.active_n, agg.c.waiting_n)
        outcome_raw = rollup.outcome_case(agg.c.partial_n)
        status_cond = rollup.status_where(lifecycle_expr, outcome_raw, set(job_status_tokens))
        stmt = stmt.join(agg, agg.c.id == Track.job_id)
        if status_cond is not None:
            stmt = stmt.where(status_cond)

    stmt = pagination.apply_cursor(stmt, _sort_key(sort), Track.id, descending=descending, cursor=cursor)
    stmt = stmt.limit(limit)
    rows = db.execute(stmt).all()

    items = []
    for row in rows:
        item = track_to_dict(row.Track)
        item["job"] = {
            "id": str(row.job_id),
            "source_url": row.job_source_url,
            "source_type": row.job_source_type.value,
            "owner_email": row.owner_email,
            "owner_username": row.owner_username,
            "title": row.job_title,
        }
        items.append(item)

    next_cursor = None
    if len(rows) == limit:
        last_track = rows[-1].Track
        next_cursor = pagination.cursor_for_row(_sort_value(last_track, sort), last_track.id)

    return {"items": items, "next_cursor": next_cursor}


def _sort_key(sort: str) -> pagination.SortKey:
    if sort == "created_at":
        return pagination.SortKey(Track.created_at)
    if sort == "title":
        return pagination.SortKey(Track.song_json["name"].astext)
    return pagination.SortKey(Track.state)


def _sort_value(track: Track, sort: str):
    if sort == "created_at":
        return track.created_at
    if sort == "title":
        return track.song_json.get("name")
    return track.state
