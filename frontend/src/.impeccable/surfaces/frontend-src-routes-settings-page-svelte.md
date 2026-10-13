---
version: 1
slug: "frontend-src-routes-settings-page-svelte"
primary_target: "frontend/src/routes/settings/+page.svelte"
related_targets: ["route:/settings"]
---

## Scope and mode

Route `/settings`. Mode: **Operate** (app UI; recorded in the v39 audit). Scanability, consistency and
the real usage scene outrank expression.

## Audience and job

Admin for output, proxies, worker controls, alerts; every user for their own log retention.

## Constraints

Admin-only sections must stay hidden from non-admins. Destructive actions (proxy removal) are confirmed from v43.

## Direction

Unresolved: the v39 audit (`plan/master-v4/v39-ui-audit-report.md`) proposes refinement vs
redesign, and the owner approves it in the v39 PR before v40 starts.
