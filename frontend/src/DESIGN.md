# DESIGN.md — spotdl-web frontend

Scope: `frontend/src/` (SvelteKit app). This is the project's first UI (v09); there is no prior
DESIGN.md to reconcile — every rule below is read off the built code, not the plan that preceded
it. Where the plan and the shipped result differ, this file records what shipped.

Status: living document. Update in the same PR as any change to a token, a state-color mapping,
or a named rule — do not let this drift from `frontend/src/app.css` and the components that
consume it.

## 1. World and thesis

**THESIS**: an instrument panel, not a dashboard. The queue reads as a live spectrum scope — ham
radio waterfall / spectrum scope, not cards-and-sidebar SaaS chrome.

**Operate mode governs every tradeoff here**: task and legibility always outrank expression. Two
concrete places this already overrode the more "authentic" version of the metaphor:

- The waterfall's signature device is a labeled per-track progress-lane list, not a literal
  rendered frequency/time spectrogram. **Deliberate simplification, not a gap** — real song/artist
  titles must stay legible text, not compete with a decorative visualization.
- The idle state is a slow, low-amplitude animated noise floor (4.2s cycle, opacity 0.45→0.7),
  not a dead flatline and not a fast/attention-grabbing animation — calibrated for the confirmed
  usage scene of "left open in a background tab for long stretches" (`Waterfall.svelte`). Fast
  idle motion was tried and rejected in review for being in tension with that scene.

This project has no logo, no brand name beyond the repo, and no existing visual identity
(confirmed in PRODUCT.md) — the instrument-panel world _is_ the brand, invented for this build,
not applied on top of one.

## 2. Palette

All colors are CSS custom properties in `:root` (`app.css`). Dark-only (`color-scheme: dark`); no
light theme exists or is planned.

### Chassis / ground

| Token            | Hex       | Use                                                                                                                                                  |
| ---------------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--bg-0`         | `#0a0c0e` | Page background, recessed input wells                                                                                                                |
| `--bg-1`         | `#191e23` | `.panel` surface: the raised faceplate (v42; was `#14181c`)                                                                                          |
| `--bg-2`         | `#1c2227` | A control's fill (buttons, chips). v42: on the `--bg-1` faceplate it is only 1.045:1, so a job or track row's hover is a title underline, not a fill |
| `--bg-3`         | `#262e34` | Hover/active surface one step brighter than `--bg-2`                                                                                                 |
| `--line`         | `#2b3339` | Default hairline border                                                                                                                              |
| `--line-bright`  | `#3a444c` | Emphasized border (major dial ticks, the idle waterfall top edge; v42: no longer a control edge, see `--line-control`)                               |
| `--line-control` | `#6a757e` | v42: the border of every neutral control (input, select, button, chip): ≥3:1                                                                         |

> **v42 (2026-10-15, F09/A2, owner's choice):** `--line` stays the quiet divider between rows and
> around panels (1.31:1 on `--bg-1`). A control's edge is `--line-control` instead, which reaches
> WCAG 1.4.11's 3:1 against `--bg-0` (4.16), `--bg-1` (3.56) and `--bg-2` (3.41). The owner chose a
> separate token over raising `--line` itself, so the job list doesn't turn into a 3:1 grid. Swapped
> tree-wide (border property only) on every route.

### Text

| Token            | Hex       | Use                                                        |
| ---------------- | --------- | ---------------------------------------------------------- |
| `--text-primary` | `#e8ecee` | Body text, primary content                                 |
| `--text-muted`   | `#8b969d` | Secondary content (artist lines, byline-weight text)       |
| `--text-dim`     | `#808b94` | Labels, meta, deliberately quiet text (v42; was `#566068`) |

> **v42 (2026-10-15, F09/A2):** `--text-dim` failed WCAG 1.4.3 everywhere (2.15–3.05:1). It now
> reaches 4.5:1 on every surface it sits on: `--bg-0` 5.63, `--bg-1` 4.83, `--bg-2` 4.62. That puts
> it close to `--text-muted` (6.48 / 5.55 / 5.31), so the two now read apart by role (size, case and
> tracking: `.label`), not by luminance. `--text-muted` stays put because `AmbientField.svelte`'s
> slate tone is calibrated against it (§6). `--signal-dim` is never text (it was 3.09:1 as link hover
> on four routes; those links now hover to `--text-primary`).
>
> A destructive control's outline at rest (clear log, a job's cancel, cancel track) is the new
> `--fail-edge` (`#b05154`: 3.87 / 3.32 / 3.17 on `--bg-0/1/2`), not `--fail-dim` (1.5:1). `--fail-dim`
> stays a fill and segment tone. `/settings`' and `WorkerStatus`' state toggles still edge in
> `--fail-dim`/`--settled-dim` with full-strength state text; they are v43's (F30).
>
> **v43 (2026-10-16, F30):** those toggles are gone. A proxy's state is a word ("switched on" in
> `--settled`, "switched off" in `--text-muted`) beside a plain `.btn` naming the action, and a
> switched-off row is no longer faded with `opacity: 0.6` (v42's 20-node remainder): its address
> drops to `--text-muted`. The worker's state is a sentence beside "pause/resume downloads".

### Signal-condition colors — the semantic core of the system

Five conditions, shared verbatim between the waterfall and the spectrum-log table via
`.cond-live` / `.cond-settled` / `.cond-waiting` / `.cond-fail` / `.cond-idle` so a state's color
means the same thing everywhere it appears. Do not introduce a second color vocabulary for a new
component — map any new state onto one of these five.

| Condition                     | Token(s)                                                       | Hex                                                        | Meaning                                                                                                                                                                                           | Exclusivity rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ----------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Live** (Committed strategy) | `--signal` / `--signal-dim` / `--signal-ink` / `--signal-glow` | `#ffb02e` / `#7a5a1e` / `#2a1c05` / `rgba(255,176,46,.35)` | Something is actively transmitting **right now**                                                                                                                                                  | **Amber is reserved exclusively for live/active state. It must never appear as permanent chrome, decoration, or a "brand" accent.** This was a deliberate fix made during finish review: round 1 shipped a constant amber top border on the waterfall panel; review flagged it as spending the one committed live-signal color on chrome and diluting its meaning, and it was changed to neutral (`--line-bright`) by default, turning amber (`--signal-dim`) only when `tracks.length > 0` (`Waterfall.svelte` `.waterfall.live`). **Any future component adding amber must justify it against "is this genuinely live right now" — if not, use a different token.** |
| **Settled**                   | `--settled` / `--settled-dim`                                  | `#5ad1a8` / `#2c5347`                                      | Completed, no longer needs attention (`completed`, `skipped_duplicate` track states)                                                                                                              | Cool mint, never used for anything mid-flight                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **Waiting**                   | `--waiting` / `--waiting-dim`                                  | `#7fa8d9` / `#35485f`                                      | Patient, scheduled, not alarming (`waiting` track state, the ladder/backoff condition, `Countdown.svelte`'s default text color)                                                                   | Soft blue reads as "scan window," must never read as an error — this is the state that represents the retry ladder, which is normal/expected per the product thesis, not a failure                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Fail** (terminal only)      | `--fail` / `--fail-dim`                                        | `#e5595c` / `#5c2f30`                                      | **Terminal failure only** — `lookup_failed` ("no signal — given up") and `failed`. Also used for the logout button's hover/focus state (a destructive-adjacent action) and for `last_error` text. | Held back deliberately — never used for `waiting`/backoff, which is expected and recoverable, only for states the retry engine will not revisit                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **Idle**                      | `--text-muted` (via `.cond-idle`)                              | `#8b969d`                                                  | Not-yet-started (`pending`, `queued`, `cancelled`)                                                                                                                                                | No dedicated hue — idle borrows the muted text color rather than inventing a sixth signal color                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |

> **v41 (2026-10-14, F03/F14):** inside the expanded track, red now marks only a terminal verdict.
> A failed attempt the ladder will retry reads in the waiting blue, `last_error` is no longer
> painted red, and a note on an attempt that didn't fail (a tag-repair warning) is neutral text
> behind an outlined `NOTE` tag, neither fail red nor the waiting blue. Still five conditions,
> no sixth hue.

### Amber on chrome: the v40 decision (v39 F10, amendment A5)

**Decided 2026-10-13 by the owner (v40): the rule above stands unamended.** Amber marks something
receiving _right now_, and nothing else. The v39 audit (F10) found it leaking onto about ten
permanent chrome sites. Each now has a verdict. v40 applies only the first row. v42 (`/`) and v43
(the other routes) apply the rest without re-deciding them.

| Site (F10)                                                                                                                                         | Verdict                                                                                                                                                                                                           | Applied in                                                                                              |
| -------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Body glow (`app.css` `body` background)                                                                                                            | **No amber at rest.** Replaced by `AmbientField.svelte`: slate (`--text-muted`) at rest, crossfading to amber (`--signal`) only while `/` shows ≥1 receiving track. Always slate on every other route (see §6)    | **v40**                                                                                                 |
| Global `a` color (`app.css` `a { color: var(--signal) }`)                                                                                          | No amber. Links are `--text-primary` with an underline: the affordance is the underline, not the hue                                                                                                              | v42 ✓                                                                                                   |
| The `>` prompt (`+page.svelte` `.prompt`)                                                                                                          | `--text-muted` at rest. It may take `--signal` only while a submission is in flight (SENDING…), which is a real transmission                                                                                      | v42 ✓                                                                                                   |
| Submit / connect / save / add hover-focus glow (`+page.svelte`, `login/+page.svelte`, `/settings` SAVE and ADD, `/account` SAVE, `/library` START) | No amber, and no zero-offset halo. Hover is `--bg-3` with a `--line-bright` → `--text-muted` border; focus is the global `--focus-ring` outline alone (v42: the rest edge is `--line-control`, A2)                | v42 ✓ (`/`) / v43 ✓                                                                                     |
| Pressed option chips (`/settings`, `/account` `.option-group`)                                                                                     | `--line-bright` border with `--text-primary` text: the scope-toggle idiom already in §6, since a pressed setting is a selection, not a signal                                                                     | v43 ✓                                                                                                   |
| Input focus borders (submit, login, settings, account)                                                                                             | No amber border. The global `--focus-ring` outline already marks focus; the border stays `--line` (or `--line-bright`) (v42: `--line-control`, A2)                                                                | v42 ✓ (`/`) / v43 ✓                                                                                     |
| Links at rest and on hover (`.settings-link`/`.back` hover at `--signal-dim`; `.inline-link` `--signal-dim` at rest, `--signal` on hover)          | `.inline-link` at rest follows the global `a` row (`--text-primary` + underline). Every link's hover/focus is `--text-primary`. `--signal-dim` as text is 3.09:1 on the page, so this is a contrast fix too (F09) | v42 (rest colour on every route with A2; hover on `/` and every `.back`) / v43 ✓ (`.inline-link` hover) |
| Idle `/login` needle                                                                                                                               | `--text-muted`, no glow, at rest. Amber with its glow only while sweeping (`submitting`), the one moment the dial is actually tuning                                                                              | v43 ✓                                                                                                   |
| Idle `/library` progress bar                                                                                                                       | `--signal-dim` only while a sweep is running (the existing "happening, but not this session's track" carve-out in §6). A finished run's bar is `--settled-dim`                                                    | v43 ✓                                                                                                   |

The same test covers sites F10 didn't list (for example `.load-more`'s and QueueControls' hover
borders at `--signal-dim`): a hover, focus, pressed or selected state is never "receiving", so it
never takes amber. Text selection (`::selection` at `--signal-dim`) is transient and user-initiated,
not chrome, and keeps its color.

> **v42 (2026-10-15):** every `/` row above is applied (✓), plus the unlisted `/` sites:
> `.load-more`, the queue controls and JobRow's priority-input focus border. On `/`, `--signal` now
> appears only on genuinely live things: a receiving lane, an expanding job's dot, the prompt while
> sending, the live bar segment, `::selection`, and an active or expanding job's
> badge (v20's `cond-live` mapping, v41's row; unchanged here). v41's job and track rows keep their amber (a downloading
> state, the live bar segment) while the link is down; only the v42 surfaces (Waterfall lanes, the
> incoming dot, the ambient field) drop it. Aligning the rows is v47's. On the other routes v42 changed only what A2 required (no `--signal-dim` text, so `.inline-link` rests at `--text-primary` and `.back` hovers to it); `.inline-link`'s amber hover and the remaining rows stay v43's.

> **v43 (2026-10-16):** every remaining row is applied (✓) on `/settings`, `/library`, `/account`
> and `/login`. The `.inline-link` class is gone: in-text links use the global `a`. A pressed option
> takes `/`'s v42 chip idiom (`--bg-3`, full text, a 2px `--text-muted` floor line) rather than the
> table's `--line-bright` border, so a pressed option reads the same on every route. On those four
> routes `--signal` appears only on the login needle while connecting and the `/library` bar while a
> sweep runs (`--signal-dim`), plus `::selection`.

### Focus

| Token          | Hex       | Use                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| -------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--focus-ring` | `#ffd479` | The single keyboard focus treatment, `:focus-visible { outline: 3px solid var(--focus-ring) }`, global, never overridden with `outline: none` anywhere in the tree. This is a direct consequence of PRODUCT.md's confirmed keyboard-only accessibility requirement — it is a hard requirement, not a nice-to-have, and the ring is intentionally a near-signal amber tint so it reads as part of the same instrument-panel world rather than a generic browser default. |

**Rule**: `--focus-ring` is distinct from `--signal` on purpose (lighter/desaturated) so a focused
element is never visually confusable with a genuinely live download.

## 3. Type system

Two families, strictly divided by _kind of content_, not by visual weight:

- **IBM Plex Mono** (`--font-mono`) — every number, timestamp, state tag, label, countdown, and
  UI chrome text (buttons, filter chips, the login dial's frequency ticks). Loaded at weights
  400/500/600 via Google Fonts in `app.html`.

> **v42 (2026-10-15, F12, owner-approved narrowing):** on `/`'s v42 surfaces mono now covers
> numbers, timestamps, state tokens, addresses (URLs), idents and control labels only. Sentences
> moved to Sans: error and hint lines, the Waterfall's status notes, the incoming failure reason,
> and every empty, loading and error state's sentences (the server's own error string and the head's
> "Loading…" count stay mono, as machine text and a count). Control labels (buttons, chips) **stay mono** in
> v42 so they match v41's row actions on the same screen; moving every control to Sans at once,
> tree-wide, is v47's.

- **IBM Plex Sans** (`--font-sans`) — the document body default and all real content: song
  titles, artist names, album names. Loaded at weights 400/500/600 alongside the mono family.

**Named rule**: this split exists so theming never sacrifices legibility of actual data — a
listener's song/artist/album text is never rendered in the "instrument" typeface. Any new
component must ask "is this a system/meta value or is it content a user is trying to read" before
picking a family; do not default new components to mono just because the world is technical.

### Type scale (v42, F12)

v39 found six ad hoc sizes, nothing above 15px, and a `15px` body that ignored the user's own text
size. v42 replaces them with a small set of named **role** tokens in `app.css` (mirrored in
`design-tokens.json`), fixed rem steps of about 1.08–1.18 (Operate mode: a dense product surface,
not a fluid display ramp):

| Token         | Size               | Role                                                                    |
| ------------- | ------------------ | ----------------------------------------------------------------------- |
| `--fs-label`  | `0.6875rem` (11px) | Uppercase idents and section labels (`.label`, the panel headings)      |
| `--fs-meta`   | `0.75rem` (12px)   | Chips, counts, mono meta, small controls                                |
| `--fs-detail` | `0.8125rem` (13px) | Secondary lines: artists, reasons, errors, countdowns, the masthead nav |
| `--fs-body`   | `0.9375rem` (15px) | Body and content; `body` uses it, so text scales with the browser       |
| `--fs-lead`   | `1.0625rem` (17px) | The wordmark (`/`'s one `h1`)                                           |
| `--fs-title`  | `1.25rem` (20px)   | A state's own heading (the empty and error states)                      |

Weights: `--fw-regular` 400, `--fw-medium` 500, `--fw-strong` 600. Every `font-size` in v42's files
(`+page.svelte`, `Waterfall`, `IncomingJobs`, `QueueControls`, `WorkerStatusPill`, `Countdown`,
`app.css`) is one of these. v41's rows and the v43 routes still carry literals from the old ramp
(most map onto the scale; the off-scale ones are the login dial's 9px ticks and one 14px `0.875rem` in `TrackRow`) and
migrate in v43/v47. Don't add a size between the steps.

> **v43 (2026-10-16):** migrated in every file v43 touches: the four secondary routes,
> `WorkerStatus`, the new components and v41's `JobRow`/`TrackRow` (touched for their
> confirmations). The values were already on the scale except two: the login dial's 9px ticks are
> now `--fs-label` (11px) and `TrackRow`'s 14px artist/album line is `--fs-detail` (13px), the role
> this table gives artists.

`.mono` utility class adds `font-variant-numeric: tabular-nums` and `letter-spacing: 0.01em` —
**any new numeric/timestamp display should use `.mono`, not a bare font-family override**, to get
tabular alignment for free.

`.label` utility: mono, 11px, weight 500, `letter-spacing: 0.12em`, uppercase, `--text-dim`. This
is the system's one "meta/eyebrow" text pattern — used for panel headers, section labels, idents.
Reuse it rather than inventing a second all-caps convention.

## 4. Spacing scale

4px base, defined once as `--space-1` through `--space-8`:

| Token       | Value     | px                                                               |
| ----------- | --------- | ---------------------------------------------------------------- |
| `--space-1` | `0.25rem` | 4                                                                |
| `--space-2` | `0.5rem`  | 8                                                                |
| `--space-3` | `0.75rem` | 12                                                               |
| `--space-4` | `1rem`    | 16                                                               |
| `--space-5` | `1.5rem`  | 24                                                               |
| `--space-6` | `2rem`    | 32                                                               |
| `--space-7` | `3rem`    | 48 (defined, not yet consumed by any built component — reserved) |
| `--space-8` | `4rem`    | 64 (defined, not yet consumed by any built component — reserved) |

**Rule**: every gap/padding value in every component reads from this scale. No bespoke pixel
value appears in any `.svelte` style block read for this document — treat that as the standing
convention for v10+.

### Row grid (v41)

`app.css` also defines the columns the job list shares, so rows line up instead of each
component guessing: `--row-pad-x`, `--row-gap`, `--col-lead` (a job's chevron, and the nesting
rail under an open job), `--col-state` (a job's badge and a track's state), `--col-progress`,
`--row-nest` (one lead column plus a gap: the indent of a nested track list) and
`--cell-inset` (a badge's text offset, so a track's state text sits under the badge text). A
nested track's state is under its job's badge and its title under the job's title; the expanded
detail hangs off the same title column. Any new row in the job list uses these, not local widths.

## 5. Motion

| Token           | Value                           | Use                                                                                                          |
| --------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `--ease-signal` | `cubic-bezier(0.16, 1, 0.3, 1)` | The one easing curve for every animated transition in the system (progress fill, sweep needle, button hover) |
| `--dur-fast`    | `120ms`                         | Hover/focus state changes                                                                                    |
| `--dur-med`     | `320ms`                         | Progress-bar fill transitions                                                                                |
| `--dur-slow`    | `900ms`                         | The ambient field's rest ↔ live tone crossfade (`AmbientField.svelte`, v40)                                  |

**Named rule — reduced motion is load-bearing, not decorative**: `@media (prefers-reduced-motion:
reduce)` zeroes all three duration tokens globally in `app.css`, and every bespoke `@keyframes`
animation in the tree (login needle sweep, waterfall noise floor, progress-fill shimmer) has its
own matching `prefers-reduced-motion` override alongside the global one. **Any new keyframe
animation added in v10+ must ship its own reduced-motion override in the same component** — the
global duration-zeroing does not reach hand-authored `animation:` shorthand time literals (e.g.
`animation: noise 4.2s ease-in-out infinite` is a literal, not a var, and needs its own `{
animation: none }` fallback).

**Script-driven motion follows the same rule** (v40, `AmbientField.svelte`, the tree's first). A
frame loop has no CSS duration to zero, so it checks `prefers-reduced-motion` itself and, when
reduced, never starts: no pointer listener, no `requestAnimationFrame`, a static layer. Any later
script-driven animation needs the same check. It must also stop when settled and while
`document.hidden`; no frame loop may spin permanently.

## 6. Component patterns

### `.panel` — the raised faceplate (v42; was "the recessed instrument housing")

The one shared surface convention (`bg-1`, `1px solid var(--line)`, `border-radius: 6px`, plus a
compound `box-shadow`: inset top shadow + inset bottom highlight hairline + outer drop shadow). _(Corrected 2026-10-15, v42: the
shadow is now an inset top bevel highlight, a 1px dark lower edge and an offset drop shadow; see the
"Decided" note below.)_
Every panel-like surface in the tree (login form, submit bar, waterfall, spectrum log) uses this
class rather than a locally redeclared surface style.

**Accepted, open gap** (do not treat as solved): the intended "matte charcoal chassis" material —
a perceptibly recessed/lifted panel, distinct from a flat SaaS card — was never made clearly
perceptible against the near-black page background, across two correction rounds. Round 1's 1px
inset hairline was mechanically present in the DOM but invisible at normal viewing distance;
round 2 widened it to the current compound shadow (`inset 0 2px 5px`, `inset 0 -1px 0`, `0 8px
20px -10px`), which is a real improvement but still not confirmed to read clearly as "recessed
housing" rather than "bordered card" on typical displays. **This is recorded honestly as unfinished
visual-polish work for whoever picks it up next (candidate for v10+), not as a closed decision** —
do not spend more `box-shadow` layers chasing it without first checking whether it's actually
legible on a real device, and do not describe the chassis material as "done" in any future
changelog entry without new evidence.

> **Decided 2026-10-15 (v42, F36; owner's choice: "make it perceptible"):** the chassis is kept and
> inverted from _recessed_ to _raised_. Shadow layers were never going to carry it: the surface step
> does. `--bg-1` moved from `#14181c` (1.10:1 against the page) to `#191e23` (1.17:1), and the shadow
> is now a machined top bevel (`inset 0 1px 0 rgba(255,255,255,.055)`), a 1px dark lower edge and a
> short offset drop shadow (`0 6px 12px -7px`, under the detector's 16px wide-shadow line). What is
> _cut into_ a plate keeps the old recessed language: text inputs and the sort select are `.well`s
> (`--bg-0`, `--line-control` edge, an inset shadow); the Waterfall meters are wells too but keep the
> quiet `--line` edge, since a meter is read by its fill, not its border. So plates are raised and
> wells recessed, and the two read apart at a glance. The ambient field (§6) still lights only the
> gutters: plates are opaque. Visible in every v42 screenshot. §8.1 is closed by this.

### Hero-marking border (the "is anything live" tell)

`Waterfall.svelte`'s top border is neutral (`--line-bright`) by default and switches to
`--signal-dim` only when `tracks.length > 0` (`.waterfall.live`; v42: and the link is live). This is the concrete embodiment
of the amber-exclusivity rule in §2 — the panel itself is the primary visual proof that "live" is
reserved, not just a color-token comment. **Any future panel that wants to signal "something in me
is currently active" should use this same neutral→signal-dim border-color swap pattern, not a
persistent accent border.**

> **v42 (2026-10-15, F04):** a third edge state. While the breaker holds and nothing of this
> session's is receiving, the edge is `--waiting-dim`: a hold is a scheduled, self-clearing
> condition, the waiting colour's meaning. A pause keeps the neutral edge: it isn't scheduled (it
> holds until a human resumes it, which is why the admin's pill shows it red).

### Waterfall idle status and the link tell (v42, F04/F05)

The full idle panel stays (owner's choice over a one-line strip). Its status line says _why_ nothing
is receiving, in priority order: **link lost — reconnecting** (this page's SSE stream is down, so
nothing else on the panel can be trusted), **tuning in…** (not yet connected), **receiver paused**,
**holding · resumes in …** (the breaker; a countdown, plus "a deliberate pause after repeated rate
limits; waiting tracks keep their place"), **no signal here — worker busy elsewhere**, and **no
signal — nothing downloading**. It never says "idle" while the breaker holds. The noise floor only
moves while the receiver is listening (or tuning in, before the stream first opens): held, paused or with the link lost it lies flat. A countdown
never sits inside a live region: the panel has one `sr-only` status region holding a fixed sentence
per state ("Downloads holding until 23:20", "Receiver paused", then once "Downloads resumed";
a lost link is announced by the masthead tell instead), and the ticking text is `aria-hidden` (F07's lesson, same in the pill). With lanes
up and the link down, the lanes dim and the head reads "link lost — progress may be stale".

The masthead carries the same link as a small tell: **linked** (a filled muted dot), **linking…**
(on load and on a mine/all-users switch, until the first attempt resolves; a first attempt that
fails reads link lost, since there is no link) or **link lost —
reconnecting**; both not-linked states take a hollow waiting-blue ring that pulses slowly (the pulse
is off under reduced motion). Lanes on screen while the link isn't open came from a REST snapshot
and don't update, so they dim, lose the amber fill, the panel edge stays neutral and the ambient
field stays slate (an expanding submission's dot likewise turns muted and still); the head reads "link lost — progress may be stale" (or "linking… — …").
The tell differs in shape as well as hue, and it is never amber: a link is not a download. It is a
`role="status"` region that changes only with the state.

**v20's "worker busy elsewhere" indicator is the sharpest test of this rule yet.** `worker-dl`'s
global `--concurrency=1` means the waterfall is idle-for-this-session far more often than not —
someone else's download, not a stall. The temptation is to reuse `--signal` for "something, out
there, is alive," but that would spend the one committed live-signal color on a condition that
isn't live _for this viewer_; the border stays neutral (`.waterfall` without `.live`) and only the
idle-state text swaps to `"no signal here — worker busy elsewhere"`, still `--text-muted` via
`.label.dim`, never amber. _(v42: that line is now the Waterfall's `.status` word in `--text-dim`, still never amber.)_ `--signal` is reserved for _this session's own_ active track, full
stop, not "the global worker."

### Ambient field (`AmbientField.svelte`, v40)

The page's light: one `position: fixed`, full-viewport, `pointer-events: none`, `z-index: -1`
layer, mounted once in `routes/+layout.svelte` so every route has it. It sits behind the panels
(their `--bg-1` fill is opaque), so it lights only the page gutters and the text set directly on
the page (headers, hints, the `/login` ident). Its home is approximately the old body ellipse's
composition: a 72×44rem element (1152×704px at the default 16px; it grows with text scaling) (the old visible ellipse was about 1080×600) centred at 50% /
−10% of the viewport, so at rest the page reads as it always did, minus the amber.

**Behavior.** With a hovering fine pointer, the glow follows the cursor. `pointermove` only stores
the latest position, and one `requestAnimationFrame` loop eases toward it (exponential approach,
τ = 180ms), moving the element by `transform: translate3d()` alone. It snaps and stops when it is
within 0.5px, and restarts on the next move. When the pointer leaves the window it drifts back
home; a native drag (which cancels the pointer and fires the same window-leave event) does not
count as leaving. A touch-type `pointermove` is ignored, so it never chases a tap. The loop reads no layout:
the viewport size comes from a `ResizeObserver`. While it can move, the moving `.glow` element
carries `will-change: transform`, so its gradient rasterizes once. Each frame then costs one 1-element
style update and a commit, with no layout and no repaint: about 0.3ms of main-thread work per
frame, measured on `/account` (v40 PR). On an idle `/` the same style update also re-samples the
Waterfall noise floor's 40 animated bars (the trace's style update counts ~80 elements; ~0.3ms
more). That is the floor for any
script-driven transform; "composite only" is reachable only for CSS/WAAPI keyframes.

**Static cases (owner's choice, 2026-10-13): no hover or a coarse pointer, and
`prefers-reduced-motion: reduce`.** Phones keep the home position with no pointer listener and no frame
loop, which saves battery and leaves the Waterfall's noise floor as the only idle motion (§1). In a
hidden tab, the loop is cancelled.

**Tone, which is the amber rule (§2).** The two gradients are stacked and crossfaded on `opacity`
(`--dur-slow`, zeroed under reduced motion like every duration token): slate (`--text-muted`) at
rest, and amber (`--signal`) only while live. The layout defines live as
`page.route.id === '/' && activeTracks.length > 0`, the same condition as the Waterfall's
`.live` border. **Only `/` holds the live stream.** Navigating away closes it but leaves
`queue.activeTracks` at its last value, so on any other route that store is stale and must never
light the page. Any future consumer of `activeTracks` outside `/` has the same problem. On
re-entering `/`, the stale value still holds until the new stream's `onopen` resync replaces it,
so the field (like the Waterfall's border) can begin warming for a moment, or stay warm while the
API is unreachable, before settling to the truth. That window is the Waterfall's own, not new.

**Contrast budget.** The peaks aren't a matter of taste. The old ellipse's centre sat off-screen,
so the brightest pixel anyone saw was its top edge, and that edge dims as the viewport grows
taller: amber at 5% × (1 − 0.1·height / 300px). The new peak sits under the cursor, over any text,
so it is held to exactly that visible maximum. `peaks()` sets `--live-peak` from the viewport
height on resize (3.5% at 900px, 2.6% at 1440px), and `--rest-peak` at 1.15× that. Slate's
luminance-equal factor is ~1.25, but 8-bit rounding can then put slate one code value above amber
at some heights, so 1.15 keeps a margin. Measured against the old rule rendered in the same
browser at eight viewports, from 1280×640 to 2560×1440 plus a 390×844 phone, no token is worse at
either tone. Beyond that range (viewports over ~2380px tall) the 8-bit model allows slate to be
one blue code value brighter than amber, a contrast difference in the third decimal place. Raising either peak breaks
that. The gradient peaks only about 4–9 8-bit code values above the page color in its strongest
channel (more on shorter viewports, about +10 below ~650px tall), so faint stepping
(banding) shows on close inspection. The pre-v40 glow had the same stepping. It is accepted,
because the only cure that stays inside the budget (dithering) costs more than it buys.

### Worker status pill + settings-page worker controls (`WorkerStatusPill.svelte`, `WorkerStatus.svelte`, `stores/worker.ts`, v25)

> **v43 (2026-10-16, F17/F30/A4):** `WorkerStatus` renders for the admin only (no `isAdmin` prop;
> `/settings` shows a non-admin the notice instead). The state is a sentence: **Downloads
> running** (muted), **Downloads paused** (`--fail`, it needs a human) and, beside either,
> **Holding until 23:20 · resumes in …** (waiting blue, the countdown `aria-hidden`; one `sr-only`
> status sentence per state). The buttons name their action: pause/resume downloads and, while
> holding, **release now** (`.btn.danger`). Pause and release ask first; resume doesn't. "Receiver
> power" and the `aria-pressed` toggle are gone.

The "worker busy elsewhere" indicator above used to live inside one full `WorkerStatus` panel
rendered on the dashboard for every user, with the pause/resume toggle and breaker-release button
sitting right alongside it, gated only by `isAdmin` at render time (the server-side `require_admin`
check was always the real enforcement — see the component's own comment). v25 splits that one
component in two. The always-visible half becomes `WorkerStatusPill.svelte`, a compact
`role="status"` pill now living in `+page.svelte`'s header `.session` row (L145), next to the
library/settings/account links and the disconnect button — **not** between the submit form and the
queue, where the old full panel would have competed with the waterfall for space above the fold.
The admin-only pause/resume toggle and breaker-release button stay in `WorkerStatus.svelte`
verbatim, unchanged except that it now only ever renders on `/settings`, under a "Worker control"
heading (`routes/settings/+page.svelte` L227-230) — reachable via every user's own `/settings` link
but functionally inert for a non-admin, same as before the split.

The pill has three states, on the same 5s poll the old panel used (still no SSE event for
worker/breaker state): `cond-fail` "breaker tripped" (+ a live `Countdown`), `cond-fail` "receiver
paused", or the default `cond-idle` "receiving" (`WorkerStatusPill.svelte` L28-39). Paused/tripped
reuse `--fail`, the same token the old toggle's `aria-pressed` state and breaker banner already
used, so the meaning doesn't shift just because the surface did. The default state is `cond-idle`,
not `--signal` — a "nothing's wrong" pill visible to every user on every page load is exactly the
kind of near-permanent chrome §2's amber-exclusivity rule exists to keep amber out of.

> **v42 (2026-10-15, F06/F07, v39 outcome 3):** the pill is operator detail, so `/` renders it
> for the admin only (absent from a non-admin's DOM; they get the Waterfall's plain status line). Its
> 5s poll moved to the page, which every user needs (the Waterfall and TrackRow's breaker-aware
> countdown read the store). A tripped breaker now reads **breaker holding · clears in …** in the
> waiting blue, not `--fail`: it is expected and self-heals. **receiver paused** stays red, since it
> holds until a human resumes it. The normal state reads **worker ready**. The live region is one
> `sr-only` sentence per state, never the per-second countdown.

v25 also threads a `username` (nullable, populated from the upstream `GET /user`) through
`SessionInfo` and the pre-existing job/track `owner_username`/`owner_email` fields. One
`api.displayName(username, email)` helper (`api.ts` L296-298) is now the single place that decides
username-vs-email, called from the dashboard header (`+page.svelte` L152), the tracks-view group
header, and `JobRow.svelte`'s owner column — so the three surfaces can't drift into showing
different identities for the same person. No new token: identity strings were already rendered
`.mono` before v25 (a system/meta value, not song content, per §3's split), and username just
extends that existing convention rather than starting a second one.

### State → color/label mapping (`TrackRow.svelte`, v20; formerly `QueueTable.svelte`)

Two parallel `Record<TrackState, string>` maps — `STATE_LABEL` (in-world copy: "receiving",
"fading — waiting", "no signal — not found", "logged", "lost") and `STATE_COND` (one of the five
`.cond-*` classes from §2) — are the single source of truth for how a track state renders. **Any
new `TrackState` value added in a future version must get an entry in both maps in the same
change**, never inferred or left to fall through to a default, or a new state will render with no
label/color at all. v16 removed `TrackState.FAILED` entirely (a migration, not a rename) — both
maps cover exactly the eight states that remain, no `failed` entry. v20 renamed
`lookup_failed`'s copy from "no signal — given up" to "no signal — not found": the behavior was
never "given up" (the state is terminal and never auto-retried, same as always), only the old
wording implied abandonment rather than "this specific lookup came up empty."

> **v41 (2026-10-14, F21, owner's call):** `STATE_LABEL` now uses the state-filter chips' words
> (pending, queued, downloading, completed, waiting, not found, duplicate, cancelled), so a state
> reads the same on a chip and on a row, and no label truncates in the state column (F13). The
> in-world voice stays on idents and moments; v46 re-words both for i18n.
>
> **v46 (2026-10-18):** the labels are now functions over the message files
> (`lib/i18n/labels.ts`'s `trackStateLabel`/`jobStatusLabel`, TrackRow's status and outcome
> tables), in Hungarian: sorban áll, indulásra kész, letöltés alatt, letöltve, várakozik, nem található,
> már megvan, megszakítva; job statuses hangolás, aktív, várakozik, kész — részben, kész,
> megszakítva, sikertelen.
>
> **v42 (2026-10-15):** one deliberate exception, the owner's choice: a non-admin's tracks scope
> has a single **in progress** chip standing for pending, queued and downloading (v39 outcome 3),
> while the rows keep the exact state word. The chip is a grouping of row words, not a fourth word.

### Job status → color/label mapping (`JobRow.svelte`, v20)

The job-level counterpart of the above, over `JobStatus`'s `statusKey()` token (`"expanding"`,
`"active"`, `"waiting"`, `"settled:partial"`, `"settled:complete"`, `"cancelled"`, `"failed"`)
rather than `TrackState` — same five `.cond-*` classes, reused rather than inventing a second
vocabulary. `expanding` maps to `cond-live` (amber), matching `IncomingJobs.svelte`'s pre-existing
pulsing-dot treatment for the same state, not `cond-idle` — a job actively being expanded reads as
"something is happening right now," the same category as a track actively downloading.
`settled:partial` maps to `cond-fail`: it is a genuinely terminal, no-further-action state with a
real gap (≥1 track that didn't make it), the same bucket `lookup_failed` already occupies at the
track level — never `cond-waiting`, which §2 reserves for recoverable backoff, not "done, but
incomplete." The labels themselves (`api.STATUS_LABEL`; v46: `lib/i18n/labels.ts`'s `jobStatusLabel`) are shared between the state-filter chips
and the job-row badge so the two can't drift apart: `"done — partial"` for `settled:partial`,
never "failed" or "partial" alone, so a glance at either surface reads the same story.

> **v42 (2026-10-15, F28):** `settled:partial` is `cond-fail` only when the job has a
> `lookup_failed` track. A job that is partial only because its owner cancelled tracks has no gap
> they didn't choose, so it reads `cond-idle`. A job whose title is still its link (nothing read yet)
> shows the link as an address (mono, muted, regular weight), not a bold title. A one-track job
> shows no separate count line, since the badge and bar already say it (the bar's accessible name
> still carries the count). A one-track job keeps it whenever the badge doesn't name its track's
> own bucket (a partial job, one cancelled after its track completed, a stale row): colour alone
> mustn't say it (WCAG 1.4.1).

### Segmented job progress bar (`JobRow.svelte`, v20)

A job row's per-state track counts render as a horizontal bar of proportionally-sized flex
segments, each colored with the same five condition tokens used everywhere else (`--signal`,
`--waiting`, `--settled`, `--fail`, `--line-bright` for idle/cancelled) — never a sixth palette.
Segment width is `count / total` as a flex-basis percentage; a zero-track job (`expanding`/
`failed`) renders no bar at all rather than an empty one, since a bar with nothing to show is
worse than no bar. `role="img"` with an `aria-label` carrying the same text as the adjacent count
breakdown (`"1,204 done · 12 waiting · 1 not found"`) rather than leaving the visual-only bar
unannounced to a screen reader.

### Library sweep page (`routes/library/+page.svelte`, v28)

> **v43 (2026-10-16, F20):** the page now has three states. _No sweep yet_ says so. _Running_ reads
> "Sweeping · 8 of 136 files" over the `--signal-dim` bar, with the four counts updating live
> (errors so far are the processed files not filed any of the three ways, since the progress event
> carries no error count) and a waiting-blue "Live updates lost" line while the stream reconnects.
> _Finished_ reads "Last sweep finished <date> · took <n>s"; its bar is `--settled-dim`, not amber.
> The report is four labelled numbers (moved, duplicates deleted, duplicates quarantined, errors: the
> backend counts a duplicate as one or the other, by the quarantine setting) (number first, `--fs-title`), errors in `--fail` only when
> non-zero; failed files are listed under "Not filed" with recovery copy, identical rows folded into one
> entry marked ×n (the count stays the backend's, matching the sweep's alert). The fill stays
> `transform: scaleX()` on `--dur-med`, and the bar is named "Sweep progress". The text below
> describes v28.

The admin-only sort-and-move sweep gets its own route rather than a modal or an inline panel on
`/settings` — reachable from the dashboard header's `library` link (`+page.svelte` L147, admin-only
alongside `settings`) and cross-linked both ways with `/settings`'s "Library sort & move" section,
which holds the actual target-directory / folder-template / quarantine form fields (`settings/
+page.svelte` L282-348) and only links out to `/library` to trigger a run. Config lives on
`/settings`, the run/report view gets its own page — the same split `/settings` (config) vs. `/`
(live queue) already establishes system-wide, rather than growing a third pattern for this one
feature.

Progress reuses the existing `role="progressbar"` convention (§7) over the sweep's `processed` /
`total` counts, but its fill color is `--signal-dim`, not the full `--signal` a live per-track
download uses (`Waterfall.svelte`, `JobRow.svelte`'s segmented bar) — the same carve-out v20 already
established for "something is genuinely happening, but not _this session's own active track_" (see
the Hero-marking border and worker-status-pill notes above): a background admin sweep is real and
running, but it isn't the one thing `--signal` is reserved for. Progress arrives over the same
shared SSE stream as everything else (a `library.progress` event type, `+page.svelte` L44) rather
than a dedicated poll or a second connection — consistent with this app having exactly one
live-update channel, not one per feature.

The finished-run report (moved / already-present / quarantined / error counts, `+page.svelte`
L114-133) colors only the error count `--fail` when non-zero (`.count.fail`) and lists individual
file errors in `--fail` text — the same "hold red back for genuinely terminal/failed outcomes" rule
§2 applies to track and job states applies here too, one level up: at the level of a whole sweep
run instead of one track.

### Sort headers (`QueueControls.svelte`, v20)

Reuses the Filter-tabs convention below (`role="group"`, `aria-pressed` buttons) rather than an
HTML `<table>`'s clickable `<th>` — this app has never used table markup for its dense lists (see
the Mobile stacked layout note), so a sort control needed the same button-group idiom instead of
relying on `aria-sort`. The active sort field's button additionally shows a `▲`/`▼` glyph
(`aria-hidden`, the button's own `aria-pressed` state is what a screen reader announces) indicating
direction; clicking the already-active field flips direction, clicking a different field switches
to it at `dir=desc`. Available fields differ by scope (`created_at`/`title`/`status`/`track_count`/
`next_retry` for Jobs, `created_at`/`title`/`state` for Tracks) — never the same fixed list for both,
since the two endpoints' own `sort=` parameters genuinely differ.

> **v42 (2026-10-15, F11):** five equal-weight sort chips were a large part of "cluttered", so sort
> is now a native `<select>` (a `.well`, labelled "sort") plus one direction button ("Reverse sort order (now
> ascending/descending)", ↑/↓). Behaviour is unchanged: a different field starts descending; the
> button flips. `next_retry` ("next retry") is offered to the admin only: it orders by the retry
> ladder, operator detail (v39 outcome 3).

### Search box (`QueueControls.svelte`, v20)

The first plain `<input type="search">` in the tree — every prior text input (`login`, URL submit,
proxy add) mapped directly onto a single immediate action; this one debounces (300ms) before
calling into the store, since every keystroke would otherwise fire a real paginated request. Still
mono-free (`font-family: var(--font-sans)`) per §3's content-vs-chrome split — a search term is
user-authored text, not a system/meta value, even though it lives inside the instrument-panel
control bar.

### Jobs/Tracks scope toggle and archived/all-users toggles (`QueueControls.svelte`, v20)

All three reuse the Filter-tabs pattern (`role="group"`, `aria-pressed`, `--line-bright` pressed
state) already established by `+page.svelte`'s mine/all-users toggle — none of them represent a
live/active condition, so none of them use `--signal`, consistent with §2's exclusivity rule. The
Jobs/Tracks toggle is a distinct control from the admin-only mine/all-users toggle; both can be
visible at once and don't interact.

> **v42 (2026-10-15):** the page starts from the queue store's own mine/all-users scope, which
> outlives the page. Returning from `/settings` therefore keeps "all users", instead of showing
> "mine" over all-users data (which put foreign rows under the admin's name).

### Filter tabs

`role="group"` of toggle buttons using `aria-pressed` (not a radio input), each showing a live
mono count next to the label (`all 12`, `waiting 3`, `given up 1`). This is the pattern for any
future filter/tab control — `aria-pressed` boolean buttons with an inline count, not a `<select>`
or unlabeled icon toggle.

> **v42 (2026-10-15, F11/F21/F32):** a chip with a zero count is hidden (a pressed one always stays,
> so a filter can be switched off). A small `.label` before the chips names what the counts count
> (**jobs** or **tracks**), so a job chip's "waiting 1" isn't read against a row's "8 waiting".
> One chip may stand for several tokens: a non-admin's tracks scope merges pending, queued and
> downloading into **in progress** (owner's choice; the admin keeps all eight). Pressed is
> `--bg-3` with a `--text-muted` edge, primary text and a 2px `--text-muted` floor line (segments
> too); hover only lifts the text, so a hovered option never passes for the selected one. On a coarse
> pointer every chip, segment, the sort select and both text inputs are 44px tall. The scope switches (jobs/tracks, mine/all users) are one
> segmented control each rather than loose chips. The focus ring is drawn inside the segment
> (`outline-offset: -3px`, v45), for `.choice-group` too: outside, it spilled over the neighbouring
> segment and read as marking both. While a pressed segment has focus, the ring covers its 2px
> floor line; the fill and primary text still mark it pressed.

### Queue panel (v42)

The controls and the list are one faceplate (`section.queue`, headed by an `h2` "Queue" and the
list's size, e.g. "7 of 7 jobs" or "Loading…"). The log's own tools sit at the head's right, apart
from the view controls: **show archived** (a toggle chip) and **clear log**, outlined in
`--fail-edge` at rest like v41's destructive row actions, so it never reads as one more toggle (it
asks first since v43; see Confirmation). Then the find row (scope switch, search, the admin's mine/all users), the
refine row (chips, sort), a divider, and the list or its state:

- **Loading:** three still placeholder rows on the row grid (no shimmer); the head says "Loading…".
- **Error:** "Couldn't load the queue", the server's own words, and **try again** (`queue.reload()`).
  A failed **load more** is not this state: the loaded rows stay, a "Couldn't load more" line
  appears above the button, and the button retries that page (`page.moreError`).
- **Empty**, four cases (the fourth: a link still being read reads "Your link is being read", or "A link is
  being read" in all-users view, not "empty"): a search or filter miss ("No jobs match "…"" + **clear search and
  filters**), the admin's all-users view ("Nobody has anything queued"), and a user's own empty
  queue ("Your queue is empty", what happens to a pasted link, where archived jobs went, and
  **paste a link**, which focuses the submit box).

### Scope toggle (mine / all users, admin-only, v17)

`+page.svelte`'s admin-only "mine / all users" toggle reuses the Filter tabs pattern above
verbatim (`role="group"`, `aria-pressed` buttons, no `<select>`) but **does not** reuse its amber
pressed state — `border-color: var(--line-bright)` instead of `--signal`. This switches a view
scope, not a live/active condition, so §2's amber-exclusivity rule applies: the toggle is pressed
indefinitely while "all users" is selected, which is exactly the "permanent chrome" amber must
never represent.

### Attempt-history fan-out (expand/collapse row detail) (`TrackRow.svelte`)

Each track row is itself a `<button>` (not a row with a separate expand icon) toggling its own
local `expanded` boolean, exposing `aria-expanded`. The revealed `.detail` block is plain mono
text: attempt count, a live `Countdown` (only when `state === 'waiting'` and `scheduled_at` is
set), and `last_error` in `--fail` color when present. **This whole row-as-button disclosure
pattern is the convention for any future expandable list row.**

> **v41 (2026-10-14): the detail was redesigned; the description above is the v20 shape.** The
> row button now carries `aria-controls` and a trailing chevron (F22). The detail is the row's own
> grid, two columns: a status strip first (the state in plain words, the next-try countdown,
> which follows the breaker's clear when that's later (F04), and, for the admin, attempts /
> failed / last path), then one action area (retry now · download · cancel track, the destructive
> one set apart and outlined in `--fail-dim`, `--fail-edge` from v42), then, **admin only**, the attempt timeline: newest
> first, the time in the state column's gutter (absolute time on hover, focus, or a click that
> pins it), consecutive identical readings collapsed into one `×n` entry that opens on demand,
> raw errors clamped to three lines with a "show full message" control and always selectable.
> A non-admin's expanded track shows the status and actions only; the history's markup never
> renders and its request is never made (master plan amendment, v39 outcome 3). History is
> fetched on open and cached until the track's state or counts change.

### File-download action (`TrackRow.svelte`, v27)

The expanded row's `.actions` group (retry / cancel, above) gains a third button, `download`,
rendered only when `track.state` is `completed` or `skipped_duplicate` — the only two states
`download_track` (`backend/app/tasks/download.py`) ever sets `output_path` from, so the button
simply doesn't render for any other state rather than rendering and then 404ing (v27's own plan:
"nothing for tracks without a file"). A file deleted from disk after the fact still shows the
button; that request 404s and surfaces through the same per-row `notice` a failed retry/cancel
already uses, not a special-cased error path.

`handleDownload` (`TrackRow.svelte`) first sends a `HEAD` probe (`api.checkTrackFile`), so a
404/error response renders through this app's own notice UI instead of the browser replacing the
whole page with raw JSON. Only then does it click a temporary `<a download href>` pointing at the
real file URL, so the browser streams the file straight to disk (v35; v27 fetched the whole file
into a `Blob` in tab memory first). The probe also keeps v27's guard against a 0-byte "successful"
response: FastAPI's side of the endpoint is headers-only, with nginx's `X-Accel-Redirect` supplying
the actual bytes, so a proxy in front that doesn't understand that header would report
`Content-Length: 0`. Under the dev override, `vite.config.ts`'s dev fallback follows the redirect
itself, for `HEAD` as well as `GET`. The button itself reuses
the plain `.action` class already shared with retry/cancel — no new visual affordance for what is,
from the design system's point of view, just a third row action.

### Job-row expansion (`JobRow.svelte`, v20)

A job row cannot reuse the plain row-as-`<button>` pattern above unmodified: it needs several
_other_ real interactive controls (priority input, bump/cancel/archive buttons) alongside the
expand toggle, and nesting a `<button>`/`<input>` inside another `<button>` is invalid HTML. The
fix is structural, not a new visual pattern: the expand toggle is its own `<button>` wrapping only
non-interactive content (chevron, badge, title, source-type, owner), and the action controls are
separate sibling elements in the same flex row, never inside the toggle button. Expanding renders
`JobTrackList.svelte` (a paginated `TrackRow` list scoped to that one job) below the row, fetched
fresh on first expand — never all of a job's tracks eagerly. Expansion state lives in
`stores/queue.ts`'s `expanded` map (keyed by job id), not component-local state, specifically so it
survives a filter/search change within the same session (the plan's explicit requirement) rather
than resetting every time the underlying page reloads.

> **v41 (2026-10-14):** the toggle has no `aria-label` any more, so its name is what it shows
> (status, title, type, owner; F16), plus `aria-controls` to the track list. The row sits on the
> row grid (§4), and the open job's tracks hang off a 1px rail in its chevron column, indented by
> `--row-nest`, on the panel's own surface rather than the old darker `--bg-0` well (F02).

### Page breakpoints (v42, F15/F37)

Three bands: phone `≤640px`, tablet `641–1023px`, desktop `≥1024px` (the stage stays a 64rem
column). Desktop: the masthead is one row (ident · receiver status · account nav). Tablet: ident and
nav share the first row and the status drops under them. Phone: the masthead is two lines (wordmark
with the link tell, then the nav, **disconnect** pushed right; an admin's five items wrap it to a second row; v44: six, with **stats**), the page gutter is
16px, the Waterfall's lanes put the title line above meter + percentage, and the incoming rows put
their actions under the link (phone and tablet, ≤1023px). Coarse pointers get 44px targets whatever the width (`@media
(pointer: coarse)`) on the controls that carry the task: v41's job and track row toggles and actions included (F32). The
admin attempt timeline's small inline toggles (time pin, show all, show full message) stay at
WCAG 2.5.8's 24px; v47. v41's rows keep their own 640/960 folds.

### Mobile stacked layout (`TrackRow.svelte`, `JobRow.svelte`, ≤640px)

`TrackRow`'s five-column grid collapses to a fully stacked flex column, one cell per line, in an
explicit `order` (state, title, artist, album, progress) — the same layout `QueueTable.svelte`
originally established, carried over verbatim when v20 extracted the row into its own component.
**Two rejected intermediate designs from that original build are worth restating so they aren't
re-attempted**: squeezing all columns proportionally became unreadable, and pairing cells onto
shared sub-columns (title+job, artist+album) reintroduced the same failure one level down — an
`auto` column sized to one row's longest value silently starved a _different_ row's column. The
fix that shipped is "give every cell its own full-width line, nothing ever competes for width" —
the standing rule for any future dense-table mobile collapse.

`JobRow` is flexbox (`flex-wrap: wrap`), not CSS Grid, so it was never exposed to that specific
shared-column-track failure mode in the first place (each `JobRow` is visually self-contained, not
sharing grid tracks with sibling rows the way `QueueTable`'s `<ul>` did) — but still gets an
explicit ≤640px `flex-direction: column` breakpoint rather than relying on wrap-based reflow alone,
confirmed against real, varied-length titles/album names at 390px (not assumed safe merely because
flexbox degrades better than grid did).

> **Correction, 2026-10-12 (v39 F01, fixed in v39.1).** That 390px check confirmed _width_ (no
> overflow) only. It missed that in a `flex-direction: column` stack every flex-basis sizes
> **height**. From v20 until v39.1, the desktop `.toggle { flex: 2 1 16rem }` made the toggle 256px
> tall (each phone job row 364px), and `.bar`'s `flex-basis: 100%` resolved against an indefinite
> height, overrode its `height: 0.5rem` and left only the 2px border, so job progress was invisible
> on phones. The mobile block now gives `.toggle`, `.bar` and `.row-actions` `flex: 0 0 auto`
> (`.breakdown` already sized to its content). Rule for any column-direction
> collapse: reset the children's flex-basis and check heights, not only widths. e2e spec 10 guards
> it.

> **v41 (2026-10-14): both stacks were redesigned on the row grid; the one-cell-per-line text above
> describes v20–v40.** A phone job row is grid rows: chevron · badge · type (and owner) on the
> first line, the whole title on the second, then the bar with its breakdown and the actions, all
> on the column the nested tracks indent to. A phone track row is state, title, then
> "artist · album" as one muted line, with the chevron at the right. Between 641 and 960px a
> track folds artist · album under its title and a job's actions drop under its title (F37, for
> these rows only; the page breakpoint is v42's).

### Command-line submit bar

The primary action (`+page.svelte`'s URL submit) is framed as a console prompt: a static `>`
glyph (v42: `--text-muted` at rest, `--signal` only while sending, per §2's F10 table), a single input, a mono SEND/SUBMIT button — deliberately not a
labeled form field with a floating label or a card-style "New Job" affordance. This is the FIRST
VIEWPORT commitment from the direction contract, shipped as literally described.

### Confirmation (`ConfirmDialog.svelte`, `stores/confirm.ts`, v43, F08)

One confirmation for every destructive or risky action, chosen with the owner over an inline
two-step: a native modal `<dialog>` (`role="alertdialog"`, named by its title, described by its
subject and body) mounted once in the layout and driven by `await confirmAction({...})`, which
resolves `true` only on the destructive button. The top layer makes the page inert and keeps Tab
off the page; focus starts on the **safe** button; Esc, the safe button, a backdrop click and any
navigation answer `false`; focus returns to the trigger. It is the `.panel` faceplate over a dimmed
(not blurred) page, entering with a 6px rise on `--dur-med` (none under reduced motion).

Copy follows `clarify`: the title is a question naming the action ("Cancel this job?"), the
subject is the object as data (a job title, a proxy address, the library folder; mono, wrapping),
the body says what happens and whether it can be undone, and both buttons name their action
("keep job" / "cancel job"), never OK/Yes. The destructive button is `.btn.danger`.

Guarded: clear log, a job's cancel (in the list, and an incoming submission's while it is still
being read), cancel track, remove proxy, start sweep, breaker "release now" and worker pause
(A4). A failed submission's dismiss doesn't ask: that job is already over. Resume, archive and unarchive don't ask: they are undoable or safe. A new
destructive action uses this, never `window.confirm`.

### Secondary pages (v43)

`/settings`, `/library` and `/account` share `SubpageHeader.svelte` (v44: `/stats` too): the wordmark and the page
links (queue, then library and settings for the admin only (v44: then stats), then account; the current one is
`aria-current="page"`, primary text, no underline). `main` then opens with the page's one `h1` (`.page-title`) in Sans at
`--fs-title`. There is no eyebrow above the `h1`: the wordmark is the masthead, not a kicker.
A non-admin is never linked to an admin page. Typing the path gets `AdminOnlyNotice.svelte`, which
makes no admin request (F17).

The form vocabulary lives in `app.css` so the routes can't drift:

- `.btn` is the one button: `--bg-2`, a `--line-control` edge, mono `--fs-meta`, lowercase verb
  labels ("save", "add proxy", "start sweep"). Hover is `--bg-3` with a `--text-muted` edge; disabled
  dims the text (never opacity). `.btn.danger` is outlined in `--fail-edge` with `--fail` text and
  stays transparent on hover. `.btn.small` is the row-level size.
- `.form-field` is a persistent `.label`, the control (a `.well`), then a `.field-hint` and a
  `.field-error` (`aria-invalid` on the input, `aria-describedby` to both). A deliberate exception
  to §6's reserved-height rule: a field error reserves nothing at rest. It appears only after a
  submit, which moves focus to the first invalid field, and a reserved line under every field
  cost about 200px on a phone `/settings`.
- `.choice-group` is the segmented few-values choice (`aria-pressed` buttons).
- `.save-row` is a section's save button followed by its `role="status"` state: "Unsaved changes"
  once the form differs from what was loaded, then "Saved at 14:03" (F31: the old "Saved." never
  cleared).
- Validation mirrors the backend's rules (alert bounds, the proxy pattern, non-blank paths and
  templates) and answers inline before any request; the backend stays the real check.
- On a coarse pointer every `.btn`, `.choice-group` option, input and nav link is 44px (F32).

`/settings` is one page of five `.panel` sections (worker, output, library, alerts, proxies) with
an anchor index: a sticky column at ≥1024px that marks the section being read (a `--text-muted`
rail, never amber), a wrapping row of links below. No sub-routes, so no nginx change (F19). Alerts
are two groups, "Send an alert when" (each category with a one-line description) and
"Thresholds" (numbers with their units).

`/account` holds "Signed in" (name, email on the page, the admin's role, **disconnect**) and
"Preferences", whose first group is log retention. v45's shortcut switch and v46's language
switch and time format are further groups in Preferences.

### Admin stats page (`routes/stats/+page.svelte`, v44)

A flight recorder, not a KPI wall: no big-number tiles and no per-chart filters. Owner-approved
"now | over window" split. At ≥1024px a ~15rem **Right now** plate (queue counts as a ruled `dl`
readout, oldest waiting age, the breaker's state, proxies switched on / cooling) sits beside the
**window** plate. Below 1024 the plates stack with now first, and at tablet the readout runs across
as a wrapping row. The 24h/7d/30d `.choice-group` lives in the window plate's own head and scopes
only that plate. Refresh (`.btn.small`) and a `role="status"` "read at 14:03" sit in the title row.
One request per load and per window change, newest-wins by a sequence number. A refetch keeps the
frame and dims the old reading (`opacity: 0.55`, `aria-busy`) instead of showing a skeleton.

Colour by meaning only, on §2's five conditions: completed = settled, a failure the ladder retries =
waiting, not found = fail, an unrecorded cause = idle. Breaker holding ("holding until 14:30") =
waiting, downloads paused = fail, clear = primary text. A cooling proxy = waiting. **Never amber**:
nothing on this page is this session's live track. Validated on `--bg-1`: settled/waiting/fail are
ΔE 12.3 apart under deuteranopia (15.7 normal vision) and all ≥3:1. The validator's band and chroma
checks are for categorical palettes and don't apply to status colours.

- **`OutcomeBar.svelte`**: a route's or proxy's attempts as a part-to-whole bar, normalized to the
  row's own attempts (how often it works, not how busy it is). It sits in a `.well` with the quiet
  `--line` edge, has 2px surface gaps between segments, and is `aria-hidden`: every number is in the
  row's text.
- **Success rate** = completed ÷ (completed + failed). Not found is a verdict on the track and is
  counted apart. The definition is a visible line (`#rate-definition`) that both the routes and the
  proxies tables reference via `aria-describedby`, never a `title`. `formatRate` never rounds a
  partial up to 100% or down to 0% (`>99%`, `<1%`).
- **Proxy labels are host:port**, never a URL (rows keyed by position, since two can share one).
- **`FailureChannels.svelte`**, the recorder: one channel per failure class that occurred, on one
  shared y-scale (stated in a line above it) and one time axis. Breaker holds are the bottom channel:
  `--waiting-dim` fill with a 2px `--waiting` top edge, at least one bucket wide. An ongoing hold
  has its leading edge drawn and a manual release has its end edged in `--text-primary`. One
  crosshair readout reads every channel at once. The drawing is `role="img"` with a summary label,
  plus a "show as a table" `<details>` (per bucket, and the holds). Phones hide every other axis
  tick. Under `forced-colors` the marks are `CanvasText`.
- On a phone each table row becomes a stacked reading (route + rate, then the bar, units spelled out).
- A non-admin gets `AdminOnlyNotice` with its v44 `reason` prop ("count every user's downloads
  together") and the page makes no request. `SubpageHeader` and `/`'s nav link it after settings,
  admin only.

### Login "tuning in" instrument

`login/+page.svelte`'s dial (21 tick marks, every 5th labeled with a fake FM frequency, a sweeping
needle animated only while `submitting`) is a one-off flourish scoped to the login route — it is
not a reusable component and has no shared token beyond the ones in §2/§3/§4. Do not generalize it
into a shared "Dial" component unless a second real use case appears; it exists to make "signing
in" itself read as tuning in a receiver, matching the THESIS.

> **v43 (2026-10-16, F10/F31):** the dial stays. At rest the needle is `--text-muted` with no glow;
> it takes `--signal` and its glow only while connecting. Under TUNE IN one line says which account
> to use ("Sign in with your vb2007.hu account. Access is by invitation."). A failed sign-in puts
> focus back on the password (selected), with one `role="alert"` line. v46's language switch goes
> beside the ident, outside the dial panel.
>
> **v46 (2026-10-18, owner's rule on PR #68):** no switch after all. Signed out, `/login` speaks
> the browser's language; the language is chosen on `/account` and applies once signed in.

### Error / status text

Inline errors (`login-error`, `submit-error`) are `role="alert"` / `aria-live="polite"`, colored
`--fail`, mono, and reserve their vertical space at rest (`min-height`) so their appearance never
reflows the layout. Apply this pattern (reserved height + `aria-live`) to any future inline
validation message.

### Keyboard: shortcuts, roving lists, help overlay (`lib/keyboard/`, v45)

**One listener, one table.** `lib/keyboard/bindings.ts` is every binding as data (pure TS, so
the e2e suite imports it too); `registry.ts` is the single `window` `keydown` listener that
matches against it and runs the handler registered under the binding's id (the layout registers
the help and the `g` chords, `/` registers the list and queue keys). The help overlay
(`HelpOverlay.svelte`) is rendered from the same table, filtered to the route and the viewer's
role, so it can never list a key that does nothing or miss one that does.

**Hungarian QWERTZ first.** Most users type on a Hungarian layout. No binding needs AltGr, `y`
and `z` (swapped against US) are never bound, keys match on `event.key` (the produced character),
and a symbol that needs Shift on Hungarian is only ever an alias for a letter or unshifted key.
`bindings.test.ts` enforces all of that on the table. Guards in `registry.ts`: nothing fires while
typing in an input, textarea or `contenteditable` (except Esc). A `<select>` isn't typing (owner's
review): the shortcuts work on it (a bound letter no longer picks an option by its first letter;
unbound ones still do), and its own arrows, Home/End, Page keys, Enter and Space stay with it. Ctrl, Meta and Alt chords
are never shadowed; AltGr (`getModifierState('AltGraph')`, or Ctrl+Alt as Windows reports it)
never fires anything; IME composition and dead keys are ignored.

**The final table** (the overlay shows the same, with the Hungarian keys for each symbol):

| Key (Hungarian QWERTZ)                                                                 | Where              | Action                                                                             |
| -------------------------------------------------------------------------------------- | ------------------ | ---------------------------------------------------------------------------------- |
| `h`, alias `?` (**Shift + ,**)                                                         | everywhere         | Show or hide the shortcut overlay                                                  |
| `f`, alias `/` (**Shift + 6**)                                                         | `/`                | Search the queue                                                                   |
| `i`                                                                                    | `/`                | The submit field                                                                   |
| `Esc`                                                                                  | everywhere         | Close a dialog, else collapse the focused row, else clear and leave the search     |
| `g` then `d` / `a`                                                                     | signed in          | Queue / Account                                                                    |
| `g` then `s` / `l` / `t`                                                               | admin              | Settings / Library / Stats (absent for everyone else)                              |
| `j` / `↓`, `k` / `↑`                                                                   | lists              | Next / previous row (`j`/`k` from anywhere on `/` enter the list)                  |
| `Home` / `End`                                                                         | lists              | First / last loaded row; `End` on the last row loads more                          |
| **Shift + G**                                                                          | lists              | Load more                                                                          |
| `Enter` / `Space`                                                                      | lists              | Open or close the row (the button's own activation)                                |
| `→` / `o`                                                                              | lists              | Open the row; on an open job, move into its tracks                                 |
| `←`                                                                                    | lists              | Close the row, or go back from a track to its job                                  |
| `r` / `d` / `x`                                                                        | rows               | Retry / download / cancel (through the confirmation), only where the row offers it |
| `a`                                                                                    | job rows           | Archive or unarchive                                                               |
| `b`, **Shift + B** (alias `+`, **Shift + 3**), `-` (unshifted, the key **right of .**) | in-flight job rows | Bump; priority +1; priority −1                                                     |
| `e`                                                                                    | track rows, admin  | Open the track's history and show or hide every collapsed repeat                   |
| `1` / `2`                                                                              | `/`                | Jobs / tracks scope                                                                |
| **Shift + F**                                                                          | `/`                | Into the filter chips (`←`/`→` roam, `Space` toggles)                              |
| `s`                                                                                    | `/`                | Next sort field                                                                    |
| **Shift + A**                                                                          | `/`                | Show or hide archived jobs                                                         |

Single-character keys (everything above except `Esc`, `Enter`, `Space`, the arrows, `Home` and
`End`) are switched off by the per-user **Keyboard shortcuts** setting on `/account` (WCAG 2.1.4),
stored server-side (`user_settings.keyboard_shortcuts`, carried on `/api/auth/me`).

**Roving lists** (`lists.ts`): the jobs list, the tracks list, an open job's tracks and the filter
chips are each one Tab stop. A row's own button (`data-kb-item`) carries the roving tabindex; the
row's other controls are in the Tab order only while it is the current row **and open** (owner's
decision): Enter opens a job, then Tab walks its priority, bump, cancel or archive, its track list
(one stop) and "load more tracks". Focus is tracked by row **id**: an SSE re-order (which moves the
DOM node and drops focus) or a reload (which remounts the list) puts it back on the same row; a row
that leaves hands it to the next row, or the previous one if it was last; an emptied list hands it
to the queue heading. Never `<body>`.

**Visuals.** Focus is still the one global ring (§2 Focus); a roving row shows it on its button,
nothing else. The overlay is the confirmation's material (a `.panel` modal on the same dimmed
backdrop): keys left in a fixed track as keycaps, meaning right, one hairline between entries,
two columns of groups on desktop and one on a phone. A keycap (`kbd`, `app.css`) is recessed like
a well with a heavier floor, never amber (a key is not a live condition). The `g` chord readout
docks at the bottom edge in the panel's material and lists where each second key goes. The skip
link ("Skip to queue" on `/`, "Skip to content" elsewhere) is the first focusable element on every
page, off-screen until focused, then a small plate at the top-left.

### Language: Hungarian and English (`lib/i18n/`, `messages/`, v46)

**Every user-visible string is a message** in `messages/en.json` and `messages/hu.json` (Paraglide
JS), keyed by meaning (`track_cancel_confirm`), never by its English. `npm run lint` fails on a
hard-coded string in `src/` (`scripts/scan-literals.mjs`) and on any difference between the two
files' keys or inputs (`scripts/check-messages.mjs`). The deliberate exceptions carry an
`i18n-ignore` comment with their reason: the `SPOTDL // WEB` wordmark, CSS selectors, the proxy
format, and the English `detail` behind a client-side error code.

**Which language** (owner's rule, PR #68). Signed out, always the browser's: the first of its
languages that is `hu` or `en`, else English. Signed in, a language the user saved on `/account`
wins, else the browser's again. So someone who prefers English on a Hungarian browser sees
Hungarian on `/login` and English once signed in. Nothing is stored in the browser and nothing is
adopted at sign-in. `<html lang>` follows it, and a switch re-renders in place (no reload).

**The switches** are on `/account` only, in Preferences, each a `.choice-group` saved to the profile
the moment the server has it, with the shortcut switch's `role="status"` save line. **Language** is
labelled with each language in its own name and marked with its own `lang` (Magyar first, since
most users read it). **Time format** is automatic / 12-hour / 24-hour, each showing the current
time as it would read. `/login` has no switch: there the browser decides.

**Formats.** Words (month names, the AM/PM marker) follow the interface language. Conventions
(date order, digit grouping, decimal mark, 12- or 24-hour) follow the browser's region: English on
a Hungarian browser reads "17 Oct 2026, 13:05" and "12 345" (`lib/i18n/format.ts`, the `en-HU`
locale). Where Intl has no data for the pair (Hungarian on a US browser, `hu-US`), numbers and the
clock still follow the region and only the date order stays the language's. A time format pinned
on `/account` overrides the region's clock once signed in.

**What is never translated:** track, artist and album metadata, raw attempt error and note text,
proxy addresses, error-type machine names (`NO_OUTPUT`), and the wordmark. Matrix alerts and logs
stay English.

**Hungarian copy** is tegező (te) and keeps the signal-receiver voice where English has it
(hangolás, nincs jel, jelvevő, HANGOLÁS / KAPCSOLÓDÁS), with plain state words beside it. The
circuit breaker is the _biztosíték_ (fuse), so it never shares a root with _megszakítva_ (cancelled).
Lowercase action labels stay lowercase. A count is a plural message with Hungarian's singular noun
after a numeral ("5 szám"), taking the raw `count` for the form and a pre-formatted `n`
(`counted()`), so the number follows the browser's region like every other. A sentence with markup (`<kbd>`) keeps it in
the message and renders through `RichText.svelte`. `Countdown`'s label stands before the time
(`feloldásig 4:32`), and the time never wraps internally. Hungarian runs longer: v46 checked every
route at 1280px and 390px for clipped text; the submit field's placeholder clips at 390px in both
languages, as it did before.

## 7. Accessibility (confirmed hard requirement, PRODUCT.md)

- Keyboard-only navigation must work for every interactive element — confirmed, not aspirational.
  The global `:focus-visible` treatment (§2, `--focus-ring`) is never suppressed anywhere in the
  tree; this file's existence should make that a load-bearing regression check for v10+, not a
  thing to rediscover.
- Every custom "widget" built so far (progressbar meter, filter tab group, expandable row) uses
  real ARIA (`role="progressbar"` + `aria-valuenow/min/max`, `role="group"` + `aria-pressed`,
  `aria-expanded`) rather than a bare styled `<div>` — continue this, do not ship a v10 control
  that looks interactive but lacks the matching ARIA role/state.
- All decorative-only motion (noise floor, dial ticks, the v40 ambient field) is
  `aria-hidden="true"`.
- **Secondary pages (v43):** the masthead's `nav[aria-label=Pages]`, then `main#main` holding the
  page's one `h1` and `h2` sections, each `section` labelled by its heading. `/settings` adds
  `nav[aria-label="Settings sections"]` (`aria-current="location"` on the section being read).
- **`/stats` (v44):** `main#main` → one `h1`, `h2` per plate, `h3` per block, each labelled by its
  heading. The window switch is `role="group"` + `aria-pressed`. The crosshair is pointer-only, so
  the recorder's `role="img"` label and its "show as a table" view are the keyboard and
  screen-reader path to the same numbers.
- **Landmarks and outline on `/` (v42, F29):** `header` (banner) → `nav[aria-label=Account]` →
  `main#main` (the id v45's skip link targets; no `tabindex` on it, since a `tabindex="-1"` container takes focus on any click inside and resets Tab order). One `h1` (the wordmark; its
  name is "spotdl-web"), then `h2`s for Incoming submissions (visually hidden), Active signal and
  Queue, each section labelled by its heading. A countdown is never inside a live region.
- **Keyboard (v45):** every action is reachable without the mouse (§6 "Keyboard"). The skip link
  focuses `main#main` with a temporary `tabindex` that goes on blur. A route change moves focus to
  the new page's `h1`; SvelteKit's own route announcer (`#svelte-announcer`) reads its title. Rows announce their name
  (what the row shows) and `aria-expanded`. Any new interactive element must be keyboard-reachable,
  and gets a row in `bindings.ts` if it gets a key.

## 8. Known, accepted gaps (do not silently "fix" without re-reading this section first)

1. **Matte charcoal chassis material** — asserted in the OWN-WORLD direction contract, attempted
   over two correction rounds, still not confirmed clearly perceptible against the near-black
   background. See §6 `.panel`. Open for future visual polish, not resolved.
   **Closed 2026-10-15 (v42):** resolved as a raised faceplate; see §6 `.panel`.
2. **Waterfall as progress-lane list, not a literal spectrogram** — this one is _not_ a gap, it is
   a deliberate, cited Operate-mode simplification (legibility of real song titles over decorative
   visualization). Recorded here explicitly so it is never "corrected" into a literal spectrogram
   under the mistaken belief that the simpler version was an oversight.

## 9. Sidecar

Machine-readable token mirror lives at `frontend/src/design-tokens.json` — kept in exact sync with
`app.css`'s `:root` block. If a token's value changes in `app.css`, update the sidecar in the same
commit; if a token is added/removed, do the same here in DESIGN.md §2/§4/§5.
