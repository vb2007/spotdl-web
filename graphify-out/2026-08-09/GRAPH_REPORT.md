# Graph Report - .  (2026-08-05)

## Corpus Check
- 120 files · ~68,198 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 729 nodes · 1306 edges · 66 communities (47 shown, 19 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 155 edges (avg confidence: 0.77)
- Token cost: 210,423 input · 0 output

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
- [[_COMMUNITY_Proxy Router Tests|Proxy Router Tests]]
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

## God Nodes (most connected - your core abstractions)
1. `$lib/api` - 51 edges
2. `Track` - 47 edges
3. `UserSession` - 31 edges
4. `request()` - 25 edges
5. `Job` - 20 edges
6. `_make_track()` - 18 edges
7. `get_settings()` - 17 edges
8. `WorkerState` - 17 edges
9. `_patch_common()` - 17 edges
10. `Base` - 14 edges

## Surprising Connections (you probably didn't know these)
- `Master plan architecture diagram` --semantically_similar_to--> `System Architecture (Tunnel/web/api/workers/beat/DB)`  [INFERRED] [semantically similar]
  plan/00-master-plan.md → CLAUDE.md
- `favicon.svg (Svelte default logo)` --semantically_similar_to--> `Instrument-panel THESIS (Operate mode)`  [AMBIGUOUS] [semantically similar]
  frontend/src/lib/assets/favicon.svg → frontend/src/DESIGN.md
- `Product purpose: fire-and-forget durable downloads` --conceptually_related_to--> `Per-track retry ladder (15m→1h→4h→12h→24h)`  [INFERRED]
  PRODUCT.md → CLAUDE.md
- `Master plan repository layout` --conceptually_related_to--> `System Architecture (Tunnel/web/api/workers/beat/DB)`  [INFERRED]
  plan/00-master-plan.md → CLAUDE.md
- `psycopg==3.3.4` --references--> `PostgreSQL (host, source of truth)`  [EXTRACTED]
  backend/requirements.txt → CLAUDE.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **CI PR-checks pipeline (pytest, publish-report, compose-config, frontend)** — github_workflows_ci_pytest_job, github_workflows_ci_publish_report_job, github_workflows_ci_compose_config_job, github_workflows_ci_frontend_job [EXTRACTED 1.00]
- **Docker Compose layered configuration (base/override/prod)** — docker_compose_doc, docker_compose_override_doc, docker_compose_prod_doc [EXTRACTED 1.00]
- **Durable-memory documentation set (CLAUDE.md, master plan, README)** — claude_doc, plan_00_master_plan_doc, readme_doc [EXTRACTED 0.90]

## Communities (66 total, 19 thin omitted)

### Community 0 - "Session Auth Routes"
Cohesion: 0.07
Nodes (57): Our own session store — separate from the upstream VB-AUTH token (see v03)., UserSession, login(), LoginRequest, logout(), me(), Request, Response (+49 more)

### Community 1 - "Config & Health Check"
Cohesion: 0.05
Nodes (41): get_settings(), Settings, health(), Response, get_output_options(), get_output_settings(), _output_settings_to_dict(), Session (+33 more)

### Community 2 - "Proxy Router Endpoints"
Cohesion: 0.07
Nodes (44): create_proxy(), CreateProxyRequest, delete_proxy(), _get_proxy_or_404(), list_proxies(), _proxy_to_dict(), Proxy, Response (+36 more)

### Community 3 - "Track Model & Beat Tests"
Cohesion: 0.12
Nodes (37): One row per individual song discovered while expanding a job — the unit the retr, Track, _make_track(), _NonClosingSession, _patch_session(), See test_download_task.py — download_track's db.close() would otherwise detach, test_dispatch_due_tracks_dispatches_and_flips_state(), test_dispatch_due_tracks_leaves_recent_downloading_track_alone() (+29 more)

### Community 4 - "DB Base & App Settings"
Cohesion: 0.08
Nodes (23): Base, get_db(), Session, AppSettings, Single-row table (v13) backing the output-format defaults editable from the, JobSourceType, JobState, Proxy (+15 more)

### Community 5 - "Job Model & Expansion Tests"
Cohesion: 0.13
Nodes (25): Job, One row per submitted URL (album/playlist/artist/track)., _capture_job_events(), _FakeSong, _NonClosingSession, Wraps db_session so expand_job's db.close() doesn't detach objects the test, _stub_download_track(), test_expand_job_db_error_during_insert_marks_job_failed() (+17 more)

### Community 6 - "Frontend API Client"
Cohesion: 0.10
Nodes (30): $lib/api, API_BASE, createJob(), createProxy(), deleteProxy(), EditableOutputSettings, getOutputOptions(), getOutputSettings() (+22 more)

### Community 7 - "Circuit Breaker & Retry"
Cohesion: 0.13
Nodes (27): Single-row table backing the global circuit breaker., WorkerState, breaker_active(), classify_error(), get_worker_state(), maybe_trip_breaker(), next_delay(), datetime (+19 more)

### Community 8 - "Frontend Lint Tooling"
Cohesion: 0.07
Nodes (29): devDependencies, eslint, eslint-config-prettier, @eslint/js, eslint-plugin-svelte, globals, prettier, prettier-plugin-svelte (+21 more)

### Community 9 - "Proxy Service Tests"
Cohesion: 0.13
Nodes (12): _aware(), _FakeSettings, _NonClosingSession, datetime, Wraps db_session so sync_from_file's db.close() doesn't detach objects the test, test_pick_proxy_stamps_last_used_at_on_selection(), test_record_proxy_result_failure_reads_ladder_before_incrementing(), test_record_proxy_result_failure_sets_cooldown_and_increments() (+4 more)

### Community 10 - "SSE Event Publishing"
Cohesion: 0.14
Nodes (13): Any, _get_client(), make_progress_callback(), publish(), publish_job_event(), publish_track_event(), datetime, Redis pub/sub event bus for live progress.  Publishers (Celery tasks) are plain (+5 more)

### Community 11 - "Dedup Ledger & Reconciliation"
Cohesion: 0.16
Nodes (15): DownloadedTrack, Dedup ledger, independent of `tracks` so it survives job/track deletion and powe, is_already_downloaded(), Path, Download dedup ledger (`downloaded_tracks`) and startup disk reconciliation., Drops ledger rows whose file no longer exists on disk, so a manually-deleted, reconcile_disk(), _FakeSettings (+7 more)

### Community 12 - "Frontend Design System"
Cohesion: 0.16
Nodes (18): ALLOWED_EMAILS allowlist gate, frontend/src/app.html, Amber-exclusivity rule for live state, Matte charcoal chassis material - accepted open gap, frontend/src/DESIGN.md, Mobile stacked layout (one-cell-per-line rule), .panel recessed instrument housing, QueueTable state to color/label mapping (+10 more)

### Community 13 - "Queue UI Components"
Cohesion: 0.15
Nodes (15): Job, StreamEvent, Track, TrackState, $lib/components/IncomingJobs.svelte, $lib/components/QueueTable.svelte, $lib/components/Waterfall.svelte, $lib/stores/queue (+7 more)

### Community 14 - "Track Router Tests"
Cohesion: 0.30
Nodes (13): _aware(), _login(), _make_track(), datetime, test_cancel_track_is_a_noop_on_terminal_states(), test_cancel_track_marks_cancelled_and_clears_schedule(), test_cancel_unknown_track_returns_404(), test_list_tracks_returns_every_track_across_every_job_in_one_call() (+5 more)

### Community 15 - "System Architecture Overview"
Cohesion: 0.23
Nodes (15): api service (FastAPI: auth, jobs, SSE), System Architecture (Tunnel/web/api/workers/beat/DB), beat (Celery Beat, dispatch_due_tracks), GET /api/tracks bulk endpoint replacing N per-job requests (v12), Cloudflare Tunnel ingress, Dedup ledger + reconcile_disk(), Non-root container needs real home dir for spotdl import (v12), PostgreSQL (host, source of truth) (+7 more)

### Community 16 - "Backend Dependencies"
Cohesion: 0.21
Nodes (14): alembic==1.18.5, celery==5.6.3, backend/requirements.txt, fastapi==0.141.1, psycopg==3.3.4, python-json-logger==4.1.0, redis==6.4.0 (python client), spotdl==4.5.2 (+6 more)

### Community 17 - "Download Service Tests"
Cohesion: 0.27
Nodes (9): _FakeDownloader, _FakeSettings, test_download_one_delegates_to_search_and_download(), test_download_one_ensures_spotify_client_before_downloading(), test_get_downloader_always_disables_rich_tui(), test_get_downloader_builds_new_instance_for_different_key(), test_get_downloader_builds_output_from_given_dir_and_template(), test_get_downloader_caches_per_format_bitrate_output_and_proxy() (+1 more)

### Community 18 - "Proxy Router Tests"
Cohesion: 0.28
Nodes (11): _login(), test_create_proxy_accepts_well_formed_url(), test_create_proxy_defaults_to_manual_source_and_enabled(), test_create_proxy_rejects_blank_url(), test_create_proxy_rejects_duplicate_url(), test_create_proxy_rejects_malformed_url(), test_delete_file_proxy_soft_disables_without_dropping_row(), test_delete_manual_proxy_hard_deletes_the_row() (+3 more)

### Community 19 - "TypeScript Config"
Cohesion: 0.15
Nodes (12): compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, moduleResolution, resolveJsonModule, rewriteRelativeImportExtensions (+4 more)

### Community 20 - "Alembic Env & JSON Logging"
Cohesion: 0.20
Nodes (7): _configure_celery_logging(), JsonFormatter, Structured JSON logging (v12) — one shared formatter both uvicorn (`api`, via `l, Adds Celery task context (`task_id`/`task_name`) when a log call happens inside, Connecting *any* receiver to this signal tells Celery to skip its own logging, _redact(), _BaseJsonFormatter

### Community 21 - "v12 Deploy Gotchas"
Cohesion: 0.27
Nodes (9): Compose list-key merge vs replace gotcha (v01, !override tag), Separate dev vs prod web healthchecks (v12), Frontend .dockerignore fix for build context bloat (v12), localhost resolves ::1 before 127.0.0.1, breaking healthchecks (v12), migrate service gates backend startup via depends_on (v12), migrate one-shot Alembic service, PUBLIC_API_BASE_URL as Dockerfile ARG, same-origin default (v12), Redis maxmemory-policy noeviction rationale (v12) (+1 more)

### Community 22 - "Settings Router Tests"
Cohesion: 0.42
Nodes (9): _FakeSettings, _login(), test_get_output_options_reflects_the_real_installed_spotdl(), test_get_output_settings_seeds_from_env_defaults(), test_update_output_settings_ignores_output_dir_if_sent(), test_update_output_settings_ignores_unset_fields(), test_update_output_settings_persists_and_returns_partial_update(), test_update_output_settings_rejects_unsupported_bitrate() (+1 more)

### Community 23 - "Master Plan Decisions"
Cohesion: 0.20
Nodes (11): Server-to-server auth proxy to vb2007.hu-api, Locked architectural decisions table, Version roadmap v00-v13, Workflow rules (one feature at a time, branch per version, etc.), Master plan architecture diagram, Master plan vb2007.hu-api verified findings, plan/00-master-plan.md, Master plan locked decisions (+3 more)

### Community 24 - "CLAUDE.md & CI Runner Docs"
Cohesion: 0.33
Nodes (6): Single workflow file over splitting CI (v12 lesson), Three CI workflow bugs surfaced only on real self-hosted runner (v12), Local dev vs Debian host environments, Postgres backup/restore (pg_backup.sh), Same-origin nginx reverse proxy design (v12), Self-hosted GitHub Actions runner on production host

### Community 25 - "Worker Status UI"
Cohesion: 0.20
Nodes (5): svelte, workerStatus, $lib/components/Countdown.svelte, $lib/components/WorkerStatus.svelte, worker

### Community 26 - "Retry Engine Spec"
Cohesion: 0.24
Nodes (10): Global circuit breaker, Proxy rotation / direct-then-proxy escalation, Per-track retry ladder (15m→1h→4h→12h→24h), Track state machine, Master plan retry engine spec, Master plan track state machine, v02 — Database Schema, v11 — Job Priority / Reordering (+2 more)

### Community 27 - "Spotify Client Tests"
Cohesion: 0.43
Nodes (5): _fake_init(), _FakeSettings, test_ensure_spotify_client_initializes_once(), test_ensure_spotify_client_prefers_configured_creds(), test_ensure_spotify_client_uses_default_creds_when_unset()

### Community 28 - "Auth Router Tests"
Cohesion: 0.48
Nodes (5): _mock_upstream_login(), test_login_success_sets_cookie_and_me_returns_email(), test_logout_clears_session(), test_vb_auth_cookie_never_reaches_the_browser(), test_wrong_password_and_disallowed_email_return_identical_response()

### Community 29 - "Worker Router Tests"
Cohesion: 0.53
Nodes (4): _login(), test_pause_and_resume_worker(), test_release_breaker_clears_countdown_without_resetting_trip_count(), test_worker_status_defaults()

### Community 30 - "Queue Store Actions"
Cohesion: 0.33
Nodes (6): bumpJob(), cancelJob(), cancelTrack(), retryTrack(), setJobPriority(), createQueueStore()

### Community 31 - "Version Roadmap Plans"
Cohesion: 0.33
Nodes (6): Master plan repository layout, pydantic-settings Env Config, v01 — Repo & Compose Scaffold, v06 — Retry Engine, v07 — Proxy Rotation, v13 — Settings UI (Final)

### Community 32 - "Stream Router Tests"
Cohesion: 0.60
Nodes (3): _fake_event_stream(), _login(), test_stream_returns_sse_headers_and_forwarded_events()

### Community 33 - "CI Workflow Jobs"
Cohesion: 0.67
Nodes (4): CI Workflow (ci.yml), frontend job, publish-report job, pytest job

## Ambiguous Edges - Review These
- `PRODUCT.md` → `frontend/static/robots.txt`  [AMBIGUOUS]
  frontend/static/robots.txt · relation: conceptually_related_to
- `favicon.svg (Svelte default logo)` → `Instrument-panel THESIS (Operate mode)`  [AMBIGUOUS]
  frontend/src/lib/assets/favicon.svg · relation: semantically_similar_to

## Knowledge Gaps
- **81 isolated node(s):** `spotdl-web-backend`, `gitignorePath`, `name`, `private`, `version` (+76 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **19 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `PRODUCT.md` and `frontend/static/robots.txt`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `favicon.svg (Svelte default logo)` and `Instrument-panel THESIS (Operate mode)`?**
  _Edge tagged AMBIGUOUS (relation: semantically_similar_to) - confidence is low._
- **Why does `request()` connect `Frontend API Client` to `Worker Status UI`, `Alembic Env & JSON Logging`, `Queue Store Actions`?**
  _High betweenness centrality (0.143) - this node is a cross-community bridge._
- **Why does `$lib/api` connect `Frontend API Client` to `API Error Class`, `Layout Load Guard`, `Queue UI Components`, `Worker Status UI`, `Queue Store Actions`?**
  _High betweenness centrality (0.117) - this node is a cross-community bridge._
- **Why does `Track` connect `Track Model & Beat Tests` to `Session Auth Routes`, `Config & Health Check`, `DB Base & App Settings`, `Job Model & Expansion Tests`, `Circuit Breaker & Retry`, `Track Router Tests`?**
  _High betweenness centrality (0.113) - this node is a cross-community bridge._
- **Are the 45 inferred relationships involving `Track` (e.g. with `Base` and `cancel_job()`) actually correct?**
  _`Track` has 45 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `UserSession` (e.g. with `Base` and `delete_session()`) actually correct?**
  _`UserSession` has 2 INFERRED edges - model-reasoned connections that need verification._