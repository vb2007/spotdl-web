---
version: 1
slug: "frontend-src-routes-login-page-svelte"
primary_target: "frontend/src/routes/login/+page.svelte"
related_targets: ["route:/login"]
---

## Scope and mode

Route `/login`. Mode: **Operate** (app UI; recorded in the v39 audit). Scanability, consistency and
the real usage scene outrank expression.

## Audience and job

An allowlisted person signing in with their vb2007.hu account.

## Constraints

Login is a server-to-server proxy; errors must not reveal whether an account exists.

## Direction

Resolved: **refinement**, not redesign. The owner approved the v39 audit's recommendation on
2026-10-12 on PR #56 ("Keep the design for now"; `plan/master-v4/v39-ui-audit-report.md` §8,
`plan/master-v4/00-master-plan.md` Amendments): keep the signal-receiver world and fix its
execution against its own rules (`frontend/src/DESIGN.md`).

v40–v47 on `/login`: the dial kept with the needle muted at rest and amber only while connecting, an account line under the button, focus back on the password after a failure (v43); no language switch, the browser decides (v46); and v47's polish: the needle moved by transform, evenly placed ticks, a top-anchored stage, `.connect` as a `.btn`, its own field check, the 5xx copy, and "Your session ended" after a 401.
