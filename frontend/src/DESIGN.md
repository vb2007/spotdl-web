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

| Token           | Hex       | Use                                                                    |
| --------------- | --------- | ---------------------------------------------------------------------- |
| `--bg-0`        | `#0a0c0e` | Page background, recessed input wells                                  |
| `--bg-1`        | `#14181c` | `.panel` surface (the base "instrument housing" fill)                  |
| `--bg-2`        | `#1c2227` | Raised/hover surface for buttons, filter chips                         |
| `--bg-3`        | `#262e34` | Hover/active surface one step brighter than `--bg-2`                   |
| `--line`        | `#2b3339` | Default hairline border                                                |
| `--line-bright` | `#3a444c` | Emphasized border (buttons, major dial ticks, idle waterfall top edge) |

### Text

| Token            | Hex       | Use                                                  |
| ---------------- | --------- | ---------------------------------------------------- |
| `--text-primary` | `#e8ecee` | Body text, primary content                           |
| `--text-muted`   | `#8b969d` | Secondary content (artist lines, byline-weight text) |
| `--text-dim`     | `#566068` | Labels, meta, deliberately quiet text                |

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
- **IBM Plex Sans** (`--font-sans`) — the document body default and all real content: song
  titles, artist names, album names. Loaded at weights 400/500/600 alongside the mono family.

**Named rule**: this split exists so theming never sacrifices legibility of actual data — a
listener's song/artist/album text is never rendered in the "instrument" typeface. Any new
component must ask "is this a system/meta value or is it content a user is trying to read" before
picking a family; do not default new components to mono just because the world is technical.

### Sizes actually in use (no formal type-scale variable exists — sizes are set ad hoc per

component; the following is the ramp as built, worth keeping consistent rather than inventing new
in-between sizes)

| Size                             | Used for                                                                                                                   |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `0.5625rem` (9px)                | Login dial frequency tick labels                                                                                           |
| `0.6875rem` (11px)               | `.label` (uppercase, letter-spaced meta), queue-table job-type cell                                                        |
| `0.75rem` (12px)                 | Filter chip buttons, state cell letter-spacing context                                                                     |
| `0.8125rem` (13px)               | Secondary/muted lines: artist byline in waterfall, error text, session email, countdown text, detail row text              |
| `15px` (root, unitless rem base) | Body default (`body { font-size: 15px }`)                                                                                  |
| `0.875rem` (14px)                | Queue-table artist/album cells                                                                                             |
| No explicit `h1` size token      | Both `h1`s in the tree (login "TUNE IN", none on dashboard) are set locally per component, not from a shared heading scale |

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

## 5. Motion

| Token           | Value                           | Use                                                                                                          |
| --------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `--ease-signal` | `cubic-bezier(0.16, 1, 0.3, 1)` | The one easing curve for every animated transition in the system (progress fill, sweep needle, button hover) |
| `--dur-fast`    | `120ms`                         | Hover/focus state changes                                                                                    |
| `--dur-med`     | `320ms`                         | Progress-bar fill transitions                                                                                |
| `--dur-slow`    | `900ms`                         | Reserved (defined, not yet consumed by a built component)                                                    |

**Named rule — reduced motion is load-bearing, not decorative**: `@media (prefers-reduced-motion:
reduce)` zeroes all three duration tokens globally in `app.css`, and every bespoke `@keyframes`
animation in the tree (login needle sweep, waterfall noise floor, progress-fill shimmer) has its
own matching `prefers-reduced-motion` override alongside the global one. **Any new keyframe
animation added in v10+ must ship its own reduced-motion override in the same component** — the
global duration-zeroing does not reach hand-authored `animation:` shorthand time literals (e.g.
`animation: noise 4.2s ease-in-out infinite` is a literal, not a var, and needs its own `{
animation: none }` fallback).

## 6. Component patterns

### `.panel` — the recessed instrument housing

The one shared surface convention (`bg-1`, `1px solid var(--line)`, `border-radius: 6px`, plus a
compound `box-shadow`: inset top shadow + inset bottom highlight hairline + outer drop shadow).
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

### Hero-marking border (the "is anything live" tell)

`Waterfall.svelte`'s top border is neutral (`--line-bright`) by default and switches to
`--signal-dim` only when `tracks.length > 0` (`.waterfall.live`). This is the concrete embodiment
of the amber-exclusivity rule in §2 — the panel itself is the primary visual proof that "live" is
reserved, not just a color-token comment. **Any future panel that wants to signal "something in me
is currently active" should use this same neutral→signal-dim border-color swap pattern, not a
persistent accent border.**

### State → color/label mapping (`QueueTable.svelte`)

Two parallel `Record<TrackState, string>` maps — `STATE_LABEL` (in-world copy: "receiving",
"fading — waiting", "no signal — given up", "logged", "lost") and `STATE_COND` (one of the five
`.cond-*` classes from §2) — are the single source of truth for how a track state renders. **Any
new `TrackState` value added in a future version must get an entry in both maps in the same
change**, never inferred or left to fall through to a default, or a new state will render with no
label/color at all.

### Filter tabs

`role="group"` of toggle buttons using `aria-pressed` (not a radio input), each showing a live
mono count next to the label (`all 12`, `waiting 3`, `given up 1`). This is the pattern for any
future filter/tab control — `aria-pressed` boolean buttons with an inline count, not a `<select>`
or unlabeled icon toggle.

### Attempt-history fan-out (expand/collapse row detail)

Each queue row is itself a `<button>` (not a row with a separate expand icon) toggling a
`SvelteSet` of expanded IDs, exposing `aria-expanded`. The revealed `.detail` block is plain mono
text: attempt count, a live `Countdown` (only when `state === 'waiting'` and `scheduled_at` is
set), and `last_error` in `--fail` color when present. **This whole row-as-button + `SvelteSet`
pattern is the convention for any future expandable list row** (v10's cancel/retry-now controls
will likely need a similar per-row disclosure).

### Mobile stacked layout (`QueueTable.svelte`, ≤640px)

The five-column grid collapses to a fully stacked flex column, one cell per line, in an explicit
`order` (state, title, artist, album, job). **Two rejected intermediate designs are recorded
directly in the component's own comments and should not be re-attempted without new evidence**:
squeezing all five columns proportionally became unreadable, and pairing cells onto shared
sub-columns (title+job, artist+album) reintroduced the same failure one level down — an `auto`
column sized to one row's longest value silently starved a _different_ row's column. The fix that
shipped is "give every cell its own full-width line, nothing ever competes for width" — treat that
as the standing rule for any future dense-table mobile collapse, not just this table's.

### Command-line submit bar

The primary action (`+page.svelte`'s URL submit) is framed as a console prompt: a static `>`
glyph in `--signal` color, a single input, a mono SEND/SUBMIT button — deliberately not a
labeled form field with a floating label or a card-style "New Job" affordance. This is the FIRST
VIEWPORT commitment from the direction contract, shipped as literally described.

### Login "tuning in" instrument

`login/+page.svelte`'s dial (21 tick marks, every 5th labeled with a fake FM frequency, a sweeping
needle animated only while `submitting`) is a one-off flourish scoped to the login route — it is
not a reusable component and has no shared token beyond the ones in §2/§3/§4. Do not generalize it
into a shared "Dial" component unless a second real use case appears; it exists to make "signing
in" itself read as tuning in a receiver, matching the THESIS.

### Error / status text

Inline errors (`login-error`, `submit-error`) are `role="alert"` / `aria-live="polite"`, colored
`--fail`, mono, and reserve their vertical space at rest (`min-height`) so their appearance never
reflows the layout. Apply this pattern (reserved height + `aria-live`) to any future inline
validation message.

## 7. Accessibility (confirmed hard requirement, PRODUCT.md)

- Keyboard-only navigation must work for every interactive element — confirmed, not aspirational.
  The global `:focus-visible` treatment (§2, `--focus-ring`) is never suppressed anywhere in the
  tree; this file's existence should make that a load-bearing regression check for v10+, not a
  thing to rediscover.
- Every custom "widget" built so far (progressbar meter, filter tab group, expandable row) uses
  real ARIA (`role="progressbar"` + `aria-valuenow/min/max`, `role="group"` + `aria-pressed`,
  `aria-expanded`) rather than a bare styled `<div>` — continue this, do not ship a v10 control
  that looks interactive but lacks the matching ARIA role/state.
- All decorative-only motion (noise floor, dial ticks) is `aria-hidden="true"`.

## 8. Known, accepted gaps (do not silently "fix" without re-reading this section first)

1. **Matte charcoal chassis material** — asserted in the OWN-WORLD direction contract, attempted
   over two correction rounds, still not confirmed clearly perceptible against the near-black
   background. See §6 `.panel`. Open for future visual polish, not resolved.
2. **Waterfall as progress-lane list, not a literal spectrogram** — this one is _not_ a gap, it is
   a deliberate, cited Operate-mode simplification (legibility of real song titles over decorative
   visualization). Recorded here explicitly so it is never "corrected" into a literal spectrogram
   under the mistaken belief that the simpler version was an oversight.

## 9. Sidecar

Machine-readable token mirror lives at `frontend/src/design-tokens.json` — kept in exact sync with
`app.css`'s `:root` block. If a token's value changes in `app.css`, update the sidecar in the same
commit; if a token is added/removed, do the same here in DESIGN.md §2/§4/§5.
