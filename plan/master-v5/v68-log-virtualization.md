# v68 — Virtualized Job & Track Lists

Branch: `dev-log-virtualization` → PR into `main`
Version: `5.68.0`
Wave / slot: 5 / 2
Depends on: waves 0–4 merged

## Scope

Ledger item **U4** (DESIGN §8.6): a fully loaded 1600-row log is about 28k DOM nodes. That was
accepted in v47 because "virtualizing is the real fix and out of polish scope". The lists keep
growing (watched jobs, v63). This version virtualizes the job list, the tracks-scope list and an
expanded job's track list, **without breaking anything built on them**:

- v45's roving tabindex (by row **id**), `Home`/`End`/`Shift+G` with load-more, and focus
  restoration after removal or load-more;
- v34's live hydration and SSE patching, and v40.2's in-place patching;
- v41's expanded track detail (variable height);
- v37's e2e selectors, which assume rows exist in the DOM;
- the help overlay and screen-reader semantics.

## Design

- **A small in-house windowing component**, or a vetted Svelte 5-compatible library (pinned).
  Choose by: variable row heights (expanded rows), measuring without layout thrash, and keeping
  `scroll anchoring` stable during SSE patches. Record the choice and the alternatives tried.
- **A threshold:** below N rows (e.g. 200), render normally. Virtualize only above it, so small
  accounts and most e2e flows see a plain list.
- **Keyboard:**
  - the roving focus moves by **id**;
  - moving focus to a not-rendered row scrolls it into the window first, then focuses it;
  - `End`/`Shift+G` on the last loaded row still triggers load-more;
  - focus restoration after a row is removed works even if the neighbor isn't rendered.
- **Accessibility:** `role="list"`/`listitem` semantics stay correct. `aria-setsize`/`aria-posinset`
  convey the full count, so a screen reader announces "row 812 of 1600".
- **Find-in-page:** Ctrl+F can't find off-window rows. The app's own search (`/`/`f`) is the
  answer. Record this trade in DESIGN.md §8 as an accepted consequence.
- **e2e:**
  - a seeded 1600-job fixture account (API seeding on the slot DB);
  - specs for scroll, keyboard traversal across the window boundary, and an SSE patch to an
    off-window row (no crash, correct when scrolled into view);
  - existing specs keep passing, since they run below the threshold, or are updated by role/name.

## Files owned

`frontend/src/routes/+page.svelte` (list rendering only), `frontend/src/lib/components/JobTrackList.svelte`,
new `frontend/src/lib/components/VirtualList.svelte` (or similar), `frontend/src/lib/keyboard/lists.ts`,
`frontend/src/lib/stores/queue.ts` (only if a windowing hook is needed), `frontend/e2e/**` (new
specs and seeding), `frontend/src/DESIGN.md` (§8.6 note only; v67 owns the rest of the file in the
same wave, so keep to that section).

## Done when

- [ ] With a 1600-job seeded account on the nginx build: DOM node count before and after (devtools
      `document.querySelectorAll('*').length`), a scrolling Performance profile showing no long
      frames, and memory before and after.
- [ ] **Keyboard:** `j`/`k` from row 1 to row 300 crosses the window with focus always visible, and
      `End` → load-more → focus on the first new row (e2e). The roving list is still one Tab stop
      (e2e count).
- [ ] **Focus restoration:** archiving the focused row at a window edge moves focus to the right
      neighbor (e2e).
- [ ] **Live:** an SSE update to an off-window job, scrolled into view, shows the new state. No
      console error (e2e).
- [ ] **Expanded rows:** expanding a track deep in the list keeps scroll position stable, and its
      detail renders fully (recording).
- [ ] **Screen reader:** the accessibility tree shows `aria-setsize`/`aria-posinset` correct for a
      row deep in the list.
- [ ] Below the threshold, the DOM is unchanged from main (snapshot of row markup).
- [ ] Full e2e is green on desktop, mobile and `hu`, plus the new specs.
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `5.68.0`. `uv lock` is in sync. `graphify update .` has been run.
