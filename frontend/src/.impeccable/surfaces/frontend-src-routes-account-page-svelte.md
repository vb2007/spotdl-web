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

Resolved: **refinement**, not redesign. The owner approved the v39 audit's recommendation on
2026-10-12 on PR #56 ("Keep the design for now"; `plan/master-v4/v39-ui-audit-report.md` §8,
`plan/master-v4/00-master-plan.md` Amendments): keep the signal-receiver world and fix its
execution against its own rules (`frontend/src/DESIGN.md`).

v40–v47 on `/account`: "Signed in" and "Preferences" panels in the shared form vocabulary (v43); the keyboard-shortcut switch (v45); language and time-format switches (v46); and v47's polish: preference groups that read apart, choice groups at a `.btn`'s height, Sans control labels, and a neutral disconnect.
