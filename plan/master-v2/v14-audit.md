# v14 — Master v1 Implementation Audit

Branch: `dev-v1-audit` → PR into `main`

## Scope

A **read-only** audit of what master v1 actually shipped against what master v1 planned, plus the
plan-folder reorganization that makes room for v2. **No application code changes in this version** —
not even "obvious" one-line fixes. Everything found gets written down and scheduled; v15 does the
fixing.

The separation is the point: mixing "here's what's wrong" with "here's a large diff" makes the
findings unreviewable, which is exactly what the one-feature-at-a-time rule exists to prevent.

## Why this comes first

Master v1 shipped 14 versions in a week. CLAUDE.md's own gotchas sections show the project already
caught real drift twice by re-reading plan files (v05's untested "small real album" bullet, v11's
untested bump endpoint) — both times *after* a PR had already been called merge-ready. This version
does that check deliberately and exhaustively instead of by luck.

Two drifts are already confirmed before the audit even starts (found while planning v2, recorded
here so they aren't "discovered" again):

- **`PACING_MIN_SEC`/`PACING_MAX_SEC` have zero consumers.** `backend/app/config.py:64-65` defines
  both; nothing anywhere reads them. The master plan says the pacing hook is "wired but off by
  default" — it is declared, not wired. A future session turning the dial up would see no effect
  and no error.
- **`list_jobs`'s N+1 is still there, with no pagination.** `serializers.job_to_dict(db, job)` runs
  a `track_counts()` query per job and `routers/jobs.py:64` loops it over every job. CLAUDE.md's
  v04 notes explicitly say "fine at current scale, revisit if job history grows large" — it has.

## Tasks

1. **Reorganize `plan/`** (the only structural change this version makes):
   - `git mv plan/*.md plan/master-v1/` — all 15 v1 files, moved verbatim, never edited again.
   - `plan/master-v2/` gets `00-master-plan.md` (the approved v2 roadmap, committed verbatim) plus
     one `vNN-*.md` per v2 version.
   - Use `git mv` rather than delete+create so the rename is detected and file history survives.
2. **Audit every v1 plan file's "Done when" section**, one bullet at a time, against the shipped
   code. For each bullet record: `met` / `partially met` / `not met` / `superseded`, the concrete
   evidence (file:line, test name, or "no consumer found"), and — where not met — the severity and
   whether it's a v15-sized fix or needs its own version.
3. **Audit the locked-decisions table** in `plan/master-v1/00-master-plan.md` the same way. A
   locked decision silently not honored in code is worse than a missed "Done when" bullet, because
   nothing downstream knows to question it.
4. **Audit the architecture invariants** that CLAUDE.md states as rules rather than features, since
   these are the ones with no test guarding them:
   - No Celery `eta`/`countdown` used for backoff anywhere (`tracks.scheduled_at` is the only
     schedule source of truth).
   - `worker-dl` still runs `--concurrency=1 --prefetch-multiplier=1`.
   - Every spotdl entry point goes through `expansion._ensure_spotify_client()`.
   - Every proxy URL that is logged or persisted goes through `proxies.redact()`.
   - Every enum column uses `values_callable`; every native enum created has an explicit
     `DROP TYPE` in its migration's `downgrade()`.
   - Every frontend route has both the SvelteKit exports *and* its own nginx `location` block.
5. **Write `plan/master-v2/v14-audit-report.md`** — the deliverable. Structured as one section per
   v1 version, a findings table, and a prioritized remediation list at the end mapping each gap to
   either "v15" or "needs its own version".
6. **Update `CLAUDE.md`**: add the Master v2 section (context, locked v2 decisions, the job-rollup
   status model, the v14–v21 roadmap table) and update the plan-file paths, which all moved.
7. **Split `CLAUDE.md` into rules vs. reference.** At 1,737 lines it was loaded into every session's
   context in full, most of it war stories about code v2 is about to change. A rule an agent must
   follow and a finding an agent might need are different documents, and only the first belongs in
   every context window.
   - Move the v01–v13 gotchas sections **verbatim** into `docs/GOTCHAS.md`, prefixed with a
     topic index so an agent can jump to the relevant one instead of reading 1,400 lines, and a
     warning that entries describe the code as of v13 and must be re-verified before being acted on.
   - Move the "Auth API" and "spotdl 4.5.2 API surface" reference sections there too, under
     "Verified external API contracts" — they're lookup material, not rules.
   - `CLAUDE.md` keeps only: graphify rules, project context, workflow rules, a file map, dev
     environments, locked decisions (v1 + v2), architecture invariants, the state machine and retry
     numbers, the rollup model, and the roadmap. Target: under ~250 lines.
   - Add a "Maintaining this file" section making the split a standing rule — new findings go to
     `docs/GOTCHAS.md`; `CLAUDE.md` changes only when a rule, decision, invariant, or roadmap
     position changes, by editing the existing line rather than appending.
   - Verify the moved gotchas are **byte-identical** to what was removed (`diff`), not merely
     "looks complete".
7. `graphify update .` — the plan files moved, so the graph's `source_file` paths are stale.

## Explicitly out of scope

- Any change under `backend/app/` or `frontend/src/`.
- Fixing the two known drifts above. They are recorded, not repaired, here.
- Re-verifying v1 behavior against the *live* stack. This audit is a code/plan comparison; where a
  bullet's evidence requires a real-stack run that wasn't recorded in the PR or CLAUDE.md, mark it
  `unverifiable from source` and let v15 decide whether it's worth re-running.

## Done when

- `plan/master-v1/` holds all 15 original files with `git log --follow` still working through the
  rename; `plan/master-v2/` holds `00-master-plan.md` + one file per v2 version.
- `v14-audit-report.md` covers **every** "Done when" bullet across all 14 v1 plan files — counted
  and stated explicitly ("N bullets audited"), not sampled. A partial audit that looks complete is
  worse than an obviously partial one.
- Every locked decision and every architecture invariant listed above has a verdict with evidence.
- The remediation list at the end of the report is prioritized and each item is assigned to v15 or
  to its own version — no findings left unrouted.
- `CLAUDE.md` reflects the new plan paths and the v2 roadmap, is under ~250 lines, and carries the
  "Maintaining this file" rule.
- `docs/GOTCHAS.md` exists, all 13 version sections are present, and its body `diff`s clean against
  what was removed from `CLAUDE.md` — verified, not assumed.
- `git diff --stat` shows changes only under `plan/`, `docs/`, `CLAUDE.md`, and `graphify-out/`.
