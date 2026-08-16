"""Paginated/filtered/sorted/searchable job listing (v18) -- `GET /api/jobs` (scope=job).
See `plan/master-v2/v18-job-centric-api.md`.

One statement produces rows, per-state counts, and derived rollup status together (the
plan's "kill the N+1 properly"): jobs are filtered *before* being aggregated against
`tracks`, so a search/source_type/archived filter that excludes a 3,000-track job never
pays to aggregate it. Filtering/sorting by rollup status happens on that aggregate, in
SQL, before `LIMIT` -- computing it in Python after paginating would sort/filter the
wrong (already-truncated) set.

Three statements total per call, independent of how many rows come back:
1. `counts_by_status` -- grouped over the *pre-status-filter* aggregate, so tab counts
   for every status stay visible regardless of which one is currently selected.
2. `total_estimate` -- a capped count over the fully filtered set.
3. the actual page.

Plus one more (`serializers.track_counts_by_job`) to get the *full* per-state count
breakdown for exactly the page's jobs, reusing `job_to_dict` unchanged for the response
shape instead of duplicating it.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Job, JobSourceType, User
from app.services import pagination, rollup, search
from app.services.serializers import job_to_dict, track_counts_by_job

_SORT_FIELDS = {"created_at", "title", "status", "track_count", "next_retry"}


class InvalidListParams(ValueError):
    pass


def list_jobs(
    db: Session,
    *,
    user_id,
    is_admin: bool,
    all_users: bool,
    q: str | None,
    status_tokens: list[str],
    source_type: JobSourceType | None,
    include_archived: bool,
    sort: str,
    dir: str,
    limit: int,
    cursor: str | None,
) -> dict:
    if sort not in _SORT_FIELDS:
        raise InvalidListParams(f"invalid sort: {sort!r}, expected one of {sorted(_SORT_FIELDS)}")
    if dir not in ("asc", "desc"):
        raise InvalidListParams(f"invalid dir: {dir!r}, expected 'asc' or 'desc'")
    bad_tokens = set(status_tokens) - rollup.VALID_STATUS_TOKENS
    if bad_tokens:
        raise InvalidListParams(f"invalid status token(s): {sorted(bad_tokens)}")

    limit = pagination.clamp_limit(limit)
    descending = dir == "desc"

    base = select(
        Job.id,
        Job.user_id,
        Job.source_url,
        Job.source_type,
        Job.state,
        Job.priority,
        Job.error,
        Job.created_at,
        Job.archived_at,
        User.email.label("owner_email"),
        User.username.label("owner_username"),
    ).join(User, Job.user_id == User.id)

    # all_users is honored only for an admin session -- a non-admin passing it is
    # silently treated exactly as if they hadn't (v17's threat model).
    if not (all_users and is_admin):
        base = base.where(Job.user_id == user_id)
    if not include_archived:
        base = base.where(Job.archived_at.is_(None))
    if source_type is not None:
        base = base.where(Job.source_type == source_type)
    if q:
        base = base.where(search.job_matches(q))

    base_subq = base.subquery()
    agg = rollup.aggregate_jobs(base_subq)

    # counts_by_status: grouped over `agg` directly, before the status filter below is
    # applied -- fresh expression objects, since the same CASE built for one statement
    # can't be reused unmodified in a second, independent one.
    count_lifecycle = rollup.lifecycle_case(agg.c.state, agg.c.active_n, agg.c.waiting_n)
    count_outcome = rollup.outcome_case_for_display(agg.c.state, agg.c.active_n, agg.c.waiting_n, agg.c.partial_n)
    counts_rows = db.execute(
        select(count_lifecycle.label("lifecycle"), count_outcome.label("outcome"), func.count().label("n"))
        .select_from(agg)
        .group_by(count_lifecycle, count_outcome)
    ).all()
    counts_by_status = {rollup.status_key(row.lifecycle, row.outcome): row.n for row in counts_rows}

    lifecycle_expr = rollup.lifecycle_case(agg.c.state, agg.c.active_n, agg.c.waiting_n)
    outcome_raw = rollup.outcome_case(agg.c.partial_n)
    outcome_disp = rollup.outcome_case_for_display(agg.c.state, agg.c.active_n, agg.c.waiting_n, agg.c.partial_n)
    rank_expr = rollup.rank_case(agg.c.state, agg.c.active_n, agg.c.waiting_n, agg.c.partial_n)
    title_expr = rollup.job_title_expr(agg.c.source_url, agg.c.id)

    filtered = select(
        *agg.c,
        lifecycle_expr.label("lifecycle"),
        outcome_disp.label("outcome"),
        rank_expr.label("rank"),
        title_expr.label("title"),
    )
    if status_tokens:
        status_cond = rollup.status_where(lifecycle_expr, outcome_raw, set(status_tokens))
        if status_cond is not None:
            filtered = filtered.where(status_cond)
    filtered_subq = filtered.subquery()

    # total_estimate: a second query, but O(1) regardless of page size -- capped so a
    # search over a huge filtered history never pays for an exact count nobody acts on.
    capped_ids = select(filtered_subq.c.id).limit(pagination.CAP + 1).subquery()
    raw_total = db.execute(select(func.count()).select_from(capped_ids)).scalar_one()
    total_estimate = min(raw_total, pagination.CAP)

    sort_key = _sort_key(sort, filtered_subq)
    page_stmt = pagination.apply_cursor(
        select(filtered_subq), sort_key, filtered_subq.c.id, descending=descending, cursor=cursor
    ).limit(limit)
    rows = db.execute(page_stmt).all()

    counts_map = track_counts_by_job(db, [row.id for row in rows])
    items = [
        job_to_dict(row, counts_map.get(row.id, {}), row.owner_email, row.owner_username, row.title)
        for row in rows
    ]

    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = pagination.cursor_for_row(
            _sort_value(last, sort), last.id, nullable=(sort == "next_retry")
        )

    return {
        "items": items,
        "next_cursor": next_cursor,
        "total_estimate": total_estimate,
        "counts_by_status": counts_by_status,
    }


def _sort_key(sort: str, subq) -> pagination.SortKey:
    if sort == "created_at":
        return pagination.SortKey(subq.c.created_at)
    if sort == "title":
        return pagination.SortKey(subq.c.title)
    if sort == "status":
        return pagination.SortKey(subq.c.rank)
    if sort == "track_count":
        return pagination.SortKey(subq.c.total_n)
    return pagination.SortKey(subq.c.next_retry_at, nullable=True)


def _sort_value(row, sort: str):
    return {
        "created_at": row.created_at,
        "title": row.title,
        "status": row.rank,
        "track_count": row.total_n,
        "next_retry": row.next_retry_at,
    }[sort]
