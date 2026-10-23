# v56 — Library Sweep & Dedup Hardening

Branch: `dev-library-hardening` → PR into `main`
Version: `5.56.0`
Wave / slot: 2 / 3
Depends on: v50

## Scope

Ledger items **L1–L8**. The sweep now runs against the **real** ~120k-track library (switched
2026-10-11), so its remaining edge cases are no longer hypothetical. Master-v3 invariants bind
everything here:

- nothing is ever deleted on the target filesystem;
- a move repoints every ledger row sharing the file in the same transaction;
- "already exists" means folder + filename.

**Every test runs against a copy** (`./test-library` on the slot stack). Never against the real
library.

## Items

- **L1. Sweep cancel.**
  - `POST /api/library/sort/cancel` (admin) sets a cancel flag (Redis, or the sweep's status row).
  - The sweep checks it **between files**, never mid-file. Every file already moved keeps its
    repointed ledger row.
  - The final report says "cancelled after N of M". `/library` gets a cancel button through the
    existing `ConfirmDialog`, keyboard-reachable, with en/hu strings.
- **L2. Path safety.**
  - On save of `LIBRARY_DIR`/quarantine settings and at sweep start: reject a library dir that is
    equal to, inside, or containing the downloads dir (`Path.resolve()` plus `is_relative_to`,
    both directions). Do the same for the quarantine dir vs both.
  - Per file: skip, with a reported reason, any source whose computed destination resolves to
    itself.
- **L3. Sweep vs worker-dl race.**
  - worker-dl commits a ledger row between the sweep's re-read and its delete of the source file.
  - Serialize per file: a Postgres advisory lock keyed on the file path hash (or the ledger
    `spotify_id`), taken by both the sweep's move and worker-dl's ledger upsert for the same file.
  - Prove it with a v50 race test.
- **L4. The reconcile "unmounted" check.**
  - `reconcile_disk` treats an empty `/downloads` as "unmounted" and skips pruning, so the 47 rows
    survived only by accident.
  - Replace that with an explicit **mount sentinel**: a `.spotdl-volume` file the app creates in
    each managed root, checked by `reconcile_disk`. A missing sentinel means "not mounted, skip".
  - An empty but mounted volume now prunes correctly.
  - Production gets its sentinels created on first boot. Document it in Deploy notes.
- **L5. Held-forever ledger row.**
  - A ledger row pointing at a hand-deleted file holds its track on every ladder step.
  - With L4's sentinel, reconcile can now prune it safely. Additionally, `download_track`'s
    "ledger says present, file missing" path drops the stale row and proceeds to download, instead
    of holding.
- **L6. Dedup across previous library roots.**
  - Dedup guards only the current roots, so a ledger row under an *old* library path (before a
    `LIBRARY_DIR` change) counts as missing.
  - Track known roots (an `app_settings` list of historic library roots). Dedup and file serving
    accept any known root whose sentinel exists.
- **L7. Disk-full partial copy.** Re-verify that v31's `copy_verify` already rejects a short copy
  as an existing target. Simulate it with a tiny tmpfs target. Close with evidence, or fix.
- **L8. Duplicate files in dev `./downloads`.** Reproduce on a fresh slot DB (download the same
  album twice via two users, plus a re-download), and find whether two files for one track can
  exist. Fix the cause, or record why it's benign.

## Files owned

`backend/app/services/{library,dedup}.py`, `backend/app/tasks/library.py`,
`backend/app/routers/library.py`, `backend/app/routers/settings.py` (the library-settings
validation only; v55 owns retention), `frontend/src/routes/library/+page.svelte`,
`frontend/src/routes/settings/+page.svelte` (library-settings errors only), migration if needed,
message JSONs (hotspot), tests. L5's change in `tasks/download.py` is a single call into
`dedup.py`. Coordinate it with v54 (same wave) by keeping it to that call site.

## Deploy notes

The mount sentinel files get created in production's downloads and library roots on first boot of
5.56.0. Verify after deploy that `reconcile_disk` logs "sentinel present" for both.

## Done when

- [ ] **L1:** a real sweep over the test-library copy, cancelled mid-run, stops between files. The
      report says "cancelled after N of M". Every moved file's ledger rows point at the target,
      and a `reconcile_disk` run afterwards prunes 0 of them (logs plus DB).
- [ ] **L2:** saving overlapping dirs (each of: equal, inside, containing, and the same for
      quarantine) gets 422. A crafted self-destination file is skipped with a reason. Nothing is
      deleted (before and after inventory).
- [ ] **L3:** a real-Postgres race test of worker-dl's upsert vs a sweep move of the same file
      fails without the advisory lock (shown) and passes with it.
- [ ] **L4:** an empty-but-mounted `/downloads` with a stale row → pruned. An unmounted root (no
      sentinel) → skipped with a log line. Both are real runs on the slot stack.
- [ ] **L5:** a hand-deleted file whose track is queued gets downloaded fresh, not held (real
      `realdl` run, attempt history).
- [ ] **L6:** after switching `LIBRARY_DIR` on the slot stack, a track under the old root still
      dedups and is still downloadable (real calls).
- [ ] **L7/L8:** evidence recorded for each (tmpfs run output; the reproduction or a benign-cause
      write-up in GOTCHAS).
- [ ] Master-v3 invariant check: the before and after inventory of the test-library target across
      every test run shows zero deletions.
- [ ] `pytest`, `npm run lint`, `npm run check`, `npm run build` and e2e pass. Both version files
      read `5.56.0`. `uv lock` is in sync. `graphify update .` has been run.
