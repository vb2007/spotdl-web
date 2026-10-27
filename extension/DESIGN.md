---
name: spotdl-web Firefox extension
description: A guest icon inside Spotify's interface, and two small pages from the app's instrument rack.
colors:
  spotify-glyph-grey: "#b3b3b3"
  spotify-white: "#ffffff"
  spotify-green: "#1ed760"
  spotify-error-rose: "#f3727f"
  spotify-menu-surface: "#282828"
  spotify-toast-surface: "#333333"
  bg-0: "#0a0c0e"
  bg-1: "#191e23"
  bg-2: "#1c2227"
  bg-3: "#262e34"
  line: "#2b3339"
  line-bright: "#3a444c"
  line-control: "#6a757e"
  text-primary: "#e8ecee"
  text-muted: "#8b969d"
  text-dim: "#808b94"
  settled: "#5ad1a8"
  fail: "#e5595c"
  focus-ring: "#ffd479"
typography:
  spotify-menu:
    fontFamily: "inherit"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.4
  spotify-menu-heading:
    fontFamily: "inherit"
    fontSize: "12px"
    fontWeight: 700
  wordmark:
    fontFamily: "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
    fontSize: "1.0625rem"
    fontWeight: 600
    letterSpacing: "0.01em"
  body:
    fontFamily: "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "0.9375rem"
    lineHeight: 1.5
  body-small:
    fontFamily: "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "0.875rem"
  control:
    fontFamily: "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
    fontSize: "0.8125rem"
    fontWeight: 500
  label:
    fontFamily: "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
    fontSize: "0.6875rem"
    fontWeight: 500
    letterSpacing: "0.12em"
rounded:
  menu-item: "2px"
  menu: "4px"
  control: "4px"
  panel: "6px"
  toast: "6px"
  icon: "50%"
spacing:
  space-1: "0.25rem"
  space-2: "0.5rem"
  space-3: "0.75rem"
  space-4: "1rem"
  space-5: "1.5rem"
  space-6: "2rem"
components:
  spotify-icon:
    textColor: "{colors.spotify-glyph-grey}"
    rounded: "{rounded.icon}"
    size: "32px"
  spotify-icon-hover:
    textColor: "{colors.spotify-white}"
  spotify-icon-done:
    textColor: "{colors.spotify-green}"
  spotify-icon-error:
    textColor: "{colors.spotify-error-rose}"
  spotify-icon-header:
    size: "48px"
  spotify-menu:
    backgroundColor: "{colors.spotify-menu-surface}"
    typography: "{typography.spotify-menu}"
    rounded: "{rounded.menu}"
    padding: "4px"
  spotify-menu-item:
    rounded: "{rounded.menu-item}"
    padding: "10px 12px"
    height: "40px"
  spotify-toast:
    backgroundColor: "{colors.spotify-toast-surface}"
    textColor: "{colors.spotify-white}"
    typography: "{typography.spotify-menu}"
    rounded: "{rounded.toast}"
    padding: "10px 14px"
  page-panel:
    backgroundColor: "{colors.bg-1}"
    rounded: "{rounded.panel}"
    padding: "1rem 1.5rem 1.5rem"
  page-button:
    backgroundColor: "{colors.bg-2}"
    textColor: "{colors.text-primary}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "0.25rem 0.75rem"
    height: "1.875rem"
  page-button-hover:
    backgroundColor: "{colors.bg-3}"
  page-button-quiet:
    textColor: "{colors.text-muted}"
    typography: "{typography.control}"
  page-input:
    backgroundColor: "{colors.bg-0}"
    textColor: "{colors.text-primary}"
    typography: "{typography.control}"
    rounded: "{rounded.control}"
    padding: "0.375rem 0.625rem"
    height: "2.25rem"
---

# Design System: spotdl-web Firefox extension

## Overview

**Creative North Star: "The Polite Guest and the Spare Panel"**

The extension has two worlds and never mixes them. On open.spotify.com it is a guest: one small glyph per track row, album card and page header, drawn in Spotify's own idiom (subdued grey that brightens to white, Spotify's green for done, Spotify's context-menu surface) so it reads as a native control, not an overlay. Nothing of the app's look (no amber, no Plex, no panels) appears on Spotify's page. Its own pages, the options page and the toolbar popup, are a different matter: they are one more panel pulled from the app's instrument rack (`frontend/src/DESIGN.md`), whose tokens are copied by value into `shared/page.css`.

Both worlds share one glyph: an arrow landing on a three-bar spectrum, the app's scope reduced to 16px of 1.5px strokes. Every visible string comes from `browser.i18n` (`_locales/en`, `_locales/hu`); no copy is hard-coded in markup or script.

**Key Characteristics:**
- In-page UI borrows Spotify's palette and inherits Spotify's font (`font-family: inherit`).
- Extension pages are the app's dark well: `bg-0` page, `bg-1` panels on hairline borders, mono labels and controls, sans prose.
- Stroked line glyphs only (`fill: none`, `stroke: currentColor`, round caps); state is a glyph swap plus a colour.
- Flat everywhere except the floating in-page layers (menu, toast, card disc), which lift with soft black shadows.
- Fully keyboard-operable, no AltGr anywhere.

## Colors

Two closed palettes: Spotify's neutrals and signals for the in-page guest, the app's cool-dark instrument palette for the extension's own pages.

### Primary
- **Spotify Green** (spotify-green): the in-page done state, on the icon (queued, already queued, in library) and on the toast's tick.
- **Settled Green** (settled): the extension pages' "the link works" status dot and an "ok" outcome in the popup's recent list. It is the app's settled colour, not Spotify's.

### Secondary
- **Spotify Error Rose** (spotify-error-rose): the in-page error state on the icon and the toast's circled "!".
- **Fail Red** (fail): the pages' broken-link status dot and an error outcome in the popup.

### Neutral
- **Spotify Glyph Grey** (spotify-glyph-grey): the idle icon and the menu heading.
- **Spotify White** (spotify-white): hover, focus and pressed icon; toast text; menu text at 90% opacity, full white on the hovered item.
- **Spotify Menu Surface** (spotify-menu-surface): the cascade menu. **Toast Surface** (spotify-toast-surface): one step lighter, for the toast.
- **Well / Panel / Control / Raised** (bg-0, bg-1, bg-2, bg-3): page background and input fill; panels; buttons; button hover and the popup's hovered row (bg-1).
- **Hairline / Bright Line / Control Line** (line, line-bright, line-control): panel and list dividers; the neutral (unknown) status dot; button and input borders.
- **Primary / Muted / Dim Text** (text-primary, text-muted, text-dim): readings; prose and field labels; uppercase section labels, placeholders and disabled buttons.

### Named Rules
**The Two Worlds Rule.** Spotify's colours never appear on the extension pages, and the app's tokens never appear on open.spotify.com. The in-page CSS writes Spotify's values literally; the pages use only `page.css` custom properties.

**The Amber-Is-Focus-Only Rule.** On the extension pages `focus-ring` (amber) is the keyboard focus outline and nothing else. Status uses green and red dots. In the app, amber means live state, and the extension has no live state to show.

## Typography

**Body Font:** IBM Plex Sans (with -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif)
**Label/Mono Font:** IBM Plex Mono (with ui-monospace, SF Mono, Menlo, Consolas, monospace)
**In-page:** inherits Spotify's own font.

**Character:** On the pages, mono carries anything that names or operates (wordmark, labels, buttons, inputs) and sans carries sentences. No fonts are bundled: Plex shows up where it's installed, otherwise the app's fallbacks.

### Hierarchy
- **Wordmark** (600, 1.0625rem, mono, 0.01em): the "spotdl-web" masthead on both pages. It is the only heading-sized text.
- **Body** (400, 0.9375rem, 1.5): page prose, capped at 60–65ch on the options page.
- **Body small** (0.875rem): status lines, recent-item titles, the empty state. Meta, reasons and hints go to 0.75–0.8125rem in muted text.
- **Control** (500, 0.8125rem, mono): every button. Inputs are mono at 0.875rem.
- **Label** (500, 0.6875rem, mono, 0.12em, uppercase, dim): section headings ("App", "Connection", "Recent"), marked up as real `h1`/`h2`.
- **In-page menu** (400, 14px, 1.4) with a 12px/700 grey heading; the toast uses the same 14px/1.4.

### Named Rules
**The Mono Names, Sans Explains Rule.** If it's a label, a control or a value, set it in mono. If it's a sentence, set it in sans.

## Layout

The options page is a single centred column (`min(40rem, 100% - 2rem)`, `space-6` top margin) of panels stacked at `space-4`. Inside a panel, rows are wrapping flex lines: a field grows from an 18rem basis and the save/clear actions sit at its baseline. The popup is a fixed 22rem strip with `space-4` padding: header (wordmark plus status) over a hairline, the recent list with hairlines between rows, then a footer of two actions pushed apart. Spacing uses the app's 4px-based `space-1`..`space-6` steps.

In-page, the icon goes where Spotify puts its own controls: in a row's trailing cell (8px before "More options"), after a header's actions (8px gap), and pinned 12px from the top-right corner of a card's cover. The menu and toast are `position: fixed` and kept 8px inside the viewport. The menu opens 4px below its icon, or above it when there's no room. The toast is centred over its icon with an 8px gap (below it if there's no room above). If the icon has been re-rendered away, the toast docks at the bottom centre, 104px up, clear of the player bar.

## Elevation & Depth

The extension pages are flat: depth comes from tonal steps (bg-0 well, bg-1 panel, bg-2 control, bg-3 hover) and 1px hairlines, with no shadows. In-page, only the layers that float over Spotify cast shadows, and they use black at Spotify-like strengths.

### Shadow Vocabulary
- **Menu lift** (`box-shadow: 0 16px 24px rgba(0,0,0,0.3), 0 6px 8px rgba(0,0,0,0.2)`): the cascade menu.
- **Toast lift** (`box-shadow: 0 8px 24px rgba(0,0,0,0.5)`): the toast.
- **Card disc** (`box-shadow: 0 4px 12px rgba(0,0,0,0.35)`): the icon's dark disc over cover art.

### Named Rules
**The Topmost Layer Rule.** The menu and the toast sit at `z-index: 2147483647` so they stay above Spotify's own overlays, its cookie banner included. Nothing else in-page takes a z-index beyond the card icon's local `2`.

## Shapes

The icon is always a circle (50%), whether it sits bare in a row or header or on a disc on a card. Menus and controls have small 4px corners, and menu items 2px. Panels and the toast use 6px. Status dots are 0.5rem circles. Glyphs are 1.5px round-capped strokes in a 16px box (1.25px at the header's 28px size, 1.75px in the toast).

## Components

### In-page icon (signature)
Quiet until wanted.
- **Sizes:** row and card 32px, header 48px (glyph 28px), all circular, transparent at rest.
- **Visibility:** `opacity: 0` until its row or card is hovered or holds focus. Always shown on a page header, and always once it carries a non-idle state or its menu is open.
- **States:** idle grey arrow-on-spectrum; hover white with a 1.04 scale; `sending` a spinning arc (800ms, static at 60% opacity under reduced motion); done = green tick; error = rose circled "!". A cascade or error state reverts to idle after 3s.
- **Card variant:** white glyph on a `rgba(0,0,0,0.6)` disc (0.8 on hover) so it reads over any artwork.
- **Opener semantics:** `aria-haspopup="menu"`. While open, `aria-expanded="true"` keeps it visible and pressed (white glyph on a 10% white wash, or a 0.85 black disc on cards).
- **Focus:** a 2px white outline at a 1px offset.

### Cascade menu
Spotify's context menu.
- 200–320px wide, 4px padding, scrolls within the viewport. Its heading (grey glyph plus label) is `aria-hidden` and the menu carries its own `aria-label`.
- **Items:** at least 40px tall. Hover or focus gives a 10% white wash with white text, and keyboard focus adds a 2px inset white ring.
- **Keyboard:** Shift+F10 or the Menu key opens it from a focused icon (never with Ctrl/Alt/Meta, never under AltGr). Arrows (wrapping), Home and End move; Enter or Space chooses; Esc or Tab closes and returns focus to the icon.

### Toast
Says what the app answered, then gets out of the way.
- Non-modal and `pointer-events: none`. `role="status"`, or `role="alert"` for errors. One at a time, gone after 4.5s.
- A 16px tick (green) or circled "!" (rose), then the sentence. It enters with a 4px rise over 160ms.
- **Never shows the app's address:** the page's own scripts can read the toast's DOM.

### Page panel
- bg-1 on a 1px `line` border, 6px corners, padding `space-4 space-5 space-5`. A label heading leads each panel.

### Buttons
- **Default:** mono 0.8125rem/500 on bg-2 with a 1px `line-control` border, 4px corners, 1.875rem minimum height; bg-3 on hover. Disabled text goes dim.
- **Quiet:** borderless and transparent in muted text, gaining bg-2 and primary text on hover. Used for the secondary action (reset, clear, settings).
- **Focus (all page elements):** a 2px amber `focus-ring` outline at a 2px offset.

### Inputs
- Full width, 2.25rem minimum height, bg-0 well, 1px `line-control` border, 4px corners, mono 0.875rem; dim placeholder.

### Status line
- An 0.5rem dot in front of a sentence in muted 0.875rem text. The dot is green (`settled`) when the link works, red (`fail`) when it's broken, and `line-bright` when unknown. In the ok tone the sentence turns primary. It collapses when empty, and every instance is `role="status"`.

### Popup recent row
- A whole-row link (bleeds `space-2` either side, 4px corners, bg-1 on hover) holding a truncated single-line title over a meta line. The outcome word in the meta is tinted `settled` or `fail`.

## Do's and Don'ts

### Do:
- **Do** write Spotify's literal values in `content/content.css` and `page.css` custom properties everywhere else (The Two Worlds Rule).
- **Do** scope every in-page rule to a `spotdl-ext-` class or the `data-spotdl-host` attribute, so nothing touches Spotify's elements.
- **Do** pair every state colour with a distinct glyph (tick, circled "!", spinning arc), so state never depends on colour alone.
- **Do** keep every new in-page control reachable by Tab and every action reachable without AltGr.
- **Do** source every string from `_locales/en` and `_locales/hu` through `browser.i18n`.
- **Do** honour `prefers-reduced-motion`: no spin, no toast rise, no transitions.

### Don't:
- **Don't** use amber, Plex, or any app token on open.spotify.com.
- **Don't** use amber on the extension pages for anything but the focus ring.
- **Don't** put the app's address (or anything else private) in in-page DOM such as the toast or menu.
- **Don't** make the toast modal or clickable, or let it hold focus.
- **Don't** bundle fonts into the extension.
- **Don't** add shadows to the extension pages. Depth there is tonal.
