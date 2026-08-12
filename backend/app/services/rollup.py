"""Job rollup status (v18) -- two independent derived axes, never a stored flag. See
`plan/master-v2/v18-job-centric-api.md` and `00-master-plan.md`'s "Job rollup status"
section for the full spec this implements.

Two implementations of the exact same branching intentionally coexist:
- `derive_rollup` -- pure Python over an already-fetched `{state: count}` dict, used by
  the single-job `job_to_dict` call sites (`create_job`, `get_job`, `cancel_job`,
  `set_job_priority`, `bump_job`) that already have `counts` in hand from
  `serializers.track_counts` and would gain nothing from a second query.
- `lifecycle_case`/`outcome_case`/`rank_case` -- SQL `CASE` expressions over a grouped
  aggregate, used by the paginated job listing so status filtering/sorting happens in
  the database before `LIMIT`, not in Python after a page is already chosen.

Both branch on the exact same `_ACTIVE_STATES`/`_WAITING_STATES`/`_PARTIAL_STATES`
groupings so they can't silently drift apart; `tests/test_rollup.py` asserts both against
the same fixture table.

Also home to the job "title" derivation (not a stored column -- there is nowhere on
`Job` that carries one): the first-created track's playlist/album name if it has one,
else its song name, else the job's own `source_url` for a job with no tracks yet
(`expanding`, or `failed` before ever creating one).
"""

from dataclasses import dataclass

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import Job, JobState, Track, TrackState

_ACTIVE_STATES = (TrackState.PENDING, TrackState.QUEUED, TrackState.DOWNLOADING)
_WAITING_STATES = (TrackState.WAITING,)
_PARTIAL_STATES = (TrackState.LOOKUP_FAILED, TrackState.CANCELLED)

# The combined (lifecycle, outcome) vocabulary and its sort rank for `sort=status`:
# still in flight or stuck-in-the-retry-ladder first (needs the least action but the
# most attention), then done-but-incomplete, then cleanly done, then the two dead ends
# last since neither needs anything further from anyone.
STATUS_ORDER: list[tuple[str, str | None]] = [
    ("expanding", None),
    ("active", None),
    ("waiting", None),
    ("settled", "partial"),
    ("settled", "complete"),
    ("cancelled", None),
    ("failed", None),
]
STATUS_RANK: dict[tuple[str, str | None], int] = {key: i for i, key in enumerate(STATUS_ORDER)}
VALID_LIFECYCLES = {lifecycle for lifecycle, _ in STATUS_ORDER}


def status_key(lifecycle: str, outcome: str | None) -> str:
    """The wire/filter form: `settled:partial`, or the bare lifecycle name otherwise."""
    return f"{lifecycle}:{outcome}" if outcome else lifecycle


def parse_status_key(value: str) -> tuple[str, str | None]:
    lifecycle, _, outcome = value.partition(":")
    return lifecycle, (outcome or None)


# Every token `?status=` accepts: the bare lifecycle names (a bare "settled" matches
# either outcome) plus the two outcome-qualified compound forms.
VALID_STATUS_TOKENS = VALID_LIFECYCLES | {status_key(*key) for key in STATUS_ORDER}


@dataclass(frozen=True, slots=True)
class Rollup:
    lifecycle: str
    outcome: str | None

    @property
    def key(self) -> str:
        return status_key(self.lifecycle, self.outcome)

    @property
    def rank(self) -> int:
        return STATUS_RANK[(self.lifecycle, self.outcome)]


def derive_rollup(job_state: JobState, counts: dict[str, int]) -> Rollup:
    if job_state == JobState.EXPANDING:
        return Rollup("expanding", None)
    if job_state == JobState.FAILED:
        return Rollup("failed", None)
    if job_state == JobState.CANCELLED:
        return Rollup("cancelled", None)
    if sum(counts.get(s.value, 0) for s in _ACTIVE_STATES) > 0:
        return Rollup("active", None)
    if sum(counts.get(s.value, 0) for s in _WAITING_STATES) > 0:
        return Rollup("waiting", None)
    partial = sum(counts.get(s.value, 0) for s in _PARTIAL_STATES)
    return Rollup("settled", "partial" if partial > 0 else "complete")


def matches_status_filter(rollup: Rollup, requested: set[str]) -> bool:
    """A bare `settled` filter token matches either outcome; `settled:partial` matches
    only that one -- mirrors `status_where`'s SQL below."""
    if rollup.key in requested:
        return True
    return rollup.outcome is not None and rollup.lifecycle in requested


def active_count_expr() -> ColumnElement:
    return func.sum(case((Track.state.in_(_ACTIVE_STATES), 1), else_=0))


def waiting_count_expr() -> ColumnElement:
    return func.sum(case((Track.state.in_(_WAITING_STATES), 1), else_=0))


def partial_count_expr() -> ColumnElement:
    return func.sum(case((Track.state.in_(_PARTIAL_STATES), 1), else_=0))


def next_retry_expr() -> ColumnElement:
    """`NULL` for a job with no `waiting` track -- fed into `pagination.SortKey(...,
    nullable=True)` for `sort=next_retry`."""
    return func.min(case((Track.state == TrackState.WAITING, Track.scheduled_at), else_=None))


def aggregate_jobs(base_jobs_subq):
    """`base_jobs_subq` is any already-built subquery over `Job` exposing at least `.id`
    and `.state` columns (typically pre-filtered by owner/search/source_type/archived --
    filtering *before* aggregating so a big job's track count never inflates the cost of
    a query that was never going to include it). Returns one row per input job: every
    original column plus `active_n`/`waiting_n`/`partial_n`/`total_n`/`next_retry_at`,
    ready for `lifecycle_case`/`outcome_case_for_display`/`rank_case`/`job_title_expr`.

    Shared by the job listing (`services.job_listing`) and, filtered down to a caller's
    own visible jobs, the track listing's `status=` filter (`services.track_listing`) --
    written once here so the two can't compute this aggregate differently."""
    return (
        select(
            *base_jobs_subq.c,
            func.coalesce(active_count_expr(), 0).label("active_n"),
            func.coalesce(waiting_count_expr(), 0).label("waiting_n"),
            func.coalesce(partial_count_expr(), 0).label("partial_n"),
            func.coalesce(func.count(Track.id), 0).label("total_n"),
            next_retry_expr().label("next_retry_at"),
        )
        .select_from(base_jobs_subq)
        .outerjoin(Track, Track.job_id == base_jobs_subq.c.id)
        .group_by(*base_jobs_subq.c)
        .subquery()
    )


def lifecycle_case(job_state_col: ColumnElement, active_n: ColumnElement, waiting_n: ColumnElement) -> ColumnElement:
    return case(
        (job_state_col == JobState.EXPANDING, "expanding"),
        (job_state_col == JobState.FAILED, "failed"),
        (job_state_col == JobState.CANCELLED, "cancelled"),
        (active_n > 0, "active"),
        (waiting_n > 0, "waiting"),
        else_="settled",
    )


def outcome_case(partial_n: ColumnElement) -> ColumnElement:
    """Only meaningful where `lifecycle_case(...) == "settled"` -- evaluates to
    "complete"/"partial" unconditionally otherwise, so callers displaying it (as opposed
    to filtering/ranking with it, which already ANDs in the lifecycle check) must gate on
    lifecycle themselves. See `outcome_case_for_display`."""
    return case((partial_n > 0, "partial"), else_="complete")


def outcome_case_for_display(job_state_col: ColumnElement, active_n: ColumnElement, waiting_n: ColumnElement, partial_n: ColumnElement) -> ColumnElement:
    return case(
        (
            case(
                (job_state_col == JobState.EXPANDING, False),
                (job_state_col == JobState.FAILED, False),
                (job_state_col == JobState.CANCELLED, False),
                (active_n > 0, False),
                (waiting_n > 0, False),
                else_=True,
            ),
            outcome_case(partial_n),
        ),
        else_=None,
    )


def rank_case(job_state_col: ColumnElement, active_n: ColumnElement, waiting_n: ColumnElement, partial_n: ColumnElement) -> ColumnElement:
    return case(
        (job_state_col == JobState.EXPANDING, STATUS_RANK[("expanding", None)]),
        (job_state_col == JobState.FAILED, STATUS_RANK[("failed", None)]),
        (job_state_col == JobState.CANCELLED, STATUS_RANK[("cancelled", None)]),
        (active_n > 0, STATUS_RANK[("active", None)]),
        (waiting_n > 0, STATUS_RANK[("waiting", None)]),
        (partial_n > 0, STATUS_RANK[("settled", "partial")]),
        else_=STATUS_RANK[("settled", "complete")],
    )


def status_where(lifecycle_expr: ColumnElement, outcome_expr: ColumnElement, requested: set[str]):
    """`outcome_expr` here is the raw (unconditional) `outcome_case`, not the display
    variant -- each generated condition ANDs in its own lifecycle check, so it's never
    evaluated for a non-settled row regardless of what it would otherwise return."""
    conditions = []
    for token in requested:
        lifecycle, outcome = parse_status_key(token)
        if outcome is None:
            conditions.append(lifecycle_expr == lifecycle)
        else:
            conditions.append(and_(lifecycle_expr == lifecycle, outcome_expr == outcome))
    return or_(*conditions) if conditions else None


def derive_job_title(source_url: str, first_track_song_json: dict | None) -> str:
    if first_track_song_json is None:
        return source_url
    list_name = first_track_song_json.get("list_name")
    if list_name:
        return list_name
    name = first_track_song_json.get("name")
    if name:
        return name
    return source_url


def job_title(db: Session, job: Job) -> str:
    """Single-job counterpart of `job_title_expr` -- one small indexed query, used by the
    five single-job `job_to_dict` call sites rather than the paginated listing's SQL
    expression, exactly the same trade `serializers.track_counts` already makes for
    those same call sites."""
    track = (
        db.query(Track).filter(Track.job_id == job.id).order_by(Track.created_at.asc()).first()
    )
    return derive_job_title(job.source_url, track.song_json if track is not None else None)


def job_title_expr(job_source_url_col: ColumnElement, job_id_col: ColumnElement):
    """Correlated scalar subqueries, not a LATERAL join -- portable across the real
    Postgres engine and the test suite's SQLite one, and cheap at listing scale: at most
    one extra tiny indexed (`job_id`, `created_at`) lookup per *returned job row*, not
    per track, so it stays O(page size) regardless of how large any single job is.

    Deliberately no explicit `.correlate(...)`: `job_id_col`/`job_source_url_col` may be
    plain `Job` columns or columns of an aggregated subquery built from `Job`, depending
    on the caller, and SQLAlchemy's default auto-correlation already finds whichever
    enclosing FROM actually provides them -- pinning it to a specific one here would
    silently turn into an uncorrelated subquery the moment a caller's outer query FROMs
    the aggregate instead of `Job` directly (caught by test_rollup.py's fixture check).

    `.correlate_except(Track)` *is* needed, though: `track_listing.list_tracks` (v20)
    selects the raw `Track` entity directly in its own outer FROM to embed each track's
    parent job title, and auto-correlation matches by FROM-clause identity, not by
    whether a WHERE clause actually reaches into the outer row -- without this, it saw
    the same `Track` table in both the outer statement and this subquery and correlated
    the subquery's own `Track` away entirely, leaving it with zero FROM clauses
    (`InvalidRequestError: ... returned no FROM clauses due to auto-correlation`, caught
    by this module's own test running against the real query, not a hypothetical)."""
    first_list_name = (
        select(Track.song_json["list_name"].astext)
        .where(Track.job_id == job_id_col)
        .order_by(Track.created_at.asc())
        .limit(1)
        .correlate_except(Track)
        .scalar_subquery()
    )
    first_name = (
        select(Track.song_json["name"].astext)
        .where(Track.job_id == job_id_col)
        .order_by(Track.created_at.asc())
        .limit(1)
        .correlate_except(Track)
        .scalar_subquery()
    )
    return func.coalesce(first_list_name, first_name, job_source_url_col)
