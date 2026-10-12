# v39 — UI/UX Audit Report (impeccable)

Version 4.39.0 · branch `dev-ui-audit` · audited 2026-10-12 on the local stack (dev database
`spotdlwebtest`, real Postgres, real Redis, real network, upstream logins via `api.vb2007.hu`).

This is the evidence base for v40–v43, v45 and v47. Every row of the ranked table (§6) is assigned to a
slice or marked won't-fix with a reason, and v47 scores itself against the totals in §1.

**The owner approves the design direction (§8) in the v39 PR before v40 starts.**

---

## 0. Method and provenance

### impeccable Setup

`node <skill>/scripts/context.mjs --target frontend/src/routes/+page.svelte` (impeccable 4.0.3):

- It loaded `PRODUCT.md` and `frontend/src/DESIGN.md`.
- **No `CONTEXT_STALE` directive**, so there was nothing to refresh, and neither `init` nor `document` ran.
- `surfaceBriefReason: not-found`. Per task 1 the mode is recorded in surface briefs, so this slice wrote
  one per route with impeccable's own `surface-brief.mjs`, in `frontend/src/.impeccable/surfaces/`. All
  five record **Mode: Operate**, with the direction left open until §8 is approved.
- The setup also reported `MANUAL_DETECTOR_REQUIRED`, since no detector hook is active. The detector
  was run, in critique Assessment B and again in the audit.

### `critique` (critique.md)

Method: dual-agent. Assessment A and Assessment B ran as isolated sub-agents that never saw each other's
output.

- **Assessment A (design review)** was split across two agents:
  - A1 covered `/`: header, submit, IncomingJobs, Waterfall, QueueControls, both list scopes, the
    expanded job and the five track states, plus empty, loading, error and offline.
  - A2 covered `/settings`, `/library`, `/account` and `/login`.
- **Assessment B (detector and browser evidence)** ran the CLI `detect.mjs --json frontend/src`. It
  also ran the overlay flow on 7 page/viewport runs: `live-server.mjs` on port 8400, injected
  `detect.js`, and captured the `[impeccable]` console output. The live server was stopped afterwards.

### `audit` (audit.md)

One sub-agent ran the audit over the same surface list. It covered:

- WCAG ratios computed from the tokens
- tab-order traces
- live-region mutation counting
- touch-target measurement at 390px
- overflow checks at 390, 820, 1024 and 1440 px, and at 200% zoom
- a production build size check, done in a copy outside the repo
- the detector

A further sub-agent measured the ten already-known items in the live DOM (§5).

### Viewports and identities

- **Viewports:** desktop 1440×900 at DPR 1, and mobile 390×844 at DPR 2, with full-page captures.
- **Identities:**
  - `v37user` (non-admin)
  - `v37admin` (admin)
  - `v39empty`: a fresh non-admin with zero jobs, registered on the live upstream for the empty state
    and added to the local `.env`'s `ALLOWED_EMAILS`

### How the dev data was produced

Option chosen by the owner: real code paths first, seeding only what can't be forced.

- **First-try success** ("Around the World"): a real submit and download.
- **`skipped_duplicate`** (several Daft Punk singles): real.
- **Failures** (album "Trick" by Barabás Lőrinc Eklektric): `worker-dl` was restarted with a dead
  `HTTP(S)_PROXY` env and `LADDER_SECONDS=15,15,15,15,15,3600`, through a scratch compose overlay that
  was not committed. The real worker then produced:
  - real `no_output` failures
  - a real escalation across IPv4, then IPv6, then four real pool proxies
  - real breaker trips (trip #2, 2h)
  - a real 1h ladder wait
- **"Dóri" with 6 failed attempts and a countdown:** the failures are real. To get one track to 6
  before the breaker re-tripped, the other album tracks' `scheduled_at` was pushed out by 2h and
  `worker_state` was reset once, in the dev database.
- **Seeded by SQL** (owner-approved), because neither can be forced naturally:
  - `lookup_failed` "Moonrise": its first attempt is real, and attempt 2 carries spotdl's real
    `No results found for song: …` text.
  - The tag-repair warning on "Kezdet": it uses the real `repair_tags` warning text, and its file path
    is fake.
- **`/library` mid-sweep:** a real sweep of the 21 dev files, captured at 6/21. That sweep also
  **archived every settled job whose tracks it moved, for every user** (v28's
  `_sync_tracks_and_archive_jobs`). All dashboard captures predate it.

### Evidence

62 screenshots, plus axe-core 4.10.2 JSON, tab traces, detector JSON, overlay screenshots, tablet and
200%-zoom captures, and focus-ring crops. They are kept out of git (binaries); the PR lists them.
References like `shots/03` below mean `03-track-5plus-failures--{desktop,mobile}.png`.

| # | Capture | # | Capture |
|---|---|---|---|
| 01 | `/` jobs scope (user) | 13 | `/` jobs request → 500 |
| 02 | expanded job: waiting album | 14 | empty new user |
| 03 | track: 6 failed attempts | 20 / 44 | `/account` user / admin |
| 04 | track: waiting + countdown | 21 / 42 | `/settings` non-admin / admin |
| 05 | track: lookup_failed | 22 / 43 | `/library` non-admin / admin idle |
| 06 | track: completed + tag warning | 45-0…3 | `/library` mid-sweep (real) |
| 07 | track: first-try success | 46 | `/library` after sweep |
| 08 | tracks scope | 30 / 31 | `/login` / login error (real upstream 401) |
| 09 | empty search result | 40 / 41 | admin dashboard mine / all users |
| 10 / 11 | offline (SSE dropped) / reconnected | `audit/tablet-*` | 820 + 1024 widths |
| 12 | loading | `overlay-*` | detector overlays |

---

## 1. Score summary (the baseline v47 scores against)

### `critique`: Nielsen heuristics (0–4 each)

| Surface | 1 Status | 2 Match | 3 Control | 4 Consist. | 5 Prevent | 6 Recog. | 7 Flex. | 8 Minimal | 9 Recover | 10 Help | Total | Band |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `/` overall | 2 | 2 | 3 | 2 | 2 | 3 | 2 | 2 | 2 | 1 | **21/40** | Acceptable |
| `/` A: header, submit, incoming, waterfall | 2 | 2 | 3 | 2 | 3 | 3 | 2 | 2 | 2 | 1 | 22/40 | Acceptable |
| `/` B: controls, job list, tracks list | 3 | 2 | 3 | 2 | 2 | 3 | 2 | 2 | 2 | 1 | 22/40 | Acceptable |
| `/` C: expanded job + 5 track states | 2 | 2 | 3 | 2 | 3 | 3 | 2 | 1 | 2 | 1 | 21/40 | Acceptable |
| `/` D: empty, loading, error, offline | 1 | 2 | 2 | 2 | 3 | 2 | n/a | 2 | 1 | 0 | **15/36** (42%) | Poor |
| `/settings` | 3 | 2 | 2 | 2 | 1 | 3 | 2 | 2 | 2 | 2 | 21/40 | Acceptable |
| `/library` | 2 | 3 | 2 | 3 | 2 | 3 | 3 | 3 | 2 | 2 | 25/40 | Acceptable |
| `/account` | 3 | 3 | 3 | 2 | 3 | 3 | n/a | 3 | 2 | 3 | 25/36 (69%) | Acceptable |
| `/login` | 3 | 2 | 3 | 3 | 3 | 3 | 3 | 3 | 2 | 1 | 26/40 | Acceptable |

Heuristic 7 is n/a where a surface has no repeated task: the state screens, and `/account` with its
single setting. Those totals are renormalized.

### `audit`: technical (0–4 each)

| Dimension | Score | Key finding |
|---|---|---|
| Accessibility | 2 | `--text-dim` fails AA on every background (2.15–3.05:1). `/` has no h1, landmarks or skip link. The status pill re-announces every second |
| Performance | 3 | About 60 KB gzipped JS. Minor: render-blocking Google Fonts, a `localStorage` write per progress tick, one interval per countdown |
| Responsive | 2 | No overflow at any width. But the mobile JobRow toggle is 256px tall, there is a single 640px breakpoint, and state labels are truncated at every desktop width |
| Theming | 3 | Tokens are used almost everywhere and `design-tokens.json` matches `app.css` exactly. The Alerts panel is off-system, and amber appears on chrome |
| Implementation integrity | 3 | Detector CLI found 0. The system is coherent and product-specific, with verified drift from its own written rules |
| **Total** | **13/20** | **Acceptable** |

### Detector

| Pass | Result |
|---|---|
| CLI | `detect.mjs --json frontend/src`: exit 0, `[]` (also with `--no-config`). A test file proved the engine does fire |
| Browser overlay | 9 distinct rules, plus 2 more from a second API pass (§4.2). 4 are real (low-contrast, cramped-padding, line-length, flat-type-hierarchy), 3 are documented or intentional patterns (dark-glow, pulsing-dot, em-dash), and 4 are full or partial false positives (gpt-thin-border in intent, text-overflow, single-font, text-occlusion) |

### axe-core (desktop, violations per surface)

| Surface | Violations |
|---|---|
| `/` jobs | color-contrast 14 · page-has-heading-one |
| expanded track | color-contrast 27 · page-has-heading-one |
| admin all users | color-contrast **61** · page-has-heading-one |
| settings | color-contrast 36 · page-has-heading-one |
| library | color-contrast 4 · page-has-heading-one · **aria-progressbar-name** |
| account | color-contrast 4 · page-has-heading-one |
| empty user | color-contrast 5 · page-has-heading-one |
| login | color-contrast 7 |

---

## 2. Testing the "cluttered" claim

It is partly true, and the cause is not density. At 1440px the page is spacious: a 64rem column with
24px gaps. The clutter comes from four things.

1. **Every control carries the same weight.** About 20 bordered 12px mono chips (scope, search, show
   archived, clear log, 5 sort chips, 7 state chips) share a single style. Nothing is primary
   (`QueueControls.svelte:250-262`, `shots/01`).
2. **The same fact is repeated.** A one-track job shows a "done" badge, "TRACK", a 265px full mint bar
   and "1 done", all saying the same thing (7 of 8 rows in `shots/01`). Tracks scope prints every
   single-track title twice (`shots/08`). An expanded album repeats "Trick" in its album column ten
   times (`shots/02`).
3. **A wall of red.** Dóri's history shows "spotdl returned no output file for this track" six times,
   plus a seventh in "last read", all in `--fail`: 13 red lines for one message (`shots/03`).
4. **An empty hero.** The Waterfall takes about 180px above the fold and showed "NO SIGNAL — QUEUE
   IDLE" in every capture, including while 8 tracks were waiting behind a tripped breaker.

**On mobile the claim is fully true.** About 950 CSS px of chrome comes before the first job, so zero
jobs are visible in the first viewport. A layout bug (F01) then adds about 250px of empty space to every
job row.

---

## 3. Per-surface findings

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

### 3.7 `/account` (`shots/20`, `44`)

- **Calm and honest.** The retention copy says archived jobs are "never deleted… can always be
  restored". 0 of 8 cognitive-load checks fail.
- **Name/label mismatch.** `aria-label="Archive after this many days of inactivity"` overrides the
  visible label "After (days)", which fails WCAG 2.5.3 (`:114`). (F30)
- **Thin identity.** It shows only the username. The email is in a `title` tooltip, which touch users
  can't reach. There is no logout here, and no admin tag. (F31)
- **Small inconsistencies.** The pressed chip is amber, and the copy uses an ASCII "--" where other
  pages use "—" (`:76`). (F10, F31)

### 3.8 `/login` (`shots/30`, `31`)

- **The strongest surface (26/40).** The FM dial and its sweeping needle are the one fully realized
  moment of the world. The dial is `aria-hidden`, has a reduced-motion override, and reserves height
  for the error.
- **No guidance.** "TUNE IN" and "CONNECT" never say *which* account to use, so a family member will
  try their Spotify credentials. After an error, focus stays on CONNECT. (F31)
- **Amber at rest.** The needle is amber with a glow before anything is live (`:162-171`), and there is
  an amber focus glow on CONNECT. (F10)
- **Conflicting roles.** The error uses `role="alert"` together with `aria-live="polite"` (`:92`).
  (F31)

---

## 4. Audit detail

### 4.1 Contrast: computed WCAG ratios for each token on each background

| Text token | bg-0 `#0a0c0e` | bg-1 `#14181c` | bg-2 `#1c2227` | bg-3 `#262e34` |
|---|---|---|---|---|
| primary `#e8ecee` | 16.48 | 15.01 | 13.51 | 11.60 |
| muted `#8b969d` | 6.48 | 5.90 | 5.31 | 4.56 |
| **dim `#566068`** | **3.05** | **2.78** | **2.50** | **2.15** |
| signal `#ffb02e` | 10.73 | 9.77 | 8.80 | 7.55 |
| **signal-dim `#7a5a1e` (used as text)** | **3.09** | **2.81** | **2.53** | **2.17** |
| settled `#5ad1a8` | 10.38 | 9.45 | 8.51 | 7.30 |
| waiting `#7fa8d9` | 7.94 | 7.23 | 6.51 | 5.59 |
| fail `#e5595c` | 5.52 | 5.02 | 4.52 | **3.88** |
| focus ring `#ffd479` (3:1 non-text) | 13.94 | 12.70 | 11.43 | 9.81 |

**`--text-dim`**

- It backs the `.label` utility (`app.css:159`) and about 25 other rules: every h2 section label, the
  login/settings/account form labels, the SORT/STATE labels, the Waterfall text, the count hint, the
  empty/loading hints, the attempt history, and the IncomingJobs URL.
- It accounts for **every** axe `color-contrast` violation except the amber `.inline-link`. (F09)

**Borders (WCAG 1.4.11):** `--line` scores 1.39–1.53:1 against the panels, under the 3:1 non-text
threshold.

### 4.2 Detector (Assessment B), verified in source

| Rule | Where | Verdict |
|---|---|---|
| low-contrast | `--text-dim` on `.label`, `.hint`, `.count-hint` | **Real** (F09) |
| cramped-padding | `section.panel.alert-settings` | **Real bug** (F18) |
| line-length | `.hint` on settings/library, ~157–162 chars, no max-width | **Real** (F19) |
| flat-type-hierarchy | 11/12/13/14/15px only | **Real** (F12) |
| gpt-thin-border-wide-shadow | every `.panel` (`app.css:165-174`) | Literal match. The −10px spread plus insets is the documented "recessed housing", so it's a false positive in intent (won't fix, F35) |
| text-overflow | `.cell.artist`, `.title` | False positive as a layout bug: intended ellipsis. The design point (cut titles) is F13 |
| single-font | settings, library | Partly a false positive: Plex Sans is loaded and used. Mono overuse is real (F12) |
| dark-glow | `IncomingJobs:86`, `login:169,237`, `+page:379`, `Waterfall:196` | Documented live-glow pattern. The login needle glow at rest is real (F10) |
| pulsing-dot | `IncomingJobs:81-88` | Intentional live indicator with a reduced-motion guard. Keep |
| em-dash-overuse (advisory) | status vocabulary ("fading — waiting" …) | Deliberate status copy. v46 rewrites every string anyway (won't fix, F35) |
| text-occlusion (second API pass only) | overlay's own labels | False positive |

### 4.3 Keyboard and semantics baseline for v45

- **Tab stops on `/` as a non-admin.** The first job toggle is **stop 22**: header 2, submit 2,
  controls 17. For an admin it is about stop 26.
- **The job list.** With "Trick" expanded, the job list costs **28 stops for 8 jobs**:
  - an in-flight job costs 4 (toggle, priority, bump, cancel);
  - a settled job costs 2;
  - **each TrackRow is its own stop**, 10 for the album, with no roving tabindex.
- **Missing structure.** There is no skip link, zero h1–h6 on `/`, `<header>` sits inside `<main>`, and
  there is no `<nav>`.
- **Expandable rows.** Enter toggles both row types and focus stays put. Esc does nothing, and neither
  has `aria-controls`.
- **Focus ring.** A 3px `#ffd479` ring at 2px offset was verified on 8 control types, with no clipping
  ancestor. It passes 2.4.7 and 2.4.11 by a wide margin.
- **Reachability.** No unreachable controls were found.
- **Live regions.**
  - `role="status"` notices are inserted already containing their text, so they are often not
    announced.
  - Filtering produces no audible result count.

### 4.4 Responsive

- **No horizontal overflow** at 390, 820, 1024, 1440, or at 200% page zoom.
- **Breakpoints.** The only width breakpoint is `@media (max-width: 640px)`, in 6 files. The other
  `@media` blocks are reduced-motion.
- **Mid-widths.** 820 and 1024 get the squeezed desktop grid: the state label truncates and artists
  truncate at 820 (`audit/tablet-*.png`).
- **Touch targets at 390px.** 27 of 45 controls on `/` and 29 of 39 on `/settings` are under 44px:
  chips and actions about 28px, the "account" link 20px. WCAG 2.5.8 AA (24px or spacing) is met.
- **Body text size.** The body is `font-size: 15px` (`app.css:112`), so with a 32px browser default the
  body stays at 15px while the rem-sized labels double, which inverts the hierarchy.

### 4.5 Performance

- **Bundle.** The production build is ~60 KB gzipped JS and 33 KB CSS. The largest chunk is 18 KB
  gzipped.
- **Re-rendering.** SSE ticks re-render only the keyed lane or row. No layout thrash, and no
  `backdrop-filter`.
- **Minor costs:**
  - Google Fonts (6 faces) block first paint.
  - `rememberProgress` does a synchronous `localStorage` read, parse and write on every tick.
  - Each `Countdown` owns its own interval.
  - The lane `.fill` animates `background-position` with a glow, so it repaints every frame.
  - The login needle animates `left`.
  - The `/library` fill has a 0.3s transition that isn't zeroed under reduced motion.
  - The body glow repeats every viewport height: a faint amber band at 844px on the mobile full-page
    shot.

---

## 5. The ten already-known items

All ten were measured live at 1440×900 in the dev stack.

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 1 | TrackRow detail is indented 9rem while the title column starts at 10.25rem | **CONFIRMED** | `.detail { padding-left: 9rem }` (`TrackRow.svelte:333`). The row grid is `9rem …` with a 0.75rem gap plus 0.5rem padding, which puts the title at 10.25rem. Measured on Dóri: detail content at x=377, title at x=397 (20px left of the title), state cell at x=241 |
| 2 | Inline and full-width detail items are mixed | **CONFIRMED** | The detail is `flex-wrap`. Inline items: the counts (203px) and the countdown (146px, same line), and "last read" (455px, wraps only by length). Full-width: `.actions`, `.attempts`, `.notice` (all 822px, `flex-basis: 100%`, `:354,380,388`) |
| 3 | JobRow (flex) and TrackRow (grid) don't align, and there's no nesting indent | **CONFIRMED** | JobRow `.row` is `display:flex`; TrackRow is `display:grid` with columns `144/307.7/205.1/205.2/48px`. Job title at x=350 vs track title at x=397. Leading edges at 249 vs 241. The job `li`, `.job-tracks`, the Tracks `ul` and the track button all sit at x=233 with w=974, so there is no indent. The only nesting cue is a `--bg-0` background (`JobTrackList.svelte:38-41`) |
| 4 | There is no type scale (DESIGN.md §3) | **CONFIRMED** | No font-size token exists (the `--text-*` tokens are colors). The source holds 6 hard-coded sizes: 0.8125rem ×24, 0.75rem ×24, 0.6875rem ×11, 0.875rem ×1, 0.5625rem ×1, 15px ×1. On `/` the computed sizes are only 11, 12, 13 and 15px; nothing is larger than body text |
| 5 | The panel "chassis" is imperceptible (§8.1) | **CONFIRMED** | `--bg-1` vs `--bg-0` is **1.098:1** (ΔL\* 4.8), far below a 1.2:1 perceptibility floor. Only the 1px `--line` border reads, at 1.53:1 against the page. The 0.5α black inset shadow makes the panel *darker*, cutting separation further (`app.css:171-174`) |
| 6 | The 640px breakpoint is the only one | **CONFIRMED** | Every width query is `max-width: 640px`: `WorkerStatusPill:54`, `TrackRow:288` and `:338` (the second duplicates `:324`), `settings:689`, `account:195`, `JobRow:380`, `+page:305`. There is no min-width or tablet query |
| 7 | The static amber body glow conflicts with the amber-is-live rule (§2) | **CONFIRMED** (barely visible) | `app.css:105-109`: `radial-gradient(… rgba(255,176,46,0.05) …)` is literally `--signal`, always on. DESIGN.md:64 says amber is "reserved exclusively for live/active state… never… permanent chrome". Its peak blend is `#161410`, only 1.065:1 against the page. It also repeats every viewport height (§4.5) |
| 8 | "passes attempted: 0" (fixed in v35, confirm it's gone) | **CONFIRMED gone; adjacent issue remains** | The strings "passes attempted" and "passes" have 0 hits. The line now reads `attempts: {attempts_made} · failures: {failure_count}` (`TrackRow.svelte:180`). First-try success shows "attempts: 1 · failures: 0", which is correct. Still misleading: a skipped_duplicate shows "attempts: 0 · failures: 0" above its own one-row history (F25) |
| 9 | Destructive actions have no confirmation (clear log, remove proxy) | **CONFIRMED** | There is no `confirm(`, `<dialog` or `showModal` anywhere. "clear log" (`QueueControls.svelte:98-100,142`) archives every settled job in one click. "remove proxy" (`settings/+page.svelte:268-282, 583-590`) is a permanent DELETE. Also unconfirmed: job cancel, track cancel (also offered on lookup_failed), IncomingJobs cancel, per-job archive, worker pause, **breaker "release now"**, disconnect, **library start sweep** |
| 10 | Every TrackRow is a separate tab stop | **CONFIRMED** | With "Trick" expanded, its 10 tracks are 10 consecutive stops, and the Tracks list has 0 `tabindex` attributes (no roving). The first job comes after 21 stops on `/` |

---

## 6. Ranked findings

Rows are ordered by severity (P1 → P3, then won't-fix). IDs are stable references, not ranks.

**Severity** uses impeccable's P0–P3 scale:

- **P0:** blocks a task.
- **P1:** significant difficulty, a misleading state, or a WCAG AA violation.
- **P2:** an annoyance that has a workaround.
- **P3:** polish.

**Slice codes:**

- **v40:** ambient background
- **v41:** track/job detail
- **v42:** dashboard
- **v43:** secondary surfaces and confirmations
- **v45:** keyboard
- **v47:** polish and harden

| ID | Sev | Surface | Finding | Evidence | Slice |
|---|---|---|---|---|---|
| F01 | P1 | `/` mobile job list | Every JobRow toggle is **308×256px** at ≤640px. `flex: 2 1 16rem` turns into a 16rem *height* under the column layout, and the bar's `flex-basis: 100%` collapses to a hairline, so job state is invisible on phones | `JobRow.svelte:218,380-389`, `shots/01--mobile`, `audit/m02crop.png` | **v41** (owns JobRow and its ≤640 stack; see amendment A1) |
| F02 | P1 | expanded job/track | Three left edges (377/397/417). No nesting indent. JobRow and TrackRow on different grids. Nested list darker than its panel. Leaked `li` borders and default `ul` padding in the history | §5 #1–3, `shots/02,03` | v41 |
| F03 | P1 | expanded track | The wall of red: every failed attempt of a *recoverable* waiting track is `--fail`, the same message repeats 6+1 times, and "last read" is red too | `TrackRow.svelte:32-38,344-348,428-433`, `shots/03` | v41 |
| F04 | P1 | `/` Waterfall + header | Status contradicts reality: "queue idle" while tracks wait behind the breaker; track countdowns ignore `breaker_tripped_until` ("next scan in 58:35" vs "clears in 1:58:35") | `Waterfall.svelte` idle branch, `Countdown` in `TrackRow.svelte:181-183`, `shots/01,03` | v42 (Waterfall/header); the countdown half is **v41** |
| F05 | P1 | `/` offline | SSE dropped looks pixel-identical to connected. No live/reconnecting tell, in an app meant to be left open for days | `shots/10` vs `01`, `+page.svelte` `connectStream` | v42 (amendment A3) |
| F06 | P1 | header pill | A tripped breaker (an expected, self-healing condition) shows in `--fail` red to every user, including a new empty account | `WorkerStatusPill.svelte:30`, `shots/14` | v42 |
| F07 | P1 | header pill | `role="status"` wraps a 1 s countdown, so screen readers re-announce it every second (5 mutations / 5 s) | `WorkerStatusPill.svelte` + `Countdown.svelte` | v42 |
| F08 | P1 | app-wide | No confirmation on irreversible or risky actions: clear log, remove proxy, job/track cancel, **start sweep**, **breaker "release now"** (resumes downloads into an active rate limit), worker pause. Library START is enabled for non-admins | §5 #9, `shots/22` | v43 (amendment A4 adds release/pause) |
| F09 | P1 | all | `--text-dim` fails WCAG 1.4.3 on every background (2.15–3.05:1), and so does `--signal-dim` used as link/hover text (2.5–3.1). This is every axe contrast violation (4–61 nodes per surface). `--line` control borders are 1.39–1.53:1 (1.4.11) | §4.1, `axe-all.json` | v42 (token change; amendment A2) |
| F10 | P1 | all | Amber leaks onto permanent chrome despite DESIGN.md §2: body glow, global `a` color, `>` prompt, submit/connect glow, pressed option chips (settings, account), input focus borders, hover links, the idle login needle, the idle library bar | `app.css:105,124`, `+page:344-380`, `settings:727`, `account:224`, `login:162-171,236`, `library:101` | **v40** decides the rule and fixes the body glow; v42 (`/`) and v43 (other routes) apply it (amendment A5) |
| F11 | P1 | `/` QueueControls | About 20 equal-weight chips with no primary. Zero-count chips are always shown. Sort is 5 chips. "clear log" is styled like "show archived". This is the main source of "cluttered" | `QueueControls.svelte:250-262`, `shots/01,08` | v42 |
| F16 | P1 | `/`, `/library` | Missing names: unnamed `role="progressbar"` on `/library` and each Waterfall lane. The JobRow `aria-label` hides the visible status/owner (WCAG 2.5.3). Job actions are named just "bump/cancel/archive" | axe `aria-progressbar-name`, `JobRow.svelte:135,174-178`, `Waterfall.svelte:49-55` | v41 (JobRow), v42 (Waterfall), v43 (library) |
| F17 | P1 | `/settings` non-admin | Admin sections render, error and spin forever, and the page states the false "No proxies configured — every attempt goes out direct" | `settings:554-557`, `WorkerStatus:141-144`, `shots/21` | v43 |
| F20 | P1 | `/library` | Idle shows a full amber 100% bar, which looks like a running sweep. No "finished at". Mid-sweep hides the live counts. Duplicate error rows with no recovery copy. SSE has no reconnect. No cancel | `library:41-66,101,114-127`, `shots/43,45,46` | v43 |
| F26 | P1 | `/` states | Empty, loading and error don't teach or recover: identical "Nothing here." for a new user and a search miss; loading shows all chips at 0; raw "Internal Server Error" with no retry | `shots/09,12,13,14`, `+page.svelte:218-223` | v42 |
| F29 | P1 | `/` keyboard | 21 stops before the first job; every TrackRow is a stop; no skip link, h1, `<nav>` or banner landmark; Esc does nothing on rows; no `aria-controls` | §4.3, §5 #10 | v45 (keyboard model, skip link); v42 (landmarks/h1, already in v42's plan); v41 (`aria-controls`) |
| F12 | P2 | all | No type scale (6 ad hoc sizes, nothing above 15px). Mono covers prose, errors, buttons and hints, giving one undifferentiated 12px texture. Body is `15px` (px), which ignores the user's text-size setting | §5 #4, `app.css:112`, detector flat-type-hierarchy | v42 (scale + `/`); v43/v47 migrate the rest |
| F13 | P2 | track rows | The state label truncates ("no signal — not fo…") at 1440/1024/820 with no `title`. The 3rem `.pct` column is empty unless downloading. Long titles/artists are cut | `TrackRow.svelte:245`, `shots/02,05`, `audit/tablet-*` | v41 |
| F14 | P2 | expanded track | The tag-repair warning uses waiting-blue, the same as "held", so it reads as a scheduling note rather than a quality warning | `TrackRow.svelte:436-441`, `shots/06` | v41 |
| F15 | P2 | `/` mobile | About 950 CSS px of chrome before the first job: header one item per line, full-width disconnect, ~780 device-px controls panel | `shots/01--mobile` | v42 |
| F18 | P2 | `/settings` alerts | The Alerts panel has no padding (selector misses `.alert-settings`), and its number inputs keep the browser's grey styling | `settings:654-656,742`, detector cramped-padding, `shots/42` | v43 |
| F19 | P2 | `/settings` | Cognitive load is high: 14 ungrouped alert controls, a 17-option bitrate select, three separate SAVEs, 157-char hint lines, ~3000px on mobile with no in-page navigation | `settings:445-521`, detector line-length | v43 |
| F21 | P2 | `/` vocabulary | Chip vs row vocabulary differs ("completed" vs "logged", "duplicate" vs "already logged"). Job count "waiting 1" sits next to "8 waiting" tracks | `QueueControls.svelte:48-57`, `TrackRow.svelte:93-102` | v42 (chips) + v41 (rows); v46 re-words both |
| F22 | P2 | track rows | No chevron or other expandability cue on track rows | `TrackRow.svelte:168-176` | v41 |
| F23 | P2 | countdowns | No days unit ("47:12:03" past 24h) | `Countdown.svelte:15-23` | v41 |
| F24 | P2 | lookup_failed | No next step. "cancel track" is offered on a terminal row next to "retry now" | `TrackRow.svelte:75-81`, `shots/05` | v41 |
| F25 | P2 | skipped_duplicate | "attempts: 0 · failures: 0" contradicts its own one-row history ("already logged · no network") | live, `claims10/track-One_More_Time.png` | v41 |
| F27 | P2 | `/` incoming (admin) | Stale "could not read this artist" banners stack above the fold in all-users view; no reason, no retry | `IncomingJobs.svelte:39-41`, `shots/41` | v42 |
| F30 | P2 | settings, account | Ambiguous names: 5 proxy toggles all "enabled", state text plus `aria-pressed` contradict each other, pause reads "resume, pressed", account `aria-label` ≠ visible label (2.5.3) | `settings:573-581`, `WorkerStatus:67-75`, `account:114` | v43 |
| F31 | P2 | secondary | Login has no account hint and leaves focus on CONNECT after an error, with conflicting `alert` + `polite`. "Saved." never clears. Account shows the email only as a tooltip and has no logout. Control jargon ("Receiver power") | `login:30-33,92`, `settings:356`, `account:68,76` | v43 |
| F32 | P2 | all (touch) | 27/45 (`/`) and 29/39 (`/settings`) controls under 44px at 390px; chips ~28px, header links 20px | `audit-results.json` | v42 (`/`), v43 (others) |
| F34 | P2 | backend | (a) The sweep error log lists the same path twice. (b) A sweep archives settled jobs of *every* user without the report saying so (v28 design). Neither is a UI-slice fix | `shots/46`, `tasks/library.py:34-77` | **won't fix in v40–v47**: backend behavior, outside the UI series' scope; proposed for v48 (amendment A6). v43 may *display* (b)'s count |
| F28 | P3 | job list | "done — partial" red badge over an all-grey bar; cancelled no-title jobs show the raw URL as a bold title; 1-track jobs repeat badge, bar and count | `shots/01,40,41` | v42 |
| F33 | P3 | perf | Render-blocking Google Fonts; a `localStorage` write per progress tick; one interval per Countdown; repainting lane shimmer; login needle animates `left`; library transition not zeroed under reduced motion; body glow repeats per viewport | §4.5 | v47 (optimize); body-glow repeat → v40 |
| F35 | — | detector | gpt-thin-border-wide-shadow on `.panel`; em-dash-overuse; text-occlusion; single-font | §4.2 | **won't fix**: documented "recessed housing" design (or v42's material decision supersedes it); status vocabulary v46 rewrites; artifacts of the overlay; Plex Sans is in use |
---

## 7. Amendment proposals

These are for the owner to accept or reject. v40–v47's plans were not edited.

- **A1. F01 is a live mobile regression.** v41 owns JobRow's ≤640 stack, so it is assigned there. The
  bug makes every job row about 4× taller and hides its progress bar on phones *today*. The owner may
  prefer a one-line hotfix (`.toggle { flex: 0 0 auto }` inside the mobile query) as a v39.1 patch
  before the v40–v41 redesign lands. The v39 rules don't allow fixing it here.
- **A2. v42 should own the contrast tokens explicitly.** v42's plan lists the type scale and the panel
  material but not color tokens. F09 is one token change (`--text-dim` to ≥ ~`#85909a` for 4.5:1 on
  bg-2, `--line` up for 1.4.11, and no `--signal-dim` as text) that clears nearly every axe violation
  at once. It belongs with v42's other design-system tokens.
- **A3. v42 should list the offline/reconnecting state and "status honesty".** v42's state list says
  "every empty, loading and error state", and v47 hardens "SSE dropped and recovering". F05 (no
  connection tell) and F04 (the Waterfall says "idle" during a breaker hold) are the dashboard's most
  misleading states, so they should be designed in v42, not hardened in v47.
- **A4. v43's confirmation list should add "release now" (breaker) and worker pause.** "release now"
  resumes downloads into an active rate limit, which is exactly the exposure the app exists to avoid.
- **A5. v40 should settle the amber rule for *all* chrome, not only the body glow.** F10 found amber
  leaking onto about 10 chrome sites. v40's plan already requires the DESIGN.md decision. Making that
  decision cover links, pressed chips, focus borders, the prompt and the idle needle lets v42 and v43
  apply one rule rather than re-deciding it per surface.
- **A6. v48 (or a backend patch) should take F34**: deduplicate the sweep error rows, and decide
  whether a sweep should archive other users' jobs silently. The UI series can't fix either.
- **No slice is unnecessary.** v40–v43 and v45 each have P1 findings assigned. v47 has P2/P3 work
  (F12's type-scale migration, F33) plus the re-audit against this baseline. v44 (admin
  stats) wasn't audited because it doesn't exist yet. It should be born on v42's tokens, and that
  already matches its plan.

---

## 8. Design direction (owner approval requested)

**Recommendation: REFINEMENT, keeping the identity. Not a redesign.**

Every independent assessor that judged direction (design reviews A1 and A2, and the audit) reached the
same verdict. Every UI finding (F01–F33) is a violation of the world's *own* rules, or an execution
gap; none is caused by the world itself. F34 is backend behavior and F35 is detector false positives.

### Keep

- **The signal-receiver world**, with a change: move it from copy into structure.
  - It is the product's only identity (PRODUCT.md records no brand), and it is authored rather than
    category-interchangeable. The login dial is the most memorable surface, and the amber-only-when-live
    border swap is a real mechanic.
  - What fails is execution. The world's hero panel reports the wrong state (F04, F05), and the
    metaphor is spent on control labels ("Receiver power", "fading — waiting", "disconnect") instead of
    information design.
  - Refinement rule: in-world words for idents, status and moments; plain words for controls and form
    labels.
- **The IBM Plex Mono + Plex Sans pairing**, with mono narrowed. Content in Sans reads well
  everywhere. Mono should shrink to numbers, timestamps, state tokens and addresses, while error
  sentences, hints, buttons and empty-state copy move to Sans. Mono's current blanket coverage is a
  large part of "cluttered" (F12).
- **The state-color semantics.** This is the system's best asset: one `.cond-*` vocabulary shared by
  track rows, job badges, segmented bars, attempt history and proxy health. Fix the leaks, not the
  palette:
  - breaker → waiting-blue
  - recoverable attempt errors de-reddened
  - a distinct caution treatment for warnings
  - red reserved for terminal or human-action states
  - amber pulled off chrome (F03, F06, F10, F14)

### Reconsider (inside the same world)

- **The Waterfall as the permanent hero.** It is empty about 95% of the time at concurrency 1. It
  should collapse to an honest one-line "receiver status" (holding / scheduled / live / reconnecting)
  and expand into lanes only while something is live. That is a v42 decision, and §8.2's "lanes, not a
  spectrogram" stays.
- **The panel "chassis" (§8.1).** At 1.098:1 it doesn't exist perceptually. v42 should either make it
  perceptible or drop the idea in DESIGN.md.
- **Who sees operator detail.** Family-member users see every state filter (7 job-state chips in jobs scope, 8 track-state chips in
  tracks scope), sort-by-"next retry", and a red breaker pill. Whether some of that moves behind an admin or "diagnostics"
  disclosure is a v42 question.

**What this means for each later slice:** v40–v43 are **refinements**. Each keeps the identity, the
fonts and the color semantics, and fixes its assigned rows above. No slice replaces the world, and
DESIGN.md is not replaced (v47 regenerates it from the shipped UI, as planned).

**Questions for the owner:**

1. Approve refinement (as above), or ask for a redesign of the visual world?
2. Accept or reject amendments A1–A6, especially whether F01 gets a v39.1 hotfix.
3. Should operator-level detail (the breaker pill, all state filters, attempt diagnostics) stay
   visible to family-member users, or move behind an admin/diagnostics disclosure?
