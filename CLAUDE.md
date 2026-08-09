## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

---

## Project: spotdl-web

A self-hosted web wrapper around the **spotdl** Python library. Users submit Spotify
album/playlist/artist/track URLs; the app downloads everything in the background, treating
YouTube-Music rate limiting as an expected, permanent condition rather than a failure.

**Core goal: get everything by dodging rate limits, even if it takes an extremely long time.**
That inverts normal web-app priorities — durability beats throughput. A track may legitimately sit
in the queue for days, and that is correct behavior, not a stall.

**Status:** master v1 (v00–v13) is complete, merged, and deployed at `spotdl.vb2007.hu`.
Current work is **master v2 (v14–v21)**: multi-user support, job/track hierarchy, search/archive.

### Where things are

| What | Where |
|---|---|
| Current roadmap + rationale | `plan/master-v2/00-master-plan.md` |
| Per-version implementation detail | `plan/master-v2/vNN-*.md` (v14–v21) |
| Master v1 plans (historical, never edited) | `plan/master-v1/` |
| **Accumulated gotchas from v01–v13** | **`docs/GOTCHAS.md`** — indexed by topic; read the relevant section before touching an area |
| Deploy runbook (Debian host) | `docs/DEPLOYMENT.md` |
| Local dev runbook | `docs/LOCAL_DEV.md` |
| CI (self-hosted runner) | `docs/CI_SELF_HOSTED_RUNNER.md` |
| Product brief / UX requirements | `PRODUCT.md` |
| Frontend design system | `frontend/src/DESIGN.md` |

`docs/GOTCHAS.md` is the single most useful file when you hit something surprising. It records
*why* things are the way they are and the failure modes already paid for. Don't read it end to end —
use its topic index. Its entries describe the code as of v13; **verify a referenced file or
function still exists before acting on it**, since v2 changes schema, endpoints, and the frontend.

### Workflow rules (do not deviate without asking)

- **One feature at a time.** Work through `plan/master-vN/vNN-*.md` in order. Never implement two
  versions in parallel. Subagents work *within* a version, on that version's single concern.
- **Branch per version**: `dev-<feature-name>`, branched from `main`. Every completed version opens
  a PR into `main`. A "version" is a feature slice, not a release.
- **Do not start a version out of order** without asking — the sequencing is deliberate (schema
  before enforcement, ownership before the API rework, UI last).
- **"Done when" is a literal checklist, not a vibe.** Every bullet needs its own concrete evidence
  (a log line, command output, a file listing) gathered *this session*. Testing one scenario and
  assuming a differently-shaped one also works is how regressions reach "merge-ready" — this has
  bitten the project twice (v05's untested album, v11's untested bump endpoint). Re-read the plan's
  list fresh before saying merge-ready.
- **A PR isn't merge-ready until every change on it has been re-tested against the real stack** —
  the local `docker compose` stack, real Postgres, real network. Not just `pytest`. Unit tests pass
  while a fix still fails against the real dialect or runtime.
- **Mocked verification is not verification.** If a feature touches the network, a proxy, or the
  database, at least one real end-to-end run is required before it ships.
- **Context comes from graphify, not exploration agents.** Run `graphify query` / `path` / `explain`
  before searching manually. Run `graphify update .` after every code-modifying version.
- **Develop locally, deploy to verify.** The local stack is the iteration loop; the Debian host is
  a final-verification target, not a place to chase build errors one SSH round trip at a time. Only
  debug there for genuinely host-specific issues (shared Postgres, tunnel/ingress, restart survival).
- **Keep this file current — but keep it short.** See "Maintaining this file" at the bottom.

### Development environments

Two environments share the physical Postgres server **and currently the same database on it**.
Revisit once there's data worth protecting; everything else about the split stays the same.

| | Local dev (`docs/LOCAL_DEV.md`) | Debian host (`docs/DEPLOYMENT.md`) |
|---|---|---|
| Purpose | Day-to-day iteration | Final per-version verification + real deployment |
| `.env` template | `.env.dev.example` | `.env.example` |
| Compose invocation | `docker compose up` (override applies — hot reload) | `docker compose -f docker-compose.yml up` |
| Postgres | Same server, reached over LAN by its real address | Same server, reached via `host.docker.internal` |
| Redis, other containers | Fully local, independent per environment | Fully local, independent per environment |

`DATABASE_URL`'s host is the one genuine difference between the two templates. Never copy
`host.docker.internal` into the local one (Postgres isn't on the local containers' host) or a
hardcoded LAN IP into the production one.

---

## Locked decisions

Settled. Don't re-litigate without asking.

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
| CI | Self-hosted GitHub Actions runner on the production host |
| Worker concurrency | `worker-dl` stays `--concurrency=1` — concurrency *is* rate-limit exposure |

### Master v2 additions

| Area | Decision |
|---|---|
| Backward compatibility | **None required.** The DB holds only POC data; destructive migrations are allowed |
| User identity | Real `users` table, row created on first successful login. `ALLOWED_EMAILS` gates *who may log in*; the table governs *what they own and may do* |
| Admin | `is_admin` column seeded from `ADMIN_EMAIL` (which must also be in `ALLOWED_EMAILS` — validated at startup) |
| Data separation | **DB-level only.** Jobs/tracks are per-user; downloaded files stay in one shared library |
| Dedup under multi-user | Stays global — a track another user already downloaded resolves instantly as `skipped_duplicate`. Never re-fetch the same audio per user |
| Ownership column | On `jobs` only; tracks inherit via `job_id`. A denormalized copy would be a second source of truth that can drift |
| Queue fairness | Unchanged: global `jobs.priority DESC, scheduled_at ASC` |
| Settings split | Output config, proxies and worker controls are **admin-only**; per-user settings (retention) are open to everyone |
| `LookupError` | Terminal, never auto-retried. Only the UI label changed — "Not found", never "Given up" |
| Log retention | Soft-archive via `jobs.archived_at`, never hard delete. Per-user threshold |
| Live view | SSE scoped per user (`spotdl:events:{user_id}`) |
| Search/sort | Server-side, always. Cursor pagination, not offset |

---

## Architecture

```
Cloudflare Tunnel ──> cloudflared ──> web (SvelteKit + nginx, same-origin /api proxy)
                                         └─> api (FastAPI: auth, jobs, SSE)
                                                │
      ┌─────────────────────────────────────────┼──────────────────────────┐
      │                                         │                          │
  PostgreSQL                                 Redis                 worker-meta (-Q meta)
 (host, source of truth)              (broker + pub/sub)           worker-dl  (-Q downloads,
      │                                         │                   --concurrency=1)
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

- **Data separation is a security property.** It fails silently — the UI looks right to everyone
  until someone spots a stranger's album. Any change to queries, endpoints, or events must re-run
  the cross-user sweep, and must cover **direct-id endpoints**, not just list endpoints. Non-owner
  access returns **404, not 403**, so an id's existence is never confirmed.
- **The SSE stream is a data surface.** Before v17 it broadcast every user's ids to every client.
  `publish_*_event` takes the owning user as a **required** argument so a new call site can't
  silently fall back to broadcasting. Verify by raw-capturing `curl -N /api/stream`, never via the UI.
- **`downloaded_tracks` is never touched by archiving or retention.** It's the dedup ledger; if
  archiving dropped a row it would cause a re-download — extra rate-limit exposure, the one thing
  this app exists to avoid.
- **A `waiting` job is never archived on age alone.** It's deliberately in a 24h ladder step.
  Eligibility is measured from the newest track `updated_at`, not `job.created_at`.

---

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
- **Global circuit breaker**: 5 consecutive `AudioProviderError`s (any track) trips a pause —
  `30m → 2h → 6h` escalating; resets to zero on the first success. While tripped,
  `dispatch_due_tracks` dispatches nothing. Only real `AudioProviderError`s feed it.
- **Proxy escalation**: attempt 1 is always direct. On failure, wait out the ladder delay *first*;
  only the following attempt uses a proxy. A failing proxy gets its own `cooldown_until`.
- **Pacing hook** (`PACING_MIN_SEC`/`PACING_MAX_SEC`): randomized inter-track delay, applied in
  `download_track` after the cancel/breaker/dedup gates and before the actual attempt. `MAX_SEC=0`
  (default) means off; `MIN` must not exceed `MAX` (rejected at startup). The first dial to turn if
  429s stay frequent. Raising it means also raising `STALE_TRACK_AFTER_SECONDS` — pacing lengthens
  how long a dispatched batch's tail sits `QUEUED`, and beat's stale-track sweep can't tell "paced"
  from "stuck".

### Job rollup status (v2) — two derived axes, never one stored flag

**Lifecycle**: `expanding` · `failed` (expansion errored, zero tracks) · `cancelled` · `active`
(≥1 track `pending`/`queued`/`downloading`) · `waiting` (no active, ≥1 `waiting`) · `settled` (all
terminal).

**Outcome**, only once `settled`: `complete` (all `completed`/`skipped_duplicate`) vs `partial`
(≥1 `lookup_failed`/`cancelled`).

A 10-track album with 1 `LookupError` is `settled · partial` — "Done — 9 of 10", never "failed"
(90% succeeded) and never a bare green tick (a real gap hidden). Both axes are derived in SQL from
per-state counts; a stored column would need updating from every path that touches a track state
and would be wrong the moment one forgot.

---

## Version roadmap

**Master v1 — complete, merged, deployed.** v00 planning · v01 scaffold · v02 db-schema ·
v03 auth · v04 url-expansion · v05 downloader · v06 retry-engine · v07 proxy-rotation ·
v08 live-progress · v09 frontend · v10 queue-controls · v11 priority · v12 deploy-hardening ·
v13 settings-ui. Detail in `plan/master-v1/`, findings in `docs/GOTCHAS.md`.

**Master v2 — in progress.**

| # | Branch | Scope |
|---|---|---|
| v14 | `dev-v1-audit` | Read-only audit of v1's code vs its plans; plan reorg. No app code changes |
| v15 | `dev-v1-gap-fixes` | **Done.** Pacing hook wired, `list_jobs` N+1 collapsed, stale docs fixed, proxy settings polling, real-stack playlist/album-dedup verification. Deferred: `TrackState.FAILED` removal (v16, needs a migration), `list_tracks` pagination (v18) |
| v16 | `dev-users-schema` | `users`, `user_settings`, `jobs.user_id`/`archived_at`. Schema only |
| v17 | `dev-multi-user-auth` | User creation, admin seeding, owner-scoped queries, admin gating, per-user SSE |
| v18 | `dev-job-centric-api` | Paginated/filtered/sorted/searchable endpoints; rollup status in one query |
| v19 | `dev-archive-retention` | `archived_at` lifecycle, per-user retention, "clear log", hourly sweep |
| v20 | `dev-job-centric-ui` | Job rows expanding to tracks, scope toggle, search, sorting, `/account` |
| v21 | `dev-multi-user-hardening` | Adversarial two-user verification, prod migration, doc reconciliation |

---

## Maintaining this file

This file is loaded into **every** session's context. Keep it under ~250 lines. It holds only what
an agent must know *before* doing anything: rules, locked decisions, invariants, and where to find
the rest.

- **New findings, bugs, and war stories go in `docs/GOTCHAS.md`**, not here. Add them under a
  version heading with enough detail to be actionable, and add a one-line entry to that file's
  topic index.
- **Change this file only when a rule, locked decision, invariant, or roadmap position changes** —
  and then edit the existing line rather than appending a new section.
- **Never append a session summary here.** If something learned this session doesn't change a rule,
  it belongs in `docs/GOTCHAS.md` or the PR description.
- When a gotcha turns out to be stale, correct it in place with a dated note rather than deleting
  it — knowing a past claim was wrong is itself worth keeping.
