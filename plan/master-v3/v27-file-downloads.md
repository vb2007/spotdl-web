# v27 — Direct File Downloads

Branch: `dev-file-downloads` → PR into `main`
Version: `3.27.0`

## Scope

Let a user download a completed track's file from the browser. There is no file-serving path today:
`frontend/nginx.conf` has no downloads location, and neither `api` nor `web` mounts the downloads
volume — only `worker-dl` and `worker-meta` do.

Single track only. A whole-job zip is deliberately deferred: building archives on demand for a job
that might hold thousands of tracks is its own feature, and it's cheap to add later once
single-track serving is proven.

## Design — nginx X-Accel-Redirect

FastAPI performs the ownership check and returns an `X-Accel-Redirect` header naming an
**internal-only** nginx location; nginx streams the bytes. The authorization decision stays entirely
in application code — nginx serves only when explicitly told to, and the internal location is
unreachable from outside — while no audio bytes pass through the Python process.

- `GET /api/tracks/{id}/file` behind `require_session`.
- Authorization: the track's owner (via `job.user_id`) **or** an admin. Non-owner gets **404, not
  403** — the standing v2 invariant, so an id's existence is never confirmed.
- **Availability is keyed on the file existing at its recorded path, never on `archived_at`.** A
  job archived by v19's retention sweep still has its file and stays downloadable. Missing file →
  404.
- Resolve the path from `tracks.output_path` / the `downloaded_tracks` ledger, **never** by
  assuming the downloads volume. v28 moves files to the library and repoints the ledger; this
  endpoint must keep working unchanged when that happens, which it only does if it reads the
  recorded path.
- Guard against path traversal: the resolved path must be confirmed inside an allowed root before
  being handed to nginx. `output_path` is app-generated today, but this endpoint turns it into an
  authorization boundary, and treating it as trusted input is exactly how that goes wrong later.
- `Content-Disposition: attachment` with a filename derived from the track metadata, correctly
  encoded for non-ASCII artist/title (RFC 5987) — this library is full of them.

Infrastructure:

- Mount the downloads volume **read-only** into `web` (nginx), in both `docker-compose.yml` and
  `docker-compose.prod.yml`. Compose override files replace mapping keys and merge list keys — the
  prod file already uses `volumes: !override` for the workers, so follow that pattern and verify
  with `docker compose config` rather than assuming (`docs/GOTCHAS.md` v01/v12).
- An `internal` nginx location for the file root. Every route needs its own explicit location block
  (`docs/GOTCHAS.md` v09/v12) — this one is `internal`, so it must be unreachable directly.

Frontend: a download action on completed tracks with a resolvable file, in the existing track row /
detail. Nothing for tracks without a file.

## Done when

- The owner downloads a real completed track and the bytes are intact — **checksum the downloaded
  file against the one on disk**, don't just check that a file arrived.
- A non-owner gets **404** for that same track id, verified against the real running API with two
  real sessions.
- An admin can download another user's file.
- Requesting the internal nginx location directly from outside returns 404 — verified by curl, since
  a misconfigured `internal` would expose the entire library unauthenticated.
- A track whose file has been deleted from disk returns 404 rather than a 500 or an empty file.
- A **retention-archived** job's track is still downloadable — the specific behavior the "archived
  means gone" instinct would have broken.
- A track with non-ASCII artist/title downloads with a correct filename in a real browser (not just
  curl — header encoding bugs surface in the browser).
- Path traversal is impossible: a manually corrupted `output_path` pointing outside the allowed root
  is rejected.
- `docker compose config` validated for both dev and prod invocations; `nginx -t` passes.
- Both version files read `3.27.0`; `graphify update .`
