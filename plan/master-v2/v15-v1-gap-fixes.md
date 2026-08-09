# v15 — Master v1 Gap Fixes

Branch: `dev-v1-gap-fixes` → PR into `main`

## Scope

Fix the gaps v14's audit found. **This version's scope is not fully knowable until v14's report
exists** — that's by design, and the plan below defines the *rules for what belongs here* plus the
two gaps already confirmed, rather than pretending to enumerate findings that haven't been made yet.

## Admission rules

A finding belongs in v15 if it is:

- a genuine deviation from a v1 plan's "Done when" bullet, locked decision, or architecture
  invariant, **and**
- small and self-contained enough to review alongside other unrelated small fixes.

A finding does **not** belong in v15 if fixing it means a schema change, a new endpoint shape, or a
UI rework — those get their own version, appended to the v2 roadmap after v21. Bundling a large fix
into a "misc fixes" PR is how a review gets rubber-stamped.

Findings that turn out to be *not actually wrong* (the plan was superseded by a later, better
decision) get recorded in `CLAUDE.md` as an explicit correction to the older plan's claim — the same
treatment v12 gave v09's incorrect "no nginx SPA-fallback needed" note — rather than silently
dropped.

## Confirmed gaps (already found, before the audit runs)

### 1. The pacing hook has no consumer

`backend/app/config.py:64-65` defines `pacing_min_sec`/`pacing_max_sec`. Nothing reads them.
`plan/master-v1/00-master-plan.md` describes the hook as "wired but off by default — the first dial
to turn if 429s stay frequent after proxies", and `plan/master-v1/v06-retry-engine.md` carries the
same claim. It is declared, not wired: raising either value today changes nothing, silently.

**Fix**: apply a randomized `sleep(uniform(min, max))` in `download_track` between tracks when
`pacing_max_sec > 0`. Placement matters — it must be *after* the dedup check and the breaker/pause
check, so a skipped-duplicate track or a track that isn't going to be attempted at all doesn't burn
wall-clock for nothing. Default stays `0` (off), preserving current behavior exactly.

**Verify**: a unit test asserting no sleep occurs at the default, and a real-stack run with the
values temporarily raised, confirming the measured gap between two consecutive `download_track`
invocations in `worker-dl`'s logs falls inside the configured window.

### 2. `list_jobs` N+1, and no pagination anywhere

`serializers.job_to_dict(db, job)` calls `track_counts(db, job.id)` — one grouped-count query per
job — and `routers/jobs.py:64` loops it over every job with no limit. CLAUDE.md's v04 notes flagged
this as acceptable "at current scale, revisit if job history grows large"; a week of real use took
it past that. `routers/tracks.py:41` has the same unbounded-query shape.

**Fix here is deliberately narrow**: collapse the per-job count queries into a **single** grouped
aggregate over all requested jobs, keeping the response shape byte-identical. Pagination, filtering,
sorting, and search are **v18's** job — doing them here would mean rewriting the endpoint twice and
would smuggle a large API change into a fixes PR.

**Verify**: query count asserted directly (a SQLAlchemy event-listener counter in the test, not a
timing measurement), and the response body compared for equality against the pre-fix implementation
across a realistic job set.

## Tasks

1. Read `plan/master-v2/v14-audit-report.md` and triage every remediation item against the
   admission rules above.
2. State the final v15 scope explicitly at the top of the PR description, listing which findings
   were taken, which were deferred to their own version, and which were reclassified as
   "not actually a gap" with reasoning.
3. Fix the two confirmed gaps above plus whatever else qualifies.
4. Add a regression test per fix. Where a gap existed because nothing tested it (the pacing hook is
   exactly this — no test ever asserted the setting had an effect), the test matters more than the
   fix; it's what stops the same drift recurring.
5. Update `CLAUDE.md` with a v15 section recording what drifted, and — importantly — *why it wasn't
   caught the first time*, since that's the reusable lesson.
6. `graphify update .`

## Done when

- Every v14 remediation item is either fixed here, assigned to a new version appended to the
  roadmap, or explicitly reclassified with reasoning — none silently dropped.
- Pacing: default-off behavior unchanged (test), and a real-stack run measurably shows the delay
  when enabled.
- N+1: the job-list endpoint issues a constant number of queries regardless of job count, proven by
  an asserted query count; response shape unchanged.
- Full backend suite passes (137 tests as of v13, plus the new regressions).
- No schema changes, no new endpoints, no UI rework in this PR.
