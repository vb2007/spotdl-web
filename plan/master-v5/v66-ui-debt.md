# v66 — UI Debt & New-Surface Audit (impeccable)

Branch: `dev-ui-debt` → PR into `main`
Version: `5.66.0`
Wave / slot: 5 / 1
Depends on: waves 0–4 merged

## Scope

Ledger items **U2, U3, U5–U13**: UI gaps v39's audit and v47's polish logged but didn't close
(DESIGN.md §8's open entries, #69's lists). Plus an **impeccable critique and audit of every
surface master v5 added**: `/account`'s API keys section (v52), the others view (v53), the sweep
cancel (v56), alert history (v58), `+error` (v61), the watch, retry and export controls
(v62/v63), `/share` and install (v64), notifications and my stats (v65). All of it goes
**strictly through the impeccable skill** (`critique`/`audit` first, then the sub-commands its
findings call for), as a **refinement** of the existing world (v39's approved direction), not a
redesign.

v67 (same wave) owns list virtualization and the job/track list container. v66 must **not** touch
the list rendering in `+page.svelte`/`JobTrackList.svelte`, or the roving-focus code.

## Items

- **U2:** `/settings` is about 4000px tall on a phone. Section navigation (sticky in-page TOC or
  collapsible sections) and denser forms (`adapt`/`layout`). Every setting stays reachable by
  keyboard.
- **U3:** the tracks scope repeats the job title on every row (§8.5). Group headers carry the title;
  rows don't.
- **U5:** every phone job row carries a full archive button. Move it into a row overflow (keyboard
  and screen-reader complete), or show it only on the expanded row.
- **U6: copy** (`clarify`, en and hu):
  - "done — partial" on a one-track not-found job (say "not found");
  - the Hungarian "indulásra kész", which reads as "done";
  - the ambiguous "no signal".

  List each old → new string in the PR for owner review.
- **U7:** remove the unused tokens (`--signal-ink`, `--fail-dim`, `--space-7`), or use them where
  intended (grep proves no references remain).
- **U8:** per-locale message chunks. Paraglide output split so a user downloads only their
  language. Measure bundle size before and after.
- **U9:** WCAG 3.1.2: every English-only fragment inside a Hungarian page (raw backend errors,
  track metadata, attempt messages) is wrapped with `lang="en"` where its language is known.
  Metadata stays unmarked if its language is unknown, with the rationale in DESIGN.md.
- **U10:** the stats chart crosshair is pointer-only. Make it keyboard-operable (arrow keys step
  through buckets, with a live-region readout).
- **U11:** a drag released outside the window can leave the ambient glow stranded. Handle
  `pointerup`/`pointercancel`/`blur` on the window.
- **U12:** resolve the `/stats` surface brief's `## Unresolved` section, so no `Unresolved` remains
  in `frontend/src/.impeccable/surfaces/`.
- **U13:** re-verify the 320px admin view's horizontal scroll (#58). Fix if still present.
- **New-surface audit:** run impeccable `critique` and `audit` on each v52–v65 surface, desktop and
  mobile, en and hu. Fix findings within refinement scope. Log anything larger in the PR's
  "Found, not fixed".
- Close the matching DESIGN.md §8 entries with dated notes. Keep the known-gaps convention.

## Files owned

`frontend/src/routes/{settings,account,stats,library,share}/+page.svelte` (layout and copy, not
behavior), `frontend/src/lib/components/{JobRow,TrackRow,QueueControls,AmbientField}.svelte`
(non-list-container parts), `frontend/src/lib/components/stats/*`, `frontend/src/app.css`,
`frontend/design-tokens.json` (wherever it lives), `frontend/src/DESIGN.md`,
`frontend/src/.impeccable/**`, the Paraglide config (U8), message JSONs (hotspot).
**Not:** `routes/+page.svelte`'s list rendering, `JobTrackList.svelte`, `lib/keyboard/lists.ts`
(v67).

## Done when

- [ ] impeccable was loaded, and its `critique`/`audit` output recorded for every surface listed,
      with before and after scores.
- [ ] **U2:** `/settings` at 390px is measured before and after (page height), and every setting
      is reachable keyboard-only (e2e).
- [ ] **U3/U5/U13:** before and after screenshots at 320/390/768/1440.
- [ ] **U6:** the old → new string table is in the PR, both languages updated, and the key-parity
      check passes.
- [ ] **U7:** grep shows no unused token.
- [ ] **U8:** the network panel shows only the active locale's messages loaded. Bundle sizes before
      and after are recorded.
- [ ] **U9:** an accessibility-tree check shows `lang="en"` on English fragments in a `hu` page.
- [ ] **U10:** the chart is operable by keyboard with the readout announced (accessibility tree
      plus an e2e step).
- [ ] **U11:** a drag-out-then-release-outside leaves no stranded glow (a manual recording or a
      Playwright pointer sequence).
- [ ] **U12:** no `Unresolved` heading remains in the surface briefs (grep).
- [ ] DESIGN.md §8 entries closed with dated notes.
- [ ] Full e2e is green on desktop, mobile and `hu`, including v45's keyboard journeys and the
      Hungarian QWERTZ emulation.
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `5.66.0`. `uv lock` is in sync. `graphify update .` has been run.
