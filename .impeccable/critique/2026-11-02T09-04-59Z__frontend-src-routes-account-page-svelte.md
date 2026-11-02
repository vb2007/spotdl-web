---
target: "v67 before: account + share"
total_score: 28
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 1
timestamp: 2026-11-02T09-04-59Z
slug: frontend-src-routes-account-page-svelte
---
Method: dual-agent (A: design review sub-agent A2 · B: detector sub-agent), v67 "before" pass.

## Design Health Score — `/account` (API keys v53, install v65, notifications v66) and `/share` (v65)
| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | blocked-notifications state styled as ordinary hint |
| 2 | Match System / Real World | 2 | /share confirms a bare Spotify ID; install shows an epoch build number |
| 3 | User Control and Freedom | 3 | fresh API key lost silently on leaving the page |
| 4 | Consistency and Standards | 3 | panel h2 visually weaker than h3 groups; installed state headed "Install the app" |
| 5 | Error Prevention | 2 | share confirms without name or size; no guard on an uncopied key |
| 6 | Recognition Rather Than Recall | 3 | |
| 7 | Flexibility and Efficiency | 3 | fully keyboard-operable |
| 8 | Aesthetic and Minimalist Design | 3 | build number noise; 1100px preferences panel on phone |
| 9 | Error Recovery | 3 | |
| 10 | Help and Documentation | 3 | no link to get the extension |
| **Total** | | **28/40** | **Good** |

Detector: CLI `[]`; browser: hu `#retention-mode-label` all-caps (the `.label` idiom); /share "not now" link 20px on touch (audit).
Priority issues: [P1] /share bare ID (needs a backend lookup: out of refinement scope); [P2] uncopied key guard; [P2] signed-out share login gives no hint; [P2] install buried + raw build; [P3] preferences panel overloaded.
