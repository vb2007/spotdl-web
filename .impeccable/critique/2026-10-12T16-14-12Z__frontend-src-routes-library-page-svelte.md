---
target: /library
total_score: 25
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
timestamp: 2026-10-12T16-14-12Z
slug: frontend-src-routes-library-page-svelte
---
Method: dual-agent (A: design-review sub-agents A1/A2 · B: detector+browser sub-agent). Full report: plan/master-v4/v39-ui-audit-report.md

### 3.6 `/library` (`shots/43` idle, `45-*` mid-sweep, `46` after, `22` non-admin)

- **Idle looks like a sweep in progress.** At idle, a full 100% amber bar from the previous run stays
  on screen (`:101`). It looks exactly like a running sweep, and "Last sweep" has no timestamp. (F20)
- **No confirmation or preview before the sweep.** START SWEEP moves real files with one click. The
  button is also enabled for non-admins (`shots/22`), and there is no cancel. (F08, F20)
- **Mid-sweep hides the details.** The previous report disappears, and the live
  moved/quarantined counts aren't shown, even though the SSE payload carries them. (F20)
- **Accessibility.** The progressbar is unnamed (axe `aria-progressbar-name`, serious), and progress
  isn't announced. (F16)
- **Error list.** The same error row appears twice ("/downloads/01 - Rick Astley - … — source file
  missing on disk", `shots/45-1`, `46`), and it has no recovery guidance. (F20; backend half in F34)
- **No reconnect.** The library SSE has no `onerror`, so a 502 during an api restart freezes progress
  mid-sweep (`:41-66`). (F20)
- **Sweeps archive jobs silently.** A sweep archives settled jobs for *every* user, and the report
  never says so. This is v28 behavior; see F34.
