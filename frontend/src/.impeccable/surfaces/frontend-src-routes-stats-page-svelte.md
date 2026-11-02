---
version: 1
slug: "frontend-src-routes-stats-page-svelte"
primary_target: "frontend/src/routes/stats/+page.svelte"
related_targets: ["route:/stats"]
---

## Scope and mode

Route `/stats` (v44). Mode: **Operate**. Since v66 every user's: a non-admin sees their own
downloads ("Your downloads", `GET /api/stats/me`) and never makes an admin request; the admin lands
on everyone's and switches to their own in the title row (`?scope=mine`).

## Audience and job

The admin, checking how downloads are actually going: whether IPv6 and the proxies earn their
place, when failures spiked and what kind, whether the breaker is holding, and how deep the
queue is. Occasional, deliberate visits, not a background tab.

## Constraints

- Global data (every user's attempts together); counts only: no titles, identities or proxy
  URLs (`host:port` labels).
- One request per load and per window change (`GET /api/admin/stats`); refresh is manual, no SSE.
- Every chart has a text alternative (the recorder's label + "show as a table"; tables elsewhere).

## Direction (owner-approved, 2026-10-17)

"Now | over window": a narrow **Right now** plate (queue readout, oldest waiting, breaker
state, proxies) beside the window plate whose own head carries the 24h/7d/30d switch; phones
stack Right now first. Success = completed ÷ (completed + failed), not-found counted apart.
Day buckets follow the viewer's local day (the page sends its UTC offset).

Memorable moment: the failure recorder: one strip per failure class on one shared scale and one
time axis, with the breaker's holds as the bottom channel, read by one crosshair.

Colour by meaning only: settled = completed, waiting = retried failure and breaker holds,
fail = a not-found verdict or a pause. Never amber.

## v66: their own (owner-approved, 2026-10-30)

The same "library | window" split for a user's own: an all-time **Your library** plate (files,
size) beside the window plate: Tracks (outcome bar, rate, completed per bucket), Time to complete
(median), Jobs you queued (by status now), Failures by type (the recorder, no breaker channel).
One request per load, window change and scope switch. Never amber.

## Unresolved

- v45 keyboard: the recorder's crosshair is pointer-only (the table view is the keyboard path).
- ~~v46: every string here is still a literal.~~ Resolved in v46: every string is a Paraglide message (en + hu).
