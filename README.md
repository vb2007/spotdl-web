# spotdl-web

A self-hosted web front end for [spotDL](https://github.com/spotDL/spotify-downloader). Paste a
Spotify track, album, playlist or artist link, and the app downloads all of it in the background
for a small allowlisted circle of users. YouTube Music's rate limiting is treated as normal
weather, not as a failure: each track waits out a retry ladder, a global circuit breaker pauses
everything when the source pushes back, and proxies come in only after a direct attempt has
waited its turn. A track may sit in the queue for days, and that is the design working. Nothing
is given up on except a track that doesn't exist.

Live updates arrive over SSE. Every user sees only their own jobs, and the audio lands in one
shared, deduplicated library. A Firefox extension ([`docs/EXTENSION.md`](docs/EXTENSION.md))
adds a download button to `open.spotify.com`.

## Status

Masters v1 to v5 (versions v00–v70) are complete and run in production. Master v5 closed every
item on its open-items ledger and added the Firefox extension, an admin view of other users'
jobs, watched playlists and artists, zip and M3U export, an installable app with a share target,
personal notifications with "my stats", and admin-managed sign-in access (`/users`). Its roadmap,
ledger and per-version plans are in [`plan/master-v5/`](plan/master-v5/00-master-plan.md); every
master's plans stay in `plan/master-vN/` as history. No master v6 is planned yet.

## Where to read next

| What | Where |
|---|---|
| Rules, locked decisions and invariants (read first when working on the code) | [`CLAUDE.md`](CLAUDE.md) |
| Local development | [`docs/LOCAL_DEV.md`](docs/LOCAL_DEV.md), with `.env.dev.example` |
| Production deployment on the Debian host | [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md), with `.env.example` |
| Release pipeline (versioning, images, deploy, rollback) | [`docs/RELEASE_PIPELINE.md`](docs/RELEASE_PIPELINE.md) |
| CI on the self-hosted runner | [`docs/CI_SELF_HOSTED_RUNNER.md`](docs/CI_SELF_HOSTED_RUNNER.md) |
| Gotchas and war stories, by topic | [`docs/GOTCHAS.md`](docs/GOTCHAS.md) |
| Product brief and design system | [`PRODUCT.md`](PRODUCT.md), [`frontend/src/DESIGN.md`](frontend/src/DESIGN.md) |
