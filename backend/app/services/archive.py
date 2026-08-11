"""Soft-archive lifecycle for jobs (v19). See `plan/master-v2/v19-archive-retention.md`.

`archive_jobs`/`unarchive_jobs` are the only places `Job.archived_at` is ever set --
shared by the manual "clear log" endpoint and the hourly sweep task so there is exactly
one eligibility rule, not two that could drift apart. Both re-derive eligibility from the
real track states themselves rather than trusting the caller (job_ids passed in from a
stale UI list, or a sweep racing a track that just became active).

Eligible lifecycles are exactly `settled`/`failed`/`cancelled` -- the same vocabulary as
`services.rollup`, computed the same way (`lifecycle_case` over `active_n`/`waiting_n`),
so a job can never be archived while it has a track in an active or *waiting* state. The
waiting exclusion is deliberate, not incidental: a `waiting` job is deliberately sitting in
the retry ladder and may not touch again for up to 24h (CLAUDE.md's retry-engine
invariants) -- archiving on `job.created_at` age alone would hide exactly the long-running
work this app exists to do. That's why the age filter compares against the newest track's
`updated_at` (falling back to the job's own `updated_at` for a job with no tracks, e.g. a
zero-track `failed` expansion), never `job.created_at`.

Never touches `downloaded_tracks` -- that ledger is keyed on Spotify track id and is what
stops a re-download; archiving a job must have zero effect on it.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Job, Track
from app.services import rollup

_ARCHIVABLE_LIFECYCLES = ("settled", "failed", "cancelled")


def _eligible_job_ids(
    db: Session,
    user_id,
    job_ids: list[uuid.UUID] | None,
    older_than: timedelta | None,
) -> list[uuid.UUID]:
    base = select(Job.id, Job.state, Job.updated_at).where(
        Job.user_id == user_id, Job.archived_at.is_(None)
    )
    if job_ids is not None:
        base = base.where(Job.id.in_(job_ids))
    base_subq = base.subquery()

    agg_subq = (
        select(
            base_subq.c.id,
            base_subq.c.state,
            func.coalesce(rollup.active_count_expr(), 0).label("active_n"),
            func.coalesce(rollup.waiting_count_expr(), 0).label("waiting_n"),
            func.coalesce(func.max(Track.updated_at), base_subq.c.updated_at).label("last_activity"),
        )
        .select_from(base_subq)
        .outerjoin(Track, Track.job_id == base_subq.c.id)
        .group_by(base_subq.c.id, base_subq.c.state, base_subq.c.updated_at)
        .subquery()
    )
    lifecycle_expr = rollup.lifecycle_case(agg_subq.c.state, agg_subq.c.active_n, agg_subq.c.waiting_n)

    stmt = select(agg_subq.c.id).where(lifecycle_expr.in_(_ARCHIVABLE_LIFECYCLES))
    if older_than is not None:
        cutoff = datetime.now(timezone.utc) - older_than
        stmt = stmt.where(agg_subq.c.last_activity < cutoff)

    return [row.id for row in db.execute(stmt).all()]


def archive_jobs(
    db: Session,
    user_id,
    *,
    job_ids: list[uuid.UUID] | None = None,
    older_than: timedelta | None = None,
) -> list[Job]:
    """`job_ids=None, older_than=None` (the "clear log" case) archives every eligible job
    for this user regardless of age. `older_than` (the sweep case) additionally requires
    the job's last track activity to predate the cutoff. Always scoped to `user_id` --
    a foreign job id passed in `job_ids` simply never matches and is silently dropped,
    same as elsewhere in this app an id's existence is never confirmed to a non-owner."""
    ids = _eligible_job_ids(db, user_id, job_ids, older_than)
    if not ids:
        return []
    now = datetime.now(timezone.utc)
    jobs = db.query(Job).filter(Job.id.in_(ids)).all()
    for job in jobs:
        job.archived_at = now
    db.commit()
    return jobs


def unarchive_jobs(db: Session, user_id, job_ids: list[uuid.UUID]) -> list[Job]:
    jobs = (
        db.query(Job)
        .filter(Job.user_id == user_id, Job.id.in_(job_ids), Job.archived_at.is_not(None))
        .all()
    )
    for job in jobs:
        job.archived_at = None
    db.commit()
    return jobs
