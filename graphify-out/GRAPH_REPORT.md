# Graph Report - spotdl-web  (2026-08-05)

## Corpus Check
- 112 files · ~67,675 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 873 nodes · 1311 edges · 117 communities (69 shown, 48 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 141 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `6bba7eb7`
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
- [[_COMMUNITY_+layout.ts|+layout.ts]]
- [[_COMMUNITY_+page.svelte|+page.svelte]]
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
- [[_COMMUNITY_spotdl-web — Master Development Plan|spotdl-web — Master Development Plan]]
- [[_COMMUNITY__NonClosingSession|_NonClosingSession]]
- [[_COMMUNITY_conftest.py|conftest.py]]
- [[_COMMUNITY_Track|Track]]
- [[_COMMUNITY_retry.py|retry.py]]
- [[_COMMUNITY_spotdl-web — Master Development Plan|spotdl-web — Master Development Plan]]
- [[_COMMUNITY_db.py|db.py]]
- [[_COMMUNITY_events.py|events.py]]
- [[_COMMUNITY_test_stream.py|test_stream.py]]
- [[_COMMUNITY_README|README.md]]
- [[_COMMUNITY_Local development environment|Local development environment]]
- [[_COMMUNITY_Architecture|Architecture]]
- [[_COMMUNITY_pg_backup.sh|pg_backup.sh]]
- [[_COMMUNITY_test_worker.py|test_worker.py]]
- [[_COMMUNITY_test_beat_task.py|test_beat_task.py]]
- [[_COMMUNITY_AppSettings|AppSettings]]
- [[_COMMUNITY_test_events.py|test_events.py]]
- [[_COMMUNITY_test_proxies_router.py|test_proxies_router.py]]
- [[_COMMUNITY_download_one|download_one]]
- [[_COMMUNITY_test_settings_router.py|test_settings_router.py]]
- [[_COMMUNITY_beat.py|beat.py]]
- [[_COMMUNITY_stream|stream]]
- [[_COMMUNITY_$libcomponentsWorkerStatus.svelte|$lib/components/WorkerStatus.svelte]]
- [[_COMMUNITY__ensure_spotify_client|_ensure_spotify_client]]
- [[_COMMUNITY_sync_from_file|sync_from_file]]
- [[_COMMUNITY_createQueueStore|createQueueStore]]
- [[_COMMUNITY_ApiError|ApiError]]

## God Nodes (most connected - your core abstractions)
1. `$lib/api` - 51 edges
2. `Track` - 47 edges
3. `UserSession` - 31 edges
4. `request()` - 25 edges
5. `Project: spotdl-web` - 23 edges
6. `Job` - 20 edges
7. `_make_track()` - 18 edges
8. `get_settings()` - 17 edges
9. `WorkerState` - 17 edges
10. `_patch_common()` - 17 edges

## Surprising Connections (you probably didn't know these)
- `_reconcile_disk_on_boot()` --calls--> `reconcile_disk()`  [INFERRED]
  backend/app/tasks/celery_app.py → backend/app/services/dedup.py
- `login()` --calls--> `get_settings()`  [INFERRED]
  backend/app/routers/auth.py → backend/app/config.py
- `_output_settings_to_dict()` --calls--> `get_settings()`  [INFERRED]
  backend/app/routers/settings.py → backend/app/config.py
- `_event_stream()` --calls--> `get_settings()`  [INFERRED]
  backend/app/routers/stream.py → backend/app/config.py
- `get_output_settings()` --calls--> `get_settings()`  [INFERRED]
  backend/app/services/app_settings.py → backend/app/config.py

## Import Cycles
- None detected.

## Communities (117 total, 48 thin omitted)

### Community 2 - "Planning & Config Docs"
Cohesion: 0.13
Nodes (12): _aware(), _FakeSettings, _NonClosingSession, datetime, Wraps db_session so sync_from_file's db.close() doesn't detach objects the test, test_pick_proxy_stamps_last_used_at_on_selection(), test_record_proxy_result_failure_reads_ladder_before_incrementing(), test_record_proxy_result_failure_sets_cooldown_and_increments() (+4 more)

### Community 12 - "Deployment Hardening"
Cohesion: 0.17
Nodes (9): get_settings(), Settings, health(), Response, login(), Check credentials against vb2007.hu-api. Never forwards or returns the upstream, download_track(), test_next_delay_follows_ladder_and_caps_at_final_step() (+1 more)

### Community 13 - "devDependencies"
Cohesion: 0.07
Nodes (29): devDependencies, eslint, eslint-config-prettier, @eslint/js, eslint-plugin-svelte, globals, prettier, prettier-plugin-svelte (+21 more)

### Community 14 - "Project: spotdl-web"
Cohesion: 0.15
Nodes (15): Job, StreamEvent, Track, TrackState, $lib/components/IncomingJobs.svelte, $lib/components/QueueTable.svelte, $lib/components/Waterfall.svelte, $lib/stores/queue (+7 more)

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

### Community 32 - "$lib/assets/favicon.svg"
Cohesion: 0.20
Nodes (7): _configure_celery_logging(), JsonFormatter, Structured JSON logging (v12) — one shared formatter both uvicorn (`api`, via `l, Adds Celery task context (`task_id`/`task_name`) when a log call happens inside, Connecting *any* receiver to this signal tells Celery to skip its own logging, _redact(), _BaseJsonFormatter

### Community 37 - "main.py"
Cohesion: 0.07
Nodes (60): Our own session store — separate from the upstream VB-AUTH token (see v03)., UserSession, login(), LoginRequest, logout(), me(), Request, Response (+52 more)

### Community 44 - "+layout.ts"
Cohesion: 0.10
Nodes (30): $lib/api, API_BASE, createJob(), createProxy(), deleteProxy(), EditableOutputSettings, getOutputOptions(), getOutputSettings() (+22 more)

### Community 45 - "+page.svelte"
Cohesion: 0.08
Nodes (24): 1. World and thesis, 2. Palette, 3. Type system, 4. Spacing scale, 5. Motion, 6. Component patterns, 7. Accessibility (confirmed hard requirement, PRODUCT.md), 8. Known, accepted gaps (do not silently "fix" without re-reading this section first) (+16 more)

### Community 78 - "Deploying spotdl-web (v01 — scaffold) to the Debian 12 host"
Cohesion: 0.10
Nodes (21): 1. Install PostgreSQL (host-native — not a container), 1. Pull the merged code, 2. Create the role and database, 2. Update `.env`, 3. Let Docker containers reach Postgres, 3. Migrate the downloads directory (one-time, before first boot with the new bind mount), 4. Bring up the stack with the production overlay, 4. Install Docker + the Compose plugin (+13 more)

### Community 79 - "Local development environment"
Cohesion: 0.17
Nodes (11): Accessibility & Inclusion, Brand Commitments, Capabilities and Constraints, Evidence on Hand, Operating Context, Platform, Positioning, Product (+3 more)

### Community 81 - "test_auth.py"
Cohesion: 0.48
Nodes (5): _mock_upstream_login(), test_login_success_sets_cookie_and_me_returns_email(), test_logout_clears_session(), test_vb_auth_cookie_never_reaches_the_browser(), test_wrong_password_and_disallowed_email_return_identical_response()

### Community 82 - "Track"
Cohesion: 0.13
Nodes (25): Job, One row per submitted URL (album/playlist/artist/track)., _capture_job_events(), _FakeSong, _NonClosingSession, Wraps db_session so expand_job's db.close() doesn't detach objects the test, _stub_download_track(), test_expand_job_db_error_during_insert_marks_job_failed() (+17 more)

### Community 83 - "test_expansion.py"
Cohesion: 0.43
Nodes (5): _fake_init(), _FakeSettings, test_ensure_spotify_client_initializes_once(), test_ensure_spotify_client_prefers_configured_creds(), test_ensure_spotify_client_uses_default_creds_when_unset()

### Community 84 - "test_downloads.py"
Cohesion: 0.27
Nodes (9): _FakeDownloader, _FakeSettings, test_download_one_delegates_to_search_and_download(), test_download_one_ensures_spotify_client_before_downloading(), test_get_downloader_always_disables_rich_tui(), test_get_downloader_builds_new_instance_for_different_key(), test_get_downloader_builds_output_from_given_dir_and_template(), test_get_downloader_caches_per_format_bitrate_output_and_proxy() (+1 more)

### Community 85 - "spotdl-web — Master Development Plan"
Cohesion: 0.09
Nodes (23): Architecture, Auth API — `vb2007.hu-api` (verified from `/home/vb2007/code/vb2007.hu-api` source), Development environments, Locked decisions, Project: spotdl-web, Retry engine numbers, spotdl 4.5.2 — verified API surface actually used, Track state machine (+15 more)

### Community 86 - "_NonClosingSession"
Cohesion: 0.29
Nodes (11): _format(), _make_record(), Structured JSON logging (v12). The one contract that matters most here: a creden, test_credentialed_url_in_exception_traceback_is_redacted(), test_credentialed_url_in_message_is_redacted(), test_no_task_context_outside_a_running_task(), test_plain_message_passes_through_unchanged(), test_task_context_injected_when_running_inside_a_task() (+3 more)

### Community 87 - "conftest.py"
Cohesion: 0.13
Nodes (27): Single-row table backing the global circuit breaker., WorkerState, breaker_active(), classify_error(), get_worker_state(), maybe_trip_breaker(), next_delay(), datetime (+19 more)

### Community 89 - "Track"
Cohesion: 0.12
Nodes (39): One row per individual song discovered while expanding a job — the unit the retr, Track, _capture_events(), _FakeDownloader, _FakeProgressHandler, _make_track(), _NonClosingSession, _patch_common() (+31 more)

### Community 90 - "retry.py"
Cohesion: 0.19
Nodes (12): next_cooldown(), pick_proxy(), Proxy, Session, timedelta, UUID, Proxy pool: file sync (`proxies.txt`), LRU selection, and per-proxy cooldown.  M, Least-recently-used selection among enabled, out-of-cooldown proxies — simple LR (+4 more)

### Community 91 - "spotdl-web — Master Development Plan"
Cohesion: 0.22
Nodes (9): Auth API — verified findings, Context, Locked decisions, Repository layout, spotdl 4.5.2 — verified API surface, spotdl-web — Master Development Plan, Verification, Version roadmap (+1 more)

### Community 92 - "db.py"
Cohesion: 0.07
Nodes (27): Base, get_db(), Session, DownloadedTrack, Dedup ledger, independent of `tracks` so it survives job/track deletion and powe, JobSourceType, JobState, Proxy (+19 more)

### Community 93 - "events.py"
Cohesion: 0.14
Nodes (13): Any, _get_client(), make_progress_callback(), publish(), publish_job_event(), publish_track_event(), datetime, Redis pub/sub event bus for live progress.  Publishers (Celery tasks) are plain (+5 more)

### Community 94 - "test_stream.py"
Cohesion: 0.60
Nodes (3): _fake_event_stream(), _login(), test_stream_returns_sse_headers_and_forwarded_events()

### Community 95 - "README.md"
Cohesion: 0.25
Nodes (3): graphify, Plan, spotdl-web

### Community 96 - "Local development environment"
Cohesion: 0.29
Nodes (7): 1. Configure `.env`, 2. Bring up the stack, 3. Verify, 4. When a version is ready, Local development environment, Once there's real data worth protecting, Troubleshooting

### Community 97 - "Architecture"
Cohesion: 0.40
Nodes (5): Architecture, Other architectural notes, Retry engine, The single most important design point, Track state machine

### Community 99 - "test_worker.py"
Cohesion: 0.53
Nodes (4): _login(), test_pause_and_resume_worker(), test_release_breaker_clears_countdown_without_resetting_trip_count(), test_worker_status_defaults()

### Community 100 - "test_beat_task.py"
Cohesion: 0.28
Nodes (11): _make_track(), _NonClosingSession, _patch_session(), See test_download_task.py — download_track's db.close() would otherwise detach, test_dispatch_due_tracks_dispatches_and_flips_state(), test_dispatch_due_tracks_leaves_recent_downloading_track_alone(), test_dispatch_due_tracks_orders_by_job_priority_over_scheduled_at(), test_dispatch_due_tracks_priority_never_pulls_forward_a_not_yet_due_track() (+3 more)

### Community 102 - "AppSettings"
Cohesion: 0.13
Nodes (19): AppSettings, Single-row table (v13) backing the output-format defaults editable from the, get_output_options(), get_output_settings(), _output_settings_to_dict(), Session, The real, live set of format/bitrate values the installed spotdl accepts --, Takes effect on the *next* download_track call, no restart needed -- get_downloa (+11 more)

### Community 103 - "test_events.py"
Cohesion: 0.28
Nodes (12): cancel_track(), _get_track_or_404(), list_tracks(), Session, Track, UUID, All tracks across every job, in one query -- what the frontend's initial load an, Same semantics as `DELETE /api/jobs/{id}` but for a single track — a track     a (+4 more)

### Community 104 - "test_proxies_router.py"
Cohesion: 0.28
Nodes (11): _login(), test_create_proxy_accepts_well_formed_url(), test_create_proxy_defaults_to_manual_source_and_enabled(), test_create_proxy_rejects_blank_url(), test_create_proxy_rejects_duplicate_url(), test_create_proxy_rejects_malformed_url(), test_delete_file_proxy_soft_disables_without_dropping_row(), test_delete_manual_proxy_hard_deletes_the_row() (+3 more)

### Community 105 - "download_one"
Cohesion: 0.24
Nodes (9): download_one(), get_downloader(), get_supported_output_options(), Path, Song, Thin wrapper around spotdl's download machinery.  Never construct a `Downloader`, The real, live set of --format/--bitrate values the installed spotdl accepts —, Must be called from a plain sync context — search_and_download raises     Downlo (+1 more)

### Community 106 - "test_settings_router.py"
Cohesion: 0.42
Nodes (9): _FakeSettings, _login(), test_get_output_options_reflects_the_real_installed_spotdl(), test_get_output_settings_seeds_from_env_defaults(), test_update_output_settings_ignores_output_dir_if_sent(), test_update_output_settings_ignores_unset_fields(), test_update_output_settings_persists_and_returns_partial_update(), test_update_output_settings_rejects_unsupported_bitrate() (+1 more)

### Community 107 - "beat.py"
Cohesion: 0.47
Nodes (5): dispatch_due_tracks(), timedelta, A track stuck in DOWNLOADING/QUEUED past this long means whatever was supposed t, _reclaim_stale_tracks(), stale_track_after()

### Community 108 - "stream"
Cohesion: 0.60
Nodes (4): _event_stream(), Request, stream(), StreamingResponse

### Community 110 - "$lib/components/WorkerStatus.svelte"
Cohesion: 0.20
Nodes (5): svelte, workerStatus, $lib/components/Countdown.svelte, $lib/components/WorkerStatus.svelte, worker

### Community 111 - "_ensure_spotify_client"
Cohesion: 0.33
Nodes (6): _ensure_spotify_client(), expand(), Song, Thin wrapper around spotdl's URL-expansion logic.  Never import spotdl.utils.sea, SpotifyClient is a process-wide singleton that raises if .init() runs twice, so, Turn a Spotify URL (track/album/playlist/artist) or a search term into Songs.

### Community 112 - "sync_from_file"
Cohesion: 0.29
Nodes (6): _probe_reachable(), Best-effort TCP connect so an obviously dead new entry doesn't get picked first, Run once on worker-meta boot (see celery_app.py). Upserts proxies.txt's URLs as, sync_from_file(), _reconcile_disk_on_boot(), _sync_proxies_on_boot()

### Community 113 - "createQueueStore"
Cohesion: 0.33
Nodes (6): bumpJob(), cancelJob(), cancelTrack(), retryTrack(), setJobPriority(), createQueueStore()

## Knowledge Gaps
- **262 isolated node(s):** `spotdl-web-backend`, `gitignorePath`, `name`, `private`, `version` (+257 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **48 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `request()` connect `+layout.ts` to `$lib/assets/favicon.svg`, `createQueueStore`, `$lib/components/WorkerStatus.svelte`?**
  _High betweenness centrality (0.100) - this node is a cross-community bridge._
- **Why does `$lib/api` connect `+layout.ts` to `$lib/components/WorkerStatus.svelte`, `Project: spotdl-web`, `createQueueStore`, `ApiError`, `+layout.ts`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._
- **Why does `Track` connect `Track` to `test_beat_task.py`, `main.py`, `test_events.py`, `beat.py`, `Deployment Hardening`, `Track`, `conftest.py`, `db.py`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Are the 45 inferred relationships involving `Track` (e.g. with `Base` and `cancel_job()`) actually correct?**
  _`Track` has 45 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `UserSession` (e.g. with `Base` and `delete_session()`) actually correct?**
  _`UserSession` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Structured JSON logging (v12) — one shared formatter both uvicorn (`api`, via `l`, `Adds Celery task context (`task_id`/`task_name`) when a log call happens inside`, `Connecting *any* receiver to this signal tells Celery to skip its own logging` to the rest of the system?**
  _316 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Planning & Config Docs` be split into smaller, more focused modules?**
  _Cohesion score 0.12681159420289856 - nodes in this community are weakly interconnected._