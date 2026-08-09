# v04 — URL Expansion

Branch: `dev-url-expansion` → PR into `main`

## Scope

Accept a Spotify URL (or search term), turn it into `tracks` rows via spotdl's own expansion logic.
No downloading happens in this version — every track should end up `pending` and stay there.

## Tasks

1. `app/services/expansion.py` — thin wrapper around `spotdl.utils.search.get_simple_songs(query,
   use_ytm_data=False, playlist_numbering=False, ...)`. Do **not** hand-roll Spotify Web API calls;
   this function already classifies track/album/playlist/artist URLs and returns `List[Song]`.
   Wrap it once so the rest of the app never imports spotdl's search internals directly.
2. `POST /api/jobs` — body `{url: str}`, behind `require_session`. Classifies `source_type` from
   the URL shape (or `search` if it's not a URL), inserts a `jobs` row in state `expanding`,
   enqueues `expand_job(job_id)` on the `meta` Celery queue, returns the job id immediately (so the
   UI doesn't block on expansion of a 500-track playlist).
3. `app/tasks/expand.py` — `expand_job(job_id)`: loads the job, calls `expansion.expand(url)`,
   inserts one `tracks` row per `Song` (state=`pending`, `song_json=song.json`,
   `spotify_track_id=song.song_id`), sets `jobs.state = expanded` (or `failed` with `error` set, if
   `get_simple_songs` raises — e.g. a malformed URL). Runs on `worker-meta` so it never competes
   with `worker-dl`'s single-concurrency download slot.
4. `GET /api/jobs` / `GET /api/jobs/{id}` — list jobs with their track counts by state (used by the
   frontend in v09, but the endpoint belongs here since it's expansion's natural read side).
5. `GET /api/jobs/{id}/tracks` — list a job's tracks with `song_json`-derived display fields
   (title, artists, album) projected out, not the raw blob.
6. `graphify update .`

## Files touched (new)

`backend/app/services/expansion.py`, `backend/app/tasks/expand.py`,
`backend/app/routers/jobs.py`.

## Done when

- `POST /api/jobs` with a real playlist URL returns quickly; polling `GET /api/jobs/{id}` shows
  `state` flip from `expanding` to `expanded` with the correct track count.
- `GET /api/jobs/{id}/tracks` lists every track as `pending` with correct title/artist/album — no
  track has moved past `pending` (proves this version touches expansion only).
- An artist URL (many albums) and a single track URL both expand correctly — confirms
  `get_simple_songs` is doing the classification, not custom code.
- A garbage URL fails the job with a readable `error` message instead of crashing the task.
