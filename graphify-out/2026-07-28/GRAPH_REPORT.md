# Graph Report - spotdl-web  (2026-07-28)

## Corpus Check
- 69 files · ~26,100 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 448 nodes · 524 edges · 89 communities (42 shown, 47 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 54 edges (avg confidence: 0.72)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `98494c82`
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
- [[_COMMUNITY_Setting up the self-hosted GitHub Actions runner|Setting up the self-hosted GitHub Actions runner]]
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
- [[_COMMUNITY_main.py|main.py]]
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
- [[_COMMUNITY_Local development environment|Local development environment]]
- [[_COMMUNITY_test_auth.py|test_auth.py]]
- [[_COMMUNITY_Track|Track]]
- [[_COMMUNITY_test_expansion.py|test_expansion.py]]
- [[_COMMUNITY_test_downloads.py|test_downloads.py]]
- [[_COMMUNITY_test_jobs.py|test_jobs.py]]
- [[_COMMUNITY_reconcile_disk|reconcile_disk]]

## God Nodes (most connected - your core abstractions)
1. `Track` - 16 edges
2. `Project: spotdl-web` - 15 edges
3. `Job` - 14 edges
4. `Base` - 13 edges
5. `UserSession` - 13 edges
6. `compilerOptions` - 11 edges
7. `Setting up the self-hosted GitHub Actions runner` - 11 edges
8. `Deploying spotdl-web (v01 — scaffold) to the Debian 12 host` - 11 edges
9. `DownloadedTrack` - 10 edges
10. `spotdl-web — Master Development Plan` - 10 edges

## Surprising Connections (you probably didn't know these)
- `login()` --calls--> `get_settings()`  [INFERRED]
  backend/app/routers/auth.py → backend/app/config.py
- `download_track()` --calls--> `get_settings()`  [INFERRED]
  backend/app/tasks/download.py → backend/app/config.py
- `DownloadedTrack` --uses--> `Base`  [INFERRED]
  backend/app/models/downloaded_track.py → backend/app/db.py
- `Proxy` --uses--> `Base`  [INFERRED]
  backend/app/models/proxy.py → backend/app/db.py
- `Track` --uses--> `Base`  [INFERRED]
  backend/app/models/track.py → backend/app/db.py

## Import Cycles
- None detected.

## Communities (89 total, 47 thin omitted)

### Community 2 - "Planning & Config Docs"
Cohesion: 0.14
Nodes (14): Architecture, Auth API — verified findings, Context, Locked decisions, Other architectural notes, Repository layout, Retry engine, spotdl 4.5.2 — verified API surface (+6 more)

### Community 12 - "Deployment Hardening"
Cohesion: 0.09
Nodes (20): get_settings(), Settings, health(), Response, download_one(), get_downloader(), Path, Song (+12 more)

### Community 13 - "devDependencies"
Cohesion: 0.06
Nodes (30): devDependencies, eslint, eslint-config-prettier, @eslint/js, eslint-plugin-svelte, globals, prettier, prettier-plugin-svelte (+22 more)

### Community 14 - "Project: spotdl-web"
Cohesion: 0.12
Nodes (16): Architecture, Auth API — `vb2007.hu-api` (verified from `/home/vb2007/code/vb2007.hu-api` source), Development environments, graphify, Locked decisions, Project: spotdl-web, Retry engine numbers, spotdl 4.5.2 — verified API surface actually used (+8 more)

### Community 15 - "Setting up the self-hosted GitHub Actions runner"
Cohesion: 0.17
Nodes (11): 1. Download and register the runner (already done), 2. Install OS-level runner dependencies, 3. Run it as a persistent service, not an interactive session, 4. Verify registration, 5. Project test dependencies, 6. What the workflow actually runs, 7. Caching across runs — already automatic, no workflow change needed, 8. Human-readable test reports (+3 more)

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

### Community 37 - "main.py"
Cohesion: 0.21
Nodes (14): login(), LoginRequest, logout(), me(), Response, Session, require_session(), _set_session_cookie() (+6 more)

### Community 78 - "Deploying spotdl-web (v01 — scaffold) to the Debian 12 host"
Cohesion: 0.08
Nodes (20): 1. Install PostgreSQL (host-native — not a container), 2. Create the role and database, 3. Let Docker containers reach Postgres, 4. Install Docker + the Compose plugin, 5. Clone the repo, 6. Configure `.env`, 7. Bring up the stack, 8. Verify (+12 more)

### Community 79 - "Local development environment"
Cohesion: 0.12
Nodes (30): Base, get_db(), Session, Job, JobSourceType, JobState, One row per submitted URL (album/playlist/artist/track)., Proxy (+22 more)

### Community 81 - "test_auth.py"
Cohesion: 0.48
Nodes (5): _mock_upstream_login(), test_login_success_sets_cookie_and_me_returns_email(), test_logout_clears_session(), test_vb_auth_cookie_never_reaches_the_browser(), test_wrong_password_and_disallowed_email_return_identical_response()

### Community 82 - "Track"
Cohesion: 0.13
Nodes (19): One row per individual song discovered while expanding a job — the unit the retr, Track, _FakeSettings, _make_track(), _NonClosingSession, _patch_common(), Wraps db_session so download_track's db.close() doesn't detach objects the test, test_download_track_failure_marks_failed_with_error() (+11 more)

### Community 83 - "test_expansion.py"
Cohesion: 0.43
Nodes (5): _fake_init(), _FakeSettings, test_ensure_spotify_client_initializes_once(), test_ensure_spotify_client_prefers_configured_creds(), test_ensure_spotify_client_uses_default_creds_when_unset()

### Community 84 - "test_downloads.py"
Cohesion: 0.32
Nodes (8): _FakeDownloader, _FakeSettings, test_download_one_delegates_to_search_and_download(), test_download_one_ensures_spotify_client_before_downloading(), test_get_downloader_builds_new_instance_for_different_key(), test_get_downloader_builds_output_template_from_settings_dir(), test_get_downloader_caches_per_format_bitrate_proxy(), test_get_downloader_sets_proxy_only_when_given()

### Community 85 - "test_jobs.py"
Cohesion: 0.47
Nodes (7): _login(), _stub_expand_job(), test_create_job_classifies_source_type_from_url(), test_create_job_enqueues_expansion_and_returns_expanding_state(), test_get_unknown_job_returns_404(), test_list_and_get_job_include_track_counts(), test_list_job_tracks_projects_display_fields_and_stays_pending()

### Community 86 - "reconcile_disk"
Cohesion: 0.12
Nodes (14): DownloadedTrack, Dedup ledger, independent of `tracks` so it survives job/track deletion and powe, is_already_downloaded(), Path, Download dedup ledger (`downloaded_tracks`) and startup disk reconciliation., Drops ledger rows whose file no longer exists on disk, so a manually-deleted, reconcile_disk(), _reconcile_disk_on_boot() (+6 more)

## Knowledge Gaps
- **200 isolated node(s):** `spotdl-web-backend`, `gitignorePath`, `name`, `private`, `version` (+195 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **47 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Base` connect `Local development environment` to `Track`, `reconcile_disk`?**
  _High betweenness centrality (0.019) - this node is a cross-community bridge._
- **Why does `DownloadedTrack` connect `reconcile_disk` to `Track`, `Local development environment`?**
  _High betweenness centrality (0.019) - this node is a cross-community bridge._
- **Why does `Track` connect `Track` to `test_jobs.py`, `reconcile_disk`, `Local development environment`?**
  _High betweenness centrality (0.016) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `Track` (e.g. with `Base` and `list_job_tracks()`) actually correct?**
  _`Track` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `Job` (e.g. with `Base` and `list_jobs()`) actually correct?**
  _`Job` has 9 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Dedup ledger, independent of `tracks` so it survives job/track deletion and powe`, `One row per submitted URL (album/playlist/artist/track).`, `Our own session store — separate from the upstream VB-AUTH token (see v03).` to the rest of the system?**
  _222 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Planning & Config Docs` be split into smaller, more focused modules?**
  _Cohesion score 0.14285714285714285 - nodes in this community are weakly interconnected._