---
version: 1
slug: "frontend-src-routes-account-page-svelte"
primary_target: "frontend/src/routes/account/+page.svelte"
related_targets: ["route:/account"]
---

## Scope and mode

Route `/account`. Mode: **Operate** (app UI; recorded in the v39 audit). Scanability, consistency and
the real usage scene outrank expression.

## Audience and job

Any user checking which identity is signed in, and (from v45/v46) per-user preferences.

## Constraints

Shows only the signed-in user's own data.

## Direction

Unresolved: the v39 audit (`plan/master-v4/v39-ui-audit-report.md`) proposes refinement vs
redesign, and the owner approves it in the v39 PR before v40 starts.
