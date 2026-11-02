---
target: "v67 after: stats + library + settings"
total_score: 29
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 0
timestamp: 2026-11-02T10-04-33Z
slug: frontend-src-routes-stats-page-svelte
---
Method: dual-agent (A: design review sub-agent A3 · B: detector sub-agent), v67 "after" pass (before the after-critique fix round).

## Design Health Score — `/stats`, `/library` sweep, `/settings` on a phone
| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | |
| 2 | Match System / Real World | 2 | user "Tracks" counts attempts (pre-existing, v66) |
| 3 | User Control and Freedom | 3 | |
| 4 | Consistency and Standards | 3 | chart keys under "In a list" (fixed after) |
| 5 | Error Prevention | 3 | |
| 6 | Recognition Rather Than Recall | 3 | hu class label clipped at 390 (fixed after) |
| 7 | Flexibility and Efficiency | 3 | charts by keyboard now |
| 8 | Aesthetic and Minimalist Design | 3 | |
| 9 | Error Recovery | 3 | |
| 10 | Help and Documentation | 3 | chart keys in the help overlay |
| **Total** | | **29/40** | **Good** (before: 27/40) |

Audit (after): 18/20 Excellent (before: 16/20); P2 charts exposed as images (fixed after: role=slider).
Fixed in the round after this pass: tap reading, chart keys' help rows, Esc in the hint, hu label fit, mono on words, 44px summaries, SW language chunk on first visit.
