---
target: "v67 before: dashboard + error"
total_score: 29
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 1
timestamp: 2026-11-02T09-04-59Z
slug: frontend-src-routes-page-svelte
---
Method: dual-agent (A: design review sub-agent A1 · B: detector sub-agent), v67 "before" pass.

## Design Health Score — dashboard `/` (others view v54, watch/retry v63, export v64) and `+error` (v62)
| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | one-track active jobs show only a grey bar; watch reading wraps in the bar column |
| 2 | Match System / Real World | 3 | "done — partial" on a one-track not-found job; "no signal" idle label; hu "indulásra kész" |
| 3 | User Control and Freedom | 3 | admin cancel of another user's job gives wrong advice ("submit again") |
| 4 | Consistency and Standards | 3 | cancel mid-cluster on the open job row; owner tag styled like the type tag |
| 5 | Error Prevention | 3 | full-width cancel per phone row invites mis-taps |
| 6 | Recognition Rather Than Recall | 3 | watch/check-now hidden until a row opens |
| 7 | Flexibility and Efficiency | 3 | strong keyboard layer; no bulk actions |
| 8 | Aesthetic and Minimalist Design | 2 | phone rows a wall of buttons (U5); tracks scope doubles titles (U3) |
| 9 | Error Recovery | 3 | +error good |
| 10 | Help and Documentation | 3 | help overlay excellent |
| **Total** | | **29/40** | **Good** |

Design specificity: authored (console prompt, waterfall, link tell, condition colours held through v5); the v63/v64 controls arrive as flat form chrome.
Detector: CLI `[]`; browser: no real defects on `/` beyond deliberate live-state motion; false positives from the injected script.
Priority issues: [P1] phone row action wall (U5); [P1] admin cancel of others' job; [P2] open-row action grouping; [P2] copy U6; [P2] U3 title repetition. U13 not reproduced (0px overflow at 320, en/hu, all views).
