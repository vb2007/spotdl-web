# The Firefox extension

`extension/` holds spotdl-web's Firefox extension (v58). It puts a download icon next to tracks,
albums, artists and playlists on `open.spotify.com`; a click sends that item straight into your
spotdl-web queue, and a right-click offers the item's album or artist instead. It's Firefox only,
Manifest V3, and has its own version (`extension/manifest.json`), separate from the app's.

Since v61 it's released as an **AMO-signed, unlisted** XPI: addons.mozilla.org signs it, but
never lists it, so it's installed from this repository's GitHub releases and updates itself from
there.

## Install

Firefox 153 (the current ESR) or newer, any release channel.

1. Open the newest `extension-v<version>` release on
   [the releases page](https://github.com/vb2007/spotdl-web/releases) (it's never the one marked
   *Latest*: that badge is the app's) and click its `spotdl-web-<version>.xpi`.
2. Firefox asks to install *spotdl-web*: confirm, and allow what it asks for (below).

It's a permanent install: it survives restarts, and `about:addons` lists it like any other
add-on. Then set it up (next section).

### Updates

The manifest's `update_url` is
`https://github.com/vb2007/spotdl-web/releases/download/extension-updates/updates.json`: the
fixed `extension-updates` release, which always carries the newest update manifest. Firefox
checks it on its own, about once a day, and installs a newer version without asking (unless it
asks for new permissions). To check at once: `about:addons` → the gear → *Check for Updates*.

The update manifest lists every released version, its XPI's sha256 and the oldest Firefox it
needs; Firefox installs the newest one it meets. Don't delete the `extension-updates` release or
its `updates.json`: an installed copy only ever reads the `update_url` it was installed with.

### Temporary, unsigned (development)

- **From the source tree:** `about:debugging#/runtime/this-firefox` → *Load Temporary Add-on…* →
  pick `extension/manifest.json`. It stays until Firefox restarts.
- **With web-ext:** `cd extension && npm ci && npm start` opens a fresh Firefox profile with the
  extension loaded (`web-ext run`; add `-- --firefox=/path/to/firefox` for another binary).

Firefox may ask to let the extension reach `open.spotify.com` and the app. Both are needed: the
first for the icons, the second to send anything.

## Set it up

Open the extension's settings (the toolbar popup's *settings*, or `about:addons` → spotdl-web →
*Preferences*):

| Setting | What it does |
|---|---|
| **App address** | Where your spotdl-web runs. Default `https://spotdl.vb2007.hu`. Any `https://` address works; plain `http://` only on `localhost`/`127.0.0.1` (a dev or agent stack). Saving another address asks Firefox for access to that host (the default's is declared up front). The address is checked with `GET /api/auth/me` first, and saved only if it answers like a spotdl app (signed in or not). |
| **API key** (optional) | A key from the app's `/account` page (*Browser extension keys*). Checked on its own (no cookie) against the *saved* app address before it's kept, so save the address first. Kept in `storage.local` only, never synced, and tied to the app address it was saved for: it's never sent anywhere else, and saving another address removes it. |
| **Connection** | *test connection* says who you're signed in as, and whether through your browser sign-in or the key. |
| **open.spotify.com** | Whether the extension may add its icons there, with a button to allow it. |

## How it signs in

1. **Your sign-in first.** The background script calls the app with `credentials: 'include'`, so
   if you're logged in to spotdl-web in the same Firefox, that session is used. v53's spike
   showed this works (`docs/GOTCHAS.md`, v53): over HTTPS and over loopback HTTP, with Total
   Cookie Protection on or off. Nothing to set up.
2. **The key, if the sign-in doesn't reach.** On a `401`, and only if a key is saved, the same
   request is sent again with `Authorization: Bearer <key>` and no cookie. That covers a private
   window, cookies cleared on close, or a browser where you never log in to the app.
3. **Neither:** the toast says *Log in to spotdl in this browser, or add an API key*, and the
   settings open.

Every request carries `X-Spotdl-Client: extension/<version>`, so the app applies its Spotify-link
allowlist (v53): only `open.spotify.com` track, album, artist and playlist links are accepted.
A key can only queue such links, read its own jobs and say whose it is. It never opens an admin
page, even when its user is an admin.

## Using it

- **The icon** sits beside a tracklist row's *More options* button (album, playlist, artist top
  tracks, search songs), in an album, artist or playlist page's action bar, and in the corner of
  album, artist and playlist cards (shelves, search, the top result). Rows and cards show it on
  hover or keyboard focus; page headers always do. It's a real button: Tab reaches it.
- **Click** (or Enter/Space) queues that item. Only your own input on the icon counts: a page
  script's synthetic click or key, a click forwarded from elsewhere, or your Enter typed into
  another field while a script moves focus onto an icon, all queue nothing.
- **Right-click**, **Shift+F10** or the **Menu key** opens the cascade menu:
  - a track: *This track · Whole album · Whole artist*;
  - an album: *This album · Whole artist*;
  - an artist or a playlist: *Download*.

  Arrow keys move, Home/End jump, Enter picks, Esc or Tab closes it and returns focus to the
  icon. Nothing needs AltGr, and an AltGr chord (Ctrl+Alt) never opens it.
- **More than one artist:** *Whole artist* on such a track asks the app, which answers with the
  candidates (v53's `409 cascade_ambiguous`). The menu then asks *Which artist?*.
- **What the toast says:**

  | Toast | Meaning |
  |---|---|
  | Queued in spotdl | A new job. The icon keeps its tick while you're on the page. |
  | Already in your queue | You have an unfinished job for that link. The app returned it, and nothing new was made. |
  | Already in the library | The track is in the shared library: the job resolves at once, nothing is downloaded. |
  | Too many submissions. Try again in N s | The app's per-user rate limit. |
  | Your spotdl app had an error | The app itself answered with a crash (a plain 500). |
  | Can't reach your spotdl app | The app's address doesn't answer, or answers with a proxy's error page (the app or its tunnel is down). The settings name the address; the page never sees it. |
  | Log in to spotdl… / the API key was refused | See "How it signs in". The settings open. |

- **The popup** (toolbar button) shows the connection's state and your last 10 submissions, with
  what the app answered. It reads them from local storage and asks the app nothing per row.

## Privacy

The extension talks to one host, the app address you configured. It sends only the item's
canonical link (`https://open.spotify.com/<type>/<id>`) and the cascade choice. Titles shown in
the popup are read from the page and stay in the browser. There's no analytics and no other
host. A network capture of v58's real run (every HTTP request Firefox made, tagged with the
principal that made it) found the extension contacting only the configured app origin.

## Not covered

- **The now-playing bar.** Spotify shows a track there only when you're logged in to Spotify. The
  owner uses Spotify logged out, so v58 skips it. The owner may revisit this if other users ask
  for it (`plan/master-v5/00-master-plan.md`, Amendments).
- The Spotify desktop app (not a web page), and Chrome.

## Cutting an extension release

1. Change `extension/` as needed, and raise `extension/manifest.json`'s `version` (its own semver,
   independent of the app's). CI's `version` job refuses a PR that touches `extension/` without
   raising it above `main`'s, and a PR that touches only `extension/` needs no app bump.
2. Merge. The merge's "Release & Deploy" run (`docs/RELEASE_PIPELINE.md`) finds the version
   above every released one, and its `extension-release` job (`.github/workflows/extension-release.yml`):
   - signs it on AMO, unlisted (`web-ext sign --channel unlisted`, `npm run sign`), waiting for
     AMO's automatic signing;
   - checks the XPI carries Mozilla's signature and the right version;
   - creates the `extension-v<version>` release with `spotdl-web-<version>.xpi` and
     `updates.json`, never marked *Latest*;
   - puts the new `updates.json` on the fixed `extension-updates` release, which installed copies
     read.

   A merge that doesn't raise the version runs no extension job at all.

**Credentials.** Signing needs AMO API credentials as two repository secrets, `AMO_JWT_ISSUER`
and `AMO_JWT_SECRET` (addons.mozilla.org → Developer Hub → *Manage API Keys*: the JWT issuer and
JWT secret). Without them the job fails, naming the missing secret, and the run's Matrix notice
names `extension-release`. Nothing is released then: Firefox installs only a signed XPI.

**Re-running.** AMO never takes the same version twice. A run that failed after AMO signed the
version (the GitHub release failed, say) re-runs fine (`gh run rerun <id> --failed`): the job
finds the version already on AMO and downloads its signed file instead of signing again. A
version already released is a successful no-op that only makes sure `updates.json` lists it.

**By hand.** *Actions* → *Extension Release* → *Run workflow* releases the chosen ref's version,
the same way. From a branch, that's an unmerged build every installed copy will update to; the
run says so.

## Development

```bash
cd extension
npm ci
npm test        # node:test: fixtures, background client, _locales parity, manifest
npm run lint    # web-ext lint --self-hosted (CI's `extension` job runs it, the parity check and the tests)
npm start       # web-ext run
```

`--self-hosted` because `update_url` is allowed only on an add-on AMO doesn't host; the linter
refuses it otherwise.

- **Selectors** live in `content/selectors.js` alone. They use `data-testid`, `data-encore-id` and
  ARIA, never class names. An item's identity is always a `/track/`, `/album/`, `/artist/` or
  `/playlist/` link (or the page's address, for a header), never text. When Spotify changes its
  markup, a target stops getting an icon, and nothing breaks on the page.
- **Fixtures** (`test/fixtures/`) are sanitized captures of real `open.spotify.com` pages. Their
  README says how to recapture them.
- **Structure:** `content/` (classic scripts sharing one global: `selectors.js`, `inject.js`,
  `main.js`, `content.css`); `background/` (the only network client); `options/` and `popup/`;
  `shared/` (settings, i18n helper, page styles); `_locales/{en,hu}` (`npm test` checks key and
  placeholder parity, and that every key used exists).
