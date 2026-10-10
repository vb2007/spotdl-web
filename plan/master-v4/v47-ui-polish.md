# v47 — UI Polish & Design-System Record

Branch: `dev-ui-polish` → PR into `main`
Version: `4.47.0`

## Scope

The closing pass on master v4's UI work, **strictly through the impeccable skill**, the same role
impeccable's own `polish` plays before shipping. It covers everything v39 assigned to v47, the
residue v40–v46 deferred, and the system-wide consistency no single slice owned.

## Tasks

1. **`polish`** across every route and component: spacing rhythm, alignment, micro-interactions,
   and consistent hover, focus and active states. Remaining ad hoc font sizes migrate to v42's type
   scale tree-wide, so `grep 'font-size:'` finds only token definitions.
2. **`harden`**: error, empty, loading and offline states everywhere. Very long titles, artist lists
   and error messages. Non-ASCII (this library is full of it). **Both languages:** every surface in Hungarian (v46), whose strings run longer than English, with no truncation, overflow or awkward wraps. A 1000+ job account. The SSE stream
   dropped and recovering. A session expiring mid-page.
3. **Re-run `critique` and `audit`** on the full v39 surface list, desktop and mobile, in **both `en` and `hu`**. Put a
   **before/after score table against v39's report** in the PR. Every v39 finding is resolved,
   or deferred with a reason, or won't-fix as v39 decided. Close the loop explicitly per row.
4. **`document`**: regenerate `frontend/src/DESIGN.md` (and `design-tokens.json`) from the shipped
   UI, per impeccable's documenter. Keep DESIGN.md's prior decision records (the "why"s) and §8's
   known-gaps convention. Use dated notes for anything that changed meaning (amber exclusivity,
   the panel material, the type scale), rather than silently overwriting.
5. Fix anything the re-audit finds, within a bounded pass, as impeccable's own "bounded passes,
   not a loop" rule says: one inspection round, one fix batch, at most one confirming round.

## Out of scope

- New features or new surfaces. Anything that isn't polish gets logged for a future master.
- Backend changes.

## Done when

- [ ] impeccable was loaded, and `polish`, `harden`, `critique`, `audit` and `document` were each
      run, with output recorded.
- [ ] The before/after score table vs v39's report covers every surface. Every v39 finding row has
      a final status.
- [ ] No `font-size` literal outside the token definitions (grep output).
- [ ] The hardening cases are each screenshotted: a long title and non-ASCII text, 1000+ jobs
      (seed via the API on dev), the SSE drop and recovery, and session expiry.
- [ ] DESIGN.md was regenerated, with prior decision records preserved and dated notes for every
      changed rule (diff reviewed in the PR).
- [ ] Every keyboard journey from v45 still passes (including the Hungarian QWERTZ emulation), and the v37 e2e suite passes on both projects plus v46's `hu` smoke project.
- [ ] Hungarian screenshots of every route at 390 and 1440 widths show no overflow or truncation.
- [ ] `npm run lint`, `npm run check` and `npm run build` pass, and `pytest` passes. Both version
      files read `4.47.0`. `uv lock` is in sync. `graphify update .` has been run.
