# Graph Report - spotdl-web  (2026-08-16)

## Corpus Check
- 172 files · ~159,930 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1633 nodes · 2514 edges · 167 communities (117 shown, 50 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 301 edges (avg confidence: 0.77)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3e5d439a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Session Auth Routes|Session Auth Routes]]
- [[_COMMUNITY_Config & Health Check|Config & Health Check]]
- [[_COMMUNITY_Proxy Router Endpoints|Proxy Router Endpoints]]
- [[_COMMUNITY_Track Model & Beat Tests|Track Model & Beat Tests]]
- [[_COMMUNITY_test_job_listing.py|test_job_listing.py]]
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
- [[_COMMUNITY_Layout Load Guard|Layout Load Guard]]
- [[_COMMUNITY_Proxy Selection & Coexistence|Proxy Selection & Coexistence]]
- [[_COMMUNITY_Track Event Schema|Track Event Schema]]
- [[_COMMUNITY_Postgres Backup Script|Postgres Backup Script]]
- [[_COMMUNITY_Frontend README|Frontend README]]
- [[_COMMUNITY_Vite Config|Vite Config]]
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
- [[_COMMUNITY_stream|stream]]
- [[_COMMUNITY_Base|Base]]
- [[_COMMUNITY__get_track_or_404|_get_track_or_404]]
- [[_COMMUNITY_Track state machine|Track state machine]]
- [[_COMMUNITY_conftest.py|conftest.py]]
- [[_COMMUNITY_auth.py|auth.py]]
- [[_COMMUNITY__ensure_spotify_client|_ensure_spotify_client]]
- [[_COMMUNITY_README|README.md]]
- [[_COMMUNITY_test_expand_task.py|test_expand_task.py]]
- [[_COMMUNITY_verify_separation_sse.sh|verify_separation_sse.sh]]
- [[_COMMUNITY_spotdl-web — Master Plan v3|spotdl-web — Master Plan v3]]
- [[_COMMUNITY_v28 — Library Sort & Move|v28 — Library Sort & Move]]
- [[_COMMUNITY_test_upstream_auth.py|test_upstream_auth.py]]
- [[_COMMUNITY_test_settings_retention.py|test_settings_retention.py]]
- [[_COMMUNITY_v23 — Download Reliability & Live-View Correctness|v23 — Download Reliability & Live-View Correctness]]
- [[_COMMUNITY_worker.py|worker.py]]
- [[_COMMUNITY_v24 — Per-Attempt History|v24 — Per-Attempt History]]
- [[_COMMUNITY_test_app_settings.py|test_app_settings.py]]
- [[_COMMUNITY_spotdl-web — Accumulated Gotchas (master v1, v01–v13)|spotdl-web — Accumulated Gotchas (master v1, v01–v13)]]
- [[_COMMUNITY_v25 — Usernames & Control Placement|v25 — Usernames & Control Placement]]
- [[_COMMUNITY_v26 — ID3 Tag Integrity|v26 — ID3 Tag Integrity]]
- [[_COMMUNITY_test_events.py|test_events.py]]
- [[_COMMUNITY_v27 — Direct File Downloads|v27 — Direct File Downloads]]
- [[_COMMUNITY__fetch_username|_fetch_username]]
- [[_COMMUNITY_track_counts|track_counts]]
- [[_COMMUNITY_Amendments|Amendments]]
- [[_COMMUNITY_One-time host setup (already done on this host — kept for reference)|One-time host setup (already done on this host — kept for reference)]]
- [[_COMMUNITY_ApiError|ApiError]]
- [[_COMMUNITY_Upgrading an existing deployment (manual fallback)|Upgrading an existing deployment (manual fallback)]]
- [[_COMMUNITY_proxies.py|proxies.py]]
- [[_COMMUNITY_list_jobs|list_jobs]]
- [[_COMMUNITY_track_counts|track_counts]]
- [[_COMMUNITY__event_stream|_event_stream]]

## God Nodes (most connected - your core abstractions)
1. `$lib/api` - 85 edges
2. `Track` - 74 edges
3. `User` - 54 edges
4. `Job` - 48 edges
5. `$lib/stores/queue` - 32 edges
6. `request()` - 31 edges
7. `_make_track()` - 28 edges
8. `Version log` - 28 edges
9. `_patch_common()` - 26 edges
10. `get_settings()` - 21 edges

## Surprising Connections (you probably didn't know these)
- `favicon.svg (Svelte default logo)` --semantically_similar_to--> `Instrument-panel THESIS (Operate mode)`  [AMBIGUOUS] [semantically similar]
  frontend/src/lib/assets/favicon.svg → frontend/src/DESIGN.md
- `test_next_delay_follows_ladder_and_caps_at_final_step()` --calls--> `get_settings()`  [INFERRED]
  backend/tests/test_retry.py → backend/app/config.py
- `_reconcile_disk_on_boot()` --calls--> `reconcile_disk()`  [INFERRED]
  backend/app/tasks/celery_app.py → backend/app/services/dedup.py
- `CI Workflow (ci.yml)` --references--> `uv override-dependencies for spotdl's pinned fastapi/uvicorn (v04)`  [EXTRACTED]
  .github/workflows/ci.yml → CLAUDE.md
- `compose-config job` --references--> `Compose list-key merge vs replace gotcha (v01, !override tag)`  [EXTRACTED]
  .github/workflows/ci.yml → CLAUDE.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **CI PR-checks pipeline (pytest, publish-report, compose-config, frontend)** — github_workflows_ci_pytest_job, github_workflows_ci_publish_report_job, github_workflows_ci_compose_config_job, github_workflows_ci_frontend_job [EXTRACTED 1.00]
- **Docker Compose layered configuration (base/override/prod)** — docker_compose_doc, docker_compose_override_doc, docker_compose_prod_doc [EXTRACTED 1.00]

## Communities (167 total, 50 thin omitted)

### Community 0 - "Session Auth Routes"
Cohesion: 0.16
Nodes (31): Row created on first successful login (v17). The `ALLOWED_EMAILS` env allowlist, User, archive_jobs(), ArchiveJobsRequest, bump_job(), cancel_job(), _classify_source_type(), create_job() (+23 more)

### Community 1 - "Config & Health Check"
Cohesion: 0.33
Nodes (6): get_settings(), health(), Response, download_track(), pacing_delay(), Seconds to wait before this track's download attempt -- a uniform sample from

### Community 2 - "Proxy Router Endpoints"
Cohesion: 0.06
Nodes (45): Base, JobSourceType, JobState, Proxy, ProxySource, One row per `download_track` invocation (v24) -- what it tried (direct vs. which, TrackAttempt, TrackAttemptOutcome (+37 more)

### Community 3 - "Track Model & Beat Tests"
Cohesion: 0.09
Nodes (61): One row per individual song discovered while expanding a job — the unit the retr, Track, _make_job(), _make_track(), _NonClosingSession, _owner(), _patch_session(), Job (+53 more)

### Community 4 - "test_job_listing.py"
Cohesion: 0.16
Nodes (19): Our own session store — separate from the upstream VB-AUTH token (see v03)., UserSession, current_session(), login(), LoginRequest, logout(), me(), Request (+11 more)

### Community 5 - "Job Model & Expansion Tests"
Cohesion: 0.05
Nodes (60): Job, One row per submitted URL (album/playlist/artist/track)., archive_jobs(), _eligible_job_ids(), Job, Session, timedelta, UUID (+52 more)

### Community 6 - "Frontend API Client"
Cohesion: 0.06
Nodes (31): $lib/api, API_BASE, ApiError, downloadTrackFile(), EditableOutputSettings, JobLifecycle, JobOutcome, JobSourceType (+23 more)

### Community 7 - "Circuit Breaker & Retry"
Cohesion: 0.11
Nodes (33): Single-row table backing the global circuit breaker., WorkerState, breaker_active(), classify_error(), get_worker_state(), maybe_trip_breaker(), next_delay(), NoOutputFileError (+25 more)

### Community 8 - "Frontend Lint Tooling"
Cohesion: 0.07
Nodes (29): devDependencies, eslint, eslint-config-prettier, @eslint/js, eslint-plugin-svelte, globals, prettier, prettier-plugin-svelte (+21 more)

### Community 9 - "Proxy Service Tests"
Cohesion: 0.11
Nodes (14): _aware(), _FakeSettings, _NonClosingSession, datetime, Wraps db_session so sync_from_file's db.close() doesn't detach objects the test, v13 shipped MANUAL-source (UI-added) proxies alongside FILE-source ones, both me, test_pick_proxy_selects_across_manual_and_file_sources_by_lru(), test_pick_proxy_stamps_last_used_at_on_selection() (+6 more)

### Community 10 - "SSE Event Publishing"
Cohesion: 0.09
Nodes (31): active_count_expr(), aggregate_jobs(), derive_job_title(), derive_rollup(), job_title(), job_title_expr(), lifecycle_case(), matches_status_filter() (+23 more)

### Community 11 - "Dedup Ledger & Reconciliation"
Cohesion: 0.14
Nodes (23): apply_cursor(), cursor_for_row(), decode_cursor(), _decode_value(), encode_cursor(), _encode_value(), _non_nullable_where(), order_by_clauses() (+15 more)

### Community 13 - "Queue UI Components"
Cohesion: 0.09
Nodes (21): Job, StreamEvent, Track, TrackJobSummary, TrackState, TrackWithJob, $lib/components/JobRow.svelte, $lib/components/TrackRow.svelte (+13 more)

### Community 14 - "Track Router Tests"
Cohesion: 0.06
Nodes (33): Auth API — `vb2007.hu-api` (verified from `/home/vb2007/code/vb2007.hu-api` source), Index by topic, spotdl 4.5.2 — verified API surface actually used, spotdl-web — Accumulated Gotchas (master v1, v01–v13), v01 deployment gotchas (learned deploying to the real host and local dev), v02 schema gotchas (learned building the SQLAlchemy models + initial migration), v03 auth gotchas (learned building the upstream login proxy + session cookie), v04 URL-expansion gotchas (learned building `get_simple_songs` wrapper + `/api/jobs`) (+25 more)

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
Nodes (9): First deploy, GHCR packages, Idempotency, Manual recovery levers, Publish & Deploy — two modes, Release pipeline (v21), The chain, The deploy job, step by step (+1 more)

### Community 22 - "Settings Router Tests"
Cohesion: 0.29
Nodes (7): _FakeSettings, test_get_output_settings_seeds_from_env_defaults(), test_update_output_settings_ignores_output_dir_if_sent(), test_update_output_settings_ignores_unset_fields(), test_update_output_settings_persists_and_returns_partial_update(), test_update_output_settings_rejects_unsupported_bitrate(), test_update_output_settings_rejects_unsupported_format()

### Community 23 - "Master Plan Decisions"
Cohesion: 0.10
Nodes (19): Architecture invariants, Locked decisions (`plan/master-v1/00-master-plan.md`), Remediation list, v00 — Planning, v01 — Scaffold, v02 — DB Schema, v03 — Auth, v04 — URL Expansion (+11 more)

### Community 25 - "Worker Status UI"
Cohesion: 0.15
Nodes (13): svelte, workerStatus, $lib/components/Countdown.svelte, $lib/components/IncomingJobs.svelte, $lib/components/QueueControls.svelte, $lib/components/Waterfall.svelte, $lib/components/WorkerStatus.svelte, $lib/components/WorkerStatusPill.svelte (+5 more)

### Community 26 - "Retry Engine Spec"
Cohesion: 0.15
Nodes (12): frontend/static/robots.txt, Accessibility & Inclusion, Brand Commitments, Capabilities and Constraints, Evidence on Hand, Operating Context, Platform, Positioning (+4 more)

### Community 27 - "Spotify Client Tests"
Cohesion: 0.43
Nodes (5): _fake_init(), _FakeSettings, test_ensure_spotify_client_initializes_once(), test_ensure_spotify_client_prefers_configured_creds(), test_ensure_spotify_client_uses_default_creds_when_unset()

### Community 28 - "Auth Router Tests"
Cohesion: 0.22
Nodes (12): _mock_upstream_login(), upstream_auth.login degrades gracefully (username=None) when GET /user fails --, A username changed upstream must propagate on the next login (same reconciliatio, Unlike every other test in this file, this does NOT mock `upstream_auth.login` -, test_login_end_to_end_through_real_cookie_extraction_path_never_leaks_vb_auth(), test_login_stores_and_returns_username_from_upstream(), test_login_success_sets_cookie_and_me_returns_email(), test_login_with_failed_username_fetch_falls_back_to_email_and_still_succeeds() (+4 more)

### Community 29 - "Worker Router Tests"
Cohesion: 0.09
Nodes (30): AppSettings, Single-row table (v13) backing the output-format defaults editable from the, Per-user preferences, get-or-create on first read -- same singleton-row pattern, UserSettings, get_output_options(), get_output_settings(), get_retention_settings(), _output_settings_to_dict() (+22 more)

### Community 30 - "Queue Store Actions"
Cohesion: 0.09
Nodes (27): archiveJobs(), bumpJob(), cancelJob(), cancelTrack(), createJob(), createProxy(), deleteProxy(), getJob() (+19 more)

### Community 31 - "Version Roadmap Plans"
Cohesion: 0.15
Nodes (12): Development environments, graphify, Job rollup status (v2) — two derived axes, never one stored flag, Locked decisions, Maintaining this file, Master v2 additions, Project: spotdl-web, Retry engine numbers (+4 more)

### Community 32 - "Stream Router Tests"
Cohesion: 0.06
Nodes (28): channel_for(), _get_client(), make_progress_callback(), publish(), publish_job_event(), publish_track_event(), Any, datetime (+20 more)

### Community 33 - "CI Workflow Jobs"
Cohesion: 0.06
Nodes (31): 1. World and thesis, 2. Palette, 3. Type system, 4. Spacing scale, 5. Motion, 6. Component patterns, 7. Accessibility (confirmed hard requirement, PRODUCT.md), 8. Known, accepted gaps (do not silently "fix" without re-reading this section first) (+23 more)

### Community 41 - "API Error Class"
Cohesion: 0.28
Nodes (7): _configure_celery_logging(), JsonFormatter, Structured JSON logging (v12) — one shared formatter both uvicorn (`api`, via `l, Adds Celery task context (`task_id`/`task_name`) when a log call happens inside, Connecting *any* receiver to this signal tells Celery to skip its own logging, _redact(), _BaseJsonFormatter

### Community 42 - "Layout Load Guard"
Cohesion: 0.14
Nodes (22): admin_client(), admin_user(), authenticated_client(), client(), count_queries(), _login(), owner(), Counts SQL statements executed inside a `with` block, for asserting a query coun (+14 more)

### Community 44 - "Proxy Selection & Coexistence"
Cohesion: 0.22
Nodes (9): Adding a second (or third) user (v17+), Automated deployment (v21+), Backups, Deploying spotdl-web to the Debian 12 host, Firewall / network notes, Ongoing maintenance, Restart-survival test, Rollback / recovery (v21) (+1 more)

### Community 45 - "Track Event Schema"
Cohesion: 0.13
Nodes (14): Architecture, Auth API — verified findings, Context, Locked decisions, Other architectural notes, Repository layout, Retry engine, spotdl 4.5.2 — verified API surface (+6 more)

### Community 56 - "Planning Version Doc"
Cohesion: 0.39
Nodes (7): job_matches(), ColumnElement, Free-text search (v18) -- case-insensitive substring matching against the existi, One concatenated blob per track: title, album, and playlist/album name (all, A job matches if its own `source_url` does, or if any of its tracks do -- so, track_matches(), track_search_text()

### Community 57 - "Auth Version Doc"
Cohesion: 0.15
Nodes (13): ADMIN_EMAIL gates who services.users.get_or_create_user marks is_admin;, Rejects a pacing window that can't mean what it says. random.uniform happily, Settings, random.uniform tolerates reversed bounds and silently samples them anyway --, An admin who isn't allowlisted could never log in -- a deployment nobody can, test_admin_email_matching_is_allowed(), test_admin_email_missing_is_rejected(), test_admin_email_not_in_allowed_emails_is_rejected() (+5 more)

### Community 58 - "URL Expansion Version Doc"
Cohesion: 0.13
Nodes (14): 1. Download and register the runner (already done), 2. Install OS-level runner dependencies, 3. Run it as a persistent service, not an interactive session, 4. Verify registration, 5. Project test dependencies, 6. What the workflows actually run, 7. Caching across runs — already automatic, no workflow change needed, 8. Human-readable test reports (+6 more)

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
Cohesion: 0.24
Nodes (12): _format(), _make_record(), Structured JSON logging (v12). The one contract that matters most here: a creden, test_credentialed_url_in_exception_traceback_is_redacted(), test_credentialed_url_in_message_is_redacted(), test_no_task_context_outside_a_running_task(), test_plain_message_passes_through_unchanged(), test_task_context_injected_when_running_inside_a_task() (+4 more)

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
Cohesion: 0.27
Nodes (13): _copy_fixture(), _make_song(), Path, Song, Regression: the flac/ogg/opus year-tag patch (tagging.py's _YEAR_TAG_GAP_FORMATS, Regression: writing str(None) into the year tag would read back as a non-empty, test_is_supported_format(), test_repair_tags_does_not_clobber_correct_year_when_not_requested() (+5 more)

### Community 73 - "beat.py"
Cohesion: 0.29
Nodes (6): Done when, Host pre-flight (one-time, done as part of this slice — see `docs/RELEASE_PIPELINE.md`), Out of scope, flagged for later, Scope, v21 — Release Automation, Why

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
Cohesion: 0.29
Nodes (6): Done when, Scope, Tasks, The sweep — every surface, explicitly, v22 — Multi-User Hardening & Real-Stack Verification, Why data separation is treated as a security property

### Community 86 - "sv"
Cohesion: 0.40
Nodes (4): Building, Creating a project, Developing, sv

### Community 107 - "Version roadmap v00-v13"
Cohesion: 0.25
Nodes (7): 1. Confirm v23 in production — **done, record it**, 2. `yt-dlp-ejs` is pinned while `yt-dlp` floats, 3. New job never appears in the Jobs list until a full refetch, 4. Doc reconciliation, Done when, Scope, v23.1 — Download Reliability Follow-Up

### Community 125 - "test_app_settings.py"
Cohesion: 0.60
Nodes (5): changed_paths(), git_show(), main(), read_backend_version(), read_frontend_version()

### Community 126 - "conftest.py"
Cohesion: 0.25
Nodes (8): 1. Configure `.env`, 2. Bring up the stack, 3. Verify, 4. Seeding a second user for multi-user testing (v17+), 5. When a version is ready, Local development environment, Once there's real data worth protecting, Troubleshooting

### Community 128 - "Deploying spotdl-web to the Debian 12 host"
Cohesion: 0.24
Nodes (10): DownloadedTrack, Dedup ledger, independent of `tracks` so it survives job/track deletion and powe, _FakeSettings, _NonClosingSession, Wraps db_session so dedup's db.close() doesn't detach objects the test still, test_is_already_downloaded_returns_none_when_missing(), test_is_already_downloaded_returns_path_when_present(), test_reconcile_disk_drops_rows_for_missing_files() (+2 more)

### Community 130 - "stream"
Cohesion: 0.29
Nodes (8): _make_job_with_tracks(), v18's rollup status -- both derivations (`rollup.derive_rollup`, used by the sin, Same branches, proven through the real single-job HTTP response (`GET     /api/j, Same branches again, this time through `GET /api/jobs?status=...` -- the SQL, test_bare_settled_status_filter_matches_both_outcomes(), test_derive_rollup_matches_every_named_branch(), test_job_to_dict_status_field_matches_every_named_branch(), test_list_jobs_status_filter_matches_every_named_branch_via_sql()

### Community 131 - "Base"
Cohesion: 0.14
Nodes (25): cancel_track(), _content_disposition(), download_track_file(), _get_track_or_404(), list_track_attempts(), list_tracks(), datetime, JobSourceType (+17 more)

### Community 132 - "_get_track_or_404"
Cohesion: 0.25
Nodes (7): Design, Done when, Open questions to resolve during implementation, Prerequisite check — do this first, and stop if it fails, Scope, v29 — Network-Path Escalation (IPv4 / IPv6), Why this exists — the proven gap

### Community 133 - "Track state machine"
Cohesion: 0.12
Nodes (18): next_cooldown(), pick_proxy(), _probe_reachable(), Proxy, Session, timedelta, UUID, Proxy pool: file sync (`proxies.txt`), LRU selection, and per-proxy cooldown.  M (+10 more)

### Community 134 - "conftest.py"
Cohesion: 0.07
Nodes (37): make_user(), Direct DB insert, no login round trip -- for task-level tests (beat/download/, Mints a session directly via `services.sessions.create_session`, bypassing     `, session_cookie(), _make_job(), v18's `GET /api/jobs` -- every parameter tested in combination, not one at a tim, The plan's own "Done when" standard, taken literally: search + status filter +, test_counts_by_status_reflects_other_filters_but_not_the_status_filter_itself() (+29 more)

### Community 135 - "auth.py"
Cohesion: 0.28
Nodes (8): is_supported_format(), Path, Song, ID3/tag integrity verification and repair (v26).  spotdl embeds tags at download, Returns the set of required field names missing or empty on the file. Caller, Re-embeds whatever's missing from `song`. Cover art is only (re-)fetched when, repair_tags(), verify_tags()

### Community 137 - "_ensure_spotify_client"
Cohesion: 0.33
Nodes (6): _ensure_spotify_client(), expand(), Song, Thin wrapper around spotdl's URL-expansion logic.  Never import spotdl.utils.sea, SpotifyClient is a process-wide singleton that raises if .init() runs twice, so, Turn a Spotify URL (track/album/playlist/artist) or a search term into Songs.

### Community 139 - "test_expand_task.py"
Cohesion: 0.25
Nodes (8): 1. Install PostgreSQL (host-native — not a container), 2. Create the role and database, 3. Let Docker containers reach Postgres, 4. Install Docker + the Compose plugin, 5. Clone the repo, 6. Configure `.env`, 7. Bring up the stack, One-time host setup (already done on this host — kept for reference)

### Community 141 - "spotdl-web — Master Plan v3"
Cohesion: 0.14
Nodes (13): 2026-08-09 — v23.1 inserted; v29 inserted; hardening close renumbered to v30, 2026-08-09 — v23's root cause was not the stale yt-dlp pin, Amendments, Context, Critical files, Critical interactions to design around, Locked decisions for v3, spotdl-web — Master Plan v3 (+5 more)

### Community 142 - "v28 — Library Sort & Move"
Cohesion: 0.22
Nodes (8): Admin settings (all on `/settings`, reusing `app_settings`'s singleton get-or-create), Done when, Non-negotiable safety rules, Scope, Tasks, The dedup-ledger interaction — the thing most likely to go wrong, v28 — Library Sort & Move, Where it runs

### Community 143 - "test_upstream_auth.py"
Cohesion: 0.29
Nodes (11): _install_transport(), v25: `upstream_auth.login` now also best-effort fetches the username via `GET /u, A 200 that parses as valid JSON but isn't an object (`null`, `[]`, a bare scalar, test_get_user_empty_string_username_degrades_to_none(), test_get_user_failure_degrades_to_none_without_failing_login(), test_get_user_non_object_json_body_degrades_to_none_without_crashing(), test_login_failure_never_calls_get_user(), test_login_success_fetches_username_using_extracted_cookie() (+3 more)

### Community 144 - "test_settings_retention.py"
Cohesion: 0.33
Nodes (5): Done when, Scope, Tasks, v30 — Production Hardening & Close, Why a separate version

### Community 145 - "v23 — Download Reliability & Live-View Correctness"
Cohesion: 0.25
Nodes (7): Done when, Part 1 — Root-cause the download failure, Part 2 — Dependency policy (regardless of root cause), Part 3 — Typed error so the breaker can see a total failure, Part 4 — Live-view metadata and the render glitch, Scope, v23 — Download Reliability & Live-View Correctness

### Community 146 - "worker.py"
Cohesion: 0.47
Nodes (9): _is_busy(), pause_worker(), Session, `worker-dl` runs `--concurrency=1` (CLAUDE.md invariant), so at most one track, Clears the countdown early without resetting `consecutive_failures` or     `brea, release_breaker(), resume_worker(), _status_dict() (+1 more)

### Community 147 - "v24 — Per-Attempt History"
Cohesion: 0.29
Nodes (6): Done when, Schema, Scope, Tasks, `track_attempts` (new), v24 — Per-Attempt History

### Community 148 - "test_app_settings.py"
Cohesion: 0.29
Nodes (7): 1. Pull the merged code, 2. Update `.env`, 3. Migrate the downloads directory (one-time, before first boot with the new bind mount), 4. Bring up the stack with the production overlay, 5. Configure the Cloudflare Tunnel (Zero Trust dashboard), 6. Verify, Upgrading an existing deployment (manual fallback)

### Community 149 - "spotdl-web — Accumulated Gotchas (master v1, v01–v13)"
Cohesion: 0.14
Nodes (20): get_or_create_user(), normalize_email(), Session, User identity (v17) -- ALLOWED_EMAILS decides who may log in at all; this module, Creates the user row on first login, or loads and reconciles it on every     lat, An empty-string username is treated the same as None -- neither is a real fetche, Changing ADMIN_EMAIL must take effect on the next login, not need manual SQL --, A None username (upstream_auth's degrade-gracefully path, e.g. a flaky `GET (+12 more)

### Community 150 - "v25 — Usernames & Control Placement"
Cohesion: 0.33
Nodes (5): Done when, Part 1 — Usernames, Part 2 — Worker control placement, Scope, v25 — Usernames & Control Placement

### Community 151 - "v26 — ID3 Tag Integrity"
Cohesion: 0.33
Nodes (5): Design, Done when, Scope, Tasks, v26 — ID3 Tag Integrity

### Community 152 - "test_events.py"
Cohesion: 0.40
Nodes (5): is_already_downloaded(), Path, Download dedup ledger (`downloaded_tracks`) and startup disk reconciliation., Drops ledger rows whose file no longer exists on disk, so a manually-deleted, reconcile_disk()

### Community 153 - "v27 — Direct File Downloads"
Cohesion: 0.40
Nodes (4): Design — nginx X-Accel-Redirect, Done when, Scope, v27 — Direct File Downloads

### Community 154 - "_fetch_username"
Cohesion: 0.40
Nodes (5): _fetch_username(), login(), Response, Check credentials against vb2007.hu-api, and best-effort fetch the username via, `isAuthenticated`'s `GET /user` reads the `VB-AUTH` cookie itself -- extracted

### Community 156 - "track_counts"
Cohesion: 0.33
Nodes (6): buildQuery(), jobsQuery(), listJobsPage(), listJobTracksPage(), listTracksPage(), tracksQuery()

### Community 158 - "Amendments"
Cohesion: 0.40
Nodes (5): 2026-08-09 — CLAUDE.md split into rules vs. reference (folded into v14), 2026-08-09 — v15 complete; two v14 findings confirmed already scheduled, one new finding added, 2026-08-09 — v16 complete; NOT NULL applied literally, login/job creation left broken for v17, 2026-08-13 — v22 complete; the v13-precedent closing pass performed, master v2 done, Amendments

### Community 159 - "One-time host setup (already done on this host — kept for reference)"
Cohesion: 0.29
Nodes (9): title/artists/album straight from a track's `song_json` -- the single field, track_song_meta(), archive_due_jobs(), dispatch_due_tracks(), timedelta, Hourly (not every 30s like dispatch_due_tracks -- this is housekeeping, and it, A track stuck in DOWNLOADING/QUEUED past this long means whatever was supposed t, _reclaim_stale_tracks() (+1 more)

### Community 161 - "ApiError"
Cohesion: 0.50
Nodes (4): Architecture, Invariants — break these and things fail silently, Master v2 invariants, Master v3 invariants

### Community 162 - "Upgrading an existing deployment (manual fallback)"
Cohesion: 0.20
Nodes (3): get_db(), Session, expand_job()

### Community 163 - "proxies.py"
Cohesion: 0.29
Nodes (14): create_proxy(), CreateProxyRequest, delete_proxy(), _get_proxy_or_404(), list_proxies(), _proxy_to_dict(), Proxy, Response (+6 more)

### Community 166 - "list_jobs"
Cohesion: 0.36
Nodes (7): InvalidListParams, list_jobs(), JobSourceType, Session, Paginated/filtered/sorted/searchable job listing (v18) -- `GET /api/jobs` (scope, _sort_key(), _sort_value()

### Community 167 - "track_counts"
Cohesion: 0.29
Nodes (9): Session, UUID, Shared REST projections for Job/Track — deliberate projections rather than expos, One grouped aggregate covering every requested job -- replaces the per-job query, Single-job convenience over the bulk query -- for endpoints that serialize exact, track_attempt_to_dict(), track_counts(), track_counts_by_job() (+1 more)

### Community 168 - "_event_stream"
Cohesion: 0.60
Nodes (4): _event_stream(), Request, stream(), StreamingResponse

## Ambiguous Edges - Review These
- `PRODUCT.md` → `frontend/static/robots.txt`  [AMBIGUOUS]
  frontend/static/robots.txt · relation: conceptually_related_to
- `favicon.svg (Svelte default logo)` → `Instrument-panel THESIS (Operate mode)`  [AMBIGUOUS]
  frontend/src/lib/assets/favicon.svg · relation: semantically_similar_to

## Knowledge Gaps
- **452 isolated node(s):** `wait_for_stack_health.sh script`, `spotdl-web-backend`, `gitignorePath`, `name`, `private` (+447 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **50 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `PRODUCT.md` and `frontend/static/robots.txt`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `favicon.svg (Svelte default logo)` and `Instrument-panel THESIS (Operate mode)`?**
  _Edge tagged AMBIGUOUS (relation: semantically_similar_to) - confidence is low._
- **Why does `Track` connect `Track Model & Beat Tests` to `Session Auth Routes`, `Config & Health Check`, `Proxy Router Endpoints`, `Base`, `Upgrading an existing deployment (manual fallback)`, `Job Model & Expansion Tests`, `conftest.py`, `Circuit Breaker & Retry`, `stream`, `SSE Event Publishing`, `Dedup Ledger & Reconciliation`, `Layout Load Guard`, `One-time host setup (already done on this host — kept for reference)`?**
  _High betweenness centrality (0.083) - this node is a cross-community bridge._
- **Why does `User` connect `Session Auth Routes` to `Stream Router Tests`, `Upgrading an existing deployment (manual fallback)`, `Proxy Router Endpoints`, `test_job_listing.py`, `proxies.py`, `Base`, `list_jobs`, `_event_stream`, `Job Model & Expansion Tests`, `Layout Load Guard`, `Dedup Ledger & Reconciliation`, `Track Model & Beat Tests`, `Circuit Breaker & Retry`, `worker.py`, `spotdl-web — Accumulated Gotchas (master v1, v01–v13)`, `Worker Router Tests`?**
  _High betweenness centrality (0.058) - this node is a cross-community bridge._
- **Why does `$lib/api` connect `Frontend API Client` to `Worker Status UI`, `track_counts`, `Queue UI Components`, `Queue Store Actions`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Are the 72 inferred relationships involving `Track` (e.g. with `Base` and `cancel_job()`) actually correct?**
  _`Track` has 72 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `User` (e.g. with `Base` and `list_jobs()`) actually correct?**
  _`User` has 6 INFERRED edges - model-reasoned connections that need verification._