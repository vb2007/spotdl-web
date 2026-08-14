# spotdl-web — Master Plan v3

> This is the master v3 roadmap, approved by the user and committed **verbatim** as the project's
> permanent record — the same treatment `plan/master-v1/00-master-plan.md` and
> `plan/master-v2/00-master-plan.md` got, and for the same reason: the roadmap must never be
> quietly reinterpreted after the fact. Individual version plans (`plan/master-v3/v23-*.md` …
> `v29-*.md`) expand the roadmap table below with implementation-level detail. `CLAUDE.md` carries
> the durable summary every future session reads first.
>
> Master v1's and v2's plans live in `plan/master-v1/` and `plan/master-v2/` and are never edited
> again.

## Context

Master v2 (v14–v22, PRs #16–#27, all merged) shipped multi-user support, the job/track hierarchy,
search/archive, and — unplanned — a full release pipeline (v21). The app is deployed at
`spotdl.vb2007.hu` and has been used by the owner and a few relatives.

That real use produced the findings below. One of them is severe: **the app currently downloads
almost nothing.** Every track fails within seconds with `spotdl returned no output file for this
track`, gets correctly re-queued by the retry ladder, and fails again. The retry engine is working
exactly as designed; what it's retrying is broken.

Master v3 is the production-readiness pass: fix what's broken, close the diagnostic gaps that made
it hard to tell *why* it broke, finish the two features that make the tool complete (direct file
downloads, sort & move into the real library), and harden. There is no master v4 planned for some
time, so v3 should leave the app in a state that doesn't need one.

**Locked for v3: the live database is still disposable.** The deployed instance was tested by the
owner and relatives who all knew data would be pruned. Destructive migrations remain allowed, and
nuking the live DB is acceptable if it makes a version faster.

---

## Verified current state

Read from the repo this session, not assumed:

| Finding | Evidence |
|---|---|
| **yt-dlp is pinned and stale** | `backend/requirements.txt:247` pins `yt-dlp==2026.7.4`; that file was last regenerated in commit `58d71e5` (v12, 2026-08-02). The Dockerfile installs strictly from it |
| Failure raised here | `backend/app/tasks/download.py:186` — `if output_path is None: raise RuntimeError(...)`. `search_and_download` returned a `None` path rather than throwing |
| Misclassified as `other` | `retry.classify_error` maps a bare `RuntimeError` to `TrackErrorType.OTHER`, which shares the ladder but **never feeds the circuit breaker** — so a total failure of every download does not trip the breaker |
| Live-view metadata gap | `frontend/src/lib/stores/queue.ts:717` — `applyTrackEvent` seeds title/artists/album from `findCachedTrackMeta`, i.e. only from rows the browser already fetched via REST. A track that fails before ever being fetched has nothing to seed from |
| Event payload lacks metadata | `events.publish_track_event` sends ids/state/progress only — no title/artist, so the frontend *can't* render it even though the worker holds `song_json` |
| Worker panel placement | `frontend/src/routes/+page.svelte:168` renders `<WorkerStatus>` as a full panel between the submit form and the queue; its only always-on content is the admin "Receiver power" toggle |
| No file serving anywhere | `frontend/nginx.conf` has no downloads location; neither `api` nor `web` mounts the downloads volume (only `worker-dl`/`worker-meta` do) |
| No per-attempt history | `tracks.last_error` holds only the most recent message; nothing records what attempt 3 tried or which proxy it used |
| Dedup ledger prunes on missing file | `dedup.reconcile_disk()` drops `downloaded_tracks` rows whose file is gone — which is what moving files out of the volume would look like |
| `uv.lock` untracked | Present in the working tree, absent from git; `requirements.txt` is hand-regenerated with no CI check that it matches `pyproject.toml` |
| Current output template | `app_settings.DEFAULT_OUTPUT_TEMPLATE = "{artists} - {title}.{output-ext}"` — no track number |

---

## Locked decisions for v3

| Area | Decision |
|---|---|
| Backward compatibility | **Still none required.** Live DB is disposable; destructive migrations allowed |
| yt-dlp | Unpinned (floats to latest) while everything else stays pinned, **plus** a scheduled CI freshness check. Pinning the one dependency whose job is chasing a moving target is what caused this outage |
| ID3 tags | Verified *and repaired* after every download, read back from the file. The **file** stays the source of truth for tags; the DB is the repair source |
| Username | Fetched from upstream `GET /user` at login and **stored** on the `users` row (refreshed every login, same reconciliation pattern as `is_admin`), so the admin all-users view needs no live upstream calls |
| Worker control | Pause/resume toggle moves to `/settings` (admin-only); a small live status pill stays on the dashboard for everyone |
| File downloads | Single track only. nginx `X-Accel-Redirect` with the ownership check in FastAPI. Owner or admin only |
| Download availability | Keyed on **whether the file exists at its recorded path**, never on `archived`. A retention-archived job with its file present stays downloadable |
| Sort & move | Admin-only, on-demand batch, runs as a Celery task on `worker-meta` with SSE progress |
| Move semantics | copy → verify (size/checksum) → delete source. **Nothing is ever deleted on the target library filesystem** — only the copy on the downloads volume |
| Duplicate detection | **Folder + filename match only.** A re-download at a different bitrate still counts as "already exists" |
| Quarantine | Permanent feature, admin-settable toggle. On: a conflicting source file moves to quarantine instead of being deleted. Off: size/checksum verification only, source deleted directly |
| Library layout | Target directory *and* folder template are admin settings, defaulting to `/mnt/raid1/media/music` and `{artist} - {album} - ({year})` |
| Output template | Default becomes `{track-number} - {artists} - {title}.{output-ext}` to match the existing library |
| Moved tracks | Marked in-library and their `downloaded_tracks.file_path` repointed to the new location. They **stay downloadable**; their jobs are archived |
| Version numbers | Slice numbers continue at **v23**; releases are `3.23.0`, `3.24.0`, … so a slice number never means two things |

---

## The download failure — investigate, don't assume

The stale `yt-dlp==2026.7.4` pin is a strong hypothesis: YouTube breaks extraction constantly,
yt-dlp ships fixes within days, and the user's own system yt-dlp downloads the same tracks
instantly from the same host and public IP. But it is a hypothesis, and v23 must *prove* the root
cause before declaring it fixed — the symptom (`output_path is None`) has at least three plausible
causes, and only one is the pin:

1. **Stale yt-dlp** — extraction fails, spotdl swallows it and returns no path.
2. **A write/permission problem** — the file downloads but can't be written where spotdl expects, so
   it reports no output. The non-root container user and the bind-mounted downloads directory make
   this genuinely possible (`docs/DEPLOYMENT.md` already documents a `chown` step for exactly this).
3. **spotdl returning `None` on a path that should have raised** — in which case the real error is
   being swallowed upstream and the fix is to surface it, not just to bump a dependency.

v23's first task is to reproduce against the real stack and capture spotdl's and yt-dlp's own
output, not to bump and hope. **A fix that isn't traced to a proven cause isn't a fix**, and the
retry ladder's design means a still-broken download looks identical to a working one from the UI —
it just quietly never finishes.

Two things v23 must fix regardless of the root cause, because both are real bugs the outage
exposed:

- **`output_path is None` becomes a typed error, not a bare `RuntimeError`.** Today it classifies as
  `OTHER`, which never feeds the circuit breaker — so a 100% failure rate across every track never
  trips the breaker that exists to notice exactly that.
- **Total-failure blindness.** Nothing anywhere notices "the last N attempts all failed the same
  way". The breaker only counts `AudioProviderError`.

---

## Version roadmap

Fix first, then features, then close. One feature per version, one `dev-<feature>` branch, one PR.

| # | Branch | Scope |
|---|---|---|
| **v23** | `dev-download-reliability` | **Root-cause and fix the download failure.** yt-dlp unpinned + bumped + CI freshness check; typed error for the no-output case so it feeds the breaker; `uv.lock` tracked and a CI check that `requirements.txt` matches `pyproject.toml`. Plus the live-view fix: `publish_track_event` carries title/artist/album so the queue never renders "unknown", and the appear/disappear/reappear glitch is fixed |
| **v24** | `dev-attempt-history` | Per-attempt log (`track_attempts`): what each attempt tried, direct vs which proxy, what failed, when. Surfaced in the track detail so a recurring failure is diagnosable from the UI instead of by SSH-ing to read worker logs |
| **v25** | `dev-username-ui` | Username from upstream `GET /user`, stored on `users` and refreshed each login; shown everywhere email is today, including the admin all-users view. Worker pause/resume moves to `/settings`; a compact live status pill replaces the dashboard panel |
| **v26** | `dev-id3-integrity` | Verify embedded tags after each download (title, artist, album, track number, year, cover art) and re-embed from `song_json` when anything is missing. Prerequisite for v28, which reads tags off files |
| **v27** | `dev-file-downloads` | `GET /api/tracks/{id}/file` — ownership-checked in FastAPI, streamed by nginx via `X-Accel-Redirect`. Owner or admin only; availability keyed on the file existing at its recorded path |
| **v28** | `dev-library-sort-move` | Admin-only sort & move into the real library. Target dir, folder template and quarantine toggle as admin settings; copy → verify → delete source; conflicts by folder+filename only; ledger repointed and tracks marked in-library; moved jobs archived; new default output template |
| **v29** | `dev-v3-hardening` | Production close: full real-stack verification of every v3 change, a genuine multi-user pass, docs + `CLAUDE.md` + `docs/GOTCHAS.md` reconciliation, and the closing re-read of every "Done when" bullet |

### Why this order

The outage is fixed and deployable before any feature work (v23). Diagnostics land next (v24) so
every later version is debuggable. ID3 integrity (v26) precedes sort & move (v28) because the sorter
reads tags off files. File downloads (v27) precede the move (v28) because they're simpler and lower
risk, and because v28 must then be verified not to break them — the move changes where files live,
which is exactly the kind of interaction that silently breaks a feature shipped one version earlier.

---

## Critical interactions to design around

These are the places where two v3 features collide, each already a decided design rather than an
open question:

- **Sort & move vs. the dedup ledger.** `reconcile_disk()` prunes `downloaded_tracks` rows whose
  file is missing — and moving a file out of the volume looks exactly like a manual deletion. v28
  must repoint `file_path` to the library location in the same transaction as the move, so the
  ledger keeps pointing at a real file and reconciliation keeps its "file gone → drop the row"
  behavior. Getting this wrong causes silent re-downloads, the one thing this app exists to avoid.
- **Sort & move vs. file downloads.** Because the ledger is repointed and the library is mounted,
  moved tracks stay downloadable. v27's serving must therefore resolve the path from the DB rather
  than assuming the downloads volume, and v28 must mount the library into whichever container
  serves files.
- **Archived ≠ unavailable.** A job archived by v19's retention sweep still has its file. Download
  availability keys on file existence, never on `archived_at`.
- **In-library is its own state.** Stored separately from `archived_at`, because a job can be
  archived without being moved and the app needs to know what it has already relocated.

---

## Critical files

- **Download path**: `backend/app/tasks/download.py` (the `output_path is None` raise at `:186`),
  `backend/app/services/downloads.py` (`download_one`, the `Downloader` cache),
  `backend/app/services/retry.py` (`classify_error`, breaker)
- **Events / live view**: `backend/app/services/events.py` (`publish_track_event`),
  `frontend/src/lib/stores/queue.ts` (`applyTrackEvent` at `:701`, `findCachedTrackMeta` at `:689`)
- **Dependencies**: `backend/pyproject.toml`, `backend/requirements.txt`, `backend/Dockerfile`,
  `.github/workflows/ci.yml`
- **Settings / admin**: `backend/app/services/app_settings.py` (the get-or-create singleton pattern
  every new admin setting should reuse), `backend/app/routers/settings.py`,
  `frontend/src/routes/settings/+page.svelte`
- **Identity**: `backend/app/services/users.py` (`get_or_create_user`'s existing admin-flag
  reconciliation is the pattern for username refresh), `backend/app/routers/auth.py`
- **File serving**: `frontend/nginx.conf`, `docker-compose.yml` / `docker-compose.prod.yml` volumes
- **Housekeeping**: `backend/app/tasks/beat.py` and `backend/app/services/dedup.py` (where the
  sweep and reconciliation conventions already live)

Reuse rather than rewrite: `app_settings`'s singleton get-or-create, `proxies.redact()`,
`serializers.track_to_dict`, `events.make_progress_callback` (the model for the sweep's progress
reporting), and the `RUN_DISK_RECONCILE`/`RUN_PROXY_SYNC` boot-hook gating convention.

---

## Verification

Every version keeps the standing rules: real `docker compose` stack, real Postgres, real network,
each "Done when" bullet evidenced individually this session. Version-specific musts:

1. **v23 proves the root cause**, with captured spotdl/yt-dlp output showing the failure *and* the
   same track succeeding after the fix. A green pytest run means nothing here — every unit test
   passed throughout this outage.
2. **v23's live-view fix verified on a real failing-then-recovering track**, watching the actual UI:
   title and artist correct from the first `downloading` event, no disappear/reappear.
3. **v26 verified by reading tags back off a real downloaded file** (all six fields plus embedded
   cover art), including one track deliberately stripped of tags to prove the repair path runs.
4. **v27 verified cross-user**: a non-owner gets 404 (not 403) on someone else's file, admin gets
   it, and the bytes actually arrive intact — checksum the downloaded file against the one on disk.
5. **v28 verified against a real copy of the library structure, never the live 120k directory on
   the first run.** Prove: nothing on the target filesystem is ever deleted; a folder+filename
   conflict quarantines (toggle on) or deletes only the source (toggle off); the ledger is
   repointed and `reconcile_disk()` then leaves those rows alone; moved tracks are still
   downloadable; moved jobs are archived; and a cross-filesystem move that fails halfway leaves the
   source intact.
6. **v29 re-runs v22's cross-user separation sweep** (`scripts/verify_separation_sse.sh` plus
   `pytest backend/tests/test_ownership.py`) — v3 adds new endpoints and a new file-serving surface,
   and every new query path is a new chance to drop the owner filter.
7. **`graphify update .`** after every code-modifying version; version bumped in both
   `backend/pyproject.toml` and `frontend/package.json` to the identical `3.NN.0` string.
