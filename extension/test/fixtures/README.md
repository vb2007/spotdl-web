# open.spotify.com fixtures

Sanitized captures of real `open.spotify.com` pages, which `test/content.test.js` runs the content
scripts over. They were captured on 2026-10-26 in Firefox 158, signed out of Spotify, in English:

| File | Page | What it exercises |
|---|---|---|
| `album.html` | `/album/4aawyAB9vmqN3uQ7FjRGTy` (Pitbull, *Global Warming*) | header, 18 tracklist rows (multi-artist tracks), "More by" album cards |
| `playlist.html` | `/playlist/37i9dQZF1DXcBWIGoYBM5M` (*Today's Top Hits*) | header, 25 rendered rows of a virtualized list (no cards) |
| `artist.html` | `/artist/4tZwfgrHOc3mvqYlEYSvVi` (Daft Punk) | header, top-track rows, album/playlist/artist cards, 10 music-video cards (no icon) |
| `search.html` | `/search/daft%20punk` | search rows (no `internal-track-link`), the top-result card, show/episode/genre/profile cards (no icon) |
| `home.html` | `/` | home shelves of album, artist and playlist cards |

There's no now-playing fixture: Spotify shows a track there only when you're logged in, and the
now-playing bar isn't a v58 target (`docs/EXTENSION.md`, "Not covered").

## Recapturing one

When Spotify changes its markup and a test (or the real page) loses icons:

1. Open the page in Firefox, signed out of Spotify. Dismiss the cookie banner, and scroll once
   so the lazy shelves render.
2. In the console: `copy(document.documentElement.outerHTML)`, and paste it into a scratch
   file outside the repo, e.g. `/tmp/album.raw.html`. A capture taken with the extension installed
   is fine: the sanitizer removes its icons, menu and toast.
3. Sanitize it into place, giving the page's address:

   ```bash
   cd extension
   node test/fixtures/sanitize.mjs /tmp/album.raw.html test/fixtures/album.html \
     https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy
   ```

   It keeps the tags, `data-testid`, `data-encore-id`, `role`, `aria-*`, `href`, `dir`, `tabindex`,
   `type`, `id` and visible text. It drops scripts, styles, class names, inline styles, image
   sources, SVG paths, the language picker, and every query string but Spotify's own
   `?highlight=`. Check the result has nothing personal before committing (`grep -i token`, `@`).
4. Update the counts in `test/content.test.js`'s `EXPECTED` to what the new page really shows,
   counted by hand, not from the code under test. Then fix `content/selectors.js` until they
   match.
