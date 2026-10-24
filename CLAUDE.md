## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Project: spotdl-web

A self-hosted web wrapper around the **spotdl** Python library. Users submit Spotify
album/playlist/artist/track URLs; the app downloads everything in the background, treating
YouTube-Music rate limiting as an expected, permanent condition rather than a failure.

**Core goal: get everything by dodging rate limits, even if it takes an extremely long time.**
That inverts normal web-app priorities — durability beats throughput. A track may legitimately sit
in the queue for days, and that is correct behavior, not a stall.

**Status:** masters v1–v4 (v00–v48) are complete and shipping to `spotdl.vb2007.hu`. **Master v5 (v49–v69)
is in progress**: close every open gotcha, a Firefox extension, an admin "others" view, new features.

### Where things are

| What | Where |
|---|---|
| Current roadmap, open-items ledger, waves (and its Amendments) | `plan/master-v5/00-master-plan.md` |
| Per-version plans (finished masters' are historical, never edited) | `plan/master-vN/vNN-*.md`; agent prompt template `plan/master-v5/IMPLEMENTATION_PROMPT.md` |
| **Accumulated gotchas, v01–v48** | **`docs/GOTCHAS.md`** — read the relevant section (via its topic index, never end to end) before touching an area, and verify a referenced file or function still exists before acting on it |
| Deploy runbook (Debian host) / local dev runbook | `docs/DEPLOYMENT.md` / `docs/LOCAL_DEV.md` |
| CI (self-hosted runner) / release pipeline (versioning, GHCR, deploy, rollback) | `docs/CI_SELF_HOSTED_RUNNER.md` / `docs/RELEASE_PIPELINE.md` |
| Product brief / frontend design system | `PRODUCT.md` / `frontend/src/DESIGN.md` |

### Workflow rules (do not deviate without asking)

- **One feature per agent, in order.** Never one out of order (the sequencing is deliberate). From v5, up
  to 4 slices of the **same wave** run in parallel, each in its own worktree and slot stack, per the master
  plan's parallel model and rebase protocol (wave 0: v49 ∥ v50, v49 merged first). Subagents stay in a slice.
- **Branch per version**: `dev-<feature-name>` from `main`, one PR into `main` per version (a
  "version" is a feature slice, not a release).
- **"Done when" is a literal checklist.** Every bullet needs its own concrete evidence gathered *this
  session*; one scenario passing never proves a differently shaped one (v05's album, v11's bump
  endpoint). Re-read the plan's list fresh before saying merge-ready.
- **A PR isn't merge-ready until every change is re-tested against the real stack** (local compose,
  real Postgres, real network), not just `pytest`: unit tests pass while a fix fails on the real runtime.
- **Mocked verification is not verification.** A feature touching the network, a proxy or the
  database needs one real end-to-end run. Login included: at least one identity goes through the
  real upstream `vb2007.hu-api` (local `host.docker.internal:3000` if running, else
  `https://api.vb2007.hu`; register a fresh test account freely), not only the direct-session-mint
  fallback (`docs/GOTCHAS.md` v15). Skip only if neither is reachable, and say so explicitly.
- **Context comes from graphify, not exploration agents** (`query`/`path`/`explain` first; `update .` after code changes).
- **Every version slice bumps the one shared app version**: identical `major.minor.patch` (master .
  slice, e.g. v21 → `2.21.0`) in `backend/pyproject.toml` and `frontend/package.json`, both bumped even if
  one side changed, plus `uv lock`; CI's `version` job enforces it (a PR touching neither needs no bump,
  cuts no release; `extension/` has its own version). **A new
  required compose variable (`${VAR:?}`)** follows `docs/RELEASE_PIPELINE.md`'s "Adding a required
  env var" checklist and goes under the PR's "Deploy notes" (preflight and CI's drift check fail on it).
- **Develop locally, deploy to verify; minimize SSH** (the host runs Matrix/Synapse, Vaultwarden); batch host actions.

### Development environments

Two environments share the physical Postgres server but **never a database**: local dev uses
**`spotdlwebtest`**, production **`spotdlweb`** (v32). The dev override sets `SPOTDL_ENV=dev` on every
backend service, and `app/config.py` refuses to boot any of them, `migrate` included, against a
production database name (`spotdlweb`, also the templates' `spotdl_web`) or an unparseable URL.
Never remove the marker or set it in production (any value but `dev` is refused). Dev uses test identities only, the
dev `ADMIN_EMAIL` included, never the real admin account; create/reset steps are in `docs/LOCAL_DEV.md`'s "Dedicated dev database".

| | Local dev (`docs/LOCAL_DEV.md`) | Debian host (`docs/DEPLOYMENT.md`) |
|---|---|---|
| `.env` template | `.env.dev.example` | `.env.example` |
| Compose invocation | `docker compose up` (override applies — hot reload) | `docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel up -d --no-build` (the overlay is mandatory) |
| Postgres | Dev DB `spotdlwebtest`, reached over LAN by its real address | Prod DB `spotdlweb`, reached via `host.docker.internal` |

Redis and the other containers are per environment. The two `DATABASE_URL`s differ in host, database
name and role; never copy one's into the other.

## Locked decisions (settled — don't re-litigate without asking)

| Area | Decision |
|---|---|
| Backend | Python 3.12, FastAPI + Celery |
| Task queue | Celery + Redis (Redis dockerized) |
| Database | PostgreSQL, non-dockerized on the Debian 12 host |
| Frontend | SvelteKit + TypeScript |
| Live updates | SSE (WebSocket later if genuinely needed) |
| Ingress | Cloudflare Tunnel only — no port forwarding, ever |
| Auth | Server-to-server login proxy to `vb2007.hu-api`, own session cookie |
| Rate-limit handling | Per-track ladder **+** global circuit breaker |
| Proxy strategy | Direct first → on failure wait out the ladder → *then* proxy |
| Dedup | Global ledger keyed on Spotify track ID + disk reconciliation |
| Deployment | Docker Compose stack on Debian 12 |
| CI | Self-hosted GitHub Actions runner on the production host; chained in-run, no `workflow_run` (v49) |
| Worker concurrency | `worker-dl` stays `--concurrency=1` — concurrency *is* rate-limit exposure |

### Master v2 additions

| Area | Decision |
|---|---|
| User identity | Real `users` table, row created on first successful login. `ALLOWED_EMAILS` gates *who may log in*; the table governs *what they own and may do* |
| Admin | `is_admin` column seeded from `ADMIN_EMAIL` (which must also be in `ALLOWED_EMAILS` — validated at startup) |
| Data separation | **DB-level only.** Jobs/tracks are per-user; downloaded files stay in one shared library |
| Dedup under multi-user | Stays global — a track another user already downloaded resolves instantly as `skipped_duplicate`. Never re-fetch the same audio per user |
| Ownership column | On `jobs` only; tracks inherit via `job_id`. A denormalized copy would be a second source of truth that can drift |
| Queue fairness | Unchanged: global `jobs.priority DESC, scheduled_at ASC` |
| Settings split | Output config, proxies and worker controls are **admin-only**; per-user settings (retention, keyboard, language, clock) are open to everyone |
| `LookupError` | Terminal, never auto-retried. Only the UI label changed — "Not found", never "Given up" |
| Log retention | Soft-archive via `jobs.archived_at`, never hard delete. Per-user threshold |
| Live view | SSE scoped per user (`spotdl:events:{user_id}`) |
| Search/sort | Server-side, always. Cursor pagination, not offset |

### Master v4 additions

| Area | Decision |
|---|---|
| Production data | **Not disposable** (v2's "destructive migrations allowed" is over). No API back-compat needed, but a migration that drops/rewrites data says so in its plan and takes a `pg_backup` first |
| Alerts | One Matrix room (host's Synapse, bot token) for pipeline and app alerts (breaker, failure spike, stale beat, library sweep); unconfigured = off; an alert never blocks work and a failed send is dropped |
| Rollback | Restores the last healthy `persist=true` release's commit **and** tag together (`.last-good`); if the DB is ahead of it, falls back to the pre-deploy commit + tag when that knows the schema (v33.1); never across a migration the target doesn't know |
| UI work | Every UI slice goes through the impeccable skill; refinement of the existing world (v39). All monitoring information is kept for the **admin**; operator detail (breaker pill, full filters, attempt diagnostics, priority/bump, which the API also refuses a non-admin since v48) is admin-only and absent from non-admin DOM; non-admins get a simpler view |
| Browser tests | Playwright suite run locally against the real stack (desktop, mobile, `hu` projects); no CI browser job (the runner is the prod host) |
| Keyboard | Full mouse-free operation, bindings designed for **Hungarian QWERTZ** (no AltGr, no `Y`/`Z`, match `event.key`); single-key shortcuts inert in text inputs and turn-off-able per user; every new interactive element is keyboard-reachable |
| i18n | `hu` + `en`, full coverage, every new string in both message files. Signed out the browser decides (`navigator.languages` → `en`); signed in, a language saved on `/account` wins, and its "automatic" choice follows the browser again (no `/login` switch, nothing adopted at sign-in). Formats = UI language + browser region, with a per-user 12h/24h override by the same rules. Backend stays language-neutral (error `code`s); track metadata/raw errors/alerts/logs untranslated |
| Library sweep scope | A sweep repoints every user's moved tracks but archives only the **sweeping admin's own** settled jobs (v48, F34) |

### Master v5 additions

| Area | Decision |
|---|---|
| Parallel agents | ≤4 per wave, own worktree + compose project + **local Postgres container** each (never the LAN DB); `worker-dl` only under the host-wide realdl lock; owner merges a wave in slice order; version must rise |
| Firefox extension | `extension/`, MV3, own semver (`manifest.json`), AMO-signed unlisted XPI; session cookie first, per-user API key fallback; keys only submit + `me`, never admin; Spotify-URL allowlist, cascades resolved server-side |
| Admin scope | `view = mine \| all \| others` (admin only; `all_users` = alias of `all`) |

## Architecture

```
Cloudflare Tunnel ──> cloudflared ──> web (SvelteKit + nginx, same-origin /api proxy)
                                         └─> api (FastAPI: auth, jobs, SSE)
                                                │
      ┌─────────────────────────────────────────┼──────────────────────────┐
      │                                         │                          │
  PostgreSQL                                 Redis                 worker-meta (-Q meta: beat housekeeping,
 (host, source of truth)              (broker + pub/sub)            alert sends)
      │                                         │                  worker-expand (-Q expand: expansion,
      │                                         │                   library sweep; v34.1)
      │                                         │                  worker-dl  (-Q downloads, --concurrency=1)
      └──── scheduled_at ──── beat (dispatch_due_tracks, every 30s)
```

### Invariants — break these and things fail silently

- **Never use Celery `eta`/`countdown` for backoff.** ETA tasks are prefetched into worker memory;
  a restart during a 24h wait loses or duplicates them. `tracks.scheduled_at` in Postgres is the
  *only* schedule source of truth; beat polls it and Celery is purely the executor.
- **`worker-dl` runs `--concurrency=1 --prefetch-multiplier=1`.** Deliberate.
- **Every spotdl entry point goes through `expansion._ensure_spotify_client()`.** `SpotifyClient`
  is a process-wide singleton that raises on a second `.init()`.
- **Every proxy URL that is logged or persisted goes through `proxies.redact()`.** spotdl's own
  error messages echo credentials.
- **Every enum column uses `values_callable`**, and every migration creating a native enum has an
  explicit `DROP TYPE` in `downgrade()`.
- **Every frontend route needs both the SvelteKit `ssr`/`prerender` exports and its own nginx
  `location` block.** Missing either half ships a 404 that only appears on hard navigation.
- **Compose override files merge list keys and replace mapping keys.** Use `!override` when a list
  must replace. Verify with `docker compose config`, never assume.
- **Never load queue data with a per-job or per-row request loop.** One bulk request, always.

### Master v2 invariants

- **Data separation is a security property; it fails silently.** Any change to queries, endpoints
  or events re-runs `pytest backend/tests/test_ownership.py` plus the gating cases in `test_jobs.py`,
  `test_settings_retention.py`, `test_proxies_router.py`, `test_worker.py`, `test_settings_router.py`
  and `test_stats.py`, **and** `scripts/verify_separation_sse.sh` against a running stack, covering
  **direct-id endpoints**. Non-owner access returns **404, not 403** (admin endpoints answer a
  non-admin 403, except `/api/admin/stats` and the test-alert send, which 404). A module-level frontend store is a data surface
  too: reset it on logout or identity change (`queue.reset()`), never just re-fetch.
- **The SSE stream is a data surface.** `publish_*_event` takes the owning user as a **required**
  argument; verify by raw-capturing `curl -N /api/stream`, never via the UI.
- **`downloaded_tracks` is never touched by archiving or retention** (a dropped ledger row means a
  re-download). **A `waiting` job is never archived on age alone**: eligibility is measured from the
  newest track `updated_at`, not `job.created_at`.

### Master v3 invariants

- **Nothing is ever deleted on the target library filesystem** (`/mnt/raid1/media/music`). The sort
  & move deletes only the *source copy* on the downloads volume, after the target is confirmed.
- **Moving a file must repoint `downloaded_tracks.file_path`** in the same transaction — for every
  ledger row sharing that file (v48). `reconcile_disk()` prunes rows whose file is missing, and a
  move looks exactly like a deletion — get this wrong and the track silently re-downloads.
- **"Already exists" is folder + filename only** — never content, bitrate or duration (a re-download
  at another bitrate still counts as present).
- **File-download availability keys on the file existing at its recorded path, never on
  `archived_at`.** A retention-archived job still has its file and stays downloadable.
- **`yt-dlp` and `yt-dlp-ejs` float to latest together** (v23.1, PO tokens); everything else is pinned.
- **Proxy escalation does not cover IP-reputation bot-checks** (v23; v29 adds the other IP family as a
  rung). **A proxy/family flag reaching `download_track` is not proof it reached the network** (until v30
  every "proxy" attempt went out directly): verify the real destination (`socket.connect`/tcpdump).

## Track state machine

```
pending ──> queued ──> downloading ──> completed
                │            │
                │            ├─> AudioProviderError ─> waiting (scheduled_at = now + ladder)
                │            │                          └─> queued (via beat) ... ∞
                │            ├─> LookupError ──────────> lookup_failed  (terminal, never retried)
                │            └─> other error ─────────> waiting (same ladder)
                └─> skipped_duplicate
any ──> cancelled
```

### Retry engine numbers

- **Per-track ladder** (`AudioProviderError`): `15m → 1h → 4h → 12h → 24h`, then 24h forever.
  Never gives up. `LADDER_SECONDS` overrides it for testing.
- **Global circuit breaker**: 5 consecutive breaker-feeding failures (`audio_provider` or
  `no_output`, any track) trip a pause — `30m → 2h → 6h` escalating. Every trip and every manual
  release starts a fresh streak; escalation resets only on the first success (v40.1). While
  tripped, `dispatch_due_tracks` dispatches nothing. Terminal verdicts and proxy transport failures
  never feed it.
- **Proxy escalation**: attempt 1 is always direct. On failure, wait out the ladder delay *first*;
  only the following attempt uses a proxy. A failing proxy gets its own `cooldown_until`. A proxy
  is TCP-probed before use, and a proxied attempt that dies at its proxy doesn't consume the
  track's rung (v40.1).
- **Pacing hook** (`PACING_MIN_SEC`/`PACING_MAX_SEC`, `MAX_SEC=0` = off, `MIN` > `MAX` rejected at
  startup): randomized delay in `download_track` after the cancel/breaker/dedup gates, before the
  attempt. The first dial to turn if 429s stay frequent; raising it means also raising
  `STALE_TRACK_AFTER_SECONDS` (beat's stale sweep can't tell "paced" from "stuck").

### Job rollup status (v2) — two derived axes, never one stored flag

**Lifecycle**: `expanding` · `failed` (expansion errored, zero tracks) · `cancelled` · `active`
(≥1 track `pending`/`queued`/`downloading`) · `waiting` (no active, ≥1 `waiting`) · `settled` (all
terminal). **Outcome**, only once `settled`: `complete` (all `completed`/`skipped_duplicate`) vs
`partial` (≥1 `lookup_failed`/`cancelled`): a 10-track album with 1 `LookupError` is "Done — 9 of
10", never "failed" or a bare green tick. Both axes are derived in SQL, never stored.

## Version roadmap

Masters v1–v4 (v00–v48) are complete; master v5 (v49–v69, waves 0–6) is in progress. Slices live in
`plan/master-vN/` (patch slices in that master's Amendments); findings in `docs/GOTCHAS.md`.

## Maintaining this file

Loaded into **every** session's context: keep it under ~250 lines, holding only what an agent must
know *before* doing anything (rules, locked decisions, invariants, where to find the rest).
- **New findings and war stories go in `docs/GOTCHAS.md`** under a version heading, with a one-line
  entry in its topic index (a stale gotcha is corrected in place with a dated note, never deleted).
- **Change this file only when a rule, locked decision, invariant, or roadmap position changes**,
  editing the existing line, never appending a section or a session summary.
