---
name: spotdl-web
description: An instrument panel, not a dashboard. A self-hosted spotdl queue that reads as a ham-radio waterfall and spectrum scope.
colors:
  bg-0: '#0a0c0e'
  bg-1: '#191e23'
  bg-2: '#1c2227'
  bg-3: '#262e34'
  line: '#2b3339'
  line-bright: '#3a444c'
  line-control: '#6a757e'
  text-primary: '#e8ecee'
  text-muted: '#8b969d'
  text-dim: '#808b94'
  signal: '#ffb02e'
  signal-dim: '#7a5a1e'
  signal-glow: 'rgba(255, 176, 46, 0.35)'
  settled: '#5ad1a8'
  settled-dim: '#2c5347'
  waiting: '#7fa8d9'
  waiting-dim: '#35485f'
  fail: '#e5595c'
  fail-edge: '#b05154'
  backdrop: 'rgba(5, 6, 7, 0.72)'
  focus-ring: '#ffd479'
typography:
  body:
    fontFamily: "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: '0.9375rem'
    fontWeight: 400
    lineHeight: 1.5
  title:
    fontFamily: "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: '1.25rem'
    fontWeight: 600
    lineHeight: 1.25
  wordmark:
    fontFamily: "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
    fontSize: '1.0625rem'
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: '0.14em'
  detail:
    fontFamily: "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: '0.8125rem'
    fontWeight: 400
  control:
    fontFamily: "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: '0.8125rem'
    fontWeight: 500
    lineHeight: 1.25
  reading:
    fontFamily: "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
    fontSize: '0.75rem'
    fontWeight: 400
    letterSpacing: '0.01em'
    fontFeature: 'tabular-nums'
  label:
    fontFamily: "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
    fontSize: '0.6875rem'
    fontWeight: 500
    letterSpacing: '0.12em'
rounded:
  hairline: '1px'
  focus: '2px'
  segment: '3px'
  control: '4px'
  panel: '6px'
  dot: '50%'
spacing:
  space-1: '0.25rem'
  space-2: '0.5rem'
  space-3: '0.75rem'
  space-4: '1rem'
  space-5: '1.5rem'
  space-6: '2rem'
  space-8: '4rem'
components:
  button:
    backgroundColor: '{colors.bg-2}'
    textColor: '{colors.text-primary}'
    typography: '{typography.control}'
    rounded: '{rounded.control}'
    padding: '0.5rem 1rem'
  button-hover:
    backgroundColor: '{colors.bg-3}'
  button-active:
    backgroundColor: '{colors.bg-3}'
  button-disabled:
    textColor: '{colors.text-dim}'
  button-danger:
    backgroundColor: 'transparent'
    textColor: '{colors.fail}'
  button-small:
    padding: '0.25rem 0.75rem'
  choice:
    backgroundColor: '{colors.bg-2}'
    textColor: '{colors.text-muted}'
    typography: '{typography.control}'
    padding: '0.5rem 0.75rem'
  choice-pressed:
    backgroundColor: '{colors.bg-3}'
    textColor: '{colors.text-primary}'
  choice-value:
    typography: '{typography.reading}'
  dense-control:
    height: '1.875rem'
  well:
    backgroundColor: '{colors.bg-0}'
    rounded: '{rounded.control}'
  panel:
    backgroundColor: '{colors.bg-1}'
    rounded: '{rounded.panel}'
  label:
    textColor: '{colors.text-dim}'
    typography: '{typography.label}'
  kbd:
    backgroundColor: '{colors.bg-0}'
    textColor: '{colors.text-primary}'
    typography: '{typography.reading}'
    rounded: '{rounded.control}'
    padding: '0 0.25rem'
---

# DESIGN.md — spotdl-web frontend

Scope: `frontend/src/` (SvelteKit app). This is the project's first UI (v09); every rule below is
read off the built code, not the plan that preceded it. Where a plan and the shipped result differ,
this file records what shipped. Last regenerated from the shipped UI in v47 (2026-10-19, impeccable
`document`), refreshed in place in this layout (owner's choice) rather than converted to
impeccable's eight-section format.

The YAML frontmatter above is normative: it carries the token values, and the prose never restates
a different one. `design-tokens.json` (§9) mirrors every `:root` custom property in `app.css`,
including the few the frontmatter leaves out because nothing consumes them.

Status: living document. Update in the same PR as any change to a token, a state-colour mapping,
or a named rule. Per-version notes (`> **vNN (date):** …`) are kept where a rule changed meaning,
so the reason for the current rule stays readable. An inline attribution to a pre-v47 decision
carries the date that decision was recorded, e.g. (v42, 2026-10-15). _(2026-10-20, v48: v47's
regeneration folded the dated v41–v46 notes into this prose and dropped most dates; they are
restored inline from the pre-v47 file, owner's answer on the v48 PR.)_

## 1. World and thesis

**THESIS**: an instrument panel, not a dashboard. The queue reads as a live spectrum scope — ham
radio waterfall / spectrum scope, not cards-and-sidebar SaaS chrome.

**Operate mode governs every tradeoff here**: task and legibility always outrank expression. Two
concrete places this overrode the more "authentic" version of the metaphor:

- The waterfall's signature device is a labeled per-track progress-lane list, not a literal
  rendered frequency/time spectrogram. **Deliberate simplification, not a gap** — real song/artist
  titles must stay legible text, not compete with a decorative visualization (§8.2).
- The idle state is a slow, low-amplitude animated noise floor (4.2s cycle, opacity 0.45→0.7),
  not a dead flatline and not a fast/attention-grabbing animation — calibrated for the confirmed
  usage scene of "left open in a background tab for long stretches" (`Waterfall.svelte`). Fast
  idle motion was tried and rejected in review for being in tension with that scene.

This project has no logo, no brand name beyond the repo, and no existing visual identity
(confirmed in PRODUCT.md) — the instrument-panel world _is_ the brand, invented for this build,
not applied on top of one.

**Direction since v39: refinement, not redesign.** The v39 audit recommended keeping the world and
fixing its execution against its own rules; the owner approved that on 2026-10-12 (PR #56; v39
report §8, master plan Amendments). v40–v47 refined inside the world: the ambient field (v40), the
track and job detail (v41), `/` and the type scale and panel material (v42), the secondary routes
and confirmations (v43), `/stats` (v44), keyboard (v45), Hungarian/English (v46) and the polish
pass (v47).

## 2. Palette

All colours are CSS custom properties in `:root` (`app.css`); the frontmatter holds their values.
Dark-only (`color-scheme: dark`); no light theme exists or is planned.

### Chassis / ground

| Token            | Use                                                                                                                                               |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--bg-0`         | Page background, recessed wells (inputs, the sort select, meters, keycaps)                                                                        |
| `--bg-1`         | `.panel` surface: the raised faceplate (v42; was `#14181c`, see §6 `.panel`)                                                                      |
| `--bg-2`         | A control's fill (buttons, chips, segments). On `--bg-1` it is only 1.045:1, so a job or track row's hover is a title underline, not a fill (v42) |
| `--bg-3`         | Hover and pressed surface of every neutral control, one step brighter than `--bg-2`                                                               |
| `--line`         | The quiet divider between rows and around panels (1.31:1 on `--bg-1`); a disabled control's edge (v47)                                            |
| `--line-bright`  | Emphasized hairline: the idle Waterfall top edge, the idle bar segment, stale lanes; not a control edge                                           |
| `--line-control` | The edge of every neutral control (input, select, button, chip, segment): ≥3:1 on `--bg-0/1/2` (4.16 / 3.56 / 3.41)                               |
| `--backdrop`     | The dimmed (never blurred) page behind a modal: the confirmation and the help overlay (v47; one token for both)                                   |
| `::placeholder`  | `--text-dim` (v47): 5.63:1 on `--bg-0`. The browser's own placeholder grey was 4.25:1, the one text under AA the audit still found                |

> **v42 (2026-10-15, F09/A2, owner's choice):** a control's edge is `--line-control`, which reaches
> WCAG 1.4.11's 3:1. The owner chose a separate token over raising `--line` itself, so the job list
> doesn't turn into a 3:1 grid.

### Text

| Token            | Use                                                                             |
| ---------------- | ------------------------------------------------------------------------------- |
| `--text-primary` | Body text, primary content, a control's label at full strength                  |
| `--text-muted`   | Secondary content (artist lines), a control's label at rest, the idle condition |
| `--text-dim`     | Labels, meta, deliberately quiet text, a disabled control's label               |

`--text-dim` reaches 4.5:1 on every surface it sits on (`--bg-0` 5.63, `--bg-1` 4.83, `--bg-2`
4.62). That puts it close to `--text-muted` (6.48 / 5.55 / 5.31), so the two read apart by role
(size, case and tracking: `.label`), not by luminance. `--text-muted` stays put because
`AmbientField.svelte`'s slate tone is calibrated against it (§6). (v42, 2026-10-15, F09/A2:
`--text-dim` was `#566068` and failed WCAG 1.4.3 everywhere, 2.15–3.05:1.)

`--signal-dim` is never text: it was 3.09:1 as link hover on four routes, so links hover to
`--text-primary` (v42, 2026-10-15, F09/A2).

A destructive control's outline at rest (clear log, a job's cancel, cancel track, `.btn.danger`) is
`--fail-edge` (3.87 / 3.32 / 3.17 on `--bg-0/1/2`), never `--fail-dim` (1.5:1; v42, 2026-10-15,
F09/A2).

State toggles were removed in v43 (2026-10-16, F30): a proxy's state is a word ("switched on" in
`--settled`, "switched off" in `--text-muted`) beside a plain `.btn` naming the action, and a
switched-off row is no longer faded with `opacity: 0.6`; its address drops to `--text-muted`. The
worker's state is a sentence beside "pause/resume downloads".

### Signal-condition colors — the semantic core of the system

Five conditions, shared verbatim between the Waterfall, the job and track rows, `/stats` and the
secondary routes via `.cond-live` / `.cond-settled` / `.cond-waiting` / `.cond-fail` /
`.cond-idle`, so a state's colour means the same thing everywhere it appears. Do not introduce a
second colour vocabulary for a new component — map any new state onto one of these five.

| Condition                     | Token(s)                                                            | Meaning                                                                                                                                                                                                                            | Exclusivity rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ----------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Live** (Committed strategy) | `--signal` / `--signal-dim` / `--signal-glow`                       | Something is receiving **right now**, and this page can see it (its link is live)                                                                                                                                                  | **Amber is reserved exclusively for live state. It must never appear as permanent chrome, decoration, or a "brand" accent.** This was a deliberate fix made during finish review: round 1 shipped a constant amber top border on the Waterfall panel; review flagged it as spending the one committed live-signal colour on chrome and diluting its meaning, and it was changed to neutral (`--line-bright`) by default, turning `--signal-dim` only while lanes are live (`.waterfall.live`). **Any future component adding amber must justify it against "is this genuinely live right now" — if not, use a different token.** |
| **Settled**                   | `--settled` / `--settled-dim`                                       | Completed, no longer needs attention (`completed`, `skipped_duplicate`)                                                                                                                                                            | Cool mint, never used for anything mid-flight                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Waiting**                   | `--waiting` / `--waiting-dim`                                       | Patient, scheduled, not alarming (`waiting`, the ladder, the breaker's hold, `Countdown`'s text)                                                                                                                                   | Soft blue reads as "scan window" and must never read as an error — it is the retry ladder, normal and expected per the product thesis                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **Fail** (terminal only)      | `--fail` / `--fail-edge`                                            | **Terminal failure only** — `lookup_failed` ("not found"), a failed job, a partial job with a real gap, a paused worker (it needs a human), a failed row action's notice, error lines; `--fail-edge` outlines destructive controls | Held back deliberately — never used for `waiting`/backoff, which is expected and recoverable                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **Idle**                      | `--text-muted` (via `.cond-idle`); `--line-bright` as a bar segment | Not receiving (`pending`, `queued`, `cancelled`, and any active job whose tracks aren't downloading)                                                                                                                               | No dedicated hue — idle borrows the muted text colour rather than inventing a sixth signal colour                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |

`--signal-ink` (`#2a1c05`, a dark ink for text on an amber fill) and `--fail-dim` (`#5c2f30`) are
defined in `:root` but consumed nowhere as of v47: nothing sets text on amber, and the controls that
once edged in `--fail-dim` moved to `--fail-edge` (v42) or became words (v43). They stay in the
sidecar; a new use must still fit the rules above.

> **v41 (2026-10-14, F03/F14):** inside the expanded track, red marks only a terminal verdict. A
> failed attempt the ladder will retry reads in the waiting blue, `last_error` is not painted red,
> and a note on an attempt that didn't fail (a tag-repair warning) is neutral text behind an
> outlined `NOTE` tag, neither fail red nor the waiting blue. Still five conditions, no sixth hue.

> **v47 (2026-10-19):** "live" on a row now means _receiving_, as it already did on the Waterfall.
> Until v47 a job's badge and bar segment were amber for any `active` job (mostly tracks queued
> behind the worker's one download, or held by the breaker) and stayed amber while `/`'s link was
> down. Now a job is amber only while one of its own tracks is `downloading` (or it is `expanding`)
> **and** the link is live; pending and queued tracks are the idle segment, as their own rows read;
> nothing on a row is amber while the link is down (`JobRow.svelte`'s `receiving`). `Countdown` has
> no amber "due" state any more: every caller had turned it off (a due wait is still waiting), so a
> new caller can't get amber by default. This completes v42's note that "aligning the rows is v47's".

### Amber on chrome: the v40 decision (v39 F10, amendment A5)

**Decided 2026-10-13 by the owner (v40): the rule above stands unamended.** Amber marks something
receiving _right now_, and nothing else. The v39 audit (F10) found it leaking onto about ten
permanent chrome sites. Each got a verdict in v40; v40 applied the first row, v42 (`/`, 2026-10-15)
and v43 (the other routes, 2026-10-16) applied the rest without re-deciding them. All are applied.

| Site (F10)                                     | Verdict (shipped)                                                                                                                                      |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Body glow (`app.css` `body` background)        | **No amber at rest.** Replaced by `AmbientField.svelte`: slate at rest, crossfading to amber only while `/` shows ≥1 receiving track (§6) (v40)        |
| Global `a` colour                              | `--text-primary` with an underline: the affordance is the underline, not the hue (v42). In-text links use the global `a`; `.inline-link` is gone (v43) |
| The `>` prompt                                 | `--text-muted` at rest; `--signal` only while a submission is in flight, which is a real transmission (v42)                                            |
| Submit / connect / save / add hover-focus glow | No amber and no zero-offset halo. Hover is §6's neutral hover; focus is the global `--focus-ring` alone (v42 / v43)                                    |
| Pressed option chips                           | A selection, not a signal: `--bg-3`, full text, a 2px `--text-muted` floor line, on every route (v42 `/`, v43 the rest)                                |
| Input focus borders                            | No amber border; the ring marks focus, the edge stays `--line-control` (v42 / v43)                                                                     |
| Links at rest and on hover                     | Every link's hover/focus is `--text-primary`; `--signal-dim` as text is 3.09:1, so this is a contrast fix too (F09) (v42 / v43)                        |
| Idle `/login` needle                           | `--text-muted`, no glow, at rest; amber with its glow only while connecting, the one moment the dial is tuning (v43)                                   |
| Idle `/library` progress bar                   | `--signal-dim` only while a sweep runs (the "happening, but not this session's track" carve-out, §6); a finished run's bar is `--settled-dim` (v43)    |

The same test covers sites F10 didn't list (`.load-more`, the queue controls, JobRow's priority
input): a hover, focus, pressed or selected state is never "receiving", so it never takes amber.
Text selection (`::selection` at `--signal-dim`) is transient and user-initiated, not chrome, and
keeps its colour.

Where `--signal` appears as shipped: on `/`, a receiving Waterfall lane, the Waterfall's live edge
(`--signal-dim`), an expanding submission's dot, the prompt while sending, a receiving job's badge
and its downloading segment, a downloading track's state, the ambient field while live, and
`::selection`; on the other routes, the login needle while connecting and the `/library` bar while a
sweep runs (`--signal-dim`), plus `::selection`. Every one of these drops amber while `/`'s link is
down (v42 for the Waterfall, incoming dot and ambient field; v47 for the rows).

### Focus

`--focus-ring` is the single keyboard focus treatment, `:focus-visible { outline: 3px solid
var(--focus-ring); outline-offset: 2px }`, global, never overridden with `outline: none` anywhere
in the tree. This is a direct consequence of PRODUCT.md's confirmed keyboard-only accessibility
requirement — a hard requirement, not a nice-to-have. The ring is intentionally a near-signal amber
tint so it reads as part of the same instrument-panel world rather than a generic browser default.
Segments (`.choice-group`, the scope switches) draw it inside (`outline-offset: -3px`, v45).

**Rule**: `--focus-ring` is distinct from `--signal` on purpose (lighter/desaturated) so a focused
element is never visually confusable with a genuinely live download.

## 3. Type system

Two families, strictly divided by _kind of content_, not by visual weight. Both are self-hosted
(v47): `@fontsource/ibm-plex-sans` and `@fontsource/ibm-plex-mono` 5.3.0 (OFL, pinned), weights
400/500/600, imported by `routes/+layout.svelte`. Each subset is a `unicode-range` face, so a page
fetches only latin and, for Hungarian, latin-ext. (Until v47 they came from a render-blocking
Google Fonts stylesheet in `app.html`: 444 of 788ms of a cold first paint and a third-party request
on every visit.)

- **IBM Plex Mono** (`--font-mono`) — readings and machine text: numbers, counts, timestamps,
  countdown times, state tokens, addresses (URLs, proxy `host:port`, paths, templates), idents
  (`.label`, the wordmark), keycaps, the console's SUBMIT beside the `>` prompt, and value choices
  (`.choice-group.values`: a window like 24h, a format like mp3).
- **IBM Plex Sans** (`--font-sans`) — the document body default, all real content (song titles,
  artist and album names), every sentence (errors, hints, notices, empty and loading states, the
  worker's state), and every control label that is a word: buttons (`.btn`), chips, segments, row
  actions, nav links, the skip link and the settings index, at `--fs-detail` medium.

**Named rule**: this split exists so theming never sacrifices legibility of actual data — a
listener's song/artist/album text is never rendered in the "instrument" typeface. Any new
component must ask "is this a system/meta value or is it content a user is trying to read" before
picking a family; do not default new components to mono just because the world is technical. A
control's label is a word, not a reading, so it is Sans; a chip's count beside it is a reading, so
it stays mono.

> **v42 (2026-10-15, F12, owner-approved narrowing):** the original v09 rule put "UI chrome text
> (buttons, filter chips, the login dial's frequency ticks)" in mono alongside every number and
> label. v42 moved sentences to Sans on `/`'s surfaces and kept control labels mono so they matched
> v41's row actions on the same screen, deferring the tree-wide move to v47.

> **v47 (2026-10-19):** control labels are Sans tree-wide (F12's last step, owner-approved with
> in-world exceptions this session: the console SUBMIT beside the `>` prompt, value choices via
> `.choice-group.values`, keycaps, and counts/readings stay mono). The remaining mono sentences (row
> notices, track-list hints, worker state, units, proxy facts) moved to Sans, and the confirmation's
> subject is mono only when it is an address (a job title is content). Raw English worker and
> backend text (attempt errors, notes, a job's read error, sweep errors) carries `lang="en"` on a
> Hungarian page (WCAG 3.1.2).

### Type scale (v42, F12)

v39 found six ad hoc sizes, nothing above 15px, and a `15px` body that ignored the user's own text
size. v42 replaced them with a small set of named **role** tokens (values in the frontmatter's
`typography` and in `app.css`), fixed rem steps of about 1.08–1.18 (Operate mode: a dense product
surface, not a fluid display ramp):

| Token         | Size               | Role                                                                                        |
| ------------- | ------------------ | ------------------------------------------------------------------------------------------- |
| `--fs-label`  | `0.6875rem` (11px) | Uppercase idents and section labels (`.label`), the login dial's ticks                      |
| `--fs-meta`   | `0.75rem` (12px)   | Mono meta and counts, a job's badge and a track's state word, keycaps, value choices, hints |
| `--fs-detail` | `0.8125rem` (13px) | Control labels, secondary lines: artists, reasons, errors, countdowns, nav                  |
| `--fs-body`   | `0.9375rem` (15px) | Body and content; `body` uses it, so text scales with the browser                           |
| `--fs-lead`   | `1.0625rem` (17px) | The wordmark, dialog titles, emphasised single lines                                        |
| `--fs-title`  | `1.25rem` (20px)   | A page's `h1` (`.page-title`) and a state's own heading (empty, error)                      |

Weights: `--fw-regular` 400, `--fw-medium` 500, `--fw-strong` 600. Every `font-size` in the tree is
one of these tokens; the only other values are two `font-size: inherit` resets (`/settings`,
`/stats`). v43 (2026-10-16) migrated the secondary routes and v41's rows (the login dial's 9px ticks
became `--fs-label`, TrackRow's 14px artist line `--fs-detail`); v47 migrated the rest, including
the remaining literal weights, and set a job's badge at `--fs-meta` like the track state word. Don't
add a size between the steps.

`.mono` utility class adds `font-variant-numeric: tabular-nums` and `letter-spacing: 0.01em` —
**any new numeric/timestamp display should use `.mono`, not a bare font-family override**, to get
tabular alignment for free.

`.label` utility: mono, `--fs-label`, weight 500, `letter-spacing: 0.12em`, uppercase,
`--text-dim`. This is the system's one "meta/eyebrow" text pattern — used for panel headers,
section labels, idents. Reuse it rather than inventing a second all-caps convention.

## 4. Spacing scale

4px base, `--space-1` through `--space-8` (values in the frontmatter and `app.css`): 4, 8, 12, 16,
24, 32, 48, 64px at the default 16px. `--space-8` is used once (the "Can't reach the server"
screen's top padding, `routes/+layout.svelte`); `--space-7` is defined and unused, reserved.

**Rule**: every gap/padding value in every component reads from this scale (the row-grid tokens
below derive from it). Don't introduce a bespoke pixel gap.

### Row grid (v41)

`app.css` also defines the columns the job list shares, so rows line up instead of each
component guessing: `--row-pad-x`, `--row-gap`, `--col-lead` (a job's chevron, and the nesting
rail under an open job), `--col-state` (a job's badge and a track's state), `--col-progress`,
`--row-nest` (one lead column plus a gap: the indent of a nested track list) and `--cell-inset` (a
badge's text offset, so a track's state text sits under the badge text). A nested track's state is
under its job's badge and its title under the job's title; the expanded detail hangs off the same
title column. Any new row in the job list uses these, not local widths.

### Control height (v47)

`--control-h` (1.875rem) is the one height of a dense control row: `/`'s find and refine rows
(segments, the search well, chips, the sort select) share it, where they ranged 26–41px before. A
coarse pointer raises every one to 44px (§6 Page breakpoints). Elsewhere a `.btn` and a
`.choice-group` option share `--space-2` vertical padding at line-height 1.25, so they match each
other's height (v47; a choice was 28px against a button's 36px).

## 5. Motion

| Token           | Use                                                                                            |
| --------------- | ---------------------------------------------------------------------------------------------- |
| `--ease-signal` | The one easing curve for every animated transition (progress fill, sweep needle, button hover) |
| `--dur-fast`    | Hover/focus state changes                                                                      |
| `--dur-med`     | Progress-bar fill transitions, the confirmation's entry                                        |
| `--dur-slow`    | The ambient field's rest ↔ live tone crossfade (`AmbientField.svelte`, v40)                    |

Values: `cubic-bezier(0.16, 1, 0.3, 1)`, 120ms, 320ms, 900ms (sidecar; motion has no frontmatter key).

**Named rule — reduced motion is load-bearing, not decorative**: `@media (prefers-reduced-motion:
reduce)` zeroes all three duration tokens globally in `app.css`, and every bespoke `@keyframes`
animation in the tree (login needle sweep, Waterfall noise floor, the lane sheen, the link tell's
pulse) has its own matching `prefers-reduced-motion` override alongside the global one. **Any new
keyframe animation must ship its own reduced-motion override in the same component** — the global
duration-zeroing does not reach hand-authored `animation:` shorthand time literals (e.g.
`animation: noise 4.2s ease-in-out infinite` is a literal, not a var, and needs its own
`{ animation: none }` fallback).

**Compositor-only where it can be** (v47, F33): continuous motion moves by `transform`, never by a
property that repaints. The lane shimmer is a `::after` sheen translated across the fill (it
animated `background-position`, which repainted the lane every frame); the login needle moves by
transform. Countdowns tick on one shared 1s clock (`stores/clock.ts`), not one interval each.

**Script-driven motion follows the same rule** (v40, `AmbientField.svelte`, the tree's first). A
frame loop has no CSS duration to zero, so it checks `prefers-reduced-motion` itself and, when
reduced, never starts: no pointer listener, no `requestAnimationFrame`, a static layer. Any later
script-driven animation needs the same check. It must also stop when settled and while
`document.hidden`; no frame loop may spin permanently.

## 6. Component patterns

### Shared controls (`app.css`): one neutral idiom

`.btn` is the one button: `--bg-2`, a `--line-control` edge, `--rounded.control`, Sans
`--fs-detail` medium, lowercase verb labels ("save", "add proxy", "start sweep"). `.btn.small` is
the row-level size. `.btn.danger` is outlined in `--fail-edge` with `--fail` text and stays
transparent on hover, since `--fail` on `--bg-3` is only 3.88:1. Every neutral control in the tree
(`.btn`, row actions, incoming actions, `/`'s disconnect, chips' and segments' fills) follows one
interaction idiom:

- **Hover:** `--bg-3` fill with a `--text-muted` edge, **only under `@media (hover: hover)`** (on
  touch, a tapped control kept its hover). Chips and segments are the documented exception: hover
  lifts only the text, so a hovered option never passes for the selected one (Filter tabs below).
- **Pressed (`:active`):** the same `--bg-3` fill, so a tap answers too.
- **Focus:** the global ring alone. Never amber, no halo.
- **Disabled:** `--text-dim` text and a `--line` edge, **never opacity** (an opacity-faded control
  drops under 4.5:1, v42's remainder; the `--line` edge is v47's, so a disabled control no longer
  passes for a live one).
- **Destructive:** outlined `--fail-edge` at rest, full `--fail` edge (and text, on row actions) on
  hover, focus and press.

> **v47 (2026-10-19):** one idiom replaced several: row actions had a waiting-blue edge, incoming
> actions a fill only, and `/`'s **disconnect** hovered to the fail red (§2's Fail row used to list
> "the logout button's hover/focus state (a destructive-adjacent action)"). Disconnect is now a
> neutral control like `/account`'s: signing out is undoable, not a terminal state.

`.well` is a recess cut into a plate: `--bg-0`, `--line-control` edge, `inset 0 1px 3px` shadow.
`kbd` (v45) is recessed like a well with a heavier floor (2px bottom edge) so it reads as a key; mono
`--fs-meta`, never amber, since a key is not a live condition.

### `.panel` — the raised faceplate

The one shared surface convention: `--bg-1`, `1px solid var(--line)`, `border-radius: 6px`, and a
machined top bevel (`inset 0 1px 0 rgba(255,255,255,.055)`), a 1px dark lower edge
(`0 1px 0 rgba(0,0,0,.6)`) and a short offset drop shadow (`0 6px 12px -7px rgba(0,0,0,.8)`) (v42,
2026-10-15; see the Decided note below). Every panel-like surface in the tree (login form, submit
bar, Waterfall, the queue, every secondary route's sections, the confirmation and help dialogs) uses
this class rather than a locally redeclared surface style. The shadow is the `--shadow-plate` token
(v47), which the `g` chord readout and `/stats`' crosshair readout share (the readout had its own
wider, softer shadow); a `.well`'s inset is `--shadow-well`, and the live meter's moving sheen is
`--sheen`.

History, kept because it is why the material is what it is: the intended "matte charcoal chassis"
— a perceptible plate, distinct from a flat SaaS card — was never made perceptible across two
correction rounds as a _recessed_ housing. Round 1's 1px inset hairline was in the DOM but invisible
at normal viewing distance; round 2's compound inset shadow (`inset 0 2px 5px`, `inset 0 -1px 0`,
`0 8px 20px -10px`) improved it without confirming it read as "recessed housing" rather than
"bordered card". That was recorded as an open gap (§8.1), with the instruction not to spend more
`box-shadow` layers chasing it without device evidence.

> **Decided 2026-10-15 (v42, F36; owner's choice: "make it perceptible"):** the chassis is kept and
> inverted from _recessed_ to _raised_. Shadow layers were never going to carry it: the surface step
> does. `--bg-1` moved from `#14181c` (1.10:1 against the page) to `#191e23` (1.17:1), with the
> bevel and short drop shadow above (under the detector's 16px wide-shadow line). What is _cut into_
> a plate keeps the recessed language: text inputs and the sort select are `.well`s; the Waterfall
> meters are wells too but keep the quiet `--line` edge, since a meter is read by its fill, not its
> border. Plates are raised and wells recessed, and the two read apart at a glance. The ambient field
> still lights only the gutters: plates are opaque. §8.1 is closed by this.

### Hero-marking border (the "is anything live" tell)

`Waterfall.svelte`'s top border is neutral (`--line-bright`) by default and switches to
`--signal-dim` only while lanes are on screen **and** the link is live (`.waterfall.live`). This is
the concrete embodiment of the amber-exclusivity rule in §2 — the panel itself is the primary visual
proof that "live" is reserved, not just a colour-token comment. **Any future panel that wants to
signal "something in me is currently active" should use this same neutral→signal-dim
border-colour swap, not a persistent accent border.**

A third edge state (v42, 2026-10-15, F04): while the breaker holds and nothing of this session's is
receiving, the edge is `--waiting-dim`: a hold is a scheduled, self-clearing condition, the waiting
colour's meaning. A pause keeps the neutral edge: it isn't scheduled (it holds until a human resumes
it, which is why the admin's pill shows it red).

### Waterfall idle status and the link tell (v42, F04/F05; v47)

The full idle panel stays (owner's choice over a one-line strip). Its status line says _why_ nothing
is receiving, in priority order: **link lost — reconnecting** (this page's SSE stream is down, so
nothing else on the panel can be trusted), **tuning in…** (not yet connected), **receiver paused**,
**holding · resumes in …** (the breaker; a countdown, plus "a deliberate pause after repeated rate
limits; waiting tracks keep their place"), **no signal here — worker busy elsewhere**, and **no
signal — nothing downloading**. It never says "idle" while the breaker holds. The noise floor only
moves while the receiver is listening (or tuning in, before the stream first opens): held, paused or
with the link lost it lies flat. A countdown never sits inside a live region: the panel has one
`sr-only` status region holding a fixed sentence per state ("Downloads holding until 23:20",
"Receiver paused", then once "Downloads resumed"; a lost link is announced by the masthead tell
instead), and the ticking text is `aria-hidden` (F07's lesson, same in the pill).

A lane's meter is a `role="progressbar"`. A lane loaded from REST (a reload, a reconnect) has no
reading until the next progress event, so it shows **—** with no `aria-valuenow` and an
"unknown" `aria-valuetext` (v47; it said "0%" for a track that may be 80% in). The title column
takes `2fr` against the meter's `minmax(8rem, 1fr)` (v47; a third of the lane cut titles at ~280px
of 950). Under `forced-colors` the meter keeps its own colours (`forced-color-adjust: none`), as
`/stats`' charts do.

The masthead carries the same link as a small tell: **linked** (a filled muted dot), **linking…**
(on load and on a mine/all-users switch, until the first attempt resolves; a first attempt that
fails reads link lost, since there is no link) or **link lost — reconnecting**; both not-linked
states take a hollow waiting-blue ring that pulses slowly (off under reduced motion). A phone shows
a short form of the link-lost tell (v47). Lanes on screen while the link isn't open came from a REST
snapshot and don't update, so they dim, lose the amber fill and sheen, the panel edge stays neutral,
the ambient field stays slate and an expanding submission's dot turns muted and still; the head
reads "link lost — progress may be stale" (or "linking… — …"). The tell differs in shape as well as
hue, and it is never amber: a link is not a download. It is a `role="status"` region that changes
only with the state.

The link drops to "link lost" on more than a closed stream (v47): on the browser's `offline` event,
and on two 5s worker polls in a row that never reached the server (a stream can stay open but
silent). It reconnects at once on `online` or on a return to the tab, rather than waiting out a
backoff of up to 30s.

**v20's "worker busy elsewhere" indicator is the sharpest test of the amber rule.** `worker-dl`'s
global `--concurrency=1` means the Waterfall is idle-for-this-session far more often than not —
someone else's download, not a stall. The temptation is to reuse `--signal` for "something, out
there, is alive," but that would spend the one committed live-signal colour on a condition that
isn't live _for this viewer_; the border stays neutral and only the status word swaps to "no signal
here — worker busy elsewhere", in `--text-dim`, never amber. `--signal` is reserved for _this
session's own_ active track, full stop, not "the global worker."

### Ambient field (`AmbientField.svelte`, v40)

The page's light: one `position: fixed`, full-viewport, `pointer-events: none`, `z-index: -1`
layer, mounted once in `routes/+layout.svelte` so every route has it. It sits behind the panels
(their `--bg-1` fill is opaque), so it lights only the page gutters and the text set directly on
the page (headers, hints, the `/login` ident). Its home is approximately the old body ellipse's
composition: a 72×44rem element (1152×704px at the default 16px; it grows with text scaling)
centred at 50% / −10% of the viewport, so at rest the page reads as it always did, minus the amber.

**Behavior.** With a hovering fine pointer, the glow follows the cursor: an exponential approach
(τ = 180ms) toward it. While the pointer moves, `pointermove` only stores the latest position, and
one `requestAnimationFrame` loop eases toward it, moving the element by `transform: translate3d()`
alone; the first frame after a wake counts as one 60Hz frame. Once ~50ms (three 60Hz frames, at
any refresh rate) pass without a move, the loop hands the rest of the approach to one compositor
animation (two keyframes and a `linear()`
easing tracing the same curve, landing exactly on target after 1.6s), back-dated by that frame's
step so the hand-off frame shows what the loop would have drawn. A move or a leave during the glide
ends it on the next frame, at the position it had one frame earlier (read from the animation's own
clock, never computed style), and the loop steps from there as v40's would have; a resize or a
hidden tab ends it at once. A glide within 0.5px of its target counts as at rest, as v40's loop
had snapped by then. Screencasts match v40's path within their 0.5px resolution, and between
`linear()` samples a long glide can drift up to ~0.09% of its distance. A
browser without `linear()` (Safari before 17.2) keeps the loop to the 0.5px snap. When the pointer
leaves the window it drifts back home; a native drag (which cancels the pointer and fires the same
window-leave event) does not count as leaving. A touch-type `pointermove` is ignored, so it never
chases a tap. Nothing reads layout: the viewport size comes from a `ResizeObserver`. While it can
move, `.glow` carries `will-change: transform`, so its gradient rasterizes once. While moving, each
frame costs one 1-element style update and a commit, with no layout and no repaint: the same
style-update count as v40, and 2–14% more main-thread time per frame (0.69 vs 0.67ms at one move
per frame, 0.50 vs 0.44ms at one per 50ms), measured on `/login`. After the pointer stops, the
rest of the approach costs 4 loop frames and about 9 style updates instead of v40's ~60 frames
(about 5ms of tasks instead of 21–25). A hidden tab stops the loop and pins the glow where it is. _(2026-10-20,
v48: the after-stop glide moved to WAAPI, owner's answer to v40's open performance question. A
first version ran every retarget as a Web Animation too; at real mouse rates that cost 1.5× the
loop while moving, so moving stayed on the loop.)_

**Static cases (owner's choice, 2026-10-13): no hover or a coarse pointer, and
`prefers-reduced-motion: reduce`.** Phones keep the home position with no pointer listener and no
frame loop, which saves battery and leaves the Waterfall's noise floor as the only idle motion (§1).
In a hidden tab, the loop is cancelled.

**Tone, which is the amber rule (§2).** The two gradients are stacked and crossfaded on `opacity`
(`--dur-slow`, zeroed under reduced motion): slate (`--text-muted`) at rest, and amber (`--signal`)
only while live. The layout defines live as `page.route.id === '/' && activeTracks.length > 0` (and
the link live), the same condition as the Waterfall's `.live` border. **Only `/` holds the live
stream.** Navigating away closes it but leaves `queue.activeTracks` at its last value, so on any
other route that store is stale and must never light the page. Any future consumer of `activeTracks`
outside `/` has the same problem. On re-entering `/`, the stale value still holds until the new
stream's `onopen` resync replaces it, so the field (like the Waterfall's border) can begin warming
for a moment before settling to the truth. In the admin's all-users view, other users' downloads
count as "receiving" here (§8.3).

**Contrast budget.** The peaks aren't a matter of taste. The old ellipse's centre sat off-screen,
so the brightest pixel anyone saw was its top edge, and that edge dims as the viewport grows
taller: amber at 5% × (1 − 0.1·height / 300px). The new peak sits under the cursor, over any text,
so it is held to exactly that visible maximum. `peaks()` sets `--live-peak` from the viewport
height on resize (3.5% at 900px, 2.6% at 1440px), and `--rest-peak` at 1.15× that. Slate's
luminance-equal factor is ~1.25, but 8-bit rounding can then put slate one code value above amber
at some heights, so 1.15 keeps a margin. Measured against the old rule rendered in the same browser
at eight viewports, from 1280×640 to 2560×1440 plus a 390×844 phone, no token is worse at either
tone. Beyond that range (viewports over ~2380px tall) the 8-bit model allows slate to be one blue
code value brighter than amber, a contrast difference in the third decimal place. Raising either
peak breaks that. The gradient peaks only about 4–9 8-bit code values above the page colour in its
strongest channel (about +10 below ~650px tall), so faint banding shows on close inspection. The
pre-v40 glow had the same stepping. It is accepted, because the only cure that stays inside the
budget (dithering) costs more than it buys.

### Worker status: the admin pill and `/settings`' worker control (`WorkerStatusPill.svelte`, `WorkerStatus.svelte`, `stores/worker.ts`)

**The pill** (`WorkerStatusPill.svelte`) is operator detail, so `/` renders it for the admin only
(absent from a non-admin's DOM; they get the Waterfall's plain status line) (v42, 2026-10-15,
F06/F07, v39 outcome 3). It is a `role="status"` pill in the masthead, beside the nav — **not**
between the submit form and the queue, where the old full panel competed with the Waterfall for
space above the fold (v25's reason for splitting it out). Three states: **worker ready**
(`cond-idle`), **breaker holding · clears in …** (waiting blue: it is expected and self-heals) and
**receiver paused** (`--fail`: it holds until a human resumes it). The default is `cond-idle`, not
`--signal`: a "nothing's wrong" pill on every page load is exactly the near-permanent chrome §2
keeps amber out of. The live region is one `sr-only` sentence per state, never the per-second
countdown. The 5s worker poll lives on the page, which every user needs (the Waterfall and
TrackRow's breaker-aware countdown read the store); there is still no SSE event for worker/breaker
state.

> **Superseded history (v25 → v42, kept for the record; dated 2026-10-19 in v47):** v25's pill
> rendered for every user, with `cond-fail` (red) "breaker tripped" + a live `Countdown`,
> `cond-fail` "receiver paused", or `cond-idle` "receiving". Red was reused for paused/tripped
> because the old toggle's `aria-pressed` state and breaker banner already used it. v42 made the
> pill admin-only and moved the breaker to the waiting blue (above); only "paused" is still red.

**Worker control** (`WorkerStatus.svelte`) renders on `/settings` for the admin only (no `isAdmin`
prop; a non-admin gets the admin-only notice instead) (v43, 2026-10-16, F17/F30/A4). The state is a
sentence: **Downloads running** (muted), **Downloads paused** (`--fail`, it needs a human) and,
beside either, **Holding until 23:20 · resumes in …** (waiting blue, the countdown `aria-hidden`;
one `sr-only` status sentence per state). The buttons name their action: pause/resume downloads and,
while holding, **release now** (`.btn.danger`). Pause and release ask first; resume doesn't. When
the breaker holds a running worker, the hold row carries pause too (v47). "Receiver power" and the
`aria-pressed` toggle are gone (v43). Server-side `require_admin` is the real enforcement.

**Identity.** v25 threads a `username` (nullable, from the upstream `GET /user`) through
`SessionInfo` and the job/track `owner_username`/`owner_email` fields. One
`api.displayName(username, email)` helper is the single place that decides username-vs-email,
called from the masthead, the tracks-view group header and `JobRow`'s owner column, so the three
can't show different identities for the same person. Identity strings are `.mono` (a system/meta
value, not song content, per §3).

### State → colour/label mapping (`TrackRow.svelte`)

Two parallel maps over `TrackState` — the label (now `lib/i18n/labels.ts`'s `trackStateLabel`) and
the condition (one of the five `.cond-*` classes) — are the single source of truth for how a track
state renders. **Any new `TrackState` value must get an entry in both in the same change**, never
inferred or left to fall through to a default, or a new state will render with no label/colour.
They cover exactly eight states (v16 removed `TrackState.FAILED` by migration): pending, queued →
idle; downloading → live (only while the link is live, §2 v47); completed, skipped_duplicate →
settled; waiting → waiting; lookup_failed → fail; cancelled → idle.

The words are the state-filter chips' words (v41, 2026-10-14, F21, owner's call): pending, queued,
downloading, completed, waiting, not found, duplicate, cancelled, so a state reads the same on a
chip and on a row and no label truncates in the state column (F13). The in-world voice stays on
idents and moments. In Hungarian (v46, 2026-10-18): sorban áll, indulásra kész, letöltés alatt,
letöltve, várakozik, nem található, már megvan, megszakítva. History: v20 renamed `lookup_failed`'s
copy from "no signal — given up" to "no signal — not found", because the state was never "given up"
(it is terminal and never auto-retried); v41 then dropped the in-world phrases for the chip words.

One deliberate exception, the owner's choice (v42, 2026-10-15): a non-admin's tracks scope has a
single **in progress** chip standing for pending, queued and downloading (v39 outcome 3), while the
rows keep the exact state word. The chip is a grouping of row words, not a fourth word.

### Job status → colour/label mapping (`JobRow.svelte`)

The job-level counterpart, over `statusKey()` (`expanding`, `active`, `waiting`,
`settled:partial`, `settled:complete`, `cancelled`, `failed`), same five classes. Labels come from
`lib/i18n/labels.ts`'s `jobStatusLabel` (Hungarian: hangolás, aktív, várakozik, kész — részben,
kész, megszakítva, sikertelen) and are shared between the filter chips and the row badge, so the two
can't drift: "done — partial" for `settled:partial`, never "failed" or "partial" alone.

- `expanding` and `active` map to `cond-live` **only while receiving** (§2 v47): expanding, or ≥1
  track downloading, with the link live. Otherwise they read `cond-idle`. Expanding is live for the
  same reason as `IncomingJobs`' pulsing dot: a job actively being read is happening right now.
- `settled:partial` maps to `cond-fail` only when the job has a `lookup_failed` track: a genuinely
  terminal state with a real gap, the bucket `lookup_failed` occupies at the track level, never
  `cond-waiting` (§2 reserves that for recoverable backoff). A job partial only because its owner
  cancelled tracks has no gap they didn't choose, so it reads `cond-idle` (v42, 2026-10-15, F28).
- A job whose title is still its link (nothing read yet) shows the link as an address (mono, muted,
  regular weight), not a bold title (v42, 2026-10-15, F28).
- A one-track job shows no separate count line, since the badge and bar already say it (the bar's
  accessible name still carries the count), except where the badge doesn't name its track's own
  bucket (a partial job, one cancelled after its track completed, a stale row): colour alone mustn't
  say it (WCAG 1.4.1) (v42, 2026-10-15, F28). A job with no tracks shows no lone "—" count (v47).
- The badge is `--fs-meta`, the same 12px as a track's state word (v47).

### Segmented job progress bar (`JobRow.svelte`, v20)

A job row's per-state track counts render as a horizontal bar of proportionally-sized flex
segments, coloured with the five condition tokens (`--signal`, `--waiting`, `--settled`, `--fail`,
`--line-bright` for idle) — never a sixth palette. Segment order: downloading (live while the link is
live, else idle), pending + queued (idle, v47; they were part of the live segment), waiting,
settled, not found, cancelled (idle). Segment width is `count / total` as a flex-basis percentage; a
zero-track job (`expanding`/`failed`) renders no bar rather than an empty one. `role="img"` with an
`aria-label` carrying the same text as the adjacent breakdown (`"1,204 done · 12 waiting · 1 not
found"`); the breakdown wraps between parts only, never stranding a separator (v47). Under
`forced-colors` the bar keeps its colours (v47).

### Long titles (v47)

A job title and a tracks-scope group title take two lines (`line-clamp: 2`, `overflow-wrap:
anywhere`) before they are cut; an open job shows its title whole. A phone's track meta line
("artist · album") wraps to two lines instead of hiding the album. Raw attempt errors stay clamped
to three lines with "show full message" (v41).

### Library sweep page (`routes/library/+page.svelte`)

The admin-only sort-and-move sweep has its own route rather than a modal or an inline panel on
`/settings` (v28): config (target directory, folder template, quarantine) lives in `/settings`'
"Library sort & move" section, which links out to `/library` to run it, the same config-vs-live
split `/settings` vs `/` already establishes, rather than a third pattern for one feature.

Three states (v43, 2026-10-16, F20). _No sweep yet_ says so. _Running_ reads "Sweeping · 8 of 136
files" over the `--signal-dim` bar, with the four counts updating live (errors so far are the
processed files not filed any of the three ways, since the progress event carries no error count)
and a waiting-blue "Live updates lost" line while the stream reconnects. _Finished_ reads "Last
sweep finished <date> · took <n>s"; its bar is `--settled-dim`, not amber. The report is four
labelled numbers (moved, duplicates deleted, duplicates quarantined, errors: the backend counts a
duplicate as one or the other, by the quarantine setting), number first at `--fs-title`, errors in
`--fail` only when non-zero. Failed files are listed under "Not filed" with recovery copy, identical
rows folded into one entry marked × n (the count stays the backend's, matching the sweep's alert);
their raw error text carries `lang="en"` (v47). The fill is `transform: scaleX()` on `--dur-med`,
and the bar is named "Sweep progress".

Why `--signal-dim` and not `--signal` while running: the same carve-out v20 established for
"something is genuinely happening, but not _this session's own active track_" (the hero border and
worker notes above). A background admin sweep is real and running, but it isn't the one thing
`--signal` is reserved for. Progress arrives over the same shared SSE stream (a `library.progress`
event), not a dedicated poll or a second connection: this app has exactly one live-update channel.
Red only for the errors is §2's "hold red back for terminal outcomes" one level up, at the level of a
whole sweep run instead of one track.

### Queue panel (`routes/+page.svelte`, v42)

The controls and the list are one faceplate (`section.queue`, headed by an `h2` "Queue" and the
list's exact size, e.g. "7 of 7 jobs" or "Loading…"; v47 counts it exactly from the chips' grouped
counts, so "1,662 of 1,000+" and "150+ tracks" are gone, and a search, filter or scope change
announces the new size once). The log's own tools sit at the head's right, apart from the view
controls: **show archived** (a toggle chip) and **clear log**, outlined in `--fail-edge` at rest so
it never reads as one more toggle (it asks first, see Confirmation). Then the find row (scope switch,
search, the admin's mine/all users), the refine row (chips, sort), a divider, and the list or its
state:

- **Loading:** three still placeholder rows on the row grid (no shimmer); the head says "Loading…".
- **Error:** "Couldn't load the queue", the server's own words, and **try again** (`queue.reload()`).
  A failed **load more** is not this state: the loaded rows stay, a "Couldn't load more" line
  appears above the button, and the button retries that page.
- **Empty**, four cases: a search or filter miss ("No jobs match "…"" + **clear search and
  filters**), the admin's all-users view ("Nobody has anything queued"), a link still being read
  ("Your link is being read", or "A link is being read" in all-users view), and a user's own empty
  queue ("Your queue is empty", what happens to a pasted link, where archived jobs went, and **paste
  a link**, which focuses the submit box).

A job's track list that fails to load says what failed and retries in place; a failed job's empty
list gives its reason (v47). A failed row action's notice reads in `--fail`; other row notices
(a retry scheduled, a bump) keep the waiting blue (v47). Priority and bump are the admin's (owner's
call, v47): a non-admin's in-flight job offers cancel only.

### Sort (`QueueControls.svelte`)

Five equal-weight sort chips were a large part of "cluttered" (v42, 2026-10-15, F11), so sort is a
native `<select>` (a `.well`, labelled "sort") plus one direction button ("Reverse sort order (now
ascending/descending)", ↑/↓). A different field starts descending; the button flips. Fields differ
by scope (`created_at`/`title`/`status`/`track_count`/`next_retry` for jobs,
`created_at`/`title`/`state` for tracks), since the two endpoints' `sort=` parameters genuinely
differ. `next_retry` is offered to the admin only: it orders by the retry ladder, operator detail
(v39 outcome 3). History: v20's sort was a button group with `aria-pressed` and a ▲/▼ glyph, chosen
over a `<table>`'s clickable `<th>` because this app has never used table markup for its dense
lists.

### Search box (`QueueControls.svelte`, v20)

A plain `<input type="search">` that debounces (300ms) before calling into the store, since every
keystroke would otherwise fire a real paginated request. Sans per §3's content-vs-chrome split — a
search term is user-authored text, not a system/meta value, even inside the instrument-panel control
bar.

### Scope switches (jobs / tracks; mine / all users, admin-only)

Each is one segmented control (v42) rather than loose chips: `role="group"`, `aria-pressed`
buttons, the pressed idiom below. Neither represents a live condition, so neither uses `--signal`
(§2): the admin's "all users" is pressed indefinitely while selected, exactly the "permanent chrome"
amber must never represent (v17's reason, when its pressed state was a `--line-bright` border
instead of the filter tabs' then-amber one). The two don't interact. The page starts from the queue
store's own mine/all-users scope, which outlives the page, so returning from `/settings` keeps "all
users" instead of showing "mine" over all-users data (v42, 2026-10-15).

### Filter tabs (chips)

`role="group"` of toggle buttons using `aria-pressed` (not a radio input), each label in Sans with a
mono count beside it (`all 12`, `waiting 3`, `not found 1`). This is the pattern for any future
filter/tab control — `aria-pressed` boolean buttons with an inline count, not a `<select>` or
unlabeled icon toggle.

A chip with a zero count is hidden (a pressed one always stays, so a filter can be switched off). A
small `.label` before the chips names what the counts count (**jobs** or **tracks**), so a job
chip's "waiting 1" isn't read against a row's "8 waiting". One chip may stand for several tokens
(the non-admin's **in progress**, above). Pressed is `--bg-3` with a `--text-muted` edge, primary
text and a 2px `--text-muted` floor line (segments and `.choice-group` too); hover only lifts the
text, so a hovered option never passes for the selected one (v42, 2026-10-15, F11/F21/F32). The
focus ring is drawn inside the segment (`outline-offset: -3px`, v45): outside, it spilled over the
neighbouring segment and read as marking both. While a pressed segment has focus, the ring covers
its floor line; the fill and primary text still mark it pressed.

### Attempt-history fan-out (`TrackRow.svelte`)

Each track row is itself a `<button>` (not a row with a separate expand icon) carrying
`aria-expanded`, `aria-controls` and a trailing chevron level with the title's first line (v41
F22; v47). **This row-as-button disclosure is the convention for any future expandable list row.**

The detail is the row's own grid, two columns (v41, 2026-10-14): a status strip first (the state in
plain words, the next-try countdown, which follows the breaker's clear when that's later (F04), and,
for the admin, attempts / failed / last path), then one action area (retry now · download · cancel
track, the destructive one set apart and outlined in `--fail-edge`), then, **admin only**, the
attempt timeline: newest first, the time in the state column's gutter (absolute time on hover,
focus, or a click that pins it), consecutive identical readings collapsed into one × n entry that
opens on demand, raw errors clamped to three lines with "show full message" and always selectable. A
non-admin's expanded track shows the status and actions only; the history's markup never renders and
its request is never made (master plan amendment, v39 outcome 3). History is fetched on open and
cached until the track's state or counts change. (v20's detail was plain mono text: attempt count, a
`Countdown` and `last_error` in `--fail`; v41 replaced it.)

### File-download action (`TrackRow.svelte`, v27)

`download` renders only when `track.state` is `completed` or `skipped_duplicate` — the only two
states `download_track` ever sets `output_path` from — so it doesn't render and then 404 for any
other state ("nothing for tracks without a file"). A file deleted from disk afterwards still shows
the button; that request 404s and surfaces through the same per-row notice a failed retry/cancel
uses. `handleDownload` first sends a `HEAD` probe (`api.checkTrackFile`), so a 404 renders through
this app's own notice instead of the browser replacing the page with raw JSON; then it clicks a
temporary `<a download href>` so the browser streams the file straight to disk (v35; v27 fetched it
into a `Blob` first). The probe keeps v27's guard against a 0-byte "successful" response: FastAPI's
side is headers-only with nginx's `X-Accel-Redirect` supplying the bytes, so a proxy that doesn't
understand that header would report `Content-Length: 0`. Under the dev override, `vite.config.ts`'s
dev fallback follows the redirect itself, for `HEAD` as well as `GET`. It is a plain row action — no
new affordance for what is, to the design system, just a third action.

### Job-row expansion (`JobRow.svelte`)

A job row can't reuse the row-as-`<button>` pattern unmodified: it has other real controls
(priority, bump, cancel, archive) beside the toggle, and nesting a `<button>`/`<input>` in a
`<button>` is invalid HTML. So the toggle is its own `<button>` wrapping only non-interactive
content (chevron, badge, title, type, owner), and the actions are siblings, never inside it (v20).
The toggle has no `aria-label`, so its name is what it shows (v41, 2026-10-14, F16), plus
`aria-controls` to the track list. Expanding renders `JobTrackList.svelte` (a paginated `TrackRow`
list for that job), fetched on first expand, never eagerly. Expansion state lives in
`stores/queue.ts`'s `expanded` map (keyed by job id), so it survives a filter/search change. The row
sits on the row grid (§4), and the open job's tracks hang off a 1px rail in its chevron column,
indented by `--row-nest`, on the panel's own surface rather than v20's darker `--bg-0` well (v41,
2026-10-14, F02).

### Page breakpoints (v42, F15/F37; em since v47)

Width breakpoints are in **em** (v47, WCAG 1.4.4), equal to the old px at the default 16px, so a
larger browser text size moves the layout to its narrower band as the text grows (in px, a 1024px
window at 200% text kept the desktop row grid and squeezed job titles to 0px). Media queries can't
read custom properties, so these are literals; use only these:

| Query                  | px at 16px | Band                                                                                    |
| ---------------------- | ---------- | --------------------------------------------------------------------------------------- |
| `max-width: 30em`      | 480        | The confirmation's buttons stack full width                                             |
| `max-width: 40em`      | 640        | Phone                                                                                   |
| `max-width: 47.5em`    | 760        | The help overlay goes to one column                                                     |
| `max-width: 60em`      | 960        | v41's job and track rows fold (artist · album under the title, actions under the title) |
| `max-width: 63.9375em` | 1023       | Tablet (and phone)                                                                      |

Desktop (≥64em) keeps the stage a 64rem column; the masthead is one row (ident · receiver status ·
account nav). Tablet: ident and nav share the first row and the status drops under them. Phone: the
masthead is two lines (wordmark with the link tell, then the nav, **disconnect** pushed right; an
admin's six items wrap it to a second row), the page gutter is 16px, the Waterfall's lanes put the
title line above meter + percentage, and the incoming rows put their actions under the link (≤1023px).

Coarse pointers get 44px targets whatever the width (`@media (pointer: coarse)`) on every control
that carries the task: `.btn`, `.choice-group` options, inputs, chips, segments, the sort select, nav
links, the job and track row toggles and actions (F32), and since v47 the admin timeline's inline
toggles and time pins too (they were WCAG 2.5.8's 24px).

### Mobile stacked layout (`TrackRow.svelte`, `JobRow.svelte`, phone band)

A phone job row is grid rows (v41, 2026-10-14): chevron · badge · type (and owner) on the first
line, the title on the second (two lines, v47), then the bar with its breakdown and the actions, all
on the column the nested tracks indent to. A phone track row is state, title, then "artist · album"
as one muted line (wrapping to two, v47), with the chevron at the right.

**Rejected designs worth restating so they aren't re-attempted** (from v09's `QueueTable`):
squeezing all columns proportionally became unreadable, and pairing cells onto shared sub-columns
(title+job, artist+album) reintroduced the same failure one level down — an `auto` column sized to
one row's longest value silently starved a _different_ row's column. "Give every cell its own line,
nothing ever competes for width" was the v09–v40 rule for a dense-table mobile collapse; v41's grid
rows keep its spirit (no shared auto tracks between rows).

> **Correction, 2026-10-12 (v39 F01, fixed in v39.1).** v20's 390px check of the flex-column job
> row confirmed _width_ (no overflow) only. In a `flex-direction: column` stack every flex-basis
> sizes **height**: the desktop `.toggle { flex: 2 1 16rem }` made the toggle 256px tall (each phone
> job row 364px), and `.bar`'s `flex-basis: 100%` resolved against an indefinite height and left only
> the 2px border, so job progress was invisible on phones. Rule for any column-direction collapse:
> reset the children's flex-basis and check heights, not only widths. e2e spec 10 guards it.

### Command-line submit bar

The primary action (`+page.svelte`'s URL submit) is framed as a console prompt: a static `>` glyph
(`--text-muted` at rest, `--signal` only while sending), a single input, and a mono SUBMIT button
(`--fw-strong`, `0.06em` tracking) — deliberately not a labeled form field with a floating label or
a card-style "New Job" affordance. This is the FIRST VIEWPORT commitment from the direction
contract, shipped as literally described, and the one button that stays mono after v47 (§3): beside
the prompt it is part of the console, not a form. The field checks the link itself (`novalidate`,
v47): the first http(s) address in what was pasted, or "That isn't a link"; a phone gets the short
placeholder.

### Confirmation (`ConfirmDialog.svelte`, `stores/confirm.ts`, v43, F08)

One confirmation for every destructive or risky action, chosen with the owner over an inline
two-step: a native modal `<dialog>` (`role="alertdialog"`, named by its title, described by its
subject and body) mounted once in the layout and driven by `await confirmAction({...})`, which
resolves `true` only on the destructive button. The top layer makes the page inert and keeps Tab off
the page; focus starts on the **safe** button; Esc, the safe button, a backdrop click and any
navigation answer `false`; focus returns to the trigger. It is the `.panel` faceplate over
`--backdrop` (dimmed, not blurred), entering with a 6px rise on `--dur-med` (none under reduced
motion). On a phone (≤30em) both buttons stack full width (v47).

Copy follows `clarify`: the title is a question naming the action ("Cancel this job?"), the subject
is the object acted on, wrapping rather than truncating (mono only when it is an address — a proxy,
the library folder; a job title is content, so Sans, v47), the body says what happens and whether it
can be undone, and both buttons name their action ("keep job" / "cancel job"), never OK/Yes. The
destructive button is `.btn.danger`.

Guarded: clear log, a job's cancel (in the list, and an incoming submission's while it is still
being read), cancel track, remove proxy, start sweep, breaker "release now" and worker pause (A4). A
failed submission's dismiss doesn't ask: that job is already over. Resume, archive and unarchive
don't ask: they are undoable or safe. A new destructive action uses this, never `window.confirm`.

### Session end and an unreachable server (`routes/+layout.svelte`, `lib/api.ts`, v47)

A 401 from anything but signing in or out runs one handler: the tab goes to `/login`, which says
"Your session ended" (instead of "Not authenticated" with a retry that looped). The stream's own
`/me` check and the 5s worker poll reach it within one poll. A 5xx or network failure of
`/api/auth/me` no longer signs the user out: the layout shows a **Can't reach the server** screen
(`.page-title`, a sentence, a retry `.btn`) that retries with backoff. A 5xx with an unknown code
reads "The server had a problem (502). Try again in a moment." in both languages.

### Secondary pages (v43)

`/settings`, `/library`, `/account` and `/stats` share `SubpageHeader.svelte`: the mono wordmark and
the page links (queue, then library, settings and stats for the admin only, then account; the
current one is `aria-current="page"`, primary text, no underline; Sans since v47). `main` opens with
the page's one `h1` (`.page-title`) in Sans at `--fs-title`. There is no eyebrow above the `h1`: the
wordmark is the masthead, not a kicker. A non-admin is never linked to an admin page; typing the path
gets `AdminOnlyNotice.svelte`, which makes no admin request (F17).

The form vocabulary lives in `app.css` so the routes can't drift:

- `.btn` and its variants (above).
- `.form-field` is a persistent `.label`, the control (a mono `.well`: what goes in is a value, a
  path or a template), then a `.field-hint` and a `.field-error` (`aria-invalid` on the input, which
  takes the `--fail-edge` edge; `aria-describedby` to both). A field error reserves nothing at rest:
  it appears only after a submit, which moves focus to the first invalid field, and a reserved line
  under every field cost about 200px on a phone `/settings` (v43). Number fields have no browser
  spinner (F18).
- **Empty live regions leave the flow** (v47): an empty `.field-error`, `.form-error` or
  `.save-state` is positioned absolutely and clipped, so it takes no room (in a flex column it still
  took a gap, and every panel ended in 16–40px of dead space). It stays rendered and in the
  accessibility tree — **never `display: none`**, which some screen readers then don't announce
  into.
- `.choice-group` is the segmented few-values choice (`aria-pressed` buttons, Sans labels; `.values`
  for readings, mono).
- `.save-row` is a section's save button followed by its `role="status"` state: "Unsaved changes"
  once the form differs from what was loaded, then "Saved at 14:03" (F31: the old "Saved." never
  cleared).
- Validation mirrors the backend's rules (alert bounds, the proxy pattern, non-blank paths and
  templates) and answers inline before any request; the backend stays the real check.

`/settings` is one page of five `.panel` sections (worker, output, library, alerts, proxies) with an
anchor index: a sticky column at desktop width that marks the section being read (a `--text-muted`
rail, never amber; Worker is marked at the top of the page, v47), a wrapping row of links below. No
sub-routes, so no nginx change (F19). A section whose first read failed says so with its own retry
(v47; it took a full reload before). Alerts are two groups, "Send an alert when" (each category with
a one-line description) and "Thresholds" (numbers with their units, inputs ending on one line
whatever the unit's length); their legends are group headings, not one more `.label` (v47).

`/account` holds "Signed in" (name, email, the admin's role, **disconnect**) and "Preferences":
log retention, the keyboard-shortcut switch (v45), language and time format (v46), as groups that
read apart (v47).

### Admin stats page (`routes/stats/+page.svelte`, v44)

A flight recorder, not a KPI wall: no big-number tiles and no per-chart filters. Owner-approved
"now | over window" split. At desktop width a ~15rem **Right now** plate (queue counts as a ruled
`dl` readout, oldest waiting age, the breaker's state, proxies switched on / cooling) sits beside the
**window** plate. Below that the plates stack with now first, and at tablet the readout runs across
as a wrapping row. The 24h/7d/30d `.choice-group.values` lives in the window plate's own head and
scopes only that plate. Refresh (`.btn.small`) and a `role="status"` "read at 14:03" sit in the
title row. One request per load and per window change, newest-wins by a sequence number. A refetch
keeps the frame and dims the old reading (`opacity: 0.55`, `aria-busy`) instead of showing a
skeleton.

Colour by meaning only, on §2's five conditions: completed = settled, a failure the ladder retries =
waiting, not found = fail, an unrecorded cause = idle. Breaker holding ("holding until 14:30") =
waiting, downloads paused = fail, clear = primary text. A cooling proxy = waiting. **Never amber**:
nothing on this page is this session's live track. Validated on `--bg-1`: settled/waiting/fail are
ΔE 12.3 apart under deuteranopia (15.7 normal vision) and all ≥3:1. The validator's band and chroma
checks are for categorical palettes and don't apply to status colours.

- **`OutcomeBar.svelte`**: a route's or proxy's attempts as a part-to-whole bar, normalized to the
  row's own attempts (how often it works, not how busy it is), in a `.well` with the quiet `--line`
  edge, 2px surface gaps between segments, `aria-hidden`: every number is in the row's text.
- **Success rate** = completed ÷ (completed + failed). Not found is a verdict on the track and is
  counted apart. The definition is a visible line (`#rate-definition`, 68ch) that both tables
  reference via `aria-describedby`, never a `title`. `formatRate` never rounds a partial up to 100%
  or down to 0% (`>99%`, `<1%`).
- **Proxy labels are host:port**, never a URL (rows keyed by position, since two can share one);
  their state reads "switched on" as on `/settings` (v47).
- **`FailureChannels.svelte`**, the recorder: one channel per failure class that occurred, on one
  shared y-scale (stated above it) and one time axis. Breaker holds are the bottom channel:
  `--waiting-dim` fill with a 2px `--waiting` top edge, at least one bucket wide. An ongoing hold has
  its leading edge drawn and a manual release has its end edged in `--text-primary`. One crosshair
  readout reads every channel at once. The drawing is `role="img"` with a summary label, plus a
  "show as a table" `<details>`. Phones hide every other axis tick. Under `forced-colors` the marks
  are `CanvasText`.
- On a phone each table row becomes a stacked reading (route + rate, then the bar, units spelled out).
- A non-admin gets `AdminOnlyNotice` with its `reason` prop and the page makes no request.

### Login "tuning in" instrument (`routes/login/+page.svelte`)

The dial (21 tick marks, evenly placed, every 5th labeled with a fake FM frequency at `--fs-label`;
a needle that sweeps only while connecting) is a one-off flourish scoped to the login route — not a
reusable component, no shared token beyond §2/§3/§4. Do not generalize it into a shared "Dial"
component unless a second real use case appears; it exists to make "signing in" itself read as
tuning in a receiver, matching the THESIS. At rest the needle is `--text-muted` with no glow; it
takes `--signal` and its glow only while connecting (v43, 2026-10-16, F10/F31). It moves by
`transform` (v47).

The stage is anchored near the top, not centred, so the error line growing under the button never
moves the card (v47). The connect button is a `.btn` (Sans, v47). Under it one line says which
account to use ("Sign in with your vb2007.hu account. Access is by invitation."). The fields are
checked by the page itself (`novalidate`, v47). A failed sign-in puts focus back on the password
(selected), with one `role="alert"` line. There is no language switch: signed out, `/login` speaks
the browser's language (owner's rule on PR #68, v46, 2026-10-18).

### Error / status text

Inline error lines (`/`'s `submit-error`, `/login`'s `#login-error`, `.form-error`, `.field-error`)
are `role="alert"` (or a polite live region), coloured `--fail`, in **Sans** at `--fs-detail` (a
field's at `--fs-meta`): an error is a sentence (§3). The server's own words inside one stay as
sent. `/login`'s line reserves its height at rest (`min-height: 1.25rem`) so its appearance never
reflows the card, and so does `/stats`' (pulled up into the title's air), so a failed window switch
never moves the switch under the pointer; `/`'s submit error and the form errors take no room while empty (v42 for
`submit-error`; v47's live-region rule above for the rest), and they keep their live region
rendered so the message is announced. For any future inline message: a live region that exists
before the message does, `--fail`, Sans; reserve height where a shift would move the thing the user
is about to press.

> **v47 (2026-10-19):** this section said inline errors were "mono" and all "reserve their vertical
> space at rest". Neither is true any more: v42 moved sentences, errors included, to Sans (F12), and
> v42/v47 let empty error regions leave the flow except where a shift would move the target
> (`/login`, `/stats`).

### Keyboard: shortcuts, roving lists, help overlay (`lib/keyboard/`, v45)

**One listener, one table.** `lib/keyboard/bindings.ts` is every binding as data (pure TS, so the
e2e suite imports it too); `registry.ts` is the single `window` `keydown` listener that matches
against it and runs the handler registered under the binding's id (the layout registers the help and
the `g` chords, `/` registers the list and queue keys). The help overlay (`HelpOverlay.svelte`) is
rendered from the same table, filtered to the route and the viewer's role, so it can never list a key
that does nothing or miss one that does.

**Hungarian QWERTZ first.** Most users type on a Hungarian layout. No binding needs AltGr, `y` and
`z` (swapped against US) are never bound, keys match on `event.key` (the produced character), and a
symbol that needs Shift on Hungarian is only ever an alias for a letter or unshifted key.
`bindings.test.ts` enforces all of that on the table. Guards in `registry.ts`: nothing fires while
typing in an input, textarea or `contenteditable` (except Esc). A `<select>` isn't typing (owner's
review): the shortcuts work on it (a bound letter no longer picks an option by its first letter;
unbound ones still do), and its own arrows, Home/End, Page keys, Enter and Space stay with it. Ctrl,
Meta and Alt chords are never shadowed; AltGr (`getModifierState('AltGraph')`, or Ctrl+Alt as
Windows reports it) never fires anything; IME composition and dead keys are ignored.

**The table** (the overlay shows the same, with the Hungarian keys for each symbol):

| Key (Hungarian QWERTZ)                                                                 | Where                     | Action                                                                             |
| -------------------------------------------------------------------------------------- | ------------------------- | ---------------------------------------------------------------------------------- |
| `h`, alias `?` (**Shift + ,**)                                                         | everywhere                | Show or hide the shortcut overlay                                                  |
| `f`, alias `/` (**Shift + 6**)                                                         | `/`                       | Search the queue                                                                   |
| `i`                                                                                    | `/`                       | The submit field                                                                   |
| `Esc`                                                                                  | everywhere                | Close a dialog, else collapse the focused row, else clear and leave the search     |
| `g` then `d` / `a`                                                                     | signed in                 | Queue / Account                                                                    |
| `g` then `s` / `l` / `t`                                                               | admin                     | Settings / Library / Stats (absent for everyone else)                              |
| `j` / `↓`, `k` / `↑`                                                                   | lists                     | Next / previous row (`j`/`k` from anywhere on `/` enter the list)                  |
| `Home` / `End`                                                                         | lists                     | First / last loaded row; `End` on the last row loads more                          |
| **Shift + G**                                                                          | lists                     | Load more                                                                          |
| `Enter` / `Space`                                                                      | lists                     | Open or close the row (the button's own activation)                                |
| `→` / `o`                                                                              | lists                     | Open the row; on an open job, move into its tracks                                 |
| `←`                                                                                    | lists                     | Close the row, or go back from a track to its job                                  |
| `r` / `d` / `x`                                                                        | rows                      | Retry / download / cancel (through the confirmation), only where the row offers it |
| `a`                                                                                    | job rows                  | Archive or unarchive                                                               |
| `b`, **Shift + B** (alias `+`, **Shift + 3**), `-` (unshifted, the key **right of .**) | in-flight job rows, admin | Bump; priority +1; priority −1 (admin-only since v47, absent from others' overlay) |
| `e`                                                                                    | track rows, admin         | Open the track's history and show or hide every collapsed repeat                   |
| `1` / `2`                                                                              | `/`                       | Jobs / tracks scope                                                                |
| **Shift + F**                                                                          | `/`                       | Into the filter chips (`←`/`→` roam, `Space` toggles)                              |
| `s`                                                                                    | `/`                       | Next sort field                                                                    |
| **Shift + A**                                                                          | `/`                       | Show or hide archived jobs                                                         |

Single-character keys (everything above except `Esc`, `Enter`, `Space`, the arrows, `Home` and
`End`) are switched off by the per-user **Keyboard shortcuts** setting on `/account` (WCAG 2.1.4),
stored server-side (`user_settings.keyboard_shortcuts`, carried on `/api/auth/me`).

**Roving lists** (`lists.ts`): the jobs list, the tracks list, an open job's tracks and the filter
chips are each one Tab stop. A row's own button (`data-kb-item`) carries the roving tabindex; the
row's other controls are in the Tab order only while it is the current row **and open** (owner's
decision): Enter opens a job, then Tab walks its controls, its track list (one stop) and "load more
tracks". Focus is tracked by row **id**: an SSE re-order (which moves the DOM node and drops focus)
or a reload (which remounts the list) puts it back on the same row; a row that leaves hands it to the
next row, or the previous one if it was last; an emptied list hands it to the queue heading. Never
`<body>`.

**Visuals.** Focus is still the one global ring (§2 Focus); a roving row shows it on its button,
nothing else. The overlay is the confirmation's material (a `.panel` modal on `--backdrop`): one grid
per group with every entry a subgrid of it, so keys sit in one fixed track as keycaps and every
meaning starts at one x (v47; each entry sized its own key column and the meanings drifted
477–505px), one hairline between entries, two columns of groups on desktop and one below 47.5em. The
`g` chord readout docks at the bottom edge in the panel's material and lists where each second key
goes. The skip link ("Skip to queue" on `/`, "Skip to content" elsewhere) is the first focusable
element on every page, off-screen until focused, then a small plate at the top-left; on `/` it lands
on the queue's heading, not 13 stops short on the submit form (v47).

### Language: Hungarian and English (`lib/i18n/`, `messages/`, v46)

**Every user-visible string is a message** in `messages/en.json` and `messages/hu.json` (Paraglide
JS), keyed by meaning (`track_cancel_confirm`), never by its English. `npm run lint` fails on a
hard-coded string in `src/` (`scripts/scan-literals.mjs`) and on any difference between the two
files' keys or inputs (`scripts/check-messages.mjs`). The deliberate exceptions carry an
`i18n-ignore` comment with their reason: the `SPOTDL // WEB` wordmark, CSS selectors, the proxy
format, and the English `detail` behind a client-side error code.

**Which language** (owner's rule, PR #68, 2026-10-18). Signed out, always the browser's: the first
of its languages that is `hu` or `en`, else English. Signed in, a language the user saved on
`/account` wins, else the browser's again. So someone who prefers English on a Hungarian browser
sees Hungarian on `/login` and English once signed in. Nothing is stored in the browser and nothing
is adopted at sign-in. `<html lang>` follows it, and a switch re-renders in place (no reload).

**The switches** are on `/account` only, in Preferences, each a `.choice-group` saved to the profile
the moment the server has it, with the shortcut switch's `role="status"` save line. **Language** is
automatic / Magyar / English: each language in its own name and marked with its own `lang` (Magyar
first, since most users read it), and "automatic (Magyar)" naming, the same way, the language the
browser gives (owner's answer on PR #68: a way back to following the browser). **Time format** is
automatic / 12-hour / 24-hour, each showing the current time as it would read. `/login` has no
switch: there the browser decides.

**Formats.** Words (month names, the AM/PM marker) follow the interface language. Conventions (date
order, digit grouping, decimal mark, 12- or 24-hour) follow the browser's region: English on a
Hungarian browser reads "17 Oct 2026, 13:05" and "12 345" (`lib/i18n/format.ts`, the `en-HU`
locale). Where Intl has no data for the pair (Hungarian on a US browser, `hu-US`), numbers and the
clock still follow the region and only the date order stays the language's. A time format pinned on
`/account` overrides the region's clock once signed in.

**What is never translated:** track, artist and album metadata, raw attempt error and note text
(marked `lang="en"` since v47), proxy addresses, error-type machine names (`NO_OUTPUT`), and the
wordmark. Matrix alerts and logs stay English.

**Hungarian copy** is tegező (te) and keeps the signal-receiver voice where English has it
(hangolás, nincs jel, jelvevő, HANGOLÁS / KAPCSOLÓDÁS), with plain state words beside it. The
circuit breaker is the _biztosíték_ (fuse), so it never shares a root with _megszakítva_
(cancelled). Lowercase action labels stay lowercase. A count is a plural message with Hungarian's
singular noun after a numeral ("5 szám"), taking the raw `count` for the form and a pre-formatted
`n` (`counted()`), so the number follows the browser's region like every other. A sentence with
markup (`<kbd>`) keeps it in the message and renders through `RichText.svelte`. `Countdown`'s label
stands before the time (`feloldásig 4:32`), and label and time never wrap apart (v47; the label is
Sans, the time mono). Hungarian runs longer: v46 and v47 checked every route at 1280/1440px and
390px for clipped text.

## 7. Accessibility (confirmed hard requirement, PRODUCT.md)

- Keyboard-only navigation must work for every interactive element — confirmed, not aspirational.
  The global `:focus-visible` treatment (§2, `--focus-ring`) is never suppressed anywhere in the
  tree; treat that as a load-bearing regression check, not a thing to rediscover.
- Every custom widget (progressbar meter, filter tab group, expandable row, segmented switch) uses
  real ARIA (`role="progressbar"` + `aria-valuenow/min/max`, or `aria-valuetext` and no
  `aria-valuenow` while the reading is unknown; `role="group"` + `aria-pressed`; `aria-expanded`)
  rather than a bare styled `<div>` — do not ship a control that looks interactive but lacks the
  matching role/state.
- All decorative-only motion (noise floor, dial ticks, the ambient field) is `aria-hidden="true"`.
- Text scaling (WCAG 1.4.4): sizes are rem tokens and width breakpoints are em (§6), so the layout
  follows the user's text size as well as the window (v47).
- Language of parts (WCAG 3.1.2): raw English text on a Hungarian page carries `lang="en"` (v47).
- Forced colours: progress meters, job bars and `/stats`' charts keep their own colours under
  `forced-colors: active` (v44 for `/stats`, v47 for the rest).
- **Landmarks and outline on `/` (v42, F29):** `header` (banner) → `nav[aria-label=Account]` →
  `main#main` (the id the skip link targets; no `tabindex` on it, since a `tabindex="-1"` container
  takes focus on any click inside and resets Tab order). One `h1` (the wordmark; its name is
  "spotdl-web"), then `h2`s for Incoming submissions (visually hidden), Active signal and Queue,
  each section labelled by its heading. A countdown is never inside a live region.
- **Secondary pages (v43):** the masthead's `nav[aria-label=Pages]`, then `main#main` holding the
  page's one `h1` and `h2` sections, each `section` labelled by its heading. `/settings` adds
  `nav[aria-label="Settings sections"]` (`aria-current="location"` on the section being read).
- **`/stats` (v44):** `main#main` → one `h1`, `h2` per plate, `h3` per block, each labelled by its
  heading. The window switch is `role="group"` + `aria-pressed`. The crosshair is pointer-only, so
  the recorder's `role="img"` label and its "show as a table" view are the keyboard and screen-reader
  path to the same numbers.
- **Keyboard (v45):** every action is reachable without the mouse (§6 "Keyboard"). A route change
  moves focus to the new page's `h1`; SvelteKit's route announcer reads its title. Rows announce
  their name (what the row shows) and `aria-expanded`. Any new interactive element must be
  keyboard-reachable, and gets a row in `bindings.ts` if it gets a key.
- **Live regions** exist before their message does and are never `display: none` while empty (§6
  Secondary pages); one fixed sentence per state, never a ticking countdown.

## 8. Known, accepted gaps (do not silently "fix" without re-reading this section first)

1. **Matte charcoal chassis material** — asserted in the OWN-WORLD direction contract, attempted
   over two correction rounds, still not confirmed clearly perceptible against the near-black
   background. See §6 `.panel`. Open for future visual polish, not resolved.
   **Closed 2026-10-15 (v42):** resolved as a raised faceplate; see §6 `.panel`.
2. **Waterfall as progress-lane list, not a literal spectrogram** — this one is _not_ a gap, it is
   a deliberate, cited Operate-mode simplification (legibility of real song titles over decorative
   visualization). Recorded here explicitly so it is never "corrected" into a literal spectrogram
   under the mistaken belief that the simpler version was an oversight.
3. **(v47, 2026-10-19) The admin's all-users view warms the page with other users' downloads.** In
   all-users scope, `activeTracks` includes every user's receiving tracks, so the Waterfall's lanes
   and live edge and the ambient field turn amber for a download that isn't the admin's own. That
   bends §6's "this session's own active track" wording, but in that view the admin has chosen to
   watch everyone's queue, and what's on screen is genuinely receiving. Left as is.
4. **(v47, 2026-10-19) `/settings` is about 4000px tall on a phone.** Five sections of real forms in
   one page (§6 Secondary pages, F19's no-sub-routes choice); the anchor index is the way through.
   Not split in v47 (no new surfaces in a polish slice).
5. **(v47, 2026-10-19) The tracks scope repeats titles.** A single-track job's title appears in its
   group header and again on its one row, and an album's name is repeated on each of its rows'
   "artist · album" line. Known redundancy; folding it changes the group-header model, which is
   beyond polish.
6. **(v47, 2026-10-19) A fully loaded 1600-row log is about 28k DOM nodes.** `content-visibility:
auto` on rows was tried and rejected: its paint containment clips the focus ring (§2 Focus, never
   suppressed) and the timeline's absolute-time popups. Virtualizing the list is the real fix and is
   out of polish scope; rows load by cursor page, so only an account that loads everything pays it.

## 9. Sidecar

The machine-readable token mirror lives at `frontend/src/design-tokens.json`, kept in exact sync
with `app.css`'s `:root` block (every custom property, the same values, including the unused
`--signal-ink`, `--fail-dim` and `--space-7`). It also carries what the frontmatter can't: motion
tokens, the em breakpoints (literals in media queries, not custom properties), the row grid and the
state → condition maps. If a token's value changes in `app.css`, update the sidecar and this file's
frontmatter in the same commit; if a token is added or removed, do the same here in §2/§3/§4/§5.
