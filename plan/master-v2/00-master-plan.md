# spotdl-web — Master Plan v2

> This is the master v2 roadmap, approved by the user and committed **verbatim** as the project's
> permanent record — the same treatment `plan/master-v1/00-master-plan.md` got, and for the same
> reason: the roadmap must never be quietly reinterpreted after the fact. Individual version plans
> (`plan/master-v2/v14-*.md` … `v21-*.md`) expand the roadmap table below with implementation-level
> detail. `CLAUDE.md` carries the durable summary every future session reads first.
>
> Master v1's plans live in `plan/master-v1/` and are never edited again.

## Context

Master v1 (v00–v13, PRs #1–#15, all merged) is deployed and working on live infrastructure at
`spotdl.vb2007.hu`. It downloads reliably, survives restarts, dodges rate limits, and has a live
UI. As a POC it succeeded.

It is not yet *usable* for its actual audience, for three reasons that only appeared under real
use:

1. **It is single-user in everything but login.** Multiple people can authenticate, but there is no
   `user_id` anywhere on `jobs` or `tracks`, no role concept, and `sessions` stores only an email
   string. Everyone sees everyone's data — including through the SSE stream, which broadcasts every
   event on one global Redis channel (`spotdl:events`) to every connected client.
2. **There is no job/track hierarchy.** `QueueTable.svelte` renders one flat row per track and
   `GET /api/tracks` returns *every track across every job, unpaginated*. A single-track submission
   and a 3,000-track discography land in the same undifferentiated list, which makes job management
   effectively impossible — the app's actual purpose.
3. **Finding anything is impossible.** The only filters are three buttons (`all` / `waiting` /
   `lookup_failed`). No search, no sorting, no way to retire finished work from view.

Master v2 fixes these. It also starts by auditing what v1 actually shipped against what v1 planned,
since a week of shipping under time pressure produced at least two known drifts (below).

**Locked for all of v2: no backward compatibility is required.** The database holds only POC test
data and can be nuked at any time. Migrations may be destructive; a clean rebuild is acceptable.
This removes the single largest source of complexity from the multi-user work.

---

## Verified current state

Read directly from the repo this session (not assumed):

| Finding | Evidence |
|---|---|
| No ownership anywhere | `models/job.py`, `models/track.py` have no `user_id`; `models/session.py` has only `email` |
| No role concept | zero matches for `is_admin`/`role` across `backend/app/` |
| SSE leaks across users | `services/events.py` publishes all events to one `CHANNEL = "spotdl:events"`; `routers/stream.py` subscribes every client to it |
| No pagination at all | `routers/tracks.py:41` `db.query(Track).order_by(Track.created_at).all()`; `routers/jobs.py:64` same for jobs |
| N+1 still present | `serializers.job_to_dict(db, job)` calls `track_counts()` per job; `list_jobs` loops it. CLAUDE.md's v04 notes flagged this as "revisit if job history grows large" — it now is |
| Pacing hook never wired | `config.py:64-65` defines `pacing_min_sec`/`pacing_max_sec`; **zero consumers** anywhere in the codebase, despite the master plan calling it "wired but off by default" |
| Filters are 3 buttons | `QueueTable.svelte:12,117` — `all` / `waiting` / `lookup_failed` |
| Test suite | 137 tests across 19 files, all passing as of v13 |

The last two rows of that table are exactly the kind of drift v14's audit exists to find
systematically rather than incidentally.

---

## Locked decisions for v2

| Area | Decision |
|---|---|
| Backward compatibility | **None required.** DB is disposable; destructive migrations allowed |
| User identity | Real `users` table; row created on first successful upstream login (env allowlist still gates *who may* log in) |
| Admin | `is_admin` boolean column in DB, seeded from a new `ADMIN_EMAIL` env var on first boot |
| Data separation | **DB-level only.** Jobs/tracks are per-user; files on disk stay in one shared library |
| Dedup | Stays global — a track another user already downloaded resolves instantly as already-downloaded |
| Queue fairness | Unchanged: global `jobs.priority DESC, scheduled_at ASC`. No round-robin, no per-user slots |
| Admin visibility | Own jobs by default; explicit "all users" toggle for troubleshooting |
| Settings page | Admin-only (proxies, format/bitrate/template). Per-user settings (retention) are separate and available to everyone |
| `LookupError` | **Unchanged from v1** — terminal, never auto-retried. Only the UI label changes ("Not found", not "Given up") |
| Log retention | Soft-archive (`archived_at`), never hard delete. Per-user threshold; per-user "clear log" |
| Live view | SSE scoped server-side per user; waterfall shows only your tracks |
| Search | Server-side, across full history; archived excluded by default with an opt-in toggle |
| Plan layout | `plan/master-v1/` (moved, untouched) + `plan/master-v2/`; version numbers continue at **v14** and never repeat |

---

## Job rollup status — answering the open design question

You asked: *an album of 10 tracks where 1 hits `LookupError` — what is that job labelled?* Calling
it "failed" is wrong (90% succeeded on best effort); calling it "completed" hides a real gap.

**A job never gets a single stored success/fail flag.** Its status is *derived* from its track
state counts, and split into two independent axes:

**Axis 1 — lifecycle** (answers "does the worker still owe this job anything?"):

| Status | Condition |
|---|---|
| `expanding` | `job.state = expanding` |
| `failed` | expansion itself failed — zero tracks ever created |
| `cancelled` | `job.state = cancelled` |
| `active` | ≥1 track in `pending`/`queued`/`downloading` |
| `waiting` | no active tracks, ≥1 in `waiting` (sitting in the retry ladder) |
| `settled` | every track is terminal |

**Axis 2 — outcome quality** (only meaningful once `settled`):

- `complete` — every track `completed` or `skipped_duplicate`
- `partial` — ≥1 track `lookup_failed` or `cancelled`

So your 9-of-10 album is **`settled · partial`**, rendered as `Done — 9 of 10` with a muted
"1 not found" note. Never "failed", never a bare green tick.

This makes the genuinely useful query a first-class filter: **"settled but partial"** = *finished
jobs that didn't get everything* — the one list worth acting on, and impossible to produce today.
Track counts are always shown as a breakdown next to the status, so the 90% is never flattened
into a binary.

**Job/track scope toggle** (your design, adopted): a two-option toggle above the sort controls.

- **Jobs** (default): search/filter/sort operate on jobs; results are collapsed job rows.
- **Tracks**: search/filter/sort operate on tracks; matching jobs auto-expand to reveal only the
  matching tracks.

One toggle, one mental model, and it makes "find that one track somewhere in my history" and
"which of my submissions are stuck" both one click away.

---

## Version roadmap

Same discipline as v1: one feature per version, one `dev-<feature>` branch, one PR into `main`,
never two in parallel.

| # | Branch | Scope |
|---|---|---|
| **v14** | `dev-v1-audit` | **Read-only audit.** Every "Done when" bullet + locked decision across all 14 v1 plan files checked against the shipped code. Produces `plan/master-v2/v14-audit-report.md`. No code changes |
| **v15** | `dev-v1-gap-fixes` | Fix the gaps v14 finds. Known already: pacing hook has no consumer; `list_jobs` N+1. Final scope set by v14's report — anything large gets its own version instead |
| **v16** | `dev-users-schema` | `users` table (+`is_admin`), `user_id` FK on `jobs`, `user_settings` (retention), `sessions.user_id`, `jobs.archived_at`. Models + migration only, no behavior change |
| **v17** | `dev-multi-user-auth` | Login creates/loads the user row; `ADMIN_EMAIL` seeding; `require_session` yields a user; **every** job/track query scoped by owner; admin "all users" toggle; settings endpoints admin-gated; **SSE moved to a per-user channel** |
| **v18** | `dev-job-centric-api` | Paginated + filtered + sorted + searchable endpoints. Job rollup status and track counts computed in **one** aggregate query (kills the N+1). Job-scope and track-scope query modes |
| **v19** | `dev-archive-retention` | `archived_at` lifecycle, per-user retention threshold, "clear log" endpoint, a beat task that auto-archives past the threshold, archived-inclusive search opt-in |
| **v20** | `dev-job-centric-ui` | The frontend rework: job rows expanding to tracks, job/track scope toggle, search box, sortable columns, state filter with live counts, archive view, per-user settings page |
| **v21** | `dev-multi-user-hardening` | Real two-user verification on the live stack (data separation treated as a security property, not a feature), migration on the real host, `docs/` + `CLAUDE.md` reconciliation |

> **2026-08-12 addendum:** this table is kept verbatim per this file's own policy above, but the
> roadmap it describes has since changed — `dev-release-automation` was inserted as the new **v21**
> (release/deploy automation, needed regardless of what ships next), and `dev-multi-user-hardening`
> above shifted to **v22**. `CLAUDE.md`'s roadmap table is the current source of truth;
> `plan/master-v2/v21-release-automation.md` and `plan/master-v2/v22-multi-user-hardening.md` are
> the real per-version plans. Left here as a correction, not a silent edit, matching how
> `docs/GOTCHAS.md` handles a stale claim.

### Why this order

Schema (v16) before enforcement (v17) mirrors v1's successful v02→v03 split and keeps each PR
reviewable. Ownership (v17) lands before the API rework (v18) so pagination and search are written
against the scoped queries from the start rather than being retrofitted — retrofitting an ownership
filter onto a search endpoint is exactly how a data-separation bug ships. The UI (v20) comes last
because it consumes everything below it.

---

## Plan file reorganization (part of v14)

```
plan/
  master-v1/
    00-master-plan.md          # moved verbatim, never edited again
    v00-planning.md … v13-settings-ui.md
  master-v2/
    00-master-plan.md          # this document, expanded
    v14-audit.md … v21-multi-user-hardening.md
    v14-audit-report.md        # v14's actual output
```

`CLAUDE.md` gains a "Master v2" section and its version-roadmap table extends to v21; the existing
v01–v13 gotchas sections stay exactly as they are — they remain true and hard-won.

---

## Critical files

- **Ownership**: `backend/app/models/{job,track,session}.py`, `backend/app/routers/auth.py`
  (`require_session` at `:23` is the single chokepoint every scoped query will depend on)
- **Query rework**: `backend/app/services/serializers.py` (`track_counts`/`job_to_dict` — the N+1),
  `backend/app/routers/{jobs,tracks}.py`
- **SSE scoping**: `backend/app/services/events.py` (`CHANNEL` at `:21`),
  `backend/app/routers/stream.py`
- **Admin gating**: `backend/app/routers/{settings,proxies,worker}.py`
- **Frontend**: `frontend/src/lib/stores/queue.ts`, `frontend/src/lib/components/QueueTable.svelte`,
  `frontend/src/routes/+page.svelte`, `frontend/src/DESIGN.md` (§2's live-accent rule and §6's
  mobile one-cell-per-line rule both constrain v20)

Reuse rather than rewrite: `serializers.track_to_dict` (the deliberate projection), `retry.py`'s
ladder/breaker, `dedup.py`'s global ledger, `app_settings.py`'s get-or-create singleton pattern
(the model for `user_settings`), and `Countdown.svelte`.

---

## Verification

Every version keeps v1's standard — real docker-compose stack, real Postgres, real network, and
each "Done when" bullet checked individually with its own evidence. Additionally:

1. **Data separation is a security property, not a feature.** v17 and v21 must prove a second user
   cannot reach the first's data via *any* surface: REST (direct id access, not just list
   endpoints), the SSE stream (raw `curl -N` capture, confirming zero foreign track ids on the
   wire), and search results. A test that only checks list endpoints is insufficient.
2. **Admin gating tested from a non-admin session** — settings/proxies/worker endpoints must return
   403, verified against the real running API, not only in unit tests.
3. **Scale, with real volume.** v18/v20 verified against a genuinely large seeded job (~3,000
   tracks): first paint, search latency, and pagination correctness. The N+1 fix confirmed by query
   count, not by feel.
4. **Retention is reversible.** v19 must show archived jobs surviving in the DB and being
   retrievable via the archive view — and that `downloaded_tracks` is never touched, so archiving
   can never cause a re-download.
5. **`graphify update .`** after every code-modifying version, per the standing project rule.

---

## Amendments

The plan above is the approved text, kept verbatim. Changes directed after approval are recorded
here rather than edited into it, so the original record stays readable.

### 2026-08-09 — CLAUDE.md split into rules vs. reference (folded into v14)

The plan-reorganization section above says "the existing v01–v13 gotchas sections stay exactly as
they are". They do — but they no longer live in `CLAUDE.md`.

At 1,737 lines, `CLAUDE.md` was loaded into every session's context in full, ~81% of it version-by-
version war stories describing code that master v2 is about to change. Per the user's direction, the
v01–v13 gotchas and the two external-API reference sections moved **verbatim** into
`docs/GOTCHAS.md` (with a topic index and a staleness warning), leaving `CLAUDE.md` at ~250 lines
holding only rules, locked decisions, invariants, the state machine, and the roadmap.

Keeping `CLAUDE.md` current remains a standing rule — but new findings now go to `docs/GOTCHAS.md`,
and `CLAUDE.md` changes only when a rule, decision, invariant, or roadmap position changes.
`plan/master-v2/v14-audit.md` carries the full task list and its verification.

### 2026-08-09 — v15 complete; two v14 findings confirmed already scheduled, one new finding added

v15 (`dev-v1-gap-fixes`) closed 7 of v14's 11 remediation items (pacing hook, `list_jobs` N+1,
stale README/nginx-comment, settings-page proxy polling, plus real-stack verification of a literal
playlist submission and album-scale re-submission dedup). Full detail in `docs/GOTCHAS.md`'s new
"v15 gap-fixes" section.

The other four were deliberately **not** taken, per this document's own "anything large gets its
own version instead" rule:

- `TrackState.FAILED` dead-code removal — confirmed still correctly routed to **v16** (`users-schema`
  already touches a migration in that version; removing a native enum value needs its own
  `DROP TYPE`, so it rides along rather than opening a migration-only PR just for this).
- `routers/tracks.py`'s unbounded `list_tracks` — confirmed still correctly routed to **v18**
  (`job-centric-api`, which already owns pagination for both jobs and tracks).
- Host-reboot log, worker-healthcheck-flip log, non-root nginx — v14 marked all three optional;
  left undone, not silently dropped.

**New finding, not from v14's audit, added to the backlog for a future version**: `download_track`
(`backend/app/tasks/download.py`) gates dispatch only on `TrackState.CANCELLED`. A redelivered
Celery message for an already-`COMPLETED` track (via `task_acks_late` on a worker crash, or via
`_reclaim_stale_tracks` sweeping a track that's actually still running) passes that gate and can
regress the row to `SKIPPED_DUPLICATE` through the dedup branch. Real defect, not urgent (a
state-accuracy bug, not data loss — both states are terminal/successful in v2's rollup), and not
small enough to fold into v15's fixes-only scope. No version number assigned yet; needs scheduling
alongside the other post-v21 backlog items above.

### 2026-08-09 — v16 complete; NOT NULL applied literally, login/job creation left broken for v17

`v16-users-schema.md`'s own text turned out self-contradictory: it specifies `jobs.user_id` and
`sessions.user_id` as NOT NULL, with `sessions.user_id` replacing `email` outright, while also
promising "no behavior change" and "existing test suite passes unchanged." Both can't hold — no
`User` row exists until v17 wires login to create one, so login and job creation break immediately.
Asked directly, the user chose to apply the schema exactly as specified and accept the breakage
(80 of 151 backend tests now fail) rather than soften the constraint or pull user-creation into v16.
This is the approved resolution — v17 must not "fix" it by reverting to nullable columns; it must do
the user-creation-on-login wiring the roadmap already assigned it. Full task list and exact failure
inventory recorded in `docs/GOTCHAS.md`'s v16 section.

`TrackState.FAILED` was also removed in this version's migration, per the routing decision recorded
in the previous amendment above. Verified zero test coverage depended on it.
