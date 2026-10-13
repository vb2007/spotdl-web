# v42 — Dashboard Redesign

Branch: `dev-dashboard-redesign` → PR into `main`
Version: `4.42.0`

## Scope

The rest of `/`, **strictly through the impeccable skill**: the header and session area, the
submit bar, `IncomingJobs`, `Waterfall` ("Active signal"), `QueueControls` (scope, search,
archived, clear log, all-users, sort, filter chips), the job list and its pagination, and every
empty, loading and error state. This slice also fixes the design-system gaps that block a
coherent dashboard. The v39 findings assigned to v42 are its checklist.

## Requirements

- **A type scale** (DESIGN.md §3 gap). A small named set of size and weight tokens in `app.css` and
  `design-tokens.json`, used by every component touched here. Components outside v42's scope
  migrate in v43/v47. No ad hoc `font-size`s remain in v42's files.
- **Contrast tokens** (v39 amendment A2, F09). Change the color tokens in `app.css` and
  `design-tokens.json`: `--text-dim` reaches 4.5:1 (WCAG 1.4.3) on every background it sits on
  (about `#85909a` or lighter on bg-2), `--line` control borders reach 3:1 (1.4.11), and
  `--signal-dim` is never used as text. This is tree-wide by nature, so it clears every route's axe
  contrast violations, not only `/`'s.
- **Status honesty** (v39 amendment A3, F04). The Waterfall and header never read "idle" while
  tracks are waiting behind a tripped breaker; that state is shown as a deliberate hold with its
  release time. (The per-track countdown half of F04 is v41's.)
- **Offline / reconnecting state** (v39 amendment A3, F05). A dropped SSE stream must look
  different from a connected one: a visible live/reconnecting tell, designed here. v47 still
  hardens it.
- **Panel material** (§8.1 gap: the "matte charcoal chassis" never reads against the near-black).
  Resolve it with impeccable, or record that the approved direction drops the chassis idea.
- **Breakpoints.** Add at least one tablet breakpoint beyond today's single 640px (`adapt`). The
  header, controls and job rows have to read well at about 390, 768, 1024 and 1440 widths.
- **The Waterfall keeps its meaning** (v23's glitch fix and v34's hydration must survive
  unchanged in behavior). §8.2's "lanes not a spectrogram" stays deliberate, unless v39's
  direction says otherwise. The idle noise floor and "busy elsewhere" distinction stay.
- **QueueControls density.** This is where "cluttered" is most likely on the dashboard: group and
  prioritize the controls (`distill`), keeping every capability. Admin-only controls stay hidden
  for non-admins.
- **Consistency with v41.** The job list and its rows already changed in v41. v42 aligns
  everything around them, and doesn't reopen them except for v39 findings that span both.
- **v40's ambient field** must still read correctly behind the redesigned panels.
- **Semantics for v45.** Landmarks (`header`, `main`, `nav`), one `h1`, a heading hierarchy, and
  labelled groups. Add an element id or landmark v45's skip link can target.

## Out of scope

- `/settings`, `/library`, `/account`, `/login` (v43).
- Destructive-action confirmations, which are designed in v43 for both "clear log" and "remove
  proxy". v42 leaves "clear log"'s behavior untouched.
- Shortcuts (v45).

## Done when

- [ ] impeccable was loaded, and its sub-commands and output recorded in the PR.
- [ ] Every v39 finding assigned to v42 is marked fixed or deferred with a reason.
- [ ] Before and after screenshots of `/` at 390, 768, 1024 and 1440 widths: idle, receiving (a live
      Waterfall), with an incoming job, with a failed incoming job, empty, loading, the error
      state, and the admin all-users view. Real dev data.
- [ ] The contrast tokens pass: an impeccable `audit` (axe) shows no `color-contrast` violations
      on `/`, and the new `--text-dim`/`--line` ratios are listed in the PR.
- [ ] Screenshots of `/` with the breaker tripped (no "idle" anywhere) and with the SSE stream
      dropped then recovered (the tell appears, then clears).
- [ ] The type scale tokens exist and are the only font sizes in v42's files (grep for
      `font-size:` literals in those files).
- [ ] The panel material decision is recorded in DESIGN.md and visible in the screenshots.
- [ ] Waterfall behavior is unchanged: v34's reload-hydration spec and a live receiving check pass,
      and there is no appear/disappear glitch (watch one failing-then-retrying track live).
- [ ] Landmarks and heading outline are verified (an accessibility-tree screenshot, or an
      impeccable `audit`), with no regressions vs v39's baseline.
- [ ] The v37 e2e suite passes on both projects (selector updates by role/name only).
- [ ] `npm run lint`, `npm run check` and `npm run build` pass, and `pytest` passes. Both version
      files read `4.42.0`. `uv lock` is in sync. `graphify update .` has been run.
