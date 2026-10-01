# v40 — Job & Track Detail Redesign

Branch: `dev-track-detail-redesign` → PR into `main`
Version: `4.40.0`

## Scope

The owner's core UI complaint. Expanding a track shows everything at once, and it feels "out of
place". In their screenshot, a single successful download shows the `logged` state label in the
far-left column. A title, artist and album row floats to its right. Then come an unaligned
"passes attempted: 0" line, a lone `download` button, and an "ATTEMPT HISTORY" block indented to a
third, unrelated position. With five error attempts it gets much worse.

**All of that information stays.** It's there by request, for monitoring. This version changes how
it is presented, **strictly through the impeccable skill** (`layout`, `distill`, `clarify`, then
`typeset`/`colorize` as its findings direct), following v38's report and approved direction. The
v38 findings assigned to v40 are this slice's checklist.

Surfaces: `TrackRow.svelte` (row plus expanded detail), `JobRow.svelte` (row plus expanded
state), `JobTrackList.svelte` (the nested list and its "load more"), and the tracks-scope group
header in `routes/+page.svelte`.

## Requirements (impeccable decides the form)

- **One grid, shared.** The expanded detail aligns to the row's own columns. Today the detail is
  indented 9rem while the title starts at 10.25rem, so it lines up with neither. A nested track
  visibly nests under its job: consistent padding and a nesting indent, with JobRow and TrackRow
  on a shared alignment. The other mismatches v38 lists all get fixed.
- **A summary strip first:** state, attempts and failures (v35's corrected counts), last network
  path, and the next retry countdown when waiting. Scannable in one line, at a fixed position.
- **One action area** at a predictable position (retry now / download / cancel), rendered only for
  the states that allow each, as today. Destructive actions are visually distinct from neutral
  ones.
- **Attempt history as a compact timeline**, newest first (or whatever impeccable justifies):
  outcome, path (v35's `network_path` plus redacted proxy label), time (relative, with the
  absolute time on hover/focus), duration, and error class.
  - **Consecutive identical errors collapse** ("×5 · NO_OUTPUT · same message") and expand on
    demand.
  - **Long error messages are clamped** (a few lines) with an accessible expand control. The full
    text stays available, selectable and copyable. Monitoring needs the raw message.
  - **Warnings (v35's flag) are styled distinctly from failures.** A tag-repair note on a
    completed attempt must never read as an error.
- **State-color semantics stay** (DESIGN.md §2: amber = live, mint = settled, blue = waiting, red =
  fail), unless v38's approved direction changes them.
- **Responsive.** The ≤640px stack is redesigned too, not just shrunk. A tablet width is covered,
  if v41's breakpoint lands first, or in coordination with it.
- **Semantics for v44.** The expandable row is a real disclosure (`aria-expanded`/`aria-controls`),
  with accessible names on every control, so v44 can add roving focus without restructuring. Keep
  the existing native-button behavior working.
- **No per-row request loop.** Attempt history stays lazy-loaded on first expand and cached (the
  existing pattern).

## Cases to design and screenshot explicitly (desktop and mobile each)

1. A completed first-try track (the owner's screenshot case).
2. A track with **5+ failed attempts**, mixed paths (ipv4, ipv6, proxy) and at least two identical
   consecutive errors.
3. A waiting track with countdown.
4. lookup_failed.
5. A completed track with a tag-repair warning.
6. A downloading track (live progress inside the expanded view).
7. A cancelled track.
8. An expanded job with 50+ tracks, plus "load more tracks".
9. The tracks-scope grouped view.

Use real dev data for every case. Induce the failure cases with the techniques v36 used (a broken
`YOUTUBE_PLAYER_CLIENTS`, a lowered ladder via `LADDER_SECONDS`).

## Out of scope

- The rest of the dashboard (v41), and keyboard shortcuts (v44).
- Backend changes. If the redesign needs a field the API lacks, stop and raise it. v35 should
  have provided everything.

## Done when

- [ ] impeccable was loaded, and each sub-command used is recorded with its output in the PR.
- [ ] Every v38 finding assigned to v40 is listed in the PR as fixed, or as deferred with a reason.
- [ ] All nine cases are screenshotted **before** (from main) and **after**, on desktop and mobile,
      from real dev data.
- [ ] Alignment: the detail block shares the row grid (a DevTools grid-overlay screenshot), and
      nested tracks indent under the job.
- [ ] Case 2 shows collapsed repeats that expand, and a clamped long error that expands, with the
      full text selectable.
- [ ] Case 5's warning does not use the failure style (screenshot plus the computed color).
- [ ] An impeccable `audit` of these components shows no contrast or accessibility regressions
      vs v38's baseline. Every control has an accessible name.
- [ ] The v37 e2e suite passes, with specs updated by role/name only. A new spec covers case 2's
      collapse and expand.
- [ ] `npm run lint`, `npm run check` and `npm run build` pass, and `pytest` passes. Both version
      files read `4.40.0`. `uv lock` is in sync. `graphify update .` has been run.
