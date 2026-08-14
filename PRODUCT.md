# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The project owner plus a small, explicitly allowlisted circle of trusted people (family/friends),
each authenticated via a server-to-server proxied login against the owner's existing
`vb2007.hu-api` account system and checked against an `ALLOWED_EMAILS` allowlist afterward. One
designated `ADMIN_EMAIL` account is the operator; everyone else is a plain user.

Confirmed (master v2, v16–v22): every allowlisted user gets their own real `users` row and their
own job/track history — `jobs.user_id` scopes ownership, enforced on every list and direct-id
endpoint (non-owner access 404s, never 403, so an id's existence is never confirmed to a
stranger), and the live SSE stream is scoped to a per-user Redis channel. This *is* private data
separation per user, adversarially verified (`backend/tests/test_ownership.py`,
`scripts/verify_separation_sse.sh`) — see `CLAUDE.md`'s "Master v2 invariants". What stays shared
on purpose: the downloaded audio files themselves live in one library, and the dedup ledger is
global — if another user already downloaded a track, yours resolves instantly rather than
re-fetching it. The admin also has an explicit, off-by-default "all users" toggle for
troubleshooting the shared queue/worker.

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
- Constraint: keyboard-only navigation must work for every interactive element in the UI.
- Terminology: a "job" is one submitted URL; a "track" is one individual song being downloaded.

## Brand Commitments

None established. No product name beyond the repository name `spotdl-web`, and no logo or visual
identity exists yet.

## Evidence on Hand

No curated screenshots or demo content compiled here — the real, running UI at
`spotdl.vb2007.hu` and `frontend/src/DESIGN.md` (updated through v20) are the source of truth for
what's actually built. Future design work must not fabricate testimonials, sample libraries, or
usage data.

## Product Principles

1. Durability over speed — infinite retry and durable Postgres-backed scheduling that survives
   restarts; a slow, correct queue beats a fast one that gives up.
2. Treat rate-limiting as normal, not exceptional — never surface it to the user as an app failure.
3. Shared trust, private data — allowlisted people share one instance, one download library, and
   one dedup ledger, but each person's own queue and job history is private from the others (v16–
   v22); the admin's "all users" view is an explicit, off-by-default exception for troubleshooting.
4. Config over UI, until proven necessary — proxy list and output settings are currently
   config-file driven; UI management is deliberately deferred to the project's final version.

## Accessibility & Inclusion

Keyboard-only navigation is a required, explicitly confirmed standard — every interactive element
in the eventual UI must be fully operable without a mouse.
