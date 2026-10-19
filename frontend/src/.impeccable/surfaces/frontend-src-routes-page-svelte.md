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

Resolved: **refinement**, not redesign. The owner approved the v39 audit's recommendation on
2026-10-12 on PR #56 ("Keep the design for now"; `plan/master-v4/v39-ui-audit-report.md` §8,
`plan/master-v4/00-master-plan.md` Amendments): keep the signal-receiver world and fix its
execution against its own rules (`frontend/src/DESIGN.md`).

v40–v47 on `/`: the cursor-following ambient field (v40); calmer job/track detail with the attempt timeline admin-only (v41); the masthead, link tell, Waterfall idle states, one queue faceplate, type scale, raised panels and tablet band (v42); keyboard (v45); Hungarian/English (v46); and v47's polish: Sans control labels, one hover/press/disabled idiom, row amber only while a track downloads with the link live, em breakpoints, `--control-h`, two-line title clamps, exact queue counts, admin-only priority/bump, and the session-ended and unreachable-server paths.
