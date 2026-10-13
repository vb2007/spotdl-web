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

Unresolved: the v39 audit (`plan/master-v4/v39-ui-audit-report.md`) proposes refinement vs
redesign, and the owner approves it in the v39 PR before v40 starts.
