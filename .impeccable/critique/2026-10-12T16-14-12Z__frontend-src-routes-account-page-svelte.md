---
target: /account
total_score: 25
max_score: 36
na_heuristics: 7
p0_count: 0
p1_count: 0
timestamp: 2026-10-12T16-14-12Z
slug: frontend-src-routes-account-page-svelte
---
Method: dual-agent (A: design-review sub-agents A1/A2 · B: detector+browser sub-agent). Full report: plan/master-v4/v39-ui-audit-report.md

### 3.7 `/account` (`shots/20`, `44`)

- **Calm and honest.** The retention copy says archived jobs are "never deleted… can always be
  restored". 0 of 8 cognitive-load checks fail.
- **Name/label mismatch.** `aria-label="Archive after this many days of inactivity"` overrides the
  visible label "After (days)", which fails WCAG 2.5.3 (`:114`). (F30)
- **Thin identity.** It shows only the username. The email is in a `title` tooltip, which touch users
  can't reach. There is no logout here, and no admin tag. (F31)
- **Small inconsistencies.** The pressed chip is amber, and the copy uses an ASCII "--" where other
  pages use "—" (`:76`). (F10, F31)
