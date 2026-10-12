---
target: / dashboard
total_score: 21
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 14
timestamp: 2026-10-12T16-14-12Z
slug: frontend-src-routes-page-svelte
---

Method: dual-agent (A: design-review sub-agents A1/A2 · B: detector+browser sub-agent). Full report: plan/master-v4/v39-ui-audit-report.md

### 3.1 `/`, group A: header, submit bar, IncomingJobs, Waterfall (`shots/01, 12, 14, 40, 41`)

**Strengths**

- The `>` console prompt and the Waterfall's noise floor are authored. A generic queue UI wouldn't
  ship them.
- The amber-only-when-live border swap is a real, enforced design rule.

**Issues**

- **Status contradicts reality.**
  - The Waterfall says "no signal — queue idle" while 8 tracks wait behind a tripped breaker. The idle
    branch never consults the breaker or waiting counts.
  - There is no SSE connection indicator. Offline (`shots/10`) is pixel-identical to connected
    (`shots/01`). (F04, F05)
- **Red for a normal condition.** The breaker pill shows "breaker tripped" in `--fail` red to every
  user, including a brand-new empty user (`WorkerStatusPill.svelte:30`, `shots/14`). This works against
  PRODUCT.md principle 2, "rate-limiting is normal". (F06)
- **The pill floods screen readers.** It is `role="status"` and wraps a per-second `Countdown`. Five
  mutations were measured in 5 s, so a screen reader re-announces "clears in 1:50:19…" every second.
  (F07)
- **Amber on chrome.**
  - The `>` prompt is permanent amber (`+page.svelte:344-346`).
  - The submit hover/focus glow is `--signal` (`:375-380`).
  - Header links turn `--signal-dim` on hover/focus, dropping them to 2.8:1 (`:317-320`). (F10)
- **The admin all-users view stacks stale banners.** Four stale "could not read this artist" failure
  banners pile up above the fold (`shots/41`). Their copy gives no reason and no retry
  (`IncomingJobs.svelte:39-41`). (F27)
- **Mobile header.** The header stacks one item per line (pill, account, username, full-width
  disconnect), which costs about 330 CSS px (`shots/01--mobile`). (F15)

### 3.2 `/`, group B: QueueControls, jobs list, tracks list (`shots/01, 08, 09, 40, 41`)

**Strengths**

- Live counts on the filter chips and the "8 of 8" hint.
- Server-side search and sort.
- Reversible archive.

**Issues**

- Equal-weight chips: 7 job-state chips, 8 track-state chips, 5 sort chips. Each of these decision
  points has more than 4 options. (F11)
- **Vocabulary splits.**
  - The chip says "completed" where the row says "logged", and "duplicate" where the row says "already
    logged" (`QueueControls.svelte:48-57` vs `TrackRow.svelte:93-102`).
  - The job chip "waiting 1" sits beside a row reading "8 waiting": one counts jobs, the other tracks.
  (F21)
- Track rows have no chevron, so you can't see that they expand (`TrackRow.svelte:168-176`). (F22)
- "clear log" bulk-archives every settled job in one click with no confirmation. It looks identical to
  "show archived", and the word "clear" reads as delete (`QueueControls.svelte:98-100,142`). (F08)
- Cancelled jobs with no title show their raw URL in bold, which makes them the heaviest rows
  (`shots/40`).
- "done — partial" uses a red badge over an all-grey (cancelled) bar, so the two signals disagree
  (`shots/41`). (F28)

### 3.3 `/`, group C: expanded job and the five track-detail states

- **Expanded job (`shots/02`).**
  - The tracks list is not indented under its job. Every container sits at x=233.
  - The job title (x=350) and track title (x=397) don't align. The leading edges differ by 8px. (F02)
  - The nested list's `--bg-0` background is darker than the panel it sits in.
- **First-try success (`shots/07`).**
  - This is the cleanest state: "attempts: 1 · failures: 0", one mint "completed · direct · IPv4" line,
    and "download". It is the shape the other states should aim for.
  - **"passes attempted: 0" is gone** (§5 #8).
- **6 failed attempts (`shots/03`).**
  - 13 red lines. The detail block sits at x=377, the title at x=397, the attempt list at x≈417, which
    is three left edges.
  - The attempt list keeps the browser's default `ul` padding, and TrackRow's scoped `li` border leaks
    onto the attempt rows (`TrackRow.svelte:234-236, 410-415`).
  - "next scan in 58:35" is false while the breaker holds everything for 1:58:35: `Countdown` reads
    only `scheduled_at`. (F02, F03, F04)
- **Waiting with countdown (`shots/04`).** "attempts: 0 · failures: 0" sits above a history whose row
  reads "held — not attempted · circuit breaker active". The line is honest but bare.
  - Countdowns have no days unit, so past 24h they read "47:12:03" (`Countdown.svelte:15-23`). (F23)
- **lookup_failed (`shots/05`).**
  - The state label is clipped to "no signal — not fo…" by the fixed 9rem column at 1440, 1024 and 820,
    with no `title` attribute.
  - No next step is offered.
  - "cancel track" is offered on this terminal row, next to "retry now"
    (`TrackRow.svelte:75-81`). (F13, F24)
- **Tag-repair warning (`shots/06`).** The warning is styled waiting-blue, the same as "held", so a
  quality note reads like a scheduling note (`TrackRow.svelte:436-441`). (F14)
- **skipped_duplicate (live).** "attempts: 0 · failures: 0" contradicts its own one-row history, which
  reads "already logged · no network". (F25)
- **Accessibility.** The JobRow toggle's `aria-label` "Expand tracks for Trick" replaces its visible
  content, so the status and owner are never exposed. This fails WCAG 2.5.3.
  - The job action buttons are named just "bump", "cancel" and "archive", without the job name.
  - Neither row type has `aria-controls`, and Esc does nothing. (F16, F29)

### 3.4 `/`, group D: empty, loading, error, offline (`shots/09–14`)

- **Offline / SSE dropped.** It looks identical to connected, and live updates stop silently. This is
  the worst failure, because the stated usage scene is a background tab left open for days. (F05)
- **Loading (`shots/12`).** Every chip shows 0, which reads as "you have nothing". Use skeletons, and
  hide the counts until they're known. (F26)
- **Error (`shots/13`).** The raw "Internal Server Error" is shown, with no retry and no "keeps
  retrying" reassurance (`+page.svelte:218-223`). (F26)
- **Empty.**
  - A new user (`shots/14`) and a search miss (`shots/09`) get the same "Nothing here.".
  - The new user sees the full 20-chip panel at zero, plus a red breaker pill.
  - Nothing teaches the product: no example URL, and no "albums can take days, that's normal". (F26)
