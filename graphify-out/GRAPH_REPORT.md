# Graph Report - spotdl-web  (2026-08-10)

## Corpus Check
- 130 files · ~93,629 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1133 nodes · 1654 edges · 136 communities (87 shown, 49 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 196 edges (avg confidence: 0.77)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `fdccac05`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Session Auth Routes|Session Auth Routes]]
- [[_COMMUNITY_Config & Health Check|Config & Health Check]]
- [[_COMMUNITY_Proxy Router Endpoints|Proxy Router Endpoints]]
- [[_COMMUNITY_Track Model & Beat Tests|Track Model & Beat Tests]]
- [[_COMMUNITY_DB Base & App Settings|DB Base & App Settings]]
- [[_COMMUNITY_Job Model & Expansion Tests|Job Model & Expansion Tests]]
- [[_COMMUNITY_Frontend API Client|Frontend API Client]]
- [[_COMMUNITY_Circuit Breaker & Retry|Circuit Breaker & Retry]]
- [[_COMMUNITY_Frontend Lint Tooling|Frontend Lint Tooling]]
- [[_COMMUNITY_Proxy Service Tests|Proxy Service Tests]]
- [[_COMMUNITY_SSE Event Publishing|SSE Event Publishing]]
- [[_COMMUNITY_Dedup Ledger & Reconciliation|Dedup Ledger & Reconciliation]]
- [[_COMMUNITY_Frontend Design System|Frontend Design System]]
- [[_COMMUNITY_Queue UI Components|Queue UI Components]]
- [[_COMMUNITY_Track Router Tests|Track Router Tests]]
- [[_COMMUNITY_System Architecture Overview|System Architecture Overview]]
- [[_COMMUNITY_Backend Dependencies|Backend Dependencies]]
- [[_COMMUNITY_Download Service Tests|Download Service Tests]]
- [[_COMMUNITY_TypeScript Config|TypeScript Config]]
- [[_COMMUNITY_Alembic Env & JSON Logging|Alembic Env & JSON Logging]]
- [[_COMMUNITY_v12 Deploy Gotchas|v12 Deploy Gotchas]]
- [[_COMMUNITY_Settings Router Tests|Settings Router Tests]]
- [[_COMMUNITY_Master Plan Decisions|Master Plan Decisions]]
- [[_COMMUNITY_CLAUDE.md & CI Runner Docs|CLAUDE.md & CI Runner Docs]]
- [[_COMMUNITY_Worker Status UI|Worker Status UI]]
- [[_COMMUNITY_Retry Engine Spec|Retry Engine Spec]]
- [[_COMMUNITY_Spotify Client Tests|Spotify Client Tests]]
- [[_COMMUNITY_Auth Router Tests|Auth Router Tests]]
- [[_COMMUNITY_Worker Router Tests|Worker Router Tests]]
- [[_COMMUNITY_Queue Store Actions|Queue Store Actions]]
- [[_COMMUNITY_Version Roadmap Plans|Version Roadmap Plans]]
- [[_COMMUNITY_Stream Router Tests|Stream Router Tests]]
- [[_COMMUNITY_CI Workflow Jobs|CI Workflow Jobs]]
- [[_COMMUNITY_ESLint Config|ESLint Config]]
- [[_COMMUNITY_Prettier Config|Prettier Config]]
- [[_COMMUNITY_SvelteKit App Types|SvelteKit App Types]]
- [[_COMMUNITY_API Error Class|API Error Class]]
- [[_COMMUNITY_Proxy Selection & Coexistence|Proxy Selection & Coexistence]]
- [[_COMMUNITY_Track Event Schema|Track Event Schema]]
- [[_COMMUNITY_Postgres Backup Script|Postgres Backup Script]]
- [[_COMMUNITY_Frontend README|Frontend README]]
- [[_COMMUNITY_Backend Package Name|Backend Package Name]]
- [[_COMMUNITY_Planning Version Doc|Planning Version Doc]]
- [[_COMMUNITY_Auth Version Doc|Auth Version Doc]]
- [[_COMMUNITY_URL Expansion Version Doc|URL Expansion Version Doc]]
- [[_COMMUNITY_Downloader Version Doc|Downloader Version Doc]]
- [[_COMMUNITY_Proxy Cooldown Backoff|Proxy Cooldown Backoff]]
- [[_COMMUNITY_Live Progress Version Doc|Live Progress Version Doc]]
- [[_COMMUNITY_Breaker Release Policy|Breaker Release Policy]]
- [[_COMMUNITY_Queue Controls Version Doc|Queue Controls Version Doc]]
- [[_COMMUNITY_Priority Dispatch Order|Priority Dispatch Order]]
- [[_COMMUNITY_Deploy Hardening Version Doc|Deploy Hardening Version Doc]]
- [[_COMMUNITY_v03 — Authentication|v03 — Authentication]]
- [[_COMMUNITY_v06 — Retry Engine|v06 — Retry Engine]]
- [[_COMMUNITY_v14 — Master v1 Implementation Audit|v14 — Master v1 Implementation Audit]]
- [[_COMMUNITY_v17 — Multi-User Auth & Ownership Enforcement|v17 — Multi-User Auth & Ownership Enforcement]]
- [[_COMMUNITY_v19 — Archive & Retention|v19 — Archive & Retention]]
- [[_COMMUNITY_v20 — Job-Centric UI|v20 — Job-Centric UI]]
- [[_COMMUNITY_v21 — Multi-User Hardening & Real-Stack Verification|v21 — Multi-User Hardening & Real-Stack Verification]]
- [[_COMMUNITY_beat.py|beat.py]]
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
- [[_COMMUNITY_stream|stream]]
- [[_COMMUNITY_sv|sv]]
- [[_COMMUNITY_ALLOWED_EMAILS allowlist gate|ALLOWED_EMAILS allowlist gate]]
- [[_COMMUNITY_System Architecture (TunnelwebapiworkersbeatDB)|System Architecture (Tunnel/web/api/workers/beat/DB)]]
- [[_COMMUNITY_Server-to-server auth proxy to vb2007.hu-api|Server-to-server auth proxy to vb2007.hu-api]]
- [[_COMMUNITY_GET apitracks bulk endpoint replacing N per-job requests (v12)|GET /api/tracks bulk endpoint replacing N per-job requests (v12)]]
- [[_COMMUNITY_Three CI workflow bugs surfaced only on real self-hosted runner (v12)|Three CI workflow bugs surfaced only on real self-hosted runner (v12)]]
- [[_COMMUNITY_Global circuit breaker|Global circuit breaker]]
- [[_COMMUNITY_Backend Dockerfile dependency-layer caching + requirements.txt lock (v12)|Backend Dockerfile dependency-layer caching + requirements.txt lock (v12)]]
- [[_COMMUNITY_Frontend .dockerignore fix for build context bloat (v12)|Frontend .dockerignore fix for build context bloat (v12)]]
- [[_COMMUNITY_localhost resolves 1 before 127.0.0.1, breaking healthchecks (v12)|localhost resolves ::1 before 127.0.0.1, breaking healthchecks (v12)]]
- [[_COMMUNITY_migrate service gates backend startup via depends_on (v12)|migrate service gates backend startup via depends_on (v12)]]
- [[_COMMUNITY_Non-root container needs real home dir for spotdl import (v12)|Non-root container needs real home dir for spotdl import (v12)]]
- [[_COMMUNITY_Postgres backuprestore (pg_backup.sh)|Postgres backup/restore (pg_backup.sh)]]
- [[_COMMUNITY_Proxy rotation  direct-then-proxy escalation|Proxy rotation / direct-then-proxy escalation]]
- [[_COMMUNITY_Redis maxmemory-policy noeviction rationale (v12)|Redis maxmemory-policy noeviction rationale (v12)]]
- [[_COMMUNITY_Per-track retry ladder (15m→1h→4h→12h→24h)|Per-track retry ladder (15m→1h→4h→12h→24h)]]
- [[_COMMUNITY_Same-origin nginx reverse proxy design (v12)|Same-origin nginx reverse proxy design (v12)]]
- [[_COMMUNITY_tracks.scheduled_at as durable scheduling source of truth|tracks.scheduled_at as durable scheduling source of truth]]
- [[_COMMUNITY_Self-hosted GitHub Actions runner on production host|Self-hosted GitHub Actions runner on production host]]
- [[_COMMUNITY_SpotifyClient process-wide singleton|SpotifyClient process-wide singleton]]
- [[_COMMUNITY_SSE live progress stream|SSE live progress stream]]
- [[_COMMUNITY_Version roadmap v00-v13|Version roadmap v00-v13]]
- [[_COMMUNITY_Workflow rules (one feature at a time, branch per version, etc.)|Workflow rules (one feature at a time, branch per version, etc.)]]
- [[_COMMUNITY_frontendsrcapp.html|frontend/src/app.html]]
- [[_COMMUNITY_Amber-exclusivity rule for live state|Amber-exclusivity rule for live state]]
- [[_COMMUNITY_Matte charcoal chassis material - accepted open gap|Matte charcoal chassis material - accepted open gap]]
- [[_COMMUNITY_frontendsrcDESIGN|frontend/src/DESIGN.md]]
- [[_COMMUNITY_Mobile stacked layout (one-cell-per-line rule)|Mobile stacked layout (one-cell-per-line rule)]]
- [[_COMMUNITY_.panel recessed instrument housing|.panel recessed instrument housing]]
- [[_COMMUNITY_QueueTable state to colorlabel mapping|QueueTable state to color/label mapping]]
- [[_COMMUNITY_Reduced-motion as load-bearing accessibility rule|Reduced-motion as load-bearing accessibility rule]]
- [[_COMMUNITY_Signal-condition color system (5 conditions)|Signal-condition color system (5 conditions)]]
- [[_COMMUNITY_Two-family type system (IBM Plex MonoSans)|Two-family type system (IBM Plex Mono/Sans)]]
- [[_COMMUNITY_Keyboard-only navigation requirement|Keyboard-only navigation requirement]]
- [[_COMMUNITY_Capabilities and constraints (shared queue, no per-user isolation)|Capabilities and constraints (shared queue, no per-user isolation)]]
- [[_COMMUNITY_Product principles (durability over speed, etc.)|Product principles (durability over speed, etc.)]]
- [[_COMMUNITY_Product purpose fire-and-forget durable downloads|Product purpose: fire-and-forget durable downloads]]
- [[_COMMUNITY_Allowlisted shared users|Allowlisted shared users]]
- [[_COMMUNITY_test_app_settings.py|test_app_settings.py]]
- [[_COMMUNITY_conftest.py|conftest.py]]
- [[_COMMUNITY_README|README.md]]
- [[_COMMUNITY_Deploying spotdl-web to the Debian 12 host|Deploying spotdl-web to the Debian 12 host]]
- [[_COMMUNITY_spotdl-web — Accumulated Gotchas (master v1, v01–v13)|spotdl-web — Accumulated Gotchas (master v1, v01–v13)]]
- [[_COMMUNITY_stream|stream]]
- [[_COMMUNITY_Base|Base]]
- [[_COMMUNITY_reconcile_disk|reconcile_disk]]
- [[_COMMUNITY_conftest.py|conftest.py]]
- [[_COMMUNITY_Amendments|Amendments]]

## God Nodes (most connected - your core abstractions)
1. `Track` - 52 edges
2. `$lib/api` - 52 edges
3. `User` - 45 edges
4. `Job` - 25 edges
5. `request()` - 25 edges
6. `_make_track()` - 22 edges
7. `get_settings()` - 20 edges
8. `_patch_common()` - 20 edges
9. `v14 — Master v1 Implementation Audit Report` - 19 edges
10. `WorkerState` - 17 edges

## Surprising Connections (you probably didn't know these)
- `favicon.svg (Svelte default logo)` --semantically_similar_to--> `Instrument-panel THESIS (Operate mode)`  [AMBIGUOUS] [semantically similar]
  frontend/src/lib/assets/favicon.svg → frontend/src/DESIGN.md
- `CI Workflow (ci.yml)` --references--> `uv override-dependencies for spotdl's pinned fastapi/uvicorn (v04)`  [EXTRACTED]
  .github/workflows/ci.yml → CLAUDE.md
- `compose-config job` --references--> `Compose list-key merge vs replace gotcha (v01, !override tag)`  [EXTRACTED]
  .github/workflows/ci.yml → CLAUDE.md
- `test_admin_email_matching_is_allowed()` --calls--> `Settings`  [INFERRED]
  backend/tests/test_config.py → backend/app/config.py
- `test_admin_email_missing_is_rejected()` --calls--> `Settings`  [INFERRED]
  backend/tests/test_config.py → backend/app/config.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **CI PR-checks pipeline (pytest, publish-report, compose-config, frontend)** — github_workflows_ci_pytest_job, github_workflows_ci_publish_report_job, github_workflows_ci_compose_config_job, github_workflows_ci_frontend_job [EXTRACTED 1.00]
- **Docker Compose layered configuration (base/override/prod)** — docker_compose_doc, docker_compose_override_doc, docker_compose_prod_doc [EXTRACTED 1.00]

## Communities (136 total, 49 thin omitted)

### Community 0 - "Session Auth Routes"
Cohesion: 0.09
Nodes (50): Row created on first successful login (v17). The `ALLOWED_EMAILS` env allowlist, User, bump_job(), cancel_job(), _classify_source_type(), create_job(), CreateJobRequest, get_job() (+42 more)

### Community 1 - "Config & Health Check"
Cohesion: 0.22
Nodes (9): get_settings(), health(), Response, login(), Check credentials against vb2007.hu-api. Never forwards or returns the upstream, download_track(), pacing_delay(), Seconds to wait before this track's download attempt -- a uniform sample from (+1 more)

### Community 2 - "Proxy Router Endpoints"
Cohesion: 0.14
Nodes (17): next_cooldown(), pick_proxy(), _probe_reachable(), Proxy, Session, timedelta, UUID, Proxy pool: file sync (`proxies.txt`), LRU selection, and per-proxy cooldown.  M (+9 more)

### Community 3 - "Track Model & Beat Tests"
Cohesion: 0.07
Nodes (57): DownloadedTrack, Dedup ledger, independent of `tracks` so it survives job/track deletion and powe, One row per individual song discovered while expanding a job — the unit the retr, Track, _make_track(), _NonClosingSession, _owner(), _patch_session() (+49 more)

### Community 4 - "DB Base & App Settings"
Cohesion: 0.21
Nodes (12): get_or_create_user(), normalize_email(), Session, User identity (v17) -- ALLOWED_EMAILS decides who may log in at all; this module, Creates the user row on first login, or loads and reconciles it on every     lat, Changing ADMIN_EMAIL must take effect on the next login, not need manual SQL --, test_get_or_create_user_bumps_last_login_at(), test_get_or_create_user_creates_row_on_first_login() (+4 more)

### Community 5 - "Job Model & Expansion Tests"
Cohesion: 0.10
Nodes (26): Job, One row per submitted URL (album/playlist/artist/track)., _capture_job_events(), _FakeSong, _NonClosingSession, _owner(), Wraps db_session so expand_job's db.close() doesn't detach objects the test, _stub_download_track() (+18 more)

### Community 6 - "Frontend API Client"
Cohesion: 0.09
Nodes (31): $lib/api, API_BASE, createJob(), createProxy(), deleteProxy(), EditableOutputSettings, getOutputOptions(), getOutputSettings() (+23 more)

### Community 7 - "Circuit Breaker & Retry"
Cohesion: 0.13
Nodes (28): Single-row table backing the global circuit breaker., WorkerState, breaker_active(), classify_error(), get_worker_state(), maybe_trip_breaker(), next_delay(), datetime (+20 more)

### Community 8 - "Frontend Lint Tooling"
Cohesion: 0.07
Nodes (29): devDependencies, eslint, eslint-config-prettier, @eslint/js, eslint-plugin-svelte, globals, prettier, prettier-plugin-svelte (+21 more)

### Community 9 - "Proxy Service Tests"
Cohesion: 0.11
Nodes (14): _aware(), _FakeSettings, _NonClosingSession, datetime, Wraps db_session so sync_from_file's db.close() doesn't detach objects the test, v13 shipped MANUAL-source (UI-added) proxies alongside FILE-source ones, both me, test_pick_proxy_selects_across_manual_and_file_sources_by_lru(), test_pick_proxy_stamps_last_used_at_on_selection() (+6 more)

### Community 10 - "SSE Event Publishing"
Cohesion: 0.30
Nodes (13): Any, channel_for(), _get_client(), make_progress_callback(), publish(), publish_job_event(), publish_track_event(), datetime (+5 more)

### Community 11 - "Dedup Ledger & Reconciliation"
Cohesion: 0.26
Nodes (8): _FakeSettings, _NonClosingSession, Wraps db_session so dedup's db.close() doesn't detach objects the test still, test_is_already_downloaded_returns_none_when_missing(), test_is_already_downloaded_returns_path_when_present(), test_reconcile_disk_drops_rows_for_missing_files(), test_reconcile_disk_refuses_to_prune_when_output_dir_empty(), test_reconcile_disk_refuses_to_prune_when_output_dir_missing()

### Community 13 - "Queue UI Components"
Cohesion: 0.15
Nodes (15): Job, StreamEvent, Track, TrackState, $lib/components/IncomingJobs.svelte, $lib/components/QueueTable.svelte, $lib/components/Waterfall.svelte, $lib/stores/queue (+7 more)

### Community 14 - "Track Router Tests"
Cohesion: 0.12
Nodes (17): v01 deployment gotchas (learned deploying to the real host and local dev), v02 schema gotchas (learned building the SQLAlchemy models + initial migration), v03 auth gotchas (learned building the upstream login proxy + session cookie), v04 URL-expansion gotchas (learned building `get_simple_songs` wrapper + `/api/jobs`), v05 downloader gotchas (learned building real downloads + dedup ledger + disk reconciliation), v06 retry-engine gotchas (learned building error classification + ladder + breaker + beat dispatch), v07 proxy-rotation gotchas (learned building `proxies.txt` sync + pick/cooldown + wiring), v08 live-progress gotchas (learned building the Redis pub/sub event bus + SSE stream) (+9 more)

### Community 16 - "Backend Dependencies"
Cohesion: 0.08
Nodes (27): alembic==1.18.5, celery==5.6.3, backend/requirements.txt, fastapi==0.141.1, psycopg==3.3.4, python-json-logger==4.1.0, redis==6.4.0 (python client), spotdl==4.5.2 (+19 more)

### Community 17 - "Download Service Tests"
Cohesion: 0.27
Nodes (9): _FakeDownloader, _FakeSettings, test_download_one_delegates_to_search_and_download(), test_download_one_ensures_spotify_client_before_downloading(), test_get_downloader_always_disables_rich_tui(), test_get_downloader_builds_new_instance_for_different_key(), test_get_downloader_builds_output_from_given_dir_and_template(), test_get_downloader_caches_per_format_bitrate_output_and_proxy() (+1 more)

### Community 19 - "TypeScript Config"
Cohesion: 0.15
Nodes (12): compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, moduleResolution, resolveJsonModule, rewriteRelativeImportExtensions (+4 more)

### Community 20 - "Alembic Env & JSON Logging"
Cohesion: 0.20
Nodes (7): _configure_celery_logging(), JsonFormatter, Structured JSON logging (v12) — one shared formatter both uvicorn (`api`, via `l, Adds Celery task context (`task_id`/`task_name`) when a log call happens inside, Connecting *any* receiver to this signal tells Celery to skip its own logging, _redact(), _BaseJsonFormatter

### Community 22 - "Settings Router Tests"
Cohesion: 0.29
Nodes (7): _FakeSettings, test_get_output_settings_seeds_from_env_defaults(), test_update_output_settings_ignores_output_dir_if_sent(), test_update_output_settings_ignores_unset_fields(), test_update_output_settings_persists_and_returns_partial_update(), test_update_output_settings_rejects_unsupported_bitrate(), test_update_output_settings_rejects_unsupported_format()

### Community 23 - "Master Plan Decisions"
Cohesion: 0.10
Nodes (19): Architecture invariants, Locked decisions (`plan/master-v1/00-master-plan.md`), Remediation list, v00 — Planning, v01 — Scaffold, v02 — DB Schema, v03 — Auth, v04 — URL Expansion (+11 more)

### Community 25 - "Worker Status UI"
Cohesion: 0.22
Nodes (5): svelte, workerStatus, $lib/components/Countdown.svelte, $lib/components/WorkerStatus.svelte, worker

### Community 26 - "Retry Engine Spec"
Cohesion: 0.15
Nodes (12): frontend/static/robots.txt, Accessibility & Inclusion, Brand Commitments, Capabilities and Constraints, Evidence on Hand, Operating Context, Platform, Positioning (+4 more)

### Community 27 - "Spotify Client Tests"
Cohesion: 0.43
Nodes (5): _fake_init(), _FakeSettings, test_ensure_spotify_client_initializes_once(), test_ensure_spotify_client_prefers_configured_creds(), test_ensure_spotify_client_uses_default_creds_when_unset()

### Community 28 - "Auth Router Tests"
Cohesion: 0.48
Nodes (5): _mock_upstream_login(), test_login_success_sets_cookie_and_me_returns_email(), test_logout_clears_session(), test_vb_auth_cookie_never_reaches_the_browser(), test_wrong_password_and_disallowed_email_return_identical_response()

### Community 30 - "Queue Store Actions"
Cohesion: 0.33
Nodes (6): bumpJob(), cancelJob(), cancelTrack(), retryTrack(), setJobPriority(), createQueueStore()

### Community 31 - "Version Roadmap Plans"
Cohesion: 0.12
Nodes (15): Architecture, Development environments, graphify, Invariants — break these and things fail silently, Job rollup status (v2) — two derived axes, never one stored flag, Locked decisions, Maintaining this file, Master v2 additions (+7 more)

### Community 32 - "Stream Router Tests"
Cohesion: 0.13
Nodes (9): _drive(), _fake_event_stream(), _FakePubSub, _FakeRedisClient, v17's threat model: a client-supplied scope flag is never trusted -- a non-admin, test_event_stream_admin_all_users_psubscribes_to_the_admin_pattern(), test_event_stream_non_admin_all_users_flag_is_ignored(), test_event_stream_subscribes_to_the_users_own_channel() (+1 more)

### Community 33 - "CI Workflow Jobs"
Cohesion: 0.08
Nodes (25): 1. World and thesis, 2. Palette, 3. Type system, 4. Spacing scale, 5. Motion, 6. Component patterns, 7. Accessibility (confirmed hard requirement, PRODUCT.md), 8. Known, accepted gaps (do not silently "fix" without re-reading this section first) (+17 more)

### Community 44 - "Proxy Selection & Coexistence"
Cohesion: 0.13
Nodes (18): is_already_downloaded(), Path, Download dedup ledger (`downloaded_tracks`) and startup disk reconciliation., Drops ledger rows whose file no longer exists on disk, so a manually-deleted, reconcile_disk(), _reconcile_disk_on_boot(), _format(), _make_record() (+10 more)

### Community 45 - "Track Event Schema"
Cohesion: 0.13
Nodes (14): Architecture, Auth API — verified findings, Context, Locked decisions, Other architectural notes, Repository layout, Retry engine, spotdl 4.5.2 — verified API surface (+6 more)

### Community 56 - "Planning Version Doc"
Cohesion: 0.20
Nodes (4): _FakeSongTracker, The whole enforcement mechanism (v17): a call site that forgets the owner fails, test_make_progress_callback_publishes_downloading_progress(), test_publish_track_event_requires_owner()

### Community 57 - "Auth Version Doc"
Cohesion: 0.15
Nodes (13): ADMIN_EMAIL gates who services.users.get_or_create_user marks is_admin;, Rejects a pacing window that can't mean what it says. random.uniform happily, Settings, random.uniform tolerates reversed bounds and silently samples them anyway --, An admin who isn't allowlisted could never log in -- a deployment nobody can, test_admin_email_matching_is_allowed(), test_admin_email_missing_is_rejected(), test_admin_email_not_in_allowed_emails_is_rejected() (+5 more)

### Community 58 - "URL Expansion Version Doc"
Cohesion: 0.17
Nodes (11): 1. Download and register the runner (already done), 2. Install OS-level runner dependencies, 3. Run it as a persistent service, not an interactive session, 4. Verify registration, 5. Project test dependencies, 6. What the workflow actually runs, 7. Caching across runs — already automatic, no workflow change needed, 8. Human-readable test reports (+3 more)

### Community 59 - "Downloader Version Doc"
Cohesion: 0.17
Nodes (11): Done when, `downloaded_tracks`, `jobs`, `proxies`, Scope, `sessions`, Tables, Tasks (+3 more)

### Community 60 - "Proxy Cooldown Backoff"
Cohesion: 0.20
Nodes (10): Context, Critical files, Job rollup status — answering the open design question, Locked decisions for v2, Plan file reorganization (part of v14), spotdl-web — Master Plan v2, Verification, Verified current state (+2 more)

### Community 61 - "Live Progress Version Doc"
Cohesion: 0.18
Nodes (10): Done when, `jobs` (modified), Scope, `sessions` (modified), Tables, Tasks, `tracks` (unchanged), `user_settings` (new) (+2 more)

### Community 62 - "Breaker Release Policy"
Cohesion: 0.24
Nodes (9): download_one(), get_downloader(), get_supported_output_options(), Path, Song, Thin wrapper around spotdl's download machinery.  Never construct a `Downloader`, The real, live set of --format/--bitrate values the installed spotdl accepts —, Must be called from a plain sync context — search_and_download raises     Downlo (+1 more)

### Community 63 - "Queue Controls Version Doc"
Cohesion: 0.15
Nodes (23): create_proxy(), CreateProxyRequest, delete_proxy(), _get_proxy_or_404(), list_proxies(), _proxy_to_dict(), Proxy, Response (+15 more)

### Community 64 - "Priority Dispatch Order"
Cohesion: 0.22
Nodes (8): 1. The pacing hook has no consumer, 2. `list_jobs` N+1, and no pagination anywhere, Admission rules, Confirmed gaps (already found, before the audit runs), Done when, Scope, Tasks, v15 — Master v1 Gap Fixes

### Community 65 - "Deploy Hardening Version Doc"
Cohesion: 0.25
Nodes (7): Design notes, Done when, Endpoints, Job rollup status (the model from the master plan), Killing the N+1 properly, Scope, v18 — Job-Centric API

### Community 66 - "v03 — Authentication"
Cohesion: 0.29
Nodes (6): Done when, Files touched (new), Scope, Tasks, v03 — Authentication, Why server-to-server (recap from master plan)

### Community 67 - "v06 — Retry Engine"
Cohesion: 0.29
Nodes (6): Done when, Files touched (new), Scope, Tasks, v06 — Retry Engine, Why not Celery `eta`/`countdown`

### Community 68 - "v14 — Master v1 Implementation Audit"
Cohesion: 0.29
Nodes (6): Done when, Explicitly out of scope, Scope, Tasks, v14 — Master v1 Implementation Audit, Why this comes first

### Community 69 - "v17 — Multi-User Auth & Ownership Enforcement"
Cohesion: 0.29
Nodes (6): Done when, Scope, SSE is the non-obvious one, Tasks, The threat model, stated plainly, v17 — Multi-User Auth & Ownership Enforcement

### Community 70 - "v19 — Archive & Retention"
Cohesion: 0.29
Nodes (6): Done when, Scope, Tasks, v19 — Archive & Retention, What is eligible, Why archive rather than delete

### Community 71 - "v20 — Job-Centric UI"
Cohesion: 0.29
Nodes (6): Constraints carried from v1 (non-negotiable, see `frontend/src/DESIGN.md`), Done when, Scope, Tasks, v20 — Job-Centric UI, What the user sees

### Community 72 - "v21 — Multi-User Hardening & Real-Stack Verification"
Cohesion: 0.29
Nodes (6): Done when, Scope, Tasks, The sweep — every surface, explicitly, v21 — Multi-User Hardening & Real-Stack Verification, Why data separation is treated as a security property

### Community 73 - "beat.py"
Cohesion: 0.47
Nodes (5): dispatch_due_tracks(), timedelta, A track stuck in DOWNLOADING/QUEUED past this long means whatever was supposed t, _reclaim_stale_tracks(), stale_track_after()

### Community 74 - "v00 — Planning"
Cohesion: 0.33
Nodes (5): Done when, Files touched, Scope, Tasks, v00 — Planning

### Community 75 - "v01 — Repo & Compose Scaffold"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v01 — Repo & Compose Scaffold

### Community 76 - "v04 — URL Expansion"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v04 — URL Expansion

### Community 77 - "v05 — Downloader"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v05 — Downloader

### Community 78 - "v07 — Proxy Rotation"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v07 — Proxy Rotation

### Community 79 - "v08 — Live Progress (SSE)"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v08 — Live Progress (SSE)

### Community 80 - "v09 — Frontend"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v09 — Frontend

### Community 81 - "v10 — Queue Controls"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v10 — Queue Controls

### Community 82 - "v11 — Job Priority / Reordering"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v11 — Job Priority / Reordering

### Community 83 - "v12 — Deployment Hardening"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v12 — Deployment Hardening

### Community 84 - "v13 — Settings UI (Final)"
Cohesion: 0.33
Nodes (5): Done when, Files touched (new), Scope, Tasks, v13 — Settings UI (Final)

### Community 85 - "stream"
Cohesion: 0.16
Nodes (19): Our own session store — separate from the upstream VB-AUTH token (see v03)., UserSession, current_session(), login(), LoginRequest, logout(), me(), Request (+11 more)

### Community 86 - "sv"
Cohesion: 0.40
Nodes (4): Building, Creating a project, Developing, sv

### Community 107 - "Version roadmap v00-v13"
Cohesion: 0.25
Nodes (8): 1. Install PostgreSQL (host-native — not a container), 2. Create the role and database, 3. Let Docker containers reach Postgres, 4. Install Docker + the Compose plugin, 5. Clone the repo, 6. Configure `.env`, 7. Bring up the stack, One-time host setup (already done on this host — kept for reference)

### Community 125 - "test_app_settings.py"
Cohesion: 0.29
Nodes (7): 1. Pull the merged code, 2. Update `.env`, 3. Migrate the downloads directory (one-time, before first boot with the new bind mount), 4. Bring up the stack with the production overlay, 5. Configure the Cloudflare Tunnel (Zero Trust dashboard), 6. Verify, Upgrading an existing deployment to v12

### Community 126 - "conftest.py"
Cohesion: 0.29
Nodes (7): 1. Configure `.env`, 2. Bring up the stack, 3. Verify, 4. When a version is ready, Local development environment, Once there's real data worth protecting, Troubleshooting

### Community 128 - "Deploying spotdl-web to the Debian 12 host"
Cohesion: 0.33
Nodes (6): Backups, Deploying spotdl-web to the Debian 12 host, Firewall / network notes, Ongoing maintenance, Restart-survival test, Troubleshooting

### Community 129 - "spotdl-web — Accumulated Gotchas (master v1, v01–v13)"
Cohesion: 0.33
Nodes (5): Auth API — `vb2007.hu-api` (verified from `/home/vb2007/code/vb2007.hu-api` source), Index by topic, spotdl 4.5.2 — verified API surface actually used, spotdl-web — Accumulated Gotchas (master v1, v01–v13), Verified external API contracts

### Community 130 - "stream"
Cohesion: 0.60
Nodes (4): _event_stream(), Request, stream(), StreamingResponse

### Community 131 - "Base"
Cohesion: 0.08
Nodes (25): Base, get_db(), Session, AppSettings, Single-row table (v13) backing the output-format defaults editable from the, JobSourceType, JobState, Proxy (+17 more)

### Community 132 - "reconcile_disk"
Cohesion: 0.33
Nodes (6): _ensure_spotify_client(), expand(), Song, Thin wrapper around spotdl's URL-expansion logic.  Never import spotdl.utils.sea, SpotifyClient is a process-wide singleton that raises if .init() runs twice, so, Turn a Spotify URL (track/album/playlist/artist) or a search term into Songs.

### Community 134 - "conftest.py"
Cohesion: 0.13
Nodes (27): admin_client(), admin_user(), authenticated_client(), client(), count_queries(), _login(), make_user(), owner() (+19 more)

### Community 135 - "Amendments"
Cohesion: 0.50
Nodes (4): 2026-08-09 — CLAUDE.md split into rules vs. reference (folded into v14), 2026-08-09 — v15 complete; two v14 findings confirmed already scheduled, one new finding added, 2026-08-09 — v16 complete; NOT NULL applied literally, login/job creation left broken for v17, Amendments

## Ambiguous Edges - Review These
- `PRODUCT.md` → `frontend/static/robots.txt`  [AMBIGUOUS]
  frontend/static/robots.txt · relation: conceptually_related_to
- `favicon.svg (Svelte default logo)` → `Instrument-panel THESIS (Operate mode)`  [AMBIGUOUS]
  frontend/src/lib/assets/favicon.svg · relation: semantically_similar_to

## Knowledge Gaps
- **339 isolated node(s):** `spotdl-web-backend`, `gitignorePath`, `name`, `private`, `version` (+334 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **49 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `PRODUCT.md` and `frontend/static/robots.txt`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `favicon.svg (Svelte default logo)` and `Instrument-panel THESIS (Operate mode)`?**
  _Edge tagged AMBIGUOUS (relation: semantically_similar_to) - confidence is low._
- **Why does `request()` connect `Frontend API Client` to `Worker Status UI`, `Alembic Env & JSON Logging`, `Queue Store Actions`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Why does `User` connect `Session Auth Routes` to `Stream Router Tests`, `stream`, `Base`, `DB Base & App Settings`, `Track Model & Beat Tests`, `conftest.py`, `Job Model & Expansion Tests`, `Circuit Breaker & Retry`, `stream`, `Queue Controls Version Doc`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Why does `Track` connect `Track Model & Beat Tests` to `Session Auth Routes`, `Config & Health Check`, `Base`, `Job Model & Expansion Tests`, `conftest.py`, `Circuit Breaker & Retry`, `beat.py`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **Are the 50 inferred relationships involving `Track` (e.g. with `Base` and `cancel_job()`) actually correct?**
  _`Track` has 50 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `User` (e.g. with `Base` and `test_get_or_create_user_creates_row_on_first_login()`) actually correct?**
  _`User` has 4 INFERRED edges - model-reasoned connections that need verification._