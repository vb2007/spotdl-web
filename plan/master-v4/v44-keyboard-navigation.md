# v44 — Complete Keyboard Navigation

Branch: `dev-keyboard-navigation` → PR into `main`
Version: `4.44.0`

## Scope

PRODUCT.md (`:71`, `:101`) has required full mouse-free operation since v00 ("a required,
explicitly confirmed standard"). Today the frontend has native Tab order and a global focus ring,
and nothing else: no `keydown` handler, `tabindex`, `.focus()` or skip link anywhere. Every
TrackRow is its own tab stop, so reaching the 300th track is 300 Tabs. Focus is lost when a
cancelled or archived row disappears.

This version makes every action reachable and fast from the keyboard, on the **final** markup of
v40–v43. Design the help overlay and focus visuals through the impeccable skill (in the established
system). The interaction model itself is specified below.

## Interaction model

**A central shortcut registry** (`frontend/src/lib/keyboard/`): a single `keydown` listener on
`window`, with scoped bindings (global, per route, per focused list), so there are no handlers
scattered through components.

- **Inert while typing:** ignore events whose target is an `input`, `textarea`, `select` or
  `[contenteditable]`, except Esc. Ignore events with Ctrl, Meta or Alt held, so browser and OS
  chords are never shadowed.
- **IME-safe:** ignore `event.isComposing`.

**Global:**

| Key | Action |
|---|---|
| `?` | Open or close the shortcut help overlay (focus-trapped dialog, Esc closes, focus returns) |
| `/` | Focus the search box (on `/`) |
| `i` | Focus the submit URL input |
| `g` then `d` / `s` / `l` / `a` / `t` | Go to dashboard / settings / library / account / stats. Admin-only targets are absent for non-admins. Show a chord indicator while `g` is pending, and time out after about 1.5s |
| `Esc` | Close the overlay or dialog, collapse the focused row, clear and blur the search, in that priority |

**Lists** (jobs, tracks, tracks within an expanded job): **roving tabindex**, so the whole list
is one tab stop and arrows move within it.

| Key | Action |
|---|---|
| `j` / `↓`, `k` / `↑` | Next / previous row |
| `Home` / `End` | First / last loaded row. `End` on the last row, or `Shift+G`, triggers "load more" when available |
| `Enter` / `Space` / `→` / `o` | Expand. On an expanded job, `→` moves into its track list |
| `←` | Collapse, or move from a track back to its parent job |
| `r` | Retry now (when allowed) |
| `d` | Download file (when allowed) |
| `x` | Cancel job or track, **through v42's confirmation** |
| `a` | Archive / unarchive (job) |
| `b` | Bump priority. `+` / `-` adjust priority by one |
| `h` | Toggle the attempt-history view of an expanded track (and collapsed repeats) |

**Queue controls:** `1` / `2` switch the jobs/tracks scope, `f` focuses the filter chips (arrow
keys roam between them, Space toggles), `s` cycles the sort, and `A` toggles "show archived".
"Clear log" is reachable via its button and confirmation. No single-key binding for a bulk
destructive action.

**Settings / account / library / login:** logical tab order, `Enter` submits forms, and confirmation
dialogs are keyboard-complete (from v42). No extra single-key shortcuts are needed there beyond
the global ones.

Keys are a proposal. Adjust where they collide with an existing behavior, and record the final
table in the help overlay **and** in `frontend/src/DESIGN.md`. The overlay is generated from the
registry, never a second hand-maintained list.

## Focus management

- **Skip link** ("Skip to queue") as the first focusable element, targeting v41's landmark.
- A row removed by an action (cancel, archive, or filtered out by an SSE update) moves focus to the
  next row, or the previous one if it was last. Never to `body`.
- "Load more" moves focus to the first newly loaded row.
- Expanding a track keeps focus on the row. Its detail actions are reachable by Tab inside the
  expanded region.
- An SSE re-order or patch must not steal focus or move the roving position to a different row
  id. Track focus by row **id**, not index.
- Route changes move focus to the new page's `h1` (or `main`), and announce the page title.

## User control (WCAG 2.1.4)

A **"Keyboard shortcuts" toggle on `/account`** (the section v42 prepared). Off disables every
single-character shortcut. Tab, arrow keys inside lists, Enter and Esc keep working. Store it
per user server-side (on the `users` row or the per-user settings that already exist for
retention), so it follows the user across devices. Default: **on**.

## Out of scope

- User-customisable key bindings.
- Vim-style counts or multi-select.

## Done when

- [ ] **Every journey completed without the mouse**, as a single keyboard-only e2e spec per
      journey (v37 harness, `page.keyboard` only, no `click()`): log in; submit a URL; find a job
      via `/`; expand it; move into its tracks; retry a waiting track; download a completed file
      (checksum); cancel through the confirmation; archive and unarchive; switch scope and toggle
      filters and sort; load more; visit every route via `g` chords; change a setting on
      `/settings` (admin) and `/account`; run `/library`'s sweep through its confirmation; log out.
- [ ] Roving tabindex: the job list is exactly one Tab stop (an e2e assertion counting Tab presses
      across the list).
- [ ] Shortcuts are inert while typing in the search, URL, priority and settings inputs (e2e:
      typing `j`, `x` and `?` into each changes only the input).
- [ ] Browser chords are untouched: Ctrl+F, Ctrl+L and Cmd+K-style chords reach the browser
      (manual check recorded).
- [ ] Focus restoration, each with its own e2e assertion: after cancel or archive removes the
      focused row, after load more, after an SSE patch of the focused row, after closing the help
      overlay or a confirmation, and after a route change.
- [ ] The shortcut toggle off disables single-key shortcuts while Tab, arrows, Enter and Esc still
      work. The setting persists across a reload and a second browser for the same user. The
      backend stores it owner-scoped (pytest), and another user's setting is unaffected.
- [ ] The help overlay lists exactly the registry's bindings, filtered by admin and route (e2e
      compares them). It was designed through impeccable (output recorded, plus a screenshot).
- [ ] The skip link works (e2e), and the focus ring stays visible on every newly focusable element
      (impeccable `audit`, plus a screenshot of the roving focus on a row).
- [ ] Screen-reader sanity: rows announce name and expanded state (accessibility-tree snapshot).
      No `aria-hidden` focusable elements.
- [ ] Cross-user: the shortcut preference endpoint is covered by `test_ownership.py`.
- [ ] `pytest`, `npm run lint`, `npm run check`, `npm run build` and `npm run test:e2e` pass. Both
      version files read `4.44.0`. `uv lock` is in sync. `graphify update .` has been run.
