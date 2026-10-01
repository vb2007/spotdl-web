# v34 — Live-State Hydration on Refresh

Branch: `dev-live-hydration` → PR into `main`
Version: `4.34.0`

## Scope

The owner's report: *add a new job, wait for it to start, refresh the page, and it's gone from the
"Active signal" section.*

The suspected mechanism, from reading the code (to be **proven**, not assumed):
`frontend/src/lib/stores/queue.ts` keeps two push-only stores.

- **`liveActive`** (`:119-129`) feeds `Waterfall.svelte` ("Active signal"). It is "SSE-fed only,
  never REST-loaded". A track enters it only on a `downloading` event.
- **`incoming`** (`:131-135`) feeds `IncomingJobs.svelte`. It holds jobs still `expanding`, or
  failed with zero tracks, and is fed by SSE plus the optimistic insert after submit.

`reload()` (`:243`) loads only `page`. `connectStream`'s `onopen` (`+page.svelte`) calls `reload()`
too. So after a hard refresh both stores start empty. A track already downloading reappears only
when its next event lands. A paced track may not send one for a long time: pacing happens before
the attempt, and the download's progress ticks come later. A job still expanding doesn't reappear
until its `job.state` event, and a failed-zero-track job never reappears at all.

## Tasks

1. **Reproduce every shape first**, on the real stack in a real browser, and record each:
   - (a) a job still `expanding` at refresh time (use a large playlist so expansion takes a while);
   - (b) a failed-zero-track job (a bad URL, for example a nonexistent track id, which yields the
     known `KeyError('uri')` failure);
   - (c) a track mid-download;
   - (d) a track `queued` and sitting in the pacing delay (set `PACING_MIN_SEC`/`PACING_MAX_SEC`
     high on dev).

   For each, capture what the UI shows after refresh and what `curl -N /api/stream` carries. If
   the root cause turns out to differ from the above, record that and fix the real one.
2. **Decide what "active" means for the reloaded view** and write it down in the store's comment:
   - Waterfall hydrates `downloading` tracks. `queued` tracks don't belong there today (the
     Waterfall represents a live lane), so case (d) is solved by showing what the worker is
     actually doing, not by inventing a lane.
   - **Verify** whether the worker publishes a `downloading` event before the pacing sleep (see
     `download_track`'s ordering in `backend/app/tasks/download.py`). If the paced track *is*
     already `downloading` in the database, hydration covers it. If it's still `queued`, decide
     whether the Waterfall should show "next up — pacing", and record the decision. Keep it
     minimal: one lane, no new semantics beyond what the backend already knows.
3. **Hydrate from REST, in one bulk request per store, on every `reload()`** (which already runs
   on every stream `onopen`):
   - Incoming: jobs in `expanding`, plus failed jobs with zero tracks. Use the existing jobs list
     endpoint with a status filter if one already expresses this (`rollup.status_where`).
     Otherwise add the narrowest filter needed.
   - Active: tracks in `downloading` (or whatever task 2 decided), through the existing tracks
     list endpoint's `state` filter, including title/artist/album so the Waterfall never renders
     "unknown" (v23's invariant).
   - Merge, don't clobber. An SSE event that arrived while the request was in flight must win over
     the older REST snapshot. Use the existing `pageFetchSeq`-style sequencing, or compare
     `updated_at`.
   - Respect admin all-users scope. `queue.setAllUsers` must re-hydrate under the new scope, and
     `queue.reset()` must clear everything v34 adds (the v22 invariant).
   - **No per-row request loop** (the CLAUDE.md invariant).
4. **Backend**, only if a filter is missing: add it owner-scoped through the same dependency every
   list endpoint uses, and add cross-user cases to `backend/tests/test_ownership.py` (non-owner
   sees nothing, admin all-users sees everyone's).

## Out of scope

- Any Waterfall redesign (v41).
- Replaying missed SSE events. The v08 contract stays: resync full state on (re)connect.

## Done when

- [ ] Each of the four shapes (a–d) was reproduced **before** the fix, with evidence of what
      disappeared, and the actual root cause recorded in GOTCHAS.
- [ ] After the fix, **each shape survives a hard reload in a real browser** (screenshots before
      and after reload, per shape): (a) the expanding job is still listed under incoming, (b) the
      failed job is still dismissible, (c) the downloading track is in Active signal with correct
      title, artist and progress, and (d) behaves per task 2's recorded decision.
- [ ] A stream reconnect (restart `api` while the page is open) re-hydrates the same way, with no
      duplicate lanes or rows.
- [ ] A race test: an SSE `downloading → completed` that lands while hydration is in flight
      doesn't resurrect the completed track (unit test on the store's merge, plus one live
      attempt).
- [ ] Admin all-users: hydrate under both scopes, and switch scope back and forth, with no
      cross-scope leakage (two real identities).
- [ ] Logout then a second identity on the same tab: no flash of the first identity's incoming or
      active rows (`queue.reset()` covers the new state).
- [ ] Cross-user REST: `pytest backend/tests/test_ownership.py` passes, with new cases for any new
      filter. `scripts/verify_separation_sse.sh` passes.
- [ ] One bulk request per store per reload (network panel screenshot or HAR count).
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `4.34.0`. `uv lock` is in sync. `graphify update .` has been run.
