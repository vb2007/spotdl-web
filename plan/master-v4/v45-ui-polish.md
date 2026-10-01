# v45 — UI Polish & Design-System Record

Branch: `dev-ui-polish` → PR into `main`
Version: `4.45.0`

## Scope

The closing pass on master v4's UI work, **strictly through the impeccable skill**, the same role
impeccable's own `polish` plays before shipping. It covers everything v38 assigned to v45, the
residue v39–v44 deferred, and the system-wide consistency no single slice owned.

## Tasks

1. **`polish`** across every route and component: spacing rhythm, alignment, micro-interactions,
   and consistent hover, focus and active states. Remaining ad hoc font sizes migrate to v41's type
   scale tree-wide, so `grep 'font-size:'` finds only token definitions.
2. **`harden`**: error, empty, loading and offline states everywhere. Very long titles, artist lists
   and error messages. Non-ASCII (this library is full of it). A 1000+ job account. The SSE stream
   dropped and recovering. A session expiring mid-page.
3. **Re-run `critique` and `audit`** on the full v38 surface list, desktop and mobile. Put a
   **before/after score table against v38's report** in the PR. Every v38 finding is resolved,
   or deferred with a reason, or won't-fix as v38 decided. Close the loop explicitly per row.
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
- [ ] The before/after score table vs v38's report covers every surface. Every v38 finding row has
      a final status.
- [ ] No `font-size` literal outside the token definitions (grep output).
- [ ] The hardening cases are each screenshotted: a long title and non-ASCII text, 1000+ jobs
      (seed via the API on dev), the SSE drop and recovery, and session expiry.
- [ ] DESIGN.md was regenerated, with prior decision records preserved and dated notes for every
      changed rule (diff reviewed in the PR).
- [ ] Every keyboard journey from v44 still passes, and the v37 e2e suite passes on both projects.
- [ ] `npm run lint`, `npm run check` and `npm run build` pass, and `pytest` passes. Both version
      files read `4.45.0`. `uv lock` is in sync. `graphify update .` has been run.
