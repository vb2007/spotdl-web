# v54 — Admin "Other Users" View

Branch: `dev-scope-others` → PR into `main`
Version: `5.54.0`
Wave / slot: 1 / 4
Depends on: v50

## Scope

An admin can view "mine" or "all users". The owner wants a third option, **other users only**,
that excludes the admin's own items. Today the scope is a single boolean, `all_users`, threaded
through REST, counts, hydration, SSE and the store. This version turns it into a three-state
`view` end to end.

It also fixes **U1** (DESIGN §8.3): in the all-users view, other users' downloads warm the page
amber, even though amber means "live *for you*". The others view makes that contradiction
permanent, so it's fixed here.

## Tasks

1. **API.**
   - `view: Literal["mine","all","others"] = "mine"` on `GET /api/jobs`, `GET /api/tracks`,
     `GET /api/stream`, and the hydration calls (which reuse the list endpoints).
   - `all_users=true` stays as an alias for `view=all`. Specifying both → 422.
   - **A non-admin is always normalized to `mine`** (today's silent-ignore behavior is kept,
     tested).
2. **Listing predicates.**
   - `services/job_listing.py:83`: `mine` → `user_id == me`; `all` → no filter; `others` →
     `user_id != me`.
   - `services/track_listing.py:79` **and** `:90` (the job-status subquery) get the same
     predicate, applied identically.
   - `counts_by_status`/`counts_by_state` inherit it.
3. **SSE** (`routers/stream.py:27-55`).
   - `others` pattern-subscribes like `all`, and drops any `pmessage` whose channel equals
     `channel_for(me)`.
   - The unsubscribe branch matches.
   - Payloads stay owner-less on the wire (the v17 invariant); filtering is by channel only.
4. **Frontend.**
   - `allUsers: boolean` → `view: 'mine'|'all'|'others'` in `queue.ts`: `setView`/`getView`,
     query building, hydration and `reset()`.
   - Update `api.ts` params and `createEventSource(view)`.
   - `+page.svelte`: rename `allUsersView` → `view`. `onViewChange` keeps the existing
     close/clear/reconnect sequence.
   - In `others`, a job the admin just submitted is **not** optimistically inserted. Instead, show
     a one-line notice "added to your queue — switch to mine to see it" (en/hu).
   - `IncomingJobs.isOwn`, the owner labels and `JobRow` treat `others` like `all`.
5. **Control.**
   - `QueueControls`' segmented control becomes three options (mine / all / others), admin-only.
   - en/hu strings via impeccable `clarify`. Keep the existing control styling.
   - The empty-state and "reading" copy each get an `others` variant.
6. **Keyboard.**
   - Add a binding that cycles the view, admin-only, following the Hungarian QWERTZ rules
     (letter primary, no AltGr). Proposed: `Shift+V`. Check the registry for conflicts.
   - It appears in the help overlay (generated from the registry).
7. **URL state:** the view is reflected in the query string (`?view=others`), so a reload keeps
   it. A non-admin with `?view=` gets `mine`.
8. **U1 (amber).**
   - The page-level live warmth (the ambient glow tint and anything else keyed on "something is
     receiving") reacts only to the **viewer's own** active tracks in every view.
   - Other users' lanes in `all`/`others` render in a neutral "elsewhere" treatment, using
     impeccable `colorize`/`quieter`.
   - Update DESIGN.md §2/§8.3 with a dated note.

## Files owned

`backend/app/routers/{jobs,tracks}.py` (the list endpoints' `view` param only; v53 owns create),
`backend/app/routers/stream.py`, `backend/app/services/{job_listing,track_listing}.py`,
`frontend/src/lib/stores/queue.ts`, `frontend/src/lib/api.ts` (list/stream params),
`frontend/src/routes/+page.svelte`, `frontend/src/lib/components/{QueueControls,IncomingJobs,JobRow,Waterfall,AmbientField}.svelte`
(scope/amber bits only), `frontend/src/lib/keyboard/bindings.ts`, `frontend/src/DESIGN.md`,
message JSONs (hotspot), and the tests named below.

`routers/jobs.py` is also touched by v53 (create only). Keep the edits in separate functions; the
rebase protocol resolves the rest.

## Out of scope

Per-view stats. A per-user picker ("show user X"). Changing which jobs a sweep archives.

## Done when

- [ ] **REST:** for an admin with 2 own jobs and 3 jobs from two other users (real slot stack,
      three real identities):
  - `mine` = 2, `all` = 5, `others` = 3, for jobs and tracks scope;
  - `counts_by_*` match each view (curl outputs).
  - A non-admin with `view=all`/`others` gets only their own.
  - `all_users=true` still means `all`; `all_users` plus `view` → 422.
- [ ] **Tests updated and extended:** `test_ownership.py:171,184,200,238`,
      `test_job_listing.py:181`, `test_track_listing.py:139`, and `test_stream.py` (the fake
      pubsub gains `channel`; `others` drops own-channel messages). All green.
- [ ] **SSE wire check:** `scripts/verify_separation_sse.sh` extended with an `others` case. A raw
      `curl -N` capture shows the admin's own events absent under `others` and present under
      `all`.
- [ ] **UI:**
  - the three-way control works by mouse and keyboard (the new binding);
  - `?view=` survives reload;
  - the own-submit notice appears in `others`;
  - screenshots in en and hu, desktop and mobile.
- [ ] **U1:** with only another user downloading, the page shows no amber warmth in `all`/
      `others` (screenshot plus the computed tint). The viewer's own download warms it in every
      view. DESIGN.md has been updated.
- [ ] **Store reset:** logout from `others`, then log in as a non-admin on the same tab, shows no
      flash of the other view's rows (the e2e spec extended).
- [ ] Full e2e is green on desktop, mobile and `hu`, with a new others-view spec.
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `5.54.0`. `uv lock` is in sync. `graphify update .` has been run.
