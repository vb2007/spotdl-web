# v42 — Secondary Surfaces Redesign

Branch: `dev-secondary-surfaces` → PR into `main`
Version: `4.42.0`

## Scope

`/settings`, `/library`, `/account` and `/login`, brought into the system v40–v41 established,
**strictly through the impeccable skill**. Also the **confirmation affordance** for destructive
actions across the app, so v44 has something safe to bind keys to. The v38 findings assigned to v42
are its checklist.

## Requirements

- **`/settings`** (admin; the longest page, 738 lines): output defaults, library settings,
  proxies (add, toggle, remove), worker controls (`WorkerStatus.svelte`: pause/resume, release
  breaker), and v36's alert toggles plus the test button.
  - Sectioning and in-page navigation, so it isn't one long scroll.
  - Form layout, validation and error states, and save feedback (`harden`/`clarify`).
  - Proxy URLs stay redacted in the UI.
- **`/library`** (admin): the idle state, the mid-sweep live progress (v28's transform-animated
  bar must stay transform-based), and the final report. The report's moved, conflict and
  quarantine counts become scannable.
- **`/account`**: retention settings, plus a placeholder section where v44 adds the shortcut
  toggle. Leave the section structure ready; don't add the toggle here.
- **`/login`**: the "TUNE IN" dial stays, unless v38's direction says otherwise. Error and
  loading states, and check it against v39's ambient field.
- **Type scale migration.** Every file touched here uses v41's tokens, with no ad hoc font sizes.
- **Destructive-action confirmation**, as one reusable component (a dialog or an inline two-step
  confirm, chosen with impeccable), applied to:
  - "clear log" (`QueueControls.svelte:98-100`, archives every settled job immediately today);
  - "remove proxy";
  - job "cancel" and track "cancel track";
  - "start sweep" on `/library`.

  It must be keyboard-complete (focus moves in, Esc cancels, focus returns to the trigger), use
  the right ARIA semantics (`role="dialog"`/`alertdialog` with a label), and default the focus to
  the *safe* choice.
- **Routing invariants.** Any new route or sub-route needs both the SvelteKit `ssr`/`prerender`
  exports and its own nginx `location` block (CLAUDE.md invariant). Prefer in-page anchors over
  new routes.

## Out of scope

- The admin stats page (v43, a new route).
- Keyboard shortcuts and the account toggle (v44).

## Done when

- [ ] impeccable was loaded, and its sub-commands and output recorded in the PR.
- [ ] Every v38 finding assigned to v42 is marked fixed or deferred with a reason.
- [ ] Before and after screenshots of all four routes at 390, 768 and 1440 widths, including
      `/settings` with a validation error, `/library` mid-sweep against the test library copy, and
      `/login` with a failed login. Real dev stack.
- [ ] The confirmation component guards every listed action. For each, show cancel does nothing
      (no API call in the network panel) and confirm performs it. A keyboard-only run through each
      shows focus in, Esc, and focus returned to the trigger (an e2e spec).
- [ ] Settings saves still round-trip (output, library, proxies, alerts), and admin gating is
      unchanged (non-admin 404 on admin APIs, e2e spec 6 green).
- [ ] The `/library` progress bar still animates via `transform` (computed style or Performance
      check).
- [ ] No ad hoc `font-size` literals in v42's files.
- [ ] An impeccable `audit` shows no regressions vs v38's baseline for these routes.
- [ ] The v37 e2e suite passes on both projects.
- [ ] `npm run lint`, `npm run check` and `npm run build` pass, and `pytest` passes. Both version
      files read `4.42.0`. `uv lock` is in sync. `graphify update .` has been run.
