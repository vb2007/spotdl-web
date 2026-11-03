---
target: "v67 before: stats + library"
total_score: 27
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 1
timestamp: 2026-11-02T09-04-59Z
slug: frontend-src-routes-stats-page-svelte
---
Method: dual-agent (A: design review sub-agent A3 · B: detector sub-agent), v67 "before" pass.

## Design Health Score — `/stats` (my stats v66, alert history v59) and `/library` sweep cancel (v57)
| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | crosshair readout pointer-only |
| 2 | Match System / Real World | 2 | user page counts attempts under "Tracks"; machine failure names (U14) |
| 3 | User Control and Freedom | 3 | |
| 4 | Consistency and Standards | 3 | disabled buttons used as status on /library |
| 5 | Error Prevention | 3 | |
| 6 | Recognition Rather Than Recall | 3 | failure classes never explained |
| 7 | Flexibility and Efficiency | 2 | charts pointer-only (U10); no page shortcuts |
| 8 | Aesthetic and Minimalist Design | 3 | repeated legends |
| 9 | Error Recovery | 3 | |
| 10 | Help and Documentation | 2 | no explanation of failure classes |
| **Total** | | **27/40** | **Acceptable** |

Detector: CLI `[]`; browser: real — `span.name.mono` clipped +28px at 390 (U14 root cause: flex container, anonymous text item), user rate definition ~103ch/line; false positives — axis ticks, sr-only thead occlusion, injected-script rules.
Priority issues: [P1] user stats speak operator language; [P2] U14 clipping; [P2] U10 keyboard crosshair; [P2] user page opens on 0 files, ends on failures; [P3] /library disabled-button status.
