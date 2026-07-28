# Graph Report - .  (2026-07-28)

## Corpus Check
- Corpus is ~9,555 words - fits in a single context window. You may not need a graph.

## Summary
- 59 nodes · 56 edges · 13 communities (8 shown, 5 thin omitted)
- Extraction: 88% EXTRACTED · 11% INFERRED · 2% AMBIGUOUS · INFERRED: 6 edges (avg confidence: 0.78)
- Token cost: 94,440 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Retry & Backoff Engine|Retry & Backoff Engine]]
- [[_COMMUNITY_Compose Service Topology|Compose Service Topology]]
- [[_COMMUNITY_Planning & Config Docs|Planning & Config Docs]]
- [[_COMMUNITY_Track Scheduling & Schema|Track Scheduling & Schema]]
- [[_COMMUNITY_Downloader Execution|Downloader Execution]]
- [[_COMMUNITY_Proxy Rotation Strategy|Proxy Rotation Strategy]]
- [[_COMMUNITY_Live Progress Streaming|Live Progress Streaming]]
- [[_COMMUNITY_Auth Login Flow|Auth Login Flow]]
- [[_COMMUNITY_Auth Allowlist Gate|Auth Allowlist Gate]]
- [[_COMMUNITY_URL Expansion|URL Expansion]]
- [[_COMMUNITY_Spotdl Client Class|Spotdl Client Class]]
- [[_COMMUNITY_Upstream User Endpoint|Upstream User Endpoint]]
- [[_COMMUNITY_Deployment Hardening|Deployment Hardening]]

## God Nodes (most connected - your core abstractions)
1. `v06 — Retry Engine` - 7 edges
2. `CLAUDE.md — Project Durable Memory` - 5 edges
3. `v02 — Database Schema` - 5 edges
4. `v05 — Downloader` - 5 edges
5. `Global Circuit Breaker` - 5 edges
6. `Direct-First Proxy Escalation Strategy` - 4 edges
7. `v01 — Repo & Compose Scaffold` - 3 edges
8. `v07 — Proxy Rotation` - 3 edges
9. `v13 — Settings UI (Final)` - 3 edges
10. `Per-Track Retry Ladder` - 3 edges

## Surprising Connections (you probably didn't know these)
- `CLAUDE.md — Project Durable Memory` --shares_data_with--> `Locked Decisions Table`  [INFERRED]
  CLAUDE.md → plan/00-master-plan.md
- `README.md — spotdl-web summary` --conceptually_related_to--> `Direct-First Proxy Escalation Strategy`  [INFERRED]
  README.md → plan/00-master-plan.md
- `CLAUDE.md — Project Durable Memory` --references--> `Master Development Plan`  [EXTRACTED]
  CLAUDE.md → plan/00-master-plan.md
- `CLAUDE.md — Project Durable Memory` --references--> `v00 — Planning`  [EXTRACTED]
  CLAUDE.md → plan/v00-planning.md
- `README.md — spotdl-web summary` --conceptually_related_to--> `Per-Track Retry Ladder`  [INFERRED]
  README.md → plan/00-master-plan.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Docker Compose Stack Topology** — plan_00_master_plan_cloudflare_tunnel, plan_00_master_plan_sveltekit_frontend, plan_00_master_plan_fastapi_backend, plan_00_master_plan_postgresql, plan_00_master_plan_redis, plan_00_master_plan_worker_meta, plan_00_master_plan_worker_dl, plan_00_master_plan_celery_beat [EXTRACTED 1.00]
- **Durable Retry Engine (ladder + breaker + scheduled_at + beat)** — plan_00_master_plan_per_track_retry_ladder, plan_00_master_plan_global_circuit_breaker, plan_00_master_plan_scheduled_at_source_of_truth, plan_00_master_plan_dispatch_due_tracks, plan_00_master_plan_celery_eta_unsafe_rationale [EXTRACTED 1.00]
- **Server-to-Server Auth Flow With Allowlist Gate** — plan_00_master_plan_vb2007_auth_login_endpoint, plan_00_master_plan_auth_server_to_server_pattern, plan_00_master_plan_allowlist_authorization_gate, plan_00_master_plan_vb2007_auth_register_endpoint [EXTRACTED 1.00]

## Communities (13 total, 5 thin omitted)

### Community 0 - "Retry & Backoff Engine"
Cohesion: 0.20
Nodes (11): dispatch_due_tracks Celery Beat Task, Global Circuit Breaker, Per-Track Retry Ladder, spotdl AudioProviderError, spotdl LookupError, v06 — Retry Engine, Proxy cooldown_until Backoff, Manual Breaker Release ≠ Earned Recovery (+3 more)

### Community 1 - "Compose Service Topology"
Cohesion: 0.22
Nodes (9): Celery Beat, Cloudflare Tunnel / cloudflared, api (FastAPI: auth, jobs, SSE), PostgreSQL (host, source of truth), Redis (broker + pub/sub), web (SvelteKit, static adapter), worker-dl (Celery -Q downloads, concurrency=1), worker-dl Single-Concurrency Rationale (+1 more)

### Community 2 - "Planning & Config Docs"
Cohesion: 0.32
Nodes (8): CLAUDE.md — Project Durable Memory, Locked Decisions Table, Master Development Plan, Repository Layout, v00 — Planning, pydantic-settings Env Config, v01 — Repo & Compose Scaffold, v13 — Settings UI (Final)

### Community 3 - "Track Scheduling & Schema"
Cohesion: 0.33
Nodes (6): Celery ETA/Countdown Is Unsafe For Backoff, Dedup + Disk Reconciliation, tracks.scheduled_at as Source of Truth, Track State Machine, v02 — Database Schema, v11 — Job Priority / Reordering

### Community 4 - "Downloader Execution"
Cohesion: 0.40
Nodes (5): Cached Downloader Instances (format, bitrate, proxy), spotdl.download.downloader.Downloader class, spotdl DownloaderError, Downloader.search_and_download, v05 — Downloader

### Community 5 - "Proxy Rotation Strategy"
Cohesion: 0.40
Nodes (5): Pacing Hook (PACING_MIN_SEC/MAX_SEC), Direct-First Proxy Escalation Strategy, v07 — Proxy Rotation, pick_proxy() LRU Selection, Dual Proxy Source (file + manual coexistence)

### Community 6 - "Live Progress Streaming"
Cohesion: 0.50
Nodes (5): Downloader.progress_handler / notify_* hooks, SSE Heartbeat + Reconnect-Then-Refetch Pattern, Provider-Agnostic track.state Event Schema, v08 — Live Progress (SSE), v09 — Frontend

### Community 7 - "Auth Login Flow"
Cohesion: 0.67
Nodes (3): Server-to-Server Login Pattern, vb2007.hu-api POST /auth/login, v03 — Authentication

## Ambiguous Edges - Review These
- `v05 — Downloader` → `spotdl DownloaderError`  [AMBIGUOUS]
  plan/v05-downloader.md · relation: references

## Knowledge Gaps
- **26 isolated node(s):** `v03 — Authentication`, `v04 — URL Expansion`, `v10 — Queue Controls`, `v11 — Job Priority / Reordering`, `v12 — Deployment Hardening` (+21 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `v05 — Downloader` and `spotdl DownloaderError`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **Why does `v06 — Retry Engine` connect `Retry & Backoff Engine` to `Track Scheduling & Schema`, `Proxy Rotation Strategy`?**
  _High betweenness centrality (0.209) - this node is a cross-community bridge._
- **Why does `v07 — Proxy Rotation` connect `Proxy Rotation Strategy` to `Retry & Backoff Engine`, `Planning & Config Docs`?**
  _High betweenness centrality (0.172) - this node is a cross-community bridge._
- **Why does `Global Circuit Breaker` connect `Retry & Backoff Engine` to `Track Scheduling & Schema`?**
  _High betweenness centrality (0.159) - this node is a cross-community bridge._
- **What connects `v03 — Authentication`, `v04 — URL Expansion`, `v10 — Queue Controls` to the rest of the system?**
  _29 weakly-connected nodes found - possible documentation gaps or missing edges._