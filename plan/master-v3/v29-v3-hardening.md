# v29 — Production Hardening & Close

Branch: `dev-v3-hardening` → PR into `main`
Version: `3.29.0`

## Scope

The closing pass that makes master v3 production-ready rather than merely merged — the same role
v13 played for v1 and v22 for v2, both of which caught real gaps that per-version verification had
missed.

This matters more than usual: there is no master v4 planned for some time, so whatever state v3
leaves behind is the state this app lives in.

## Why a separate version

Each of v23–v28 verifies its own slice. The failures that survive are the ones *between* slices:
v28 moves files and could silently break v27's downloads; v25's new upstream call is a new place to
leak the `VB-AUTH` token; v24's and v27's new endpoints are new chances to drop an owner filter.
Nothing in a per-version check looks there.

## Tasks

1. **Re-run the cross-user separation sweep.** `pytest backend/tests/test_ownership.py` plus
   `scripts/verify_separation_sse.sh` against a running stack, both from v22. Extend both to cover
   every surface v3 added:
   - `GET /api/tracks/{id}/attempts` (v24)
   - `GET /api/tracks/{id}/file` (v27) — including that a non-owner gets **404, not 403**
   - `POST /api/library/sort` and its status endpoint (v28) — admin-only
   Data separation is a security property that fails silently; a new query path is a new chance to
   drop the filter.
2. **Prove the v27 ↔ v28 interaction end to end**: download a track, run a real sort & move, then
   download the *same* track again and confirm the bytes still arrive and match. This is the single
   most likely v3 regression and no per-version check covers it.
3. **Prove downloads still work after everything.** Submit a real album on the final merged code,
   let it complete, and confirm: files on disk, full ID3 tags, ledger correct, all downloadable.
   v23 fixed the outage against v23's code — this confirms v24–v28 didn't quietly reintroduce it.
4. **Full multi-user pass on the deployed instance**: two real accounts, each seeing only their own
   queue, the admin's all-users toggle working, usernames rendering, the worker pill visible to a
   non-admin.
5. **Deploy and verify on the real host** via the v21 release pipeline. Confirm the migration chain
   applies cleanly, all services report healthy, and the library mount is present and writable by
   the container user (uid 1000 — `docs/GOTCHAS.md` and `docs/DEPLOYMENT.md`'s `chown` step).
6. **Documentation reconciliation** — everything v23–v28 invalidated:
   - `CLAUDE.md`: the v3 roadmap marked complete, plus any new locked decision or invariant. Keep it
     under ~250 lines; findings go to `docs/GOTCHAS.md`, not here (the standing rule from v14).
   - `docs/GOTCHAS.md`: one section per v3 version under a new "Master v3" heading, with topic-index
     entries. **Correct the stale v01–v13 entries this version's work disproved** — in place, with a
     dated note, never by deletion.
   - `docs/DEPLOYMENT.md`: the library mount, `chown` requirements, new admin settings.
   - `docs/LOCAL_DEV.md`: how to exercise sort & move locally without a real 120k library.
   - `.env.example` / `.env.dev.example`: every new variable.
   - `PRODUCT.md` and `frontend/src/DESIGN.md`: the new pages, the status pill, the download action.
7. **The closing re-read.** Go through every "Done when" bullet across `plan/master-v3/v23`–`v28`
   fresh and check each against evidence gathered *this session*. Both prior closes found real gaps
   this way; assume this one will too, and record what it finds rather than quietly fixing and
   moving on.
8. `graphify update .` — a full rebuild, since v23–v28 changed most of the backend.

## Done when

- The separation sweep passes with **zero** foreign rows or ids on every surface including the three
  new ones, evidenced by captured output rather than a summary claim. The SSE capture is attached,
  since it's the surface with no REST equivalent and the one that leaked by default before v17.
- The v27 ↔ v28 interaction is proven with a real checksum match after a real move.
- A real album downloads end to end on the final merged code, fully tagged and downloadable.
- Both real users work correctly on the **deployed** instance, not only locally.
- Every doc in task 6 is updated; no doc still describes behavior v3 changed.
- The closing re-read is done and its findings recorded — including anything found and *not* fixed,
  stated plainly rather than omitted.
- Both version files read `3.29.0`; `graphify update .`
