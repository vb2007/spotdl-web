# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The project owner plus a small, explicitly allowlisted circle of trusted people (family/friends),
each authenticated via a server-to-server proxied login against the owner's existing
`vb2007.hu-api` account system and checked against an `ALLOWED_EMAILS` allowlist afterward.
Confirmed: all allowlisted users currently share one global download queue and job history — the
schema has no per-user ownership field (`jobs`/`tracks` are not scoped to a session or account).
This is a shared personal tool among trusted people, not a multi-tenant product with private
libraries per user.

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
independently sit in a retry/backoff loop for a long time before completing. There is currently no
frontend — all interaction so far is via the API/tests; the web UI is future work (v09 in the
version roadmap).

## Capabilities and Constraints

- Confirmed: submit a Spotify URL (track/album/playlist/artist) → it expands into tracks → each
  track downloads with a retry ladder, circuit breaker, proxy rotation, dedup, and live progress
  over SSE.
- Constraint (explicit, not yet decided whether to change): jobs and tracks have no owner/user_id
  — the queue is shared, not private per allowlisted person, even though multiple people may be
  allowlisted. Future work should not assume per-user data isolation exists.
- Constraint: keyboard-only navigation must work for every interactive element in the eventual UI.
- Terminology: a "job" is one submitted URL; a "track" is one individual song being downloaded.

## Brand Commitments

None established. No product name beyond the repository name `spotdl-web`, and no logo or visual
identity exists yet.

## Evidence on Hand

None — no screenshots, demo content, or built UI exist yet (frontend/v09 has not started). Future
design work must not fabricate testimonials, sample libraries, or usage data; the only real content
available is the backend's own API responses.

## Product Principles

1. Durability over speed — infinite retry and durable Postgres-backed scheduling that survives
   restarts; a slow, correct queue beats a fast one that gives up.
2. Treat rate-limiting as normal, not exceptional — never surface it to the user as an app failure.
3. Shared trust, not multi-tenant isolation — allowlisted people share one instance and one queue;
   don't design as if users need private data separation from each other.
4. Config over UI, until proven necessary — proxy list and output settings are currently
   config-file driven; UI management is deliberately deferred to the project's final version.

## Accessibility & Inclusion

Keyboard-only navigation is a required, explicitly confirmed standard — every interactive element
in the eventual UI must be fully operable without a mouse.
