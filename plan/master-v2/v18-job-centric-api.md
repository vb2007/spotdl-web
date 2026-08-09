# v18 — Job-Centric API

Branch: `dev-job-centric-api` → PR into `main`

## Scope

The API the v20 UI needs: paginated, filterable, sortable, searchable job and track endpoints, with
the job rollup status computed server-side in a single aggregate query. This is where the "3,000
tracks in one flat unpaginated list" problem is actually solved; v20 only renders the result.

Everything here is written against v17's owner-scoped queries from the start. Retrofitting an
ownership filter onto a search endpoint afterwards is precisely how a data-separation bug ships.

## Job rollup status (the model from the master plan)

Two independent derived axes, never a single stored flag:

**Lifecycle** — `expanding` (job.state) → `failed` (expansion errored, zero tracks) → `cancelled`
(job.state) → `active` (≥1 track `pending`/`queued`/`downloading`) → `waiting` (no active, ≥1
`waiting`) → `settled` (all tracks terminal).

**Outcome** (only meaningful when `settled`) — `complete` (all `completed`/`skipped_duplicate`) vs
`partial` (≥1 `lookup_failed`/`cancelled`).

A 10-track album with 1 `LookupError` is `settled · partial`, never "failed". `settled · partial`
is a first-class filter value — *finished jobs that didn't get everything* is the one list actually
worth acting on, and it's impossible to produce today.

Derive both from the per-state counts in SQL. Do not add a stored status column: it would need
updating from every task and every endpoint that touches a track state, and would be wrong the
moment one path forgot.

## Killing the N+1 properly

v15 collapses `track_counts` into one grouped query as a narrow fix. v18 goes further: the job list
query returns jobs **joined against a grouped per-state count subquery**, so one query produces
rows, counts, and derived status together. Ordering/filtering on rollup status happens in SQL
against that subquery — sorting by "most stuck first" cannot be done in the application layer once
results are paginated, since the page is chosen before the sort would run.

## Endpoints

```
GET /api/jobs
  ?scope=job|track            (default job — the toggle from the master plan)
  &q=<free text>
  &status=<lifecycle or settled:partial>   (repeatable)
  &source_type=track|album|playlist|artist|search
  &include_archived=false     (default false)
  &sort=created_at|title|status|track_count|next_retry
  &dir=asc|desc
  &limit=50&cursor=<opaque>
  &all_users=false            (admin only; ignored for non-admins, never trusted from the client)
→ { items: [...], next_cursor, total_estimate, counts_by_status }

GET /api/jobs/{id}/tracks
  ?q= &state=<repeatable> &sort= &dir= &limit= &cursor=
→ { items: [...], next_cursor, counts_by_state }

GET /api/tracks        (scope=track searches: tracks across all the caller's jobs)
  same filter/sort/paging params, plus the job each track belongs to
→ { items: [...], next_cursor }
```

`GET /api/tracks`'s current "every track, unpaginated" behavior is **removed**, not deprecated —
it's the specific thing making the UI unusable at scale. v20 lands in the same roadmap, so there's
no window where a shipped frontend depends on the old shape.

## Design notes

- **Cursor pagination, not offset.** Rows are inserted and change state constantly while a user
  pages; offset paging silently skips and duplicates rows under concurrent writes. Cursor on
  `(sort_key, id)` is stable. `total_estimate` is explicitly an estimate — an exact count of a
  filtered search over the full history is a second expensive query for a number nobody acts on.
- **Search** matches track title/artist/album out of the existing `song_json` JSONB and the job's
  `source_url`. Start with case-insensitive substring matching plus a GIN index on the extracted
  text; only reach for Postgres full-text search if real use shows it's needed. Two or three users
  searching a few hundred thousand rows do not need `tsvector` ranking, and the operational cost of
  a materialized search column is real.
- **`scope=track`** returns tracks with their parent job embedded, so v20 can auto-expand the
  matching jobs and show only matching tracks without a second round trip per job.
- **Archived** rows are excluded by default everywhere; `include_archived=true` is the explicit
  opt-in (`archived_at` exists from v16, the lifecycle around it is v19's).
- Reuse `serializers.track_to_dict` unchanged — it's a deliberate projection and its shape is
  already correct. Add `job_to_dict`'s rollup fields rather than rewriting it.

## Done when

- Every parameter above works and composes: search + status filter + sort + pagination together
  return correct, stable results — tested as combinations, not one parameter at a time.
- **Query count is constant** with respect to result size: asserted with a SQLAlchemy
  event-listener counter, not inferred from response time. A 50-job page must not issue 51 queries.
- A **real ~3,000-track job** seeded in the real Postgres instance: first page of jobs, first page
  of that job's tracks, and a `scope=track` search across it all return in a reasonable time with
  correct data. Verified against real data volume, not a 10-row fixture.
- Rollup status correctness proven per branch with explicitly constructed jobs: all-completed →
  `settled·complete`; 9 completed + 1 `lookup_failed` → `settled·partial`; 1 downloading + 9
  completed → `active`; all-waiting → `waiting`; zero tracks + `job.state=failed` → `failed`.
- Cursor paging returns every row exactly once across pages **while rows are concurrently changing
  state** — the specific failure offset paging has, so it must be tested under concurrent writes,
  not on a static table.
- Owner scoping still holds on every new endpoint and every new parameter (re-run v17's
  cross-user checks against these endpoints — new query paths mean new chances to drop the filter).
- `all_users=true` from a non-admin session is ignored, returning only their own rows.
- `graphify update .`
