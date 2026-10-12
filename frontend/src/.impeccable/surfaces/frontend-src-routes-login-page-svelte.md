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

Unresolved: the v39 audit (`plan/master-v4/v39-ui-audit-report.md`) proposes refinement vs
redesign, and the owner approves it in the v39 PR before v40 starts.
