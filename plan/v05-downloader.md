# v05 — Downloader

Branch: `dev-downloader` → PR into `main`

## Scope

Actually download tracks. Dedup against `downloaded_tracks` first. Error handling here is
deliberately naive (log + mark `failed`) — the real ladder/breaker logic is v06's job, kept
separate so this version is reviewable purely on "does spotdl download the right file to the right
place with the right tags."

## Tasks

1. `app/services/downloads.py`:
   - `get_downloader(format, bitrate, proxy=None) -> Downloader` — construct
     `spotdl.download.downloader.Downloader(settings)` with `DownloaderOptions` built from
     `DEFAULT_FORMAT`/`DEFAULT_BITRATE`/`DOWNLOAD_OUTPUT_DIR` (+ `proxy` when given), **cached** in
     a process-level dict keyed by `(format, bitrate, proxy)` — construction initializes every
     audio/lyrics provider and should not happen per track.
   - `download_one(song: Song, downloader: Downloader) -> Tuple[Song, Optional[Path]]` — calls
     `downloader.search_and_download(song)`. Must run on a plain sync Celery task (no running
     asyncio loop) since `search_and_download` raises `DownloaderError` if called from one.
2. `app/services/dedup.py`:
   - `is_already_downloaded(spotify_track_id) -> Optional[Path]` — checks `downloaded_tracks`.
   - `reconcile_disk()` — startup scan: walks `DOWNLOAD_OUTPUT_DIR`, matches files back to
     `downloaded_tracks` rows (by embedded tags or filename convention), removes ledger rows whose
     file no longer exists, and can be pointed at manually-added files later. Run once on
     `worker-meta` boot in this version; a scheduled periodic reconciliation is a nice-to-have, not
     required here.
3. `app/tasks/download.py` — `download_track(track_id)`:
   - Load track; if `is_already_downloaded` hits, set `state=skipped_duplicate`, done.
   - Else `state=downloading`, build/find the cached `Downloader`, call `download_one`.
   - On success: `state=completed`, `output_path` set, insert/upsert `downloaded_tracks`.
   - On any exception in this version: log it fully, `state=failed`, `last_error` set. (v06
     replaces this branch with ladder/breaker classification — do not build that logic here, just
     leave a clearly marked seam, e.g. a single `except Exception as e:` block that v06 will
     restructure.)
4. Wire `expand_job` (v04) to enqueue `download_track` for each inserted track once expansion
   finishes, on the `downloads` queue, so end-to-end submission → download works manually even
   before retry logic exists.
5. `graphify update .`

## Files touched (new)

`backend/app/services/downloads.py`, `backend/app/services/dedup.py`,
`backend/app/tasks/download.py`; edits to `backend/app/tasks/expand.py`.

## Done when

- Submitting a small real album URL downloads every track to `DOWNLOAD_OUTPUT_DIR` with correct
  filenames (per the output template) and embedded tags (artist/album/track number).
- Re-submitting the same album afterward marks every track `skipped_duplicate` immediately, no
  network calls made for those tracks.
- Deleting one file on disk and restarting the worker causes `reconcile_disk()` to drop that file's
  `downloaded_tracks` row so it would be re-downloaded on the next submission.
- A single bad track (e.g. simulate by breaking one file's metadata) ends in `failed` without
  taking down the rest of the album's downloads.
