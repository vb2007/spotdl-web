# v41 — Dashboard Redesign

Branch: `dev-dashboard-redesign` → PR into `main`
Version: `4.41.0`

## Scope

The rest of `/`, **strictly through the impeccable skill**: the header and session area, the
submit bar, `IncomingJobs`, `Waterfall` ("Active signal"), `QueueControls` (scope, search,
archived, clear log, all-users, sort, filter chips), the job list and its pagination, and every
empty, loading and error state. This slice also fixes the design-system gaps that block a
coherent dashboard. The v38 findings assigned to v41 are its checklist.

## Requirements

- **A type scale** (DESIGN.md §3 gap). A small named set of size and weight tokens in `app.css` and
  `design-tokens.json`, used by every component touched here. Components outside v41's scope
  migrate in v42/v45. No ad hoc `font-size`s remain in v41's files.
- **Panel material** (§8.1 gap: the "matte charcoal chassis" never reads against the near-black).
  Resolve it with impeccable, or record that the approved direction drops the chassis idea.
- **Breakpoints.** Add at least one tablet breakpoint beyond today's single 640px (`adapt`). The
  header, controls and job rows have to read well at about 390, 768, 1024 and 1440 widths.
- **The Waterfall keeps its meaning** (v23's glitch fix and v34's hydration must survive
  unchanged in behavior). §8.2's "lanes not a spectrogram" stays deliberate, unless v38's
  direction says otherwise. The idle noise floor and "busy elsewhere" distinction stay.
- **QueueControls density.** This is where "cluttered" is most likely on the dashboard: group and
  prioritize the controls (`distill`), keeping every capability. Admin-only controls stay hidden
  for non-admins.
- **Consistency with v40.** The job list and its rows already changed in v40. v41 aligns
  everything around them, and doesn't reopen them except for v38 findings that span both.
- **v39's ambient field** must still read correctly behind the redesigned panels.
- **Semantics for v44.** Landmarks (`header`, `main`, `nav`), one `h1`, a heading hierarchy, and
  labelled groups. Add an element id or landmark v44's skip link can target.

## Out of scope

- `/settings`, `/library`, `/account`, `/login` (v42).
- Destructive-action confirmations, which are designed in v42 for both "clear log" and "remove
  proxy". v41 leaves "clear log"'s behavior untouched.
- Shortcuts (v44).

## Done when

- [ ] impeccable was loaded, and its sub-commands and output recorded in the PR.
- [ ] Every v38 finding assigned to v41 is marked fixed or deferred with a reason.
- [ ] Before and after screenshots of `/` at 390, 768, 1024 and 1440 widths: idle, receiving (a live
      Waterfall), with an incoming job, with a failed incoming job, empty, loading, the error
      state, and the admin all-users view. Real dev data.
- [ ] The type scale tokens exist and are the only font sizes in v41's files (grep for
      `font-size:` literals in those files).
- [ ] The panel material decision is recorded in DESIGN.md and visible in the screenshots.
- [ ] Waterfall behavior is unchanged: v34's reload-hydration spec and a live receiving check pass,
      and there is no appear/disappear glitch (watch one failing-then-retrying track live).
- [ ] Landmarks and heading outline are verified (an accessibility-tree screenshot, or an
      impeccable `audit`), with no regressions vs v38's baseline.
- [ ] The v37 e2e suite passes on both projects (selector updates by role/name only).
- [ ] `npm run lint`, `npm run check` and `npm run build` pass, and `pytest` passes. Both version
      files read `4.41.0`. `uv lock` is in sync. `graphify update .` has been run.
