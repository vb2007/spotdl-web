# v02 — Database Schema

Branch: `dev-db-schema` → PR into `main`

## Scope

All SQLAlchemy models and one Alembic migration that creates the full schema. No routers, no
Celery tasks consume these tables yet — this version is purely the data model, reviewable on its
own.

## Tables

### `sessions`
Our own session store (see v03) — deliberately separate from the upstream `VB-AUTH` token.
- `id` (uuid, pk)
- `email` (text) — the allowlisted user this session belongs to
- `token` (text, unique, indexed) — value stored in our cookie
- `created_at`, `last_seen_at` (timestamptz)

### `jobs`
One row per submitted URL (album/playlist/artist/track).
- `id` (uuid, pk)
- `source_url` (text)
- `source_type` (enum: `track`, `album`, `playlist`, `artist`, `search`)
- `state` (enum: `expanding`, `expanded`, `failed`)
- `priority` (int, default 0) — used by v11, present now so the column doesn't need a later
  migration
- `created_at`, `updated_at` (timestamptz)
- `error` (text, nullable)

### `tracks`
One row per individual song discovered while expanding a job. This is the unit the retry engine
and worker operate on.
- `id` (uuid, pk)
- `job_id` (fk → `jobs.id`, indexed)
- `spotify_track_id` (text, indexed) — dedup key
- `song_json` (jsonb) — the spotdl `Song` serialized verbatim (`Song.json` / `dict`), so nothing
  from spotdl's rich metadata is lost even though only a few fields are surfaced in the UI
- `state` (enum: `pending`, `queued`, `downloading`, `completed`, `waiting`, `lookup_failed`,
  `failed`, `skipped_duplicate`, `cancelled`) — matches the master plan's state machine exactly
- `attempt_count` (int, default 0) — drives the per-track ladder index
- `scheduled_at` (timestamptz, indexed — partial index `WHERE state = 'waiting'`) — the sole
  source of truth for "when is this eligible again"
- `last_error` (text, nullable)
- `last_error_type` (enum: `audio_provider`, `lookup`, `other`, nullable)
- `used_proxy_id` (fk → `proxies.id`, nullable) — which proxy (if any) the last attempt used
- `output_path` (text, nullable) — set once `completed`
- `created_at`, `updated_at` (timestamptz)

### `downloaded_tracks`
Dedup ledger, independent of `tracks` so it survives job/track deletion and powers the startup
disk-reconciliation scan (v05).
- `spotify_track_id` (text, pk)
- `file_path` (text)
- `format` (text), `bitrate` (text, nullable)
- `downloaded_at` (timestamptz)

### `proxies`
- `id` (uuid, pk)
- `url` (text, unique) — full proxy URL as spotdl's `proxy` option expects
- `enabled` (bool, default true)
- `cooldown_until` (timestamptz, nullable)
- `consecutive_failures` (int, default 0)
- `last_used_at`, `last_success_at` (timestamptz, nullable)
- `source` (enum: `file`, `manual`) — v07 seeds from `proxies.txt`; v13's UI adds `manual` rows

### `worker_state`
Single-row (or small, keyed) table backing the global circuit breaker.
- `id` (int, pk, always `1`)
- `breaker_tripped_until` (timestamptz, nullable)
- `breaker_trip_count` (int, default 0) — indexes into the `30m → 2h → 6h` escalation
- `consecutive_failures` (int, default 0) — resets to 0 on any success
- `paused` (bool, default false) — manual pause/resume from v10, column added now to avoid a
  later migration touching this already-hot table

## Tasks

1. Write SQLAlchemy models for every table above under `backend/app/models/`.
2. Generate one Alembic revision (`alembic revision --autogenerate`) that creates all of them,
   with the partial index on `tracks (scheduled_at) WHERE state = 'waiting'` added by hand since
   autogenerate won't produce partial indexes correctly.
3. Seed a single `worker_state` row (id=1) via a data migration in the same revision.
4. `graphify update .`

## Done when

- `alembic upgrade head` against a scratch Postgres database creates every table with correct
  types, indexes, and the seeded `worker_state` row.
- `alembic downgrade base` cleanly drops everything (reversibility check).
- A short schema review confirms every field referenced by later versions' plans (v04–v13) exists
  here — no version should need an ad-hoc migration for a field this document should have
  anticipated.
