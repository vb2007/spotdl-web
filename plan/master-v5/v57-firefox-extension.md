# v57 — Firefox Extension

Branch: `dev-firefox-extension` → PR into `main`
Version: **app version not bumped** (the slice touches only `extension/`, plus docs). The
extension's own version starts at `1.0.0` in `extension/manifest.json`.
Wave / slot: 2 / 4
Depends on: v52 (API keys, `/api/auth/me`, cascades, allowlist, the cookie spike verdict)

## Scope

The owner keeps Spotify and the app in split tabs and copy-pastes URLs between them. This
version builds a small, functional **Firefox extension** in this repo:

- It puts a **download icon next to tracks, albums, artists and playlists** on
  `open.spotify.com`. Clicking it sends that item straight into the spotdl queue.
- **Right-clicking the icon** (or its keyboard equivalent) opens a menu with **cascades**: a track
  offers *this track / whole album / whole artist*; an album offers *this album / whole artist*.

Signing and distribution are v60. This slice ships an extension that runs unsigned via
`web-ext run` / `about:debugging`.

## Design

- **Manifest V3, Firefox only.**
  - `browser_specific_settings.gecko.id` pinned (e.g. `spotdl-web@vb2007.hu`), with
    `strict_min_version` set to the current ESR.
  - Permissions: `storage`. `host_permissions` holds `https://open.spotify.com/*` plus the
    configured app origin, requested at runtime from the options page via
    `permissions.request` for a non-default origin.
  - No `<all_urls>`.
- **Plain JS (ES modules) or TypeScript compiled by a tiny build.** Pick the lighter one, but keep
  `web-ext lint` clean. No framework. The bundle stays small.
- **Content script** (`open.spotify.com`):
  - A **MutationObserver** over the SPA (Spotify re-renders constantly), debounced, idempotent: an
    element gets at most one icon, marked with a data attribute.
  - **Targets:**
    - tracklist rows (album, playlist, artist top tracks, search results);
    - album, artist and playlist page headers;
    - album, artist and playlist cards in shelves and search;
    - the now-playing bar's track.
  - **Identity** comes from the nearest `/track/`, `/album/`, `/artist/`, `/playlist/` link (or
    the page URL for headers), never from text.
  - Selectors are isolated in one `selectors.js`, built on `data-testid`/ARIA attributes wherever
    they exist. **A selector miss degrades to "no icon", never a thrown error.**
  - **The icon** is a real `<button>` with an `aria-label` (en/hu), sized and coloured to sit
    quietly in Spotify's UI (a small spotdl glyph), and visible on hover/focus of the row plus
    always on headers. Tab-reachable.
  - **States:** idle → sending → queued ✓ / already queued / in library / error. These map v52's
    `hint`s and error codes to localized text, shown in a small non-modal toast near the icon.
  - **Cascade menu:** on `contextmenu` over the icon, `preventDefault` and show an in-page menu
    (`role="menu"`, arrow keys, Enter, Esc, focus returns to the icon).
    - **Keyboard equivalents:** the Menu key / Shift+F10 on the focused icon. Shortcut rules
      follow Hungarian QWERTZ, with no AltGr.
    - **Options per type:**
      - track: this track · whole album · whole artist;
      - album: this album · whole artist;
      - artist and playlist: just "download".
    - Multi-artist → v52's 409 candidates → a submenu to pick the artist.
- **Background script:** owns all network I/O. Content scripts message it, and never fetch the app
  directly (page CORS would apply).
  1. **Cookie first:** `fetch(appOrigin + '/api/jobs', {method:'POST', credentials:'include',
     headers:{'Content-Type':'application/json','X-Spotdl-Client':'extension/<ver>'}, body})`.
  2. On 401: if a key is stored, retry with `Authorization: Bearer`. Otherwise the toast says
     "Log in to spotdl in this browser, or add an API key" and opens the options page.
  3. The approach follows v52's spike verdict. If cookies proved not to flow, skip step 1
     entirely, and say so in the options page copy.
- **Options page:**
  - App URL (default `https://spotdl.vb2007.hu`, validated by `GET /api/auth/me`);
  - API key (optional, stored in `storage.local`, never synced);
  - a "Test connection" button showing who you're signed in as and via cookie or key.
- **Popup:** the last 10 submissions (title, type, status, link to the app), plus the connection
  status.
- **i18n:** `_locales/en` and `_locales/hu` (`default_locale: en`), following the browser UI
  language. Every user-visible string comes from `browser.i18n`. A key-parity check runs in the
  extension's test script.
- **Privacy:** the extension sends only the item URL (and the cascade choice) to the configured
  app origin. No analytics, and no other host.

## Tests

- **Unit tests** (vitest + jsdom, or node's test runner) run over **captured, sanitized
  `open.spotify.com` DOM fixtures**:
  - one per page type: album, playlist, artist, search, home shelves, the now-playing bar;
  - they assert icon placement count, identity extraction and idempotence under re-render.
  - Save the fixtures under `extension/test/fixtures/`, with a README on how to recapture them.
- **Background tests:** cookie → key fallback, error-code mapping, allowlist rejection display.
- **`web-ext lint`** is clean.

## Files owned

`extension/**` (new), `docs/EXTENSION.md` (new: install via `about:debugging`, options, how auth
works), message JSONs: none (the extension has its own `_locales`).

## Out of scope

- Signing, the XPI release, auto-update and CI jobs (v60).
- Chrome support.
- Any backend change: if the contract is missing something, stop and raise it. v52 owns it.
- Spotify desktop app (not a browser page).

## Done when

- [ ] **Real Firefox, real `open.spotify.com`** (`web-ext run` with a fresh profile against the
      slot stack, logged in to the app):
  - icons appear on each target type (tracklist row, album/artist/playlist header, a card of
    each type, the now-playing bar), each shown in a screenshot;
  - each click queues the right job (the slot app's jobs list, plus API output).
- [ ] **Cascades in that real run:**
  - track → whole album and track → whole artist (single-artist);
  - a multi-artist track → candidate submenu → the chosen artist;
  - album → artist.

  Each one creates the expected job.
- [ ] **Keyboard-only:** Tab to an icon, Enter queues it, and Menu/Shift+F10 opens the cascade
      menu, which arrows, Enter and Esc operate (screen recording or a step log). No AltGr is
      needed on Hungarian QWERTZ.
- [ ] **Auth:**
  - the cookie path works when logged in, if v52's spike said cookies flow (shown);
  - after logging out of the app, a click asks for login or a key;
  - with a key set, the same click succeeds via Bearer (the app's key `last_used_at` advances).
- [ ] **Hints and errors render localized:** already queued, in library, rate limited, and the
      app unreachable (each screenshot, en and hu).
- [ ] **Resilience:** fixture tests pass. Removing a selector's match from a fixture yields zero
      icons and no console error (test). Navigating within the SPA (album → artist → search)
      keeps icons correct, with no duplicates (real run).
- [ ] `web-ext lint` is clean. The extension test script, including the `_locales` key-parity
      check, passes.
- [ ] Privacy: a network capture during the real run shows the extension contacting only the app
      origin.
- [ ] `docs/EXTENSION.md` is written. A GOTCHAS v57 entry (selectors, cookie behavior). `graphify
      update .` has been run. The app version is **unchanged** (`check_version.py` passes with no
      bump, since only `extension/` and `docs/` changed).
