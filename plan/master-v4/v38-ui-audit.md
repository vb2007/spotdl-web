# v38 — UI/UX Audit (impeccable)

Branch: `dev-ui-audit` → PR into `main`
Version: `4.38.0` only if the slice touches `frontend/` (e.g. `frontend/src/DESIGN.md`).
Otherwise no bump. State which in the PR.

## Scope

The owner finds the UI cluttered. Evaluate the whole frontend **strictly through the impeccable
skill** before any redesign, so v39–v42 are scoped by evidence rather than taste, and v46 has a
baseline to score against. The same role v14's audit played for master v2.

**No component or style changes in this slice.** The deliverable is a report. The only
`frontend/` edits allowed are impeccable's own context files, when its `context.mjs` flags them as
stale.

## Tasks

1. **Load the impeccable skill** and run its Setup:
   `node <skill-base-dir>/scripts/context.mjs`, so PRODUCT.md and `frontend/src/DESIGN.md` are
   loaded.
   - If it reports `CONTEXT_STALE`, run only the refresh it names (`init`/`document`), and record
     it.
   - The mode for every surface is **Operate** (app UI). Record it in the surface briefs.
2. **`critique`** every surface on the real running stack (dev database, real data, both an admin
   and a non-admin identity), desktop and mobile:
   - `/`: header, submit, IncomingJobs, Waterfall, QueueControls, the jobs scope list, the tracks
     scope list;
   - an expanded job, and an expanded track. For the track, specifically: a first-try success
     (the owner's screenshot), 5+ failure attempts, waiting with countdown, lookup_failed, and a
     completed track with a tag-repair warning;
   - `/settings`, `/library` (idle and mid-sweep), `/account`, `/login`;
   - empty, loading, error and offline (SSE dropped) states.
3. **`audit`** the same surfaces: accessibility (contrast, focus order, names/roles, keyboard
   reachability as a baseline for v44), performance, responsive behavior, anti-patterns.
4. **Write `plan/master-v4/v38-ui-audit-report.md`**:
   - **Per surface:** impeccable's scores and findings, with screenshots attached or listed (the
     screenshots themselves are gitignored or kept in the PR body; don't commit binaries unless
     small).
   - **A ranked findings table:** severity, surface, finding, and **assigned slice**: v39 ambient
     background, v40 track/job detail, v41 dashboard, v42 secondary surfaces, v44 keyboard, v46
     polish, or "won't fix" with a reason.
   - **These already-known items must appear,** confirmed or refuted:
     - the TrackRow detail is indented 9rem while the title column starts at 10.25rem;
     - inline and full-width detail items are mixed;
     - JobRow (flex) and TrackRow (grid) don't align, with no nesting indent;
     - there is no type scale (DESIGN.md §3);
     - the panel "chassis" is imperceptible (§8.1);
     - the 640px breakpoint is the only one;
     - the static amber body glow conflicts with the amber-is-live rule (§2);
     - "passes attempted: 0" (fixed in v35, so confirm it's gone);
     - destructive actions without confirmation (clear log, remove proxy);
     - every TrackRow is a separate tab stop.
   - **A "design direction" section:** what impeccable recommends keeping (the signal-receiver
     world, the IBM Plex pairing, the state-color semantics) vs reconsidering. This tells v39–v42
     whether each is a **refinement** (keep the identity) or a **redesign** (replace the world).
     That's impeccable's own distinction; follow it. **The owner approves the direction in the PR
     before v39 starts.**
5. If the audit finds that a planned slice's scope is wrong (too big, missing a surface, or
   unnecessary), record it as an amendment proposal in the report. Don't edit v39–v46's plans
   yourself.

## Out of scope

- Any fix, even a one-line contrast tweak. It gets logged and assigned.
- Keyboard shortcut design (v44). The audit only records today's reachability.

## Done when

- [ ] impeccable's `context.mjs` was run, and its output (or `CONTEXT_STALE` handling) recorded.
- [ ] A `critique` was run for **every** surface and state listed in task 2, on desktop and mobile,
      against the real stack, with the impeccable output captured per surface.
- [ ] An `audit` was run for the same set, with output captured.
- [ ] `v38-ui-audit-report.md` exists, with per-surface sections, the ranked table (every row has
      an assigned slice or a won't-fix reason), and the design-direction section.
- [ ] Every one of the ten already-known items is present, with a confirmed or refuted verdict.
- [ ] `git diff main --stat` shows no component, route or style changes (only the report, plus
      any impeccable context refresh).
- [ ] The v37 e2e suite still passes (unchanged code, but proves the stack used was healthy).
- [ ] The owner's direction approval is requested in the PR body. Version handling is as stated in
      the header, and `graphify update .` has been run.
