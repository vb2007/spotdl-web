# v39 — Ambient Field (cursor-following background)

Branch: `dev-ambient-field` → PR into `main`
Version: `4.39.0`

## Scope

Today the background is a static radial gradient on `body` (`frontend/src/app.css:105-109`): an
amber ellipse fixed at the top of the screen. The owner wants that blurred glow to **follow the
cursor** across the background. Do this **strictly through the impeccable skill** (`animate`,
escalating to `overdrive` only if the v38-approved direction calls for it), within the direction
the owner approved in v38's report.

## Design constraints (non-negotiable; impeccable decides the look within them)

- **A single fixed, full-viewport layer** behind the content (`position: fixed`,
  `pointer-events: none`, `z-index` below everything). It is **moved by `transform` only**, with
  no `background-position`, `top`/`left` or `filter` animation per frame. Any blur is applied once
  to the element, never animated.
- **Input decoupled from paint.** `pointermove` only writes the latest coordinates. A single
  `requestAnimationFrame` loop eases the glow toward them (lerp or spring), with no layout reads
  (`getBoundingClientRect`) in the loop. The loop **stops** once the glow has settled, and
  restarts on the next move. No permanently spinning rAF.
- **Touch / no fine pointer** (`(pointer: coarse)` or no hover): a slow idle drift, or a static
  position. impeccable chooses, but it must never chase a tap.
- **`prefers-reduced-motion: reduce`**: static. No following, no drift. This matches DESIGN.md §5:
  every new animation ships its own override.
- **`document.hidden`**: the loop pauses.
- **Amber exclusivity (DESIGN.md §2): resolve it, don't ignore it.** A permanent amber glow is
  chrome in the "live" color. Either the glow is neutral at rest and takes the signal tint only
  while something is receiving (`activeTracks.length > 0`, which ties the effect to the
  product's meaning), or DESIGN.md's rule is explicitly amended with the reason. Record the
  decision in DESIGN.md either way.
- **Contrast and legibility unchanged.** Text over the glow's brightest point must still meet the
  same contrast as today (`audit` before and after).
- It lives as one small component (e.g. `AmbientField.svelte`) mounted once in
  `routes/+layout.svelte`, so every route gets it. `/login`'s dial must still read; check it there.

## Out of scope

- Any other component's styling (v40–v42).
- WebGL/canvas. Only if `overdrive` is approved in v38's direction *and* CSS can't achieve it.
  Record why if so.

## Done when

- [ ] impeccable was loaded, `animate` (or `overdrive`) run, and its output recorded in the PR.
- [ ] The glow follows the cursor smoothly on desktop (a short screen recording or frame sequence).
- [ ] **Performance:** a Chrome Performance profile of 10s of continuous cursor movement shows no
      long frames from this layer, no layout or style recalculation per frame from it, and only
      composite work (profile screenshot). Idle CPU drops to about zero once the cursor stops
      (the rAF loop stopped, shown in the profile).
- [ ] Reduced motion (emulated in DevTools) gives a static glow with no rAF activity (profile).
- [ ] Mobile emulation: no cursor chasing, and the drift or static behavior matches the design
      (screenshots).
- [ ] A hidden tab stops the loop (profile or a counter log while backgrounded).
- [ ] The amber-exclusivity decision is recorded in `frontend/src/DESIGN.md`, and the
      implementation matches it (e.g. a screenshot idle vs receiving, if tinted by state).
- [ ] Contrast is re-audited at the glow's brightest point, and is no worse than before
      (impeccable `audit` output).
- [ ] The v37 e2e suite passes on both projects.
- [ ] `npm run lint`, `npm run check` and `npm run build` pass, and `pytest` passes. Both version
      files read `4.39.0`. `uv lock` is in sync. `graphify update .` has been run.
