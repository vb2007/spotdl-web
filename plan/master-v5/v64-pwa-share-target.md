# v64 — Installable PWA & Share Target

Branch: `dev-pwa-share-target` → PR into `main`
Version: `5.64.0`
Wave / slot: 4 / 3
Depends on: v52 (Spotify URL allowlist and normalization), waves 0–3 merged

## Scope

The extension (v57) solves split-tab copy-paste on desktop Firefox. On a **phone**, the same
friction is sharing a song from the Spotify app. This version makes spotdl-web an **installable
PWA** with a **Web Share Target**: Spotify app → Share → spotdl → queued.

## Design

- **Manifest** (`frontend/static/manifest.webmanifest`):
  - name, short_name, icons (reuse v45.1's favicon art, 192/512 plus maskable);
  - `display: standalone`, theme/background colors from the design tokens, `start_url: /`,
    `scope: /`.
  - `share_target`: `{ action: "/share", method: "GET", params: { title: "title", text: "text",
    url: "url" } }`. GET, so no service-worker POST handling is needed. The Spotify app often puts
    the link in `text`, so read all three.
- **Service worker:** minimal, via SvelteKit's `src/service-worker.ts`.
  - Caches the static app shell only, for an installability and offline notice.
  - **Never caches `/api/`**, so live data and auth always go to the network.
  - Versioned by the build, so an update is picked up on the next load.
  - nginx serves `service-worker.js` with `Cache-Control: no-cache`.
- **`/share` route:**
  - New route with the SvelteKit `ssr`/`prerender` exports **and** its own nginx `location` (the
    CLAUDE.md invariant).
  - Extracts the first Spotify URL from `url`, `text` or `title`, normalized with the same rules
    as v52's allowlist (reuse the server's validation by submitting; the client only extracts).
  - **Logged in:** shows what will be queued (type and id) with "Queue it" focused, so a single tap
    or Enter confirms. **No silent auto-submit**: a share is user-initiated, but one confirm
    prevents accidental queues. On success, a toast and a link to the job.
  - **Not logged in:** goes to `/login?next=/share?...`. The share parameters survive the
    round-trip, and `next` is validated to be a same-origin relative path (no open redirect).
  - **No Spotify URL found:** a clear en/hu message, and no job created.
- **Install affordance:** a discreet "install app" entry on `/account` when `beforeinstallprompt`
  is available (Chromium/Android). On Firefox Android and iOS, a one-line hint, since those
  browsers don't fire it.
- **Design:** `/share` and the install entry go through impeccable (Operate mode, mobile-first),
  en/hu, keyboard-complete.

## Files owned

New `frontend/static/manifest.webmanifest` and icons, new `frontend/src/service-worker.ts`,
`frontend/src/app.html` (manifest link and theme-color), new `frontend/src/routes/share/+page.svelte`
and `+page.ts`, `frontend/src/routes/login/+page.svelte` (`next` handling only),
`frontend/src/routes/account/+page.svelte` (install entry only; v65 touches account too, so keep
blocks separate), `frontend/nginx.conf` (`/share` location, SW cache header), message JSONs
(hotspot), tests.

## Out of scope

Push notifications (v65 uses the Notification API in-page, not push). Offline queueing of shares.
Native apps.

## Done when

- [ ] Lighthouse (or Chrome devtools' Application → Manifest) reports the app **installable** on
      the nginx build of the slot stack (screenshot), with no manifest errors.
- [ ] **A real phone share:** on an Android phone (Chrome), installed from the slot stack exposed
      via a temporary tunnel, or from production after merge if the owner prefers. Record which.
      Sharing a track from the Spotify app opens `/share`, and confirming queues the job
      (screenshots plus the job in the list). If no device or tunnel is available, emulate with
      the exact share URL Spotify produces (captured from a real share) and say so explicitly.
- [ ] `title`/`text`/`url` variants are each extracted correctly (unit table, using Spotify's real
      share text formats).
- [ ] **Login round-trip:** logged out → share → login → back on `/share` with the item. An
      open-redirect attempt in `next` is refused (e2e).
- [ ] Hard navigation to `/share` on the nginx build works (not a 404).
- [ ] The service worker never serves `/api/`: devtools network shows `/api/*` from the network
      with the SW active, and offline gives the shell plus a notice, not stale data.
- [ ] An update is picked up: build N then N+1, and a reload serves N+1 (the SW version shown).
- [ ] impeccable output and en/hu mobile screenshots recorded. The e2e spec covers `/share`
      logged-in and logged-out.
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass, and `nginx -t` passes.
      Both version files read `5.64.0`. `uv lock` is in sync. `graphify update .` has been run.
