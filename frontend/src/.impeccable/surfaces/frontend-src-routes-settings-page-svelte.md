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

Resolved: **refinement**, not redesign. The owner approved the v39 audit's recommendation on
2026-10-12 on PR #56 ("Keep the design for now"; `plan/master-v4/v39-ui-audit-report.md` §8,
`plan/master-v4/00-master-plan.md` Amendments): keep the signal-receiver world and fix its
execution against its own rules (`frontend/src/DESIGN.md`).

v40–v47 on `/settings`: one page of five panels with an anchor index, state words beside named buttons instead of toggles, the shared form vocabulary and confirmations (v43); i18n (v46); and v47's polish: a per-section retry when a section's first read fails, alert legends as group headings, thresholds on one line, Sans controls, and empty live regions out of the flow.
