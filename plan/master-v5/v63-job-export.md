# v63 — Job Export (zip + M3U)

Branch: `dev-job-export` → PR into `main`
Version: `5.63.0`
Wave / slot: 4 / 2
Depends on: waves 0–3 merged

## Scope

Downloads are single-track only (v27). A whole-job zip was deferred in v27 and again in v4 ("not
planned"). The owner now wants it, plus an M3U playlist, so a downloaded album or playlist can
come out of the app in one action.

## Design

- **`GET /api/jobs/{id}/export.zip`** (owner or admin, non-owner 404).
  - **Membership rule** (the v27/v38 rule): a track is included only if its file **exists at its
    recorded path** (downloads volume or any known library root, via v56's root handling). It's
    never keyed on `archived_at`, so an archived job stays exportable.
  - Tracks without a file are listed in a `MISSING.txt` inside the zip, rather than silently
    omitted.
  - **Streaming, STORED (no compression):** audio doesn't compress, and STORED allows a correct
    `Content-Length` up front, so the browser shows real progress. Use a streaming zip writer
    (e.g. `zipstream-ng`, pinned). Never build the archive on disk or in memory.
  - **No DB transaction is held during streaming:** resolve the file list first, close the
    session, then stream (the v31 connection-leak lesson).
  - **Filenames inside:** the file's own basename, deduplicated with a ` (2)` suffix, plus an
    `<job title>.m3u8`. The archive name is the job title, sanitized and RFC 5987-encoded in
    `Content-Disposition` (v27's encoder reused).
  - **Bounds:** max N files or M GB per export (settings, defaults documented). Beyond that,
    413 `export_too_large`, and the UI suggests the M3U or per-track downloads instead.
  - Path traversal: every path is re-confirmed inside an allowed root (v27's guard reused).
  - nginx: `/api/` already proxies. Set `proxy_buffering off` for this location so the stream
    isn't buffered to disk by nginx. Verify against the nginx build, not just Vite.
- **`GET /api/jobs/{id}/playlist.m3u8`:** UTF-8 extended M3U with `#EXTINF:<duration>,<artist> -
  <title>` and **relative** paths (the zip layout). With `?paths=library`, it lists absolute
  library paths (useful for a media server pointed at the library). That variant is admin-only,
  since it reveals the filesystem layout.
- **UI:** JobRow actions "download all (zip)" and "playlist (.m3u8)". They're shown only when ≥1
  track has a file, with a count ("12 of 14 files"). Keyboard-reachable, en/hu, designed through
  impeccable. Use a real navigation to stream the zip, with v35(e)'s error-surface technique (a
  probe first) so a 404/413 shows inline.

## Files owned

New `backend/app/routers/export.py` (or endpoints in `jobs.py` if graphify shows that's the
convention; if so, keep them in a delimited block, since v62 also edits `jobs.py`), new
`backend/app/services/export.py`, `backend/pyproject.toml` (one dependency), `frontend/nginx.conf`
(one location), `frontend/src/lib/components/JobRow.svelte` (export block only),
`frontend/src/lib/api.ts`, message JSONs (hotspot), tests.

## Out of scope

Transcoding. Exporting multiple jobs at once. Background-built archives.

## Done when

- [ ] A real album job (files on the slot stack) exports as a zip whose every entry's sha256
      matches the file on disk, plus a valid `.m3u8` that plays in a real player (VLC or mpv
      reading the extracted folder). Show command output.
- [ ] A job with 2 deleted files: those tracks are listed in `MISSING.txt`, and the rest are
      intact.
- [ ] A retention-archived job is still exportable.
- [ ] Non-owner gets 404 on both endpoints. Admin can export another user's job.
      `?paths=library` is admin-only (`test_ownership.py` cases).
- [ ] Streaming:
  - a 1GB+ export through the **nginx build** shows a correct `Content-Length` and progress in the
    browser;
  - `api` memory stays flat (`docker stats` before and during);
  - `pg_stat_activity` shows no idle-in-transaction session during the stream.
- [ ] Over the limit gets 413, and the UI shows the inline message (screenshot).
- [ ] A non-ASCII job title produces a correct filename in a real browser.
- [ ] Path traversal: a corrupted `output_path` outside the roots is excluded and listed as
      missing (test).
- [ ] The UI works keyboard-only; en/hu; impeccable output recorded. An e2e spec has been added
      (zip checksum of a small job).
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass, and `nginx -t` passes.
      Both version files read `5.63.0`. `uv lock` is in sync. `graphify update .` has been run.
