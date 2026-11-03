---
target: "v67 after: dashboard + error"
total_score: 31
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 0
timestamp: 2026-11-02T10-04-33Z
slug: frontend-src-routes-page-svelte
---
Method: dual-agent (A: design review sub-agent A1 · B: detector sub-agent), v67 "after" pass (before the after-critique fix round).

## Design Health Score — dashboard `/` and `+error`
| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | "active" jobs with idle bars under "quiet — nothing downloading" |
| 2 | Match System / Real World | 3 | "check now" doesn't say what it checks |
| 3 | User Control and Freedom | 3 | the other-user cancel now names the owner; Esc returns focus |
| 4 | Consistency and Standards | 3 | active / in progress / pending for one situation |
| 5 | Error Prevention | 3 | "clear log" armed in the others view |
| 6 | Recognition Rather Than Recall | 3 | watch/check-now hidden until open |
| 7 | Flexibility and Efficiency | 4 | full QWERTZ keymap incl. v63/v64 keys |
| 8 | Aesthetic and Minimalist Design | 3 | admin closed desktop rows carry operator controls |
| 9 | Error Recovery | 3 | |
| 10 | Help and Documentation | 3 | |
| **Total** | | **31/40** | **Good** (before: 29/40) |

Detector: CLI `[]`; browser: no new real defects (live-state motion sanctioned; injected-script false positives).
Fixed in the round after this pass: the open row's cancel orphaned when the line wraps; a desktop one-track tracks row's empty title column.
