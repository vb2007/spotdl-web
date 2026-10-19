---
version: 1
slug: "frontend-src-routes-library-page-svelte"
primary_target: "frontend/src/routes/library/+page.svelte"
related_targets: ["route:/library"]
---

## Scope and mode

Route `/library`. Mode: **Operate** (app UI; recorded in the v39 audit). Scanability, consistency and
the real usage scene outrank expression.

## Audience and job

Admin running the sort & move sweep into the real music library and reading its result.

## Constraints

Nothing on the target library is ever deleted; the page shows progress and per-file errors.

## Direction

Resolved: **refinement**, not redesign. The owner approved the v39 audit's recommendation on
2026-10-12 on PR #56 ("Keep the design for now"; `plan/master-v4/v39-ui-audit-report.md` §8,
`plan/master-v4/00-master-plan.md` Amendments): keep the signal-receiver world and fix its
execution against its own rules (`frontend/src/DESIGN.md`).

v40–v47 on `/library`: three states (no sweep yet, running over the `--signal-dim` bar, finished in `--settled-dim`), four labelled counts and a "Not filed" list, and a confirmed start (v43); i18n (v46); and v47's polish: spacing and rhythm ("× 2" spaced, no doubled hairline, unsplit counts) and raw sweep errors marked `lang="en"`.
