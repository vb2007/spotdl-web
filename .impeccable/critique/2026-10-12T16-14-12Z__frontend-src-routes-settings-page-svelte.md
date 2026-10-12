---
target: /settings
total_score: 21
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
timestamp: 2026-10-12T16-14-12Z
slug: frontend-src-routes-settings-page-svelte
---
Method: dual-agent (A: design-review sub-agents A1/A2 · B: detector+browser sub-agent). Full report: plan/master-v4/v39-ui-audit-report.md

### 3.5 `/settings` (`shots/42` admin, `shots/21` non-admin)

**Strengths**

- The worker strip sits at the top with a live breaker countdown, and its color meaning matches the
  dashboard.
- Proxy rows carry real operational data with redacted credentials.
- Client-side proxy-URL validation mirrors the backend regex.

**Issues**

- **One-click risky actions.**
  - Proxy "remove" is a permanent DELETE (`:268-282, 583-590`).
  - "release now" resumes downloads while the app is still rate-limited (`WorkerStatus.svelte:86`).
  - On mobile, "remove" sits about 12px from the "enabled" toggle, both about 22px tall. (F08)
- **Broken for non-admins (`shots/21`).** The four admin sections render and error, show "Admin access
  required" four times, and "Loading options…" never resolves. The page states "No proxies configured
  — every attempt goes out direct", which is false because 5 exist: a failed load is treated as an
  empty list (`:554-557`). A stray divider also renders (`WorkerStatus.svelte:141-144`). (F17)
- **The Alerts panel is off-system.** It has no padding, because `.alert-settings` is missing from the
  selector at `:654-656`, and its number inputs keep the browser's grey styling (`:742`). This was
  confirmed by the detector (cramped-padding) and the audit. (F18)
- **Amber on chrome.** The pressed option chips are `--signal` (`:727-730`), so seven amber chips sit on
  one screen. SAVE and ADD glow amber on hover. (F10)
- **Ambiguous toggles.**
  - All five proxy toggles are named "enabled", with no proxy in the name.
  - The text flips *and* `aria-pressed` is set, so a screen reader hears "disabled, not pressed".
  - "disabled" reuses `--fail`.
  - The pause button reads "resume, pressed" (`:573-581`, `WorkerStatus.svelte:67-75`). (F30)
- **Stale feedback.** "Saved." never clears after further edits (`:356-358`), and "Receiver power" is
  jargon on a control. (F31)
- **Cognitive load: high.** 4 of the 8 checks fail. The Alerts panel holds 14 ungrouped controls, the
  bitrate select has 17 options, and the page is about 3000 CSS px tall on mobile with no in-page
  navigation. (F19)
