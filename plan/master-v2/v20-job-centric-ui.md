# v20 — Job-Centric UI

Branch: `dev-job-centric-ui` → PR into `main`

## Scope

The frontend rework that consumes v17–v19: job rows that expand to tracks, the job/track scope
toggle, search, sorting, a redesigned state filter, the archive view, and a per-user settings page.
This is the version the user actually experiences as "the app got usable".

Largest frontend change since v09, so it replaces `QueueTable.svelte` outright rather than
accreting onto it — the current component is built around a flat `trackList` and one of three
hardcoded filters, and bending it into a hierarchical paginated view would leave both models
half-present.

## What the user sees

**Default view — jobs.** One row per job: source (album/artist name, not the raw URL where
metadata is available), rollup status badge (`active` / `waiting` / `settled·complete` /
`settled·partial` / `failed` / `cancelled`), a segmented progress bar, and the count breakdown
(`1,204 done · 12 waiting · 1 not found`). A 3,000-track discography is **one line** until asked to
expand.

**Expanding a job** fetches that job's tracks paginated (v18's endpoint) — never all 3,000 at once.
Expansion state is per-row and survives filter changes within a session.

**Scope toggle** (`Jobs` | `Tracks`), sitting above the sort controls:
- `Jobs` — search/filter/sort run against jobs; results are collapsed job rows.
- `Tracks` — the same controls run against tracks; matching jobs **auto-expand** showing only their
  matching tracks. This is "find that one track somewhere in my history".

**Search box** — debounced, server-side, hits v18. Never filters only the loaded page; that would
make search silently lie about history.

**State filter** — every state selectable with live counts, replacing the three buttons. `settled ·
partial` is a first-class option ("finished, didn't get everything"). `lookup_failed` is labelled
**"Not found"**, never "Given up" — the behavior is unchanged from v1 (terminal, no auto-retry),
only the wording was misleading.

**Sorting** — clickable column headers, both directions, server-side (`sort`/`dir` params). Sorting
a paginated result client-side sorts one page, which is worse than not offering it.

**Archive** — an `include_archived` toggle beside the search box (off by default), plus per-job
archive/unarchive actions and a "clear log" button that calls `POST /api/jobs/archive` with
`all_settled`.

**Per-user settings** — retention window, on a page every user can reach. Separate from the
admin-only `/settings` (proxies, format/bitrate/template), which non-admins never see a link to and
get 403 from anyway (v17's server-side gate is the real control; hiding the link is cosmetic).

**Admin** — a "mine / all users" toggle, admin-only, adding an owner column when on.

## Constraints carried from v1 (non-negotiable, see `frontend/src/DESIGN.md`)

- **§2 — `--signal` (phosphor amber) marks things that are live right now, never permanent chrome.**
  A job row uses it only while genuinely active. v09's finish review already caught this exact
  misuse once.
- **§6 — mobile collapse is one cell per line below 640px.** v09 shipped two separate broken
  attempts at pairing cells on shared grid tracks before landing on this; a hierarchical job/track
  table is *more* prone to it, not less. Default straight to one-cell-per-line.
- The `updatedAt` secondary sort tiebreaker must survive in any client-side ordering that remains,
  or live-updating rows visibly "vanish" on state change (v09's gotcha).
- `TRULY_TERMINAL_STATES` guarding in `applyTrackEvent` must survive the store rewrite — it's what
  stops a cancelled track flickering back to `downloading` from a stray progress event (v10's
  gotcha, found twice, at two different layers).
- Every new route needs **both** the SvelteKit `ssr`/`prerender` exports **and** its own explicit
  nginx `location` block (v09/v12 — the `/login` 404 shipped for three versions because only one
  half was done).

## Tasks

1. Rewrite `lib/stores/queue.ts` around a paginated, server-filtered model: query params are the
   state, results are a page rather than a full mirror of the database. Keep the SSE-merge path and
   both gotcha guards above.
2. New `lib/components/JobRow.svelte` (rollup badge, progress bar, counts, actions) and
   `JobTrackList.svelte` (paginated tracks within an expanded job). Retire `QueueTable.svelte`.
3. New `lib/components/QueueControls.svelte`: scope toggle, search, state filter with counts, sort,
   archived toggle, admin all-users toggle.
4. `Waterfall.svelte` keeps showing only the caller's active tracks (v17 scoped the stream) — add a
   neutral "worker busy elsewhere" indicator sourced from `GET /api/worker/status` so an idle
   waterfall during someone else's download doesn't read as broken.
5. New `/account` route for per-user settings; `/settings` stays admin-only.
6. `api.ts`: typed wrappers for every v18/v19 endpoint and param.

## Done when

Verified in a real browser against the real stack (headless Playwright is acceptable for
regression, but the click-through must actually happen — v13's four real defects were all found by
manual clicking after `svelte-check`/`eslint`/`vite build` were already clean):

- A real ~3,000-track job renders as **one row**, expands to a paginated track list, and the page
  stays responsive throughout.
- Scope toggle: `Tracks` + a search term auto-expands matching jobs showing only matching tracks;
  `Jobs` returns collapsed rows. Both verified with a search that matches tracks across more than
  one job.
- Search finds a track that is **not on the first page** of any job — proving it's server-side over
  full history, not a client filter over loaded rows.
- Sorting reorders the whole result set, not just the current page (check by sorting descending and
  confirming the first row is the true extreme across all pages).
- State filter counts match the API's `counts_by_status`; `settled · partial` returns exactly the
  jobs with ≥1 non-completed terminal track.
- Archive: a job archived from the UI leaves the default view live (no reload), returns with the
  archived toggle on, and can be unarchived.
- Non-admin sees no `/settings` link and gets 403 on direct navigation; `/account` works for both
  roles. Admin's all-users toggle adds the owner column and other users' jobs.
- Mobile at 390px: real screenshots of a real populated table with **varied-length** titles and
  album names, expanded and collapsed. Both v09 mobile failures were invisible with short test data.
- Keyboard-only navigation end-to-end (PRODUCT.md hard requirement): scope toggle, search, filters,
  sort headers, and job expansion all reachable and operable via `Tab`/`Enter`/arrows, with a
  visible focus ring — screenshotted.
- `svelte-check` / `eslint` / `vite build` clean; new routes have both SvelteKit exports and nginx
  `location` blocks.
