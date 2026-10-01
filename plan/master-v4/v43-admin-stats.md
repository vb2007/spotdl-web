# v43 — Admin Stats Page

Branch: `dev-admin-stats` → PR into `main`
Version: `4.43.0`

## Scope

There's no way to see how downloads are actually going. Proving v31.1's `android_vr` block took a
manual CLI session, and nobody can tell whether IPv6 or the proxies are earning their place. The
data already exists: v24's `track_attempts` and v35's `network_path`/`error_type`/duration. This
version adds an **admin-only observability page** built on it, designed **through the impeccable
skill plus the dataviz skill**, born in the v40–v42 system.

## Backend

- `GET /api/admin/stats?window=24h|7d|30d`: admin-only, **non-admin gets 404** (not 403). It
  returns, aggregated **in SQL in a single request** (no per-proxy, per-path or per-day loops,
  per the bulk invariant):
  - attempts and success rate per `network_path` (direct-ipv4 / direct-ipv6 / proxy);
  - per proxy: attempts, success rate, last success, and current cooldown, by **redacted label
    only**;
  - failure counts by `error_type` over time (hourly buckets for 24h, daily for 7d/30d);
  - breaker trips over time, from a new **`breaker_events`** table (tripped, escalated, released,
    with step and timestamp) written at the existing trip point in
    `backend/app/services/retry.py`, the same hook v36's alert uses. Its migration includes a
    `DROP TYPE` if it adds an enum (CLAUDE.md invariant);
  - current queue depth by track state, and the oldest waiting track's age.
- Indexes on what the aggregation needs (`track_attempts.finished_at`, and `network_path` if
  needed). Check the real query plan with `EXPLAIN ANALYZE` on dev with realistic row counts.
- **Global by design.** Stats aggregate across all users. That's why it's admin-only. It returns no
  per-user identity, job title or track title, only counts.

## Frontend

- A new route, `/stats` (or `/admin/stats`), with the SvelteKit `ssr`/`prerender` exports **and** its
  own nginx `location` block (CLAUDE.md invariant: missing either ships a hard-navigation 404).
  Linked from the header for admins only.
- Load the dataviz skill before writing any chart. Charts follow its form heuristic and palette
  method, mapped onto DESIGN.md's state colors (success = settled, failure = fail).
- impeccable: a new surface in Operate mode. Scanability first, with the brand in the details.
- Window switcher (24h/7d/30d). Empty and low-data states (a fresh dev database has little).
- Every chart has an accessible text alternative (a table or summary), which v44's keyboard user
  also needs.

## Out of scope

- Per-user stats, or exposing stats to non-admins.
- Alert history (v36 sends alerts; it doesn't record them for display).
- Real-time chart updates over SSE. Fetch on load and on window change, plus a manual refresh.

## Done when

- [ ] The endpoint returns correct aggregates on dev. Check every metric against a hand-written SQL
      query on the same data (both outputs in the PR).
- [ ] One request per page load and per window change (network panel). `EXPLAIN ANALYZE` shows
      index use on the attempts aggregation.
- [ ] Non-admin: `GET /api/admin/stats` returns 404, and the `/stats` nav link is absent (two real
      sessions). A test in `test_ownership.py` (or the admin-gating suite) covers it.
- [ ] The response contains no titles, emails, usernames or proxy URLs (grep the response body).
      Proxy labels are redacted.
- [ ] `breaker_events` rows are written by a real induced trip and release on dev, and appear in
      the chart. The migration's `downgrade()` is clean (round-trip on dev).
- [ ] A hard navigation to `/stats` in the built nginx image (not just the Vite dev server)
      returns the page, not a 404.
- [ ] impeccable and dataviz were loaded, with output recorded. Desktop and mobile screenshots of
      populated, low-data and empty states.
- [ ] Charts have text alternatives (audit or accessibility-tree check).
- [ ] The v37 e2e suite passes, plus a new spec (admin sees stats, non-admin can't).
- [ ] `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read
      `4.43.0`. `uv lock` is in sync. `graphify update .` has been run.
