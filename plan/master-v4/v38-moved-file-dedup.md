# v38 — Moved-File Dedup & Download

Branch: `dev-moved-file-dedup` → PR into `main`
Version: `4.38.0`

## Scope

Inserted by the owner on 2026-10-10, after v37 found the defect (`docs/GOTCHAS.md` v37 section,
"Found, not fixed"). It lands before the UI work because it breaks the master-v3 invariant that
moving a file never causes a re-download.

**The defect.** `worker-dl` mounts only `/downloads`, in `docker-compose.yml`,
`docker-compose.override.yml` and `docker-compose.prod.yml` alike. v28's library sort & move
repoints `downloaded_tracks.file_path` into the library root (`/mnt/raid1/media/music`).
`dedup.is_already_downloaded` (`backend/app/services/dedup.py:16`) checks `path.exists()` in the
calling process, and `download_track` calls it on `worker-dl` (`backend/app/tasks/download.py:141`).
So a moved file looks missing, and the track downloads again. Measured on dev in v37:
`is_already_downloaded("3H3cOQ6LBLSvmcaV7QkZEu")`, a sorted Discovery track, returns the library
path in `worker-meta` and `None` in `worker-dl`. The re-download then `db.merge`s the ledger row
back to the new `/downloads` copy (`download.py:378-385`), so the next sweep meets a target that
already exists.

**The required behavior (owner's words, restated):** when a track has already been downloaded
and later moved, and the same user or another user submits it again:

1. It **must not re-download.** The track resolves as `skipped_duplicate`, with no attempt that
   touches the network.
2. **The download-to-disk feature must still work** for that track. The ledger knows where the
   file now lives, so `GET /api/tracks/{id}/file` serves the library copy without fetching
   anything.

## Tasks

1. **Reproduce first, on dev.** Find a ledger row with `in_library = true` and its file present
   under the dev library (`./test-library`). Submit its Spotify URL as a fresh job, as a test
   identity, and record the outcome before the fix: the attempt row (`network_path`, outcome),
   the worker-dl log, and the ledger row's `file_path` before and after. If the re-download
   really reaches the network, use a track you can afford to fetch (the same rule as v37's
   `@network` spec), and run it only once.
2. **Make the library visible to `worker-dl`, read-only.** Mount it at the same container path
   the other services use (`/mnt/raid1/media/music`), with `:ro`, in all three compose files:
   - the base file's named `library` volume;
   - the dev override's `./test-library` bind, inside worker-dl's existing `volumes: !override`;
   - production's `${LIBRARY_DIR:?…}`, which is already required, so no new variable is added.
   `:ro` enforces the master-v3 rule that nothing on the library filesystem is ever deleted:
   worker-dl only needs to see the library, never to write it. Verify the merged result with
   `docker compose config` (the override list-merge gotcha), never by reading YAML.
3. **Fail safe when the library can't be seen.** A mount that's missing, or not attached yet,
   must not read as "file gone". Reuse `reconcile_disk`'s rule (`_mount_looks_missing`): if the
   ledger row's path is under a root that looks unmounted in this process, `is_already_downloaded`
   must not report a miss that leads to a download.
   - Decide and record the behavior: hold the track as `waiting` with a logged reason, or
     resolve it as a duplicate on the ledger's word. A silent re-download is not an option.
   - Log it at error level once per occurrence, with the root and the track id.
   - This guards the next mount mistake, not only this one: an admin can repoint
     `library_target_dir` (`docs/GOTCHAS.md` v28 entry).
4. **The duplicate path records the library location.** A `skipped_duplicate` track gets
   `output_path` set to the ledger's current path (today's behavior at `download.py:144`; confirm
   it holds for a library path). `_resolve_track_file_path` (`backend/app/routers/tracks.py:53`)
   already reads the ledger first, and the nginx `X-Accel-Redirect` library location already
   exists (v28). Prove the whole path works end to end rather than assuming it does.
5. **Measure existing damage, read-only.** Write one SQL query that finds tracks downloaded again
   after their first copy had moved: a Spotify id with more than one network-touching completed
   attempt, or a ledger row back under `/downloads` while a library copy exists. Run it on dev.
   **Hand it to the owner for production**: read-only queries on production's database go
   through the owner, never this session. Report the counts in the PR. Cleaning up any
   duplicates found is out of scope; list them.
6. **Tests.**
   - `pytest`: `is_already_downloaded` returns the library path when the file exists there;
     the unmounted-root case from task 3 never yields a download; `download_track` on a moved
     ledger row writes `SKIPPED_DUPLICATE` with the library `output_path` and no network attempt.
   - The v37 e2e suite: add a spec (`09-moved-file.e2e.ts`) that picks a dev ledger row with
     `in_library = true` (querying the dev DB the way global setup's `findRealPathTrack` does),
     submits it as the **non-admin** identity (the cross-user half of the owner's scenario), expects
     `skipped_duplicate`, and downloads the file through the UI with its sha256 matching the
     library file (spec 4's check). Teardown's zero-download guard already fails the run if it
     re-downloads. Desktop and mobile.
   - Update the e2e ledger preflight comment and `docs/GOTCHAS.md`: once worker-dl sees the
     library, its preflight no longer differs from worker-meta's.

## Out of scope

- Cleaning up duplicate files or ledger rows already created by this defect in production
  (task 5 only reports them).
- The library flip from `/mnt/raid1/media/test` to `/mnt/raid1/media/music` (deferred by the
  owner, master plan "Not planned").
- Changing what "already exists" means. It stays folder + filename via the ledger, never content
  or bitrate (master-v3 invariant).
- Moving dedup out of `worker-dl` or changing which worker runs `download_track`.
- Any UI change beyond what the e2e spec needs.

## Deploy notes

No new `.env` variable: `LIBRARY_DIR` is already required by `docker-compose.prod.yml`. The
deploy recreates `worker-dl` with one extra read-only mount. No migration.

## Done when

- [ ] The pre-fix reproduction is recorded: a moved track resubmitted on dev, with worker-dl's
      `is_already_downloaded` returning `None` for it and the resulting attempt and ledger rows.
- [ ] `docker compose config` shows the library mounted `:ro` on `worker-dl` at
      `/mnt/raid1/media/music`, for both the dev invocation and `-f docker-compose.yml -f
      docker-compose.prod.yml` (with a dummy `.env`); a write attempt from inside worker-dl fails.
- [ ] After the fix, the same moved track resubmitted **by the same identity** resolves as
      `skipped_duplicate`, with no attempt carrying a `network_path`, and its ledger `file_path`
      unchanged (DB rows before and after).
- [ ] The same moved track resubmitted **by a different identity** resolves the same way.
- [ ] `GET /api/tracks/{id}/file` for each of those duplicate tracks returns the library file,
      and the downloaded bytes' sha256 matches the file under `./test-library` (captured).
- [ ] With the library mount removed from worker-dl (a temporary local override), a moved track
      is not downloaded again, and the error log line from task 3 appears.
- [ ] Task 5's query has run on dev with its output in the PR, and has been handed to the owner
      for production.
- [ ] The new e2e spec passes on both projects, and goes red when worker-dl's library mount is
      removed. The full `npm run test:e2e` is green, with teardown reporting zero network
      attempts.
- [ ] `pytest` (including the new cases), `pytest backend/tests/test_ownership.py`,
      `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `4.38.0`. `uv lock` is in sync. `graphify update .` has been run.
