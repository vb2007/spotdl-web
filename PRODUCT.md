# Product

<!-- impeccable:product-schema 1 -->

## Platform

web (an installable PWA since v65), plus a Firefox extension for `open.spotify.com` (v58, v61)

## Users

The project owner plus a small, explicitly allowlisted circle of trusted people (family/friends),
each authenticated via a server-to-server proxied login against the owner's existing
`vb2007.hu-api` account system and checked against an allowlist afterward. Since v69 the admin
manages that allowlist on `/users` (the env's `ALLOWED_EMAILS` only seeded it once); removing an
address signs the person out everywhere at once, and their jobs and files stay. One designated
`ADMIN_EMAIL` account is the operator, always allowed; everyone else is a plain user.

Confirmed (master v2, v16–v22): every allowlisted user gets their own real `users` row and their
own job/track history — `jobs.user_id` scopes ownership, enforced on every list and direct-id
endpoint (non-owner access 404s, never 403, so an id's existence is never confirmed to a
stranger), and the live SSE stream is scoped to a per-user Redis channel. This *is* private data
separation per user, adversarially verified (`backend/tests/test_ownership.py`,
`scripts/verify_separation_sse.sh`) — see `CLAUDE.md`'s "Master v2 invariants". What stays shared
on purpose: the downloaded audio files themselves live in one library, and the dedup ledger is
global — if another user already downloaded a track, yours resolves instantly rather than
re-fetching it. The admin also has an explicit, off-by-default view of everyone's queue, or of
only other users' (`mine | all | others`, v54), for troubleshooting the shared queue/worker.

## Product Purpose

Give a Spotify listener a "fire and forget" way to get real audio files for anything on Spotify
(track, album, playlist, or artist) even when the actual download path (YouTube Music, via spotdl)
is aggressively and repeatedly rate-limited. Success is defined as: every submitted track
eventually gets downloaded, no matter how long it takes — legitimately days — never a fast
response or a "gave up" state.

## Positioning

Unlike running the spotdl CLI directly, or any one-shot download tool, this treats YouTube Music
rate limiting as a permanent, expected condition rather than a failure to report. An infinite
per-track retry ladder, a global circuit breaker, and proxy rotation are all driven off a durable
Postgres schedule (`tracks.scheduled_at`) that survives worker and process restarts — nothing ever
needs to be manually re-run or babysat.

## Operating Context

Self-hosted on a personal Debian 12 host behind a Cloudflare Tunnel (no port forwarding, ever).
Users log in via a proxied session against `vb2007.hu-api`, an existing separate personal identity
service, rather than a fresh signup flow of its own. Submitting one album/playlist/artist URL
expands into potentially hundreds of individual track-download jobs, each of which can
independently sit in a retry/backoff loop for a long time before completing. A SvelteKit web UI
(job rows expanding to their tracks, server-side search/sort/filter, an archive view, a per-user
retention setting) has shipped since v09/v20 — deployed and in real use at `spotdl.vb2007.hu`.

## Capabilities and Constraints

- Confirmed: submit a Spotify URL (track/album/playlist/artist) → it expands into tracks → each
  track downloads with a retry ladder, circuit breaker, proxy rotation, dedup, and live progress
  over SSE.
- Confirmed (v16–v22): jobs and tracks are owned per user (`jobs.user_id`) and enforced as a
  security property, not a display filter — see the "Users" section above. Every allowlisted
  person has their own private queue and job history; only the downloaded files and the dedup
  ledger are shared.
- Confirmed (master v3, v23–v31): each completed track has a direct file-download action
  (owner/admin only, non-owner 404s exactly like any other direct-id endpoint), verified/repaired
  ID3 tags (title, artist, album, track number, year, cover art), and a per-attempt download
  history for diagnosing a recurring failure without reading worker logs. An admin-only, on-demand
  sort & move sweep relocates completed downloads into a real library folder structure
  (`{artist} - {album} - ({year})`) without ever deleting anything already at the target — moved
  tracks stay downloadable. Usernames (fetched from the same upstream identity service at login)
  display everywhere email used to; a compact live status pill on the dashboard shows worker
  health to every user, with the actual pause/resume control moved to admin-only `/settings`.
- Constraint: keyboard-only navigation must work for every interactive element in the UI.
  **Met in master v4 (v45, carried through v46–v47):** the whole app runs without a mouse. The
  bindings are designed for the Hungarian QWERTZ layout first: nothing needs AltGr, `Y`/`Z` are
  never bound, keys match on `event.key`, and an AltGr (Ctrl+Alt) chord never fires a shortcut.
  `h` opens a help overlay listing exactly the shortcuts that work on the current page, and
  `/account` has a per-user switch that turns single-key shortcuts off (Tab, arrows, Enter and Esc
  keep working). Single keys are inert while typing in a text field. Playwright's keyboard journeys
  (spec 14, including an emulated Hungarian QWERTZ pass) guard it; the owner did the real
  Hungarian-layout pass.
- Confirmed (master v4, v46): the interface is fully available in **Hungarian and English**.
  Signed out, the browser's language preference decides (anything not Hungarian gets English);
  signed in, a language saved on `/account` wins, and its "automatic" choice follows the browser
  again. Dates and numbers follow the interface language with the browser's region, with a
  per-user 12-hour/24-hour override. Hungarian copy is informal (tegező) and keeps the radio
  metaphor. Track metadata, raw error text, alerts and logs stay untranslated; the backend answers
  with stable error codes that the frontend translates. Both message files must carry identical
  keys (`npm run lint` checks it).
- Confirmed (master v5, v53–v69): a **Firefox extension** puts a download icon beside tracks,
  albums, artists and playlists on `open.spotify.com`; a click queues the item, a right-click
  offers its album or artist (resolved by the server). It signs in with the browser's own app
  session, or a per-user API key from `/account` that can only submit and read its own jobs,
  never anything admin. A playlist or artist job can be **watched**, re-expanded on a schedule
  for new tracks only; any job can re-run its expansion or retry its failed tracks. A job
  **exports** as a streamed zip of its files or an `.m3u8`. The app **installs** as a PWA whose
  share target queues a link shared from Spotify's app. A user can turn on **browser
  notifications** for their own settled jobs and has their own **"my stats"** on `/stats`.
- Terminology: a "job" is one submitted URL; a "track" is one individual song being downloaded.

## Brand Commitments

None established. No product name beyond the repository name `spotdl-web`, and no logo or visual
identity exists yet.

## Evidence on Hand

No curated screenshots or demo content compiled here — the real, running UI at
`spotdl.vb2007.hu` and `frontend/src/DESIGN.md` (refreshed in v47) are the source of truth for
what's actually built. Future design work must not fabricate testimonials, sample libraries, or
usage data.

## Product Principles

1. Durability over speed — infinite retry and durable Postgres-backed scheduling that survives
   restarts; a slow, correct queue beats a fast one that gives up.
2. Treat rate-limiting as normal, not exceptional — never surface it to the user as an app failure.
3. Shared trust, private data — allowlisted people share one instance, one download library, and
   one dedup ledger, but each person's own queue and job history is private from the others (v16–
   v22); the admin's "all"/"others" views are an explicit, off-by-default exception for troubleshooting.
4. Config over UI, until proven necessary — but this narrowed over time, not stayed fixed: proxy
   management (v13), output/library settings (v13, v28) and worker pause/resume (v25) all moved
   into the settings UI once they proved to need routine adjustment. The proxy list file
   (`proxies.txt`) itself and a few one-off deploy-time values remain config/env-only.

## Accessibility & Inclusion

Keyboard-only navigation is a required, explicitly confirmed standard — every interactive element
must be fully operable without a mouse. Met since v45, Hungarian QWERTZ first (see Users &
Purpose above); any new interactive element must be keyboard-reachable and, if it gets a key,
registered in the shortcut registry. The UI is bilingual (Hungarian/English, v46), and v42–v43
raised the text and control contrast tokens to WCAG AA (4.5:1 text, 3:1 control borders).
