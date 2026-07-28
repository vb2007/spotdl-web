# Graph Report - spotdl-web  (2026-07-28)

## Corpus Check
- 42 files · ~12,783 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 262 nodes · 190 edges · 79 communities (32 shown, 47 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 1 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8a379a70`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

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
- [[_COMMUNITY_devDependencies|devDependencies]]
- [[_COMMUNITY_Project spotdl-web|Project: spotdl-web]]
- [[_COMMUNITY_scripts|scripts]]
- [[_COMMUNITY_compilerOptions|compilerOptions]]
- [[_COMMUNITY_Tables|Tables]]
- [[_COMMUNITY_v03 — Authentication|v03 — Authentication]]
- [[_COMMUNITY_v06 — Retry Engine|v06 — Retry Engine]]
- [[_COMMUNITY_v00 — Planning|v00 — Planning]]
- [[_COMMUNITY_v01 — Repo & Compose Scaffold|v01 — Repo & Compose Scaffold]]
- [[_COMMUNITY_v04 — URL Expansion|v04 — URL Expansion]]
- [[_COMMUNITY_v05 — Downloader|v05 — Downloader]]
- [[_COMMUNITY_v07 — Proxy Rotation|v07 — Proxy Rotation]]
- [[_COMMUNITY_v08 — Live Progress (SSE)|v08 — Live Progress (SSE)]]
- [[_COMMUNITY_v09 — Frontend|v09 — Frontend]]
- [[_COMMUNITY_v10 — Queue Controls|v10 — Queue Controls]]
- [[_COMMUNITY_v11 — Job Priority  Reordering|v11 — Job Priority / Reordering]]
- [[_COMMUNITY_v12 — Deployment Hardening|v12 — Deployment Hardening]]
- [[_COMMUNITY_v13 — Settings UI (Final)|v13 — Settings UI (Final)]]
- [[_COMMUNITY_sv|sv]]
- [[_COMMUNITY_$libassetsfavicon.svg|$lib/assets/favicon.svg]]
- [[_COMMUNITY_eslint.config.js|eslint.config.js]]
- [[_COMMUNITY_prettier.config.js|prettier.config.js]]
- [[_COMMUNITY_app.d.ts|app.d.ts]]
- [[_COMMUNITY_CLAUDE.md — Project Durable Memory|CLAUDE.md — Project Durable Memory]]
- [[_COMMUNITY_spotdl-web-backend|spotdl-web-backend]]
- [[_COMMUNITY_Cloudflare Tunnel  cloudflared|Cloudflare Tunnel / cloudflared]]
- [[_COMMUNITY_Dedup + Disk Reconciliation|Dedup + Disk Reconciliation]]
- [[_COMMUNITY_api (FastAPI auth, jobs, SSE)|api (FastAPI: auth, jobs, SSE)]]
- [[_COMMUNITY_Global Circuit Breaker|Global Circuit Breaker]]
- [[_COMMUNITY_Master Development Plan|Master Development Plan]]
- [[_COMMUNITY_Per-Track Retry Ladder|Per-Track Retry Ladder]]
- [[_COMMUNITY_PostgreSQL (host, source of truth)|PostgreSQL (host, source of truth)]]
- [[_COMMUNITY_Direct-First Proxy Escalation Strategy|Direct-First Proxy Escalation Strategy]]
- [[_COMMUNITY_Redis (broker + pubsub)|Redis (broker + pub/sub)]]
- [[_COMMUNITY_tracks.scheduled_at as Source of Truth|tracks.scheduled_at as Source of Truth]]
- [[_COMMUNITY_spotdl AudioProviderError|spotdl AudioProviderError]]
- [[_COMMUNITY_spotdl.download.downloader.Downloader class|spotdl.download.downloader.Downloader class]]
- [[_COMMUNITY_spotdl DownloaderError|spotdl DownloaderError]]
- [[_COMMUNITY_spotdl LookupError|spotdl LookupError]]
- [[_COMMUNITY_Downloader.search_and_download|Downloader.search_and_download]]
- [[_COMMUNITY_SSE Heartbeat + Reconnect-Then-Refetch Pattern|SSE Heartbeat + Reconnect-Then-Refetch Pattern]]
- [[_COMMUNITY_web (SvelteKit, static adapter)|web (SvelteKit, static adapter)]]
- [[_COMMUNITY_vb2007.hu-api POST authlogin|vb2007.hu-api POST /auth/login]]
- [[_COMMUNITY_vb2007.hu-api POST authregister|vb2007.hu-api POST /auth/register]]
- [[_COMMUNITY_worker-dl (Celery -Q downloads, concurrency=1)|worker-dl (Celery -Q downloads, concurrency=1)]]
- [[_COMMUNITY_worker-dl Single-Concurrency Rationale|worker-dl Single-Concurrency Rationale]]
- [[_COMMUNITY_worker-meta (Celery -Q meta)|worker-meta (Celery -Q meta)]]
- [[_COMMUNITY_pydantic-settings Env Config|pydantic-settings Env Config]]
- [[_COMMUNITY_pick_proxy() LRU Selection|pick_proxy() LRU Selection]]
- [[_COMMUNITY_Proxy cooldown_until Backoff|Proxy cooldown_until Backoff]]
- [[_COMMUNITY_Provider-Agnostic track.state Event Schema|Provider-Agnostic track.state Event Schema]]
- [[_COMMUNITY_Manual Breaker Release ≠ Earned Recovery|Manual Breaker Release ≠ Earned Recovery]]
- [[_COMMUNITY_Priority-Ordered Dispatch (ORDER BY jobs.priority DESC)|Priority-Ordered Dispatch (ORDER BY jobs.priority DESC)]]
- [[_COMMUNITY_Dual Proxy Source (file + manual coexistence)|Dual Proxy Source (file + manual coexistence)]]
- [[_COMMUNITY_README.md — spotdl-web summary|README.md — spotdl-web summary]]
- [[_COMMUNITY_Deploying spotdl-web (v01 — scaffold) to the Debian 12 host|Deploying spotdl-web (v01 — scaffold) to the Debian 12 host]]

## God Nodes (most connected - your core abstractions)
1. `compilerOptions` - 11 edges
2. `Deploying spotdl-web (v01 — scaffold) to the Debian 12 host` - 11 edges
3. `spotdl-web — Master Development Plan` - 10 edges
4. `scripts` - 9 edges
5. `Project: spotdl-web` - 9 edges
6. `Tables` - 7 edges
7. `v03 — Authentication` - 6 edges
8. `v06 — Retry Engine` - 6 edges
9. `Settings` - 5 edges
10. `Architecture` - 5 edges

## Surprising Connections (you probably didn't know these)
- `health()` --calls--> `get_settings()`  [INFERRED]
  backend/app/routers/health.py → backend/app/config.py

## Import Cycles
- None detected.

## Communities (79 total, 47 thin omitted)

### Community 2 - "Planning & Config Docs"
Cohesion: 0.10
Nodes (17): Architecture, Auth API — verified findings, Context, Locked decisions, Other architectural notes, Repository layout, Retry engine, spotdl 4.5.2 — verified API surface (+9 more)

### Community 12 - "Deployment Hardening"
Cohesion: 0.14
Nodes (9): get_settings(), Settings, Base, get_db(), health(), BaseSettings, DeclarativeBase, Response (+1 more)

### Community 13 - "devDependencies"
Cohesion: 0.12
Nodes (17): devDependencies, eslint, eslint-config-prettier, @eslint/js, eslint-plugin-svelte, globals, prettier, prettier-plugin-svelte (+9 more)

### Community 14 - "Project: spotdl-web"
Cohesion: 0.18
Nodes (10): Architecture, Auth API — `vb2007.hu-api` (verified from `/home/vb2007/code/vb2007.hu-api` source), graphify, Locked decisions, Project: spotdl-web, Retry engine numbers, spotdl 4.5.2 — verified API surface actually used, Track state machine (+2 more)

### Community 15 - "scripts"
Cohesion: 0.14
Nodes (13): name, private, scripts, build, check, check:watch, dev, format (+5 more)

### Community 16 - "compilerOptions"
Cohesion: 0.15
Nodes (12): compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, moduleResolution, resolveJsonModule, rewriteRelativeImportExtensions (+4 more)

### Community 17 - "Tables"
Cohesion: 0.17
Nodes (11): Done when, `downloaded_tracks`, `jobs`, `proxies`, Scope, `sessions`, Tables, Tasks (+3 more)

### Community 18 - "v03 — Authentication"
Cohesion: 0.29
Nodes (6): Done when, Files touched (new), Scope, Tasks, v03 — Authentication, Why server-to-server (recap from master plan)

### Community 19 - "v06 — Retry Engine"
Cohesion: 0.29
Nodes (6): Done when, Files touched (new), Scope, Tasks, v06 — Retry Engine, Why not Celery `eta`/`countdown`

### Community 20 - "v00 — Planning"
Cohesion: 0.33
Nodes (5): Done when, Files touched, Scope, Tasks, v00 — Planning

### Community 21 - "v01 — Repo & Compose Scaffold"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v01 — Repo & Compose Scaffold

### Community 22 - "v04 — URL Expansion"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v04 — URL Expansion

### Community 23 - "v05 — Downloader"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v05 — Downloader

### Community 24 - "v07 — Proxy Rotation"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v07 — Proxy Rotation

### Community 25 - "v08 — Live Progress (SSE)"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v08 — Live Progress (SSE)

### Community 26 - "v09 — Frontend"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v09 — Frontend

### Community 27 - "v10 — Queue Controls"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v10 — Queue Controls

### Community 28 - "v11 — Job Priority / Reordering"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v11 — Job Priority / Reordering

### Community 29 - "v12 — Deployment Hardening"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v12 — Deployment Hardening

### Community 30 - "v13 — Settings UI (Final)"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v13 — Settings UI (Final)

### Community 31 - "sv"
Cohesion: 0.40
Nodes (4): Building, Creating a project, Developing, sv

### Community 78 - "Deploying spotdl-web (v01 — scaffold) to the Debian 12 host"
Cohesion: 0.18
Nodes (11): 1. Install PostgreSQL (host-native — not a container), 2. Create the role and database, 3. Let Docker containers reach Postgres, 4. Install Docker + the Compose plugin, 5. Clone the repo, 6. Configure `.env`, 7. Bring up the stack, 8. Verify (+3 more)

## Knowledge Gaps
- **179 isolated node(s):** `spotdl-web-backend`, `gitignorePath`, `name`, `private`, `version` (+174 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **47 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Deploying spotdl-web (v01 — scaffold) to the Debian 12 host` connect `Deploying spotdl-web (v01 — scaffold) to the Debian 12 host` to `Planning & Config Docs`?**
  _High betweenness centrality (0.010) - this node is a cross-community bridge._
- **Why does `devDependencies` connect `devDependencies` to `scripts`?**
  _High betweenness centrality (0.010) - this node is a cross-community bridge._
- **What connects `spotdl-web-backend`, `gitignorePath`, `name` to the rest of the system?**
  _185 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Planning & Config Docs` be split into smaller, more focused modules?**
  _Cohesion score 0.1 - nodes in this community are weakly interconnected._
- **Should `Deployment Hardening` be split into smaller, more focused modules?**
  _Cohesion score 0.13725490196078433 - nodes in this community are weakly interconnected._
- **Should `devDependencies` be split into smaller, more focused modules?**
  _Cohesion score 0.11764705882352941 - nodes in this community are weakly interconnected._
- **Should `scripts` be split into smaller, more focused modules?**
  _Cohesion score 0.14285714285714285 - nodes in this community are weakly interconnected._