# v70 — Master v5 Hardening & Close

Branch: `dev-v5-hardening` → PR into `main`
Version: `5.70.0`
Wave / slot: 6 / 1 (serial, last)
Depends on: every v49–v69 slice merged

## Scope

The production close, in the same role v13, v22, v31 and v48 played, with one v5-specific worry
added: **parallel development.** Twenty-one slices were built side by side and rebased onto each
other. Failures between them are more likely than in any earlier master: a migration re-parented
wrongly, a hotspot conflict resolved by dropping a line, two slices' assumptions about
`queue.ts` or `jobs.py` colliding. The close looks exactly there.

## Tasks

1. **Integration integrity.**
   - `alembic heads` returns exactly one head.
   - A full `downgrade base` → `upgrade head` round trip on a fresh slot DB.
   - A diff of `messages/en.json` vs `hu.json` key sets (parity).
   - Every v5 GOTCHAS heading exists, with an index line.
   - `graphify update .` is clean.
2. **The cross-user separation sweep:** `pytest backend/tests/test_ownership.py` plus the gating
   suites (CLAUDE.md's v2 invariant list, plus v53's keys, v54's views, v56's single-track GET and
   admin rule, v59's alert history, v63's watch and re-expand, v64's export, v65's share, v66's
   my-stats and notification preference, v69's allowlist endpoints), **and**
   `scripts/verify_separation_sse.sh` (including v54's `others` case and v69's revocation case: a
   removed user's open stream ends, the admin's stays) against a running stack. Cover direct-id
   endpoints. Non-owner gets 404, and admin endpoints follow v56's rule.
3. **The key boundary:** a parametrized test asserting an API key is rejected or treated as
   non-admin on **every** route except the two it's allowed on. A new route added without
   considering keys must fail this test by default (deny-by-default check).
4. **The full e2e** on desktop, mobile and `hu`, plus the keyboard journeys and the Hungarian
   QWERTZ emulation, on a slot stack.
5. **A full extension pass:**
   - the signed XPI from v61 installed in release Firefox against **production** (real Spotify,
     a test identity);
   - every target type and cascade;
   - the cookie path and the key fallback;
   - auto-update confirmed from the latest release.
6. **A production smoke** in a real browser with a test identity: every route, `/share`
   (emulated), export of a small job, my stats, notifications, and `/users` (add and remove a test
   address, confirming the removed identity is logged out live).
7. **Pipeline record:** every "Release & Deploy", manual Publish & Deploy and extension-release run
   since v49, with outcome and whether its notice arrived (P1's fix proven in production if any
   failure happened). v49's rule holds across the whole master: **no run was skipped or cancelled**,
   and no `workflow_run` crept back in (a `gh run list` count by conclusion, plus a grep). Also
   whether logs from before the last deploy are readable (O3).
8. **Ledger re-confirmation:** walk `00-master-plan.md`'s open-items ledger row by row. Each row is
   either fixed (pointer to its PR and evidence) or, for "accepted" rows, re-confirmed with the
   owner (ask in the PR). Nothing may stay silently open. Anything found to have regressed gets
   fixed here, if it's a regression of a v5 change.
9. **Owner housekeeping:** ask about each unchecked item in the master plan's list, and record the
   answers.
10. **Docs reconciliation:**
    - `CLAUDE.md` (≤250 lines; status, roadmap, any changed invariant: the admin 403/404 rule, the
      key boundary, the extension, agent stacks);
    - `README.md`, `docs/LOCAL_DEV.md`, `docs/DEPLOYMENT.md`, `docs/RELEASE_PIPELINE.md`,
      `docs/EXTENSION.md`;
    - `PRODUCT.md` (the extension, PWA and notifications now exist).
11. **The closing re-read:** every Done-when bullet of v49–v69, fresh, against merged code and PR
    evidence. Each one is re-evidenced, re-verified, or declared a known gap here.
12. **Clean up agent artifacts:** stale worktrees, slot stacks and volumes, and leftover realdl
    lock files on the dev machine (list them before removing; ask before deleting anything not
    clearly an agent artifact).

## Out of scope

New features. Anything found that isn't a regression of a v5 change is logged for a future master.

## Done when

- [ ] **Integrity:** one Alembic head; a clean round trip on a fresh DB; message key parity;
      GOTCHAS index complete (each with output).
- [ ] The cross-user sweep and `verify_separation_sse.sh` pass. The per-endpoint non-owner table is
      listed.
- [ ] The key deny-by-default test exists and passes, and fails for a deliberately unguarded
      scratch route (shown, then removed).
- [ ] The e2e suite plus the keyboard and QWERTZ journeys pass on all projects.
- [ ] The extension pass against production is evidenced (screenshots per target type and
      cascade, the auth paths, the update check).
- [ ] The production smoke is evidenced by screenshots.
- [ ] The pipeline record table is in the PR, with zero skipped or cancelled runs since v49 (or
      each one explained).
- [ ] **Ledger:** every row has a final status in the PR, with accepted rows' owner
      re-confirmation linked.
- [ ] Housekeeping answers recorded. Docs reconciled. `CLAUDE.md` ≤ 250 lines.
- [ ] The closing re-read is done for every v49–v69 bullet.
- [ ] Agent artifacts listed and cleaned (`git worktree list`, `docker compose ls`, `docker volume
      ls` before and after).
- [ ] `pytest`, `npm run lint`, `npm run check`, `npm run build` and `npm run test:e2e` pass. Both
      version files read `5.70.0`. `uv lock` is in sync. `graphify update .` has been run.
