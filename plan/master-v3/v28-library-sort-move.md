# v28 — Library Sort & Move

Branch: `dev-library-sort-move` → PR into `main`
Version: `3.28.0`

## Scope

An admin-only, on-demand batch that sorts downloaded files into the real music library and moves
them there — replacing the manual "download with the CLI, run
[music-sorter](https://github.com/vb2007/music-sorter), move to `/mnt/raid1/media/music`" workflow
this app exists to obsolete.

The target directory already holds ~120,000 tracks. **This version moves and deletes real files**,
so its safety rules are stricter than anything else in the project.

## Non-negotiable safety rules

1. **Nothing is ever deleted on the target library filesystem.** Not once, not under any flag. The
   only deletions this feature performs are of the *source copy* on the Docker downloads volume,
   and only after the file is confirmed present at the target.
2. **Move = copy → verify → delete source.** The downloads volume and `/mnt/raid1` are different
   filesystems, so a "move" is really copy+delete and can fail halfway. Verify by size and checksum
   before removing the source; a failed verification leaves the source untouched.
3. **"Already exists" is decided by folder + filename only.** Not content, not bitrate, not
   duration. A track re-downloaded a year later at a different bitrate still counts as already
   present — matching the same folder and filename is the whole test.
4. **Quarantine is a permanent, admin-toggleable feature.** When on, a source file whose destination
   already exists moves to a quarantine directory instead of being deleted, so a wrong match is
   recoverable. When off, size/checksum verification still runs and the source is deleted directly.

## Admin settings (all on `/settings`, reusing `app_settings`'s singleton get-or-create)

| Setting | Default |
|---|---|
| Library target directory | `/mnt/raid1/media/music` |
| Folder template | `{artist} - {album} - ({year})` |
| Quarantine enabled | on |
| Quarantine directory | under the downloads volume |

The output **filename** template default also changes here to
`{track-number} - {artists} - {title}.{output-ext}`, matching the existing library's convention so
newly downloaded files sort correctly. Since the live DB is disposable (locked v3 decision), the
migration may simply reset the stored template rather than conditionally patching it.

## Where it runs

`worker-meta`, as a Celery task. It already owns every housekeeping job (`reconcile_disk`, proxy
sync, the hourly archive sweep), already mounts the downloads volume, and running as a task means
the sweep survives the admin closing the page. It gains a read-write mount of the library
directory — in both compose files, following the existing `volumes: !override` pattern, verified
with `docker compose config`.

Progress reports over the existing per-user SSE channel (`events.make_progress_callback` is the
model), so the UI's progress bar is live rather than polled.

## The dedup-ledger interaction — the thing most likely to go wrong

`dedup.reconcile_disk()` deletes `downloaded_tracks` rows whose file is missing. Moving a file out
of the downloads volume looks **identical** to a manual deletion, so a naive implementation would
have the next reconciliation drop those ledger rows — and every moved track would eventually be
re-downloaded. That is the exact rate-limit exposure this whole application exists to avoid.

**Therefore**: the move updates `downloaded_tracks.file_path` to the new library location in the
same transaction as the filesystem move. The ledger keeps pointing at a real file,
`reconcile_disk()` keeps its "file gone → drop the row" behavior unchanged, and moved tracks stay
downloadable through v27's endpoint (which resolves the recorded path rather than assuming the
volume). `reconcile_disk()` must therefore be able to see the library mount — confirm it can, or it
will prune every moved row on its next run.

## Tasks

1. `app/services/library.py` — destination-path building from tags, conflict detection
   (folder+filename), copy/verify/delete, quarantine. Pure filesystem + metadata logic, no Celery,
   so it's testable directly.
2. Read tags off the file via v26's `tagging` service — works for files that never came through
   this app, which the DB-only approach could not.
3. `app/tasks/library.py` — the Celery task: iterate, report progress, accumulate a report.
4. Mark moved tracks **in-library** (a distinct stored state, separate from `archived_at`, so the
   app knows what it has relocated) and repoint the ledger.
5. **Archive the jobs of moved tracks** — including other users' jobs when the admin runs the
   sweep, since the files are shared.
6. Endpoints: `POST /api/library/sort` (admin-only, starts the sweep), `GET /api/library/sort/status`
   (progress + last report). Admin-gated server-side via `require_admin`.
7. Frontend: a separate admin page with the trigger, a live progress bar, and a final report —
   moved / skipped-as-already-present / quarantined / errors, with counts and a per-file list.
8. `graphify update .`

## Done when

Verified against a **copy** of the library structure, never the live 120k directory on the first
run:

- **Zero deletions on the target filesystem**, proven by a before/after file inventory of the target
  root across a sweep that includes conflicts.
- A folder+filename conflict with quarantine **on** moves the source to quarantine and leaves both
  the target file and the source content intact; with quarantine **off**, deletes only the source.
- A bitrate-differing re-download of an already-present track is treated as already present —
  explicitly tested, since it's the case the "obvious" content-comparison implementation gets wrong.
- A cross-filesystem move interrupted partway (simulate a verification failure) leaves the source
  file intact and the ledger unchanged.
- `downloaded_tracks.file_path` is repointed for every moved track, and a subsequent **real**
  `reconcile_disk()` run leaves those rows alone — the single most important check in this version.
- Moved tracks are **still downloadable** via v27's endpoint.
- Moved tracks are marked in-library, and their jobs archived — including a second user's job moved
  by the admin.
- A non-admin gets 403 from both library endpoints against the real API.
- Progress reaches the UI live during a real sweep of a meaningful number of files, and the final
  report's counts match the filesystem.
- `docker compose config` validated for dev and prod; the library mount present in both.
- Both version files read `3.28.0`; `graphify update .`
