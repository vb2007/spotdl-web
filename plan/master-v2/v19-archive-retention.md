# v19 — Archive & Retention

Branch: `dev-archive-retention` → PR into `main`

## Scope

Give the log a way to forget. Terminal jobs older than a per-user threshold drop out of the default
view; a "clear log" button does it on demand. Soft-archive only — nothing is ever deleted.

`jobs.archived_at` and `user_settings.retention_days` both exist from v16, and v18's endpoints
already honor `include_archived`. This version is purely the lifecycle and the controls.

## Why archive rather than delete

CLAUDE.md's v12 notes describe this app as one that "never deletes history" — that's load-bearing,
not incidental. The download history is the record of what was attempted and when, which is exactly
what you need when a track quietly never arrived. Bounding the *view* solves the usability problem;
bounding the *data* solves a problem this app doesn't have (a few users' text rows are not a
storage concern for years).

**`downloaded_tracks` is never touched by any of this.** It is the dedup ledger, keyed on Spotify
track id, and it is what stops a re-download. Archiving a job must not be able to cause the same
track to be fetched again — that would turn a UI convenience into extra rate-limit exposure, which
is the one thing this whole application is built to avoid.

## What is eligible

Only jobs whose lifecycle status (v18) is **`settled`**, **`failed`**, or **`cancelled`**, and
whose most recent track activity is older than the threshold. Explicitly never:

- a job with any track in `pending`/`queued`/`downloading` — it's live;
- a job with any track in `waiting` — it is *deliberately* sitting in a 24h ladder step and may not
  touch again for a day. Archiving on "age" alone would hide exactly the long-running work this app
  exists to do. Age is measured from the newest track `updated_at`, not from `job.created_at`, for
  this reason.

## Tasks

1. **`app/services/archive.py`**:
   - `archive_jobs(db, user_id, job_ids=None, older_than=None)` — the one place `archived_at` is
     set, used by both the manual button and the scheduled sweep. Re-asserts eligibility itself
     rather than trusting its caller.
   - `unarchive_jobs(db, user_id, job_ids)` — archiving is reversible, so the endpoint exists from
     the start rather than being a "later if needed".
2. **Endpoints** (owner-scoped, per v17):
   - `POST /api/jobs/archive` — body `{job_ids: [...]}` or `{all_settled: true}`. This is "clear
     log": it archives the caller's finished jobs only, never in-flight ones, never another user's.
   - `POST /api/jobs/unarchive` — body `{job_ids: [...]}`.
   - `GET /api/settings/retention` / `PATCH /api/settings/retention` — the **per-user** setting,
     available to every user (not the admin-only `/api/settings/output`). `retention_days = null`
     means never auto-archive, and that is the default.
3. **Scheduled sweep** — a new Celery Beat task (`archive_due_jobs`), hourly. Not every 30s: this is
   housekeeping, and it competes with `dispatch_due_tracks` for the same `worker-meta` process.
   Iterates users with a non-null `retention_days` and calls `archive_jobs` with their threshold.
   Registered in `beat_schedule` alongside `dispatch-due-tracks`.
4. **Events** — publish a job event on archive/unarchive so an open tab updates live rather than
   showing rows that no longer match the current filter until a reload.
5. `graphify update .`

## Done when

- "Clear log" archives only the caller's `settled`/`failed`/`cancelled` jobs. Verified with a mixed
  set: a live job, a `waiting` job mid-ladder, a settled job, and another user's settled job — only
  the caller's settled one is archived, confirmed by SQL.
- **A `waiting` job is never archived by the sweep**, even when its `job.created_at` is far older
  than the threshold — the specific mistake this design guards against, so it gets its own explicit
  test with a real 24h-ladder-shaped row.
- Archived jobs are absent from default queries and present with `include_archived=true`, and the
  **rows still exist in Postgres** — checked directly, not inferred from the API.
- Unarchive restores a job to the default view.
- **`downloaded_tracks` row count is identical before and after** an archive sweep, and
  re-submitting an archived job's URL still resolves as `skipped_duplicate` rather than
  re-downloading. This is the property that matters most in this version.
- `retention_days = null` (default) archives nothing, ever.
- A non-admin user can read and change their own retention setting, and cannot read or change
  another user's.
- The hourly sweep is registered and fires — confirmed from real `beat` container logs, not just
  from the config literal.
