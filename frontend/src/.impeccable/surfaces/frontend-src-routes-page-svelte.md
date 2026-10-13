---
version: 1
slug: "frontend-src-routes-page-svelte"
primary_target: "frontend/src/routes/+page.svelte"
related_targets: ["route:/"]
---

## Scope and mode

Route `/`. Mode: **Operate** (app UI; recorded in the v39 audit). Scanability, consistency and
the real usage scene outrank expression.

## Audience and job

Every allowlisted user (and the admin) submitting Spotify URLs and monitoring a queue that legitimately runs for days. The recurring task is a glance: is anything live, is anything stuck, what failed and why.

## Constraints

All monitoring information (attempt history, network path, countdowns, breaker state) stays; only its presentation may change. Data separation per user; the admin's all-users scope is opt-in.

## Direction

Unresolved: the v39 audit (`plan/master-v4/v39-ui-audit-report.md`) proposes refinement vs
redesign, and the owner approves it in the v39 PR before v40 starts.
