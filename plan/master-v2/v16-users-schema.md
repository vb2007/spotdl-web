# v16 — Users & Ownership Schema

Branch: `dev-users-schema` → PR into `main`

## Scope

Every model and migration multi-user needs. **No behavior change** — nothing reads or writes the
new columns yet. This mirrors v1's successful v02 (schema-only) → v03 (wiring) split, which kept
both PRs reviewable on their own terms.

**Backward compatibility is explicitly not required** (locked v2 decision): the database holds only
POC test data. The migration may drop and recreate rather than contort itself into a
backfill-then-tighten dance, and a full `downgrade base` → `upgrade head` rebuild is an acceptable
deployment step for this version.

## Tables

### `users` (new)

- `id` (uuid, pk)
- `email` (text, unique, indexed) — matched case-insensitively against the `ALLOWED_EMAILS`
  allowlist, so store it normalized (lowercased, trimmed) at write time
- `is_admin` (bool, default false)
- `created_at`, `last_login_at` (timestamptz)

The env allowlist still decides *who may log in*; this table decides *what they own and may do*.
The two are deliberately separate — one is deployment config, the other is application state.

### `user_settings` (new)

Per-user preferences, get-or-create on first read — the same pattern
`app/services/app_settings.py` already established for the singleton `app_settings` row, reused
rather than reinvented.

- `user_id` (uuid, pk, fk → `users.id`)
- `retention_days` (int, nullable — `NULL` means "never auto-archive", the default)
- `created_at`, `updated_at` (timestamptz)

Kept separate from `users` rather than adding columns to it: `users` is identity/authorization and
is read on every authenticated request, while settings are read rarely and will keep growing as v19
and later versions add preferences.

### `jobs` (modified)

- `user_id` (uuid, fk → `users.id`, **not null**, indexed) — ownership lives on the job. Tracks
  inherit it through `job_id` rather than carrying a duplicate `user_id`: a track can never belong
  to a different user than its job, and a denormalized copy is a second source of truth that can
  drift. The composite index below is what keeps the join cheap.
- `archived_at` (timestamptz, nullable, indexed) — the retention lifecycle field. Added here rather
  than in v19 so v19 is purely behavior; no schema churn mid-roadmap.
- New composite index on `(user_id, created_at DESC)` — the exact shape of v18's default job-list
  query.
- New partial index on `(user_id, created_at DESC) WHERE archived_at IS NULL` — the default
  (non-archived) list is the hot path and deserves its own index. Write this one by hand:
  autogenerate does not emit partial indexes, per v02's own gotcha.

### `sessions` (modified)

- `user_id` (uuid, fk → `users.id`, not null, indexed) replaces the bare `email` column. The model
  class stays `UserSession` (v02's naming gotcha: `sqlalchemy.orm.Session` is dep-injected
  everywhere, so a model named `Session` would force an import alias at every call site).

### `tracks` (unchanged)

Deliberately. Ownership resolves through `job_id`.

## Tasks

1. Write the models under `backend/app/models/`, exporting them from `models/__init__.py` alongside
   the existing ones.
2. One Alembic revision creating `users`/`user_settings`, altering `jobs`/`sessions`, and adding
   both indexes. Since existing rows have no owner and compatibility isn't required, the migration
   drops existing `jobs`/`tracks`/`sessions` rows rather than inventing an owner for them — stated
   loudly in the migration's docstring so nobody runs it on real data by accident.
3. `downgrade()` must fully reverse it, including an explicit `DROP TYPE` for any native enum this
   revision creates (v02's gotcha — autogenerate never emits these).
4. Timestamps use bare `Mapped[datetime]` so `Base.type_annotation_map` gives them `timestamptz`;
   uuids likewise (v02's mapping).
5. `graphify update .`

## Done when

- `alembic upgrade head` → `downgrade -1` → `upgrade head` round-trips cleanly against the real
  shared Postgres instance, verified by inspecting `\d jobs` / `\d users` / `\d sessions` after
  each step — not just by the commands exiting 0.
- Both new indexes exist with the expected definitions, the partial one confirmed to carry its
  `WHERE archived_at IS NULL` clause (`\d jobs` output pasted into the PR, per v02's precedent).
- Every field v17–v21's plans reference exists here — no later version should need an ad-hoc
  migration for something this document should have anticipated.
- All four backend processes (`api`, `worker-dl`, `worker-meta`, `beat`) start with zero import
  errors after the new models land.
- Existing test suite still passes unchanged: no behavior was altered, so any test that breaks
  indicates this version did more than it should have.
