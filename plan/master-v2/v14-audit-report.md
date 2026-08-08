# v14 — Master v1 Implementation Audit Report

Read-only audit of what master v1 (v00–v13) actually shipped against what each version's plan
promised. No application code was changed to produce this report — see "Explicitly out of scope"
in `plan/master-v2/v14-audit.md`. Every plan file's `## Done when` section was audited bullet by
bullet against the current codebase, plus the locked-decisions table and the six architecture
invariants CLAUDE.md states as rules.

**Scope actually covered: 52 "Done when" bullets across all 14 v1 plan files** (v00: 4, v01: 4,
v02: 3, v03: 4, v04: 4, v05: 4, v06: 4, v07: 4, v08: 3, v09: 4, v10: 4, v11: 2, v12: 4, v13: 4 — sum
verified by `awk` count against each plan file's `## Done when` section, not sampled), **14
locked-decisions rows**, and **6 architecture invariants**. Zero bullets were skipped.

**Headline finding: master v1 is in genuinely good shape.** No locked decision and no architecture
invariant was found silently violated. Of 52 "Done when" bullets, the overwhelming majority are
`met` with real-stack evidence (not just unit tests) already recorded in `docs/GOTCHAS.md` or PR
bodies — a direct payoff of the project's "mocked verification is not verification" rule. The real
findings are: two already-known drifts (pacing hook, `list_jobs` N+1), a handful of `partially met`
bullets where only part of a scenario was ever run against the real stack (e.g. album-scale
re-submission, a literal playlist URL, a literal host reboot), one dead enum value, one stale/wrong
README paragraph, and one stale code comment. Nothing found here rises to "needs its own version" —
everything is routed to v15.

---

## v00 — Planning

| Bullet | Verdict | Evidence | Severity/Routing |
|---|---|---|---|
| All 15 plan files exist and are internally consistent with each other and with `CLAUDE.md` | partially met | `plan/master-v1/` holds all 15 files. `00-master-plan.md`'s own "Repository layout" ASCII block (line 178) says "v00…v12 plan files" while its "Version roadmap" table correctly lists v13 — an internal inconsistency inside a file that is policy-locked "never edited again." | Cosmetic; no action — the file is frozen by policy. |
| `CLAUDE.md` contains no reference to information that only exists in this chat session | met | `git show 914d30f:CLAUDE.md` — grounded, file:line-cited facts throughout, no chat-only references. | — |
| `graphify-out/graph.json` exists | met | Added by commit `783d39d`; still present at HEAD. | — |
| PR opened `dev-planning` → `main` | met | `e3729cd` "Merge pull request #1 from vb2007/dev-planning". | — |

Extra drift: v00's task text says `CLAUDE.md` should inline the auth API contract and spotdl API
surface "so every future session loads" them directly — true at v00 merge, but this v14 branch's
own restructuring (`b83762b`) has since moved both into `docs/GOTCHAS.md`. Deliberate, self-
consistent supersession, not a regression; noted only because v00's task text now reads as stale to
a literal reader.

## v01 — Scaffold

| Bullet | Verdict | Evidence | Severity/Routing |
|---|---|---|---|
| `docker compose up` brings up every service without crash-looping | met | Real crash-loop bugs found and fixed while actually running the stack, documented in `docs/GOTCHAS.md:225-262` (fixes in `8a379a7`, `b8604bd`). Not covered by CI (`compose-config` job only runs `docker compose config`, never `up`). | — |
| `curl .../api/health` returns `200 {"status":"ok"}` with both DB and Redis reachable | met | `backend/app/routers/health.py:16-43`; documented as actually exercised in `docs/GOTCHAS.md:230`. | — |
| `alembic upgrade head` runs cleanly with zero revisions | met, superseded by v12 | True at v01 merge (zero revisions existed). v12's `migrate` one-shot compose service now runs this automatically on every boot — intentional evolution. | — |
| No feature logic beyond health/config exists yet | met at v01 scope | `git show a43f89a --stat` — only health router + empty module scaffolding. | — |

Extra drift (real, worth fixing): **`README.md:17-18` is stale and contradicts current
`CLAUDE.md`.** It states local dev and the Debian host "each use their own separate database";
`CLAUDE.md` (and `.env.dev.example:7-12`) now correctly state they share the same database. Written
at v01, never touched since. **Severity: minor, routed to v15** (one-paragraph doc fix).

## v02 — DB Schema

| Bullet | Verdict | Evidence | Severity/Routing |
|---|---|---|---|
| `alembic upgrade head` against scratch Postgres creates every table with correct types/indexes, seeds `worker_state` | met | `ebc1d43e2c21_initial_schema.py:24-97`; verified against a real scratch `postgres:17-alpine` container per `docs/GOTCHAS.md:297-302`. | — |
| `alembic downgrade base` cleanly drops everything | met | Same migration's `downgrade()` explicitly `DROP TYPE`s all 5 native enums (lines 100-122); round-trip verified for real. | — |
| Schema review confirms every field v04–v13 needs already exists — no version should need an ad-hoc migration | partially met | Confirmed true for v04–v12 per `docs/GOTCHAS.md:299-302`, **except** `job_state`'s `CANCELLED` value (needed by v10), which v02 did not anticipate and required an unplanned `ALTER TYPE ... ADD VALUE` migration (`46be30064f8b`). | Minor, historical only — already fixed and reversible. No v15 action. |

## v03 — Auth

| Bullet | Verdict | Evidence | Severity/Routing |
|---|---|---|---|
| Real allowlisted login returns 200 + session cookie; `/api/auth/me` returns that email | met | `backend/app/routers/auth.py:47-78`; real-account verification in `docs/GOTCHAS.md:337-341`. | — |
| Disallowed email gets identical rejection to wrong password, verified byte-for-byte | partially met | One shared exception object guarantees identical status+body (`auth.py:15,52-56`); test asserts parsed-body equality, not literal byte comparison. | Cosmetic — functionally airtight; trivial test tightening, not worth its own action. |
| `VB-AUTH` never appears in any response returned to the browser | met | `upstream_auth.py:16-23` never reads `.cookies`/`.text`; directly tested. | — |
| Any protected route without a session returns 401 | met | `require_session` applied via `Depends` on every router except the intentionally-open `/api/health`; broad test coverage across 6 test files. | — |

## v04 — URL Expansion

| Bullet | Verdict | Evidence | Severity/Routing |
|---|---|---|---|
| `POST /api/jobs` with a real playlist URL: `expanding`→`expanded` with correct track count | partially met | Mechanism is source-type-agnostic and real-verified for track/album/artist URLs (`docs/GOTCHAS.md:396-401`), but a literal **playlist** URL was never run. | Minor — quick v15 fix: one real playlist submission, logged. |
| `GET /api/jobs/{id}/tracks` lists every track `pending`; none moved past `pending` | superseded by v05 | True at v04 merge; v05 deliberately made `expand_job` dispatch downloads immediately after insert. Intentional evolution. | Note-only: mark superseded in the plan file's own context (no code change). |
| Artist URL (many albums) and single track URL both expand correctly via `get_simple_songs` | met | Real-verified: track + artist (390 tracks across every album), `docs/GOTCHAS.md:396-401`. | — |
| Garbage URL fails the job with readable `error`, doesn't crash the task | met | `test_expand_job_failure_marks_job_failed_with_error`; broad `except Exception` documented and regression-tested. | — |

**Confirmed drift — `PACING_MIN_SEC`/`PACING_MAX_SEC` have zero consumers.** `backend/app/config.py:64-65`
defines both fields; repo-wide grep finds them nowhere else except env templates and doc/plan
files. `download_track` never sleeps between attempts. **Already scoped to v15**
(`plan/master-v2/v15-v1-gap-fixes.md`).

## v05 — Downloader

| Bullet | Verdict | Evidence | Severity/Routing |
|---|---|---|---|
| Small real album downloads every track with correct filenames/tags | partially met | Real 15-track album run landed 14/15 (15th hit a real transient Spotify API error, now auto-retried by v06's ladder rather than stopping). Single-track tagging fully confirmed. | Cosmetic/informational — plan's own wording anticipates single-bad-track handling; no action. |
| Re-submitting the same album marks every track `skipped_duplicate` immediately, no network calls | partially met | Verified for single-track re-submission (`docs/GOTCHAS.md:475-476`); album-scale re-submission never run end-to-end, though dedup is per-track and keyed by `spotify_track_id` so the mechanism generalizes trivially. | Minor — quick v15 fix: one real album re-submission, logged. |
| Deleting one file + restarting worker drops that ledger row via `reconcile_disk()` | met | Real-stack verified log line + unit tests, including the v12-added empty-mount guard. | — |
| A single bad track ends in `failed` without taking down the rest of the album | superseded (was: met) | True at v05 merge. v06's ladder/breaker replaced the terminal `TrackState.FAILED` path with `WAITING`/`LOOKUP_FAILED` — **`TrackState.FAILED` is now dead code**, only referenced in `routers/tracks.py:16`'s retry-set, never written. Track isolation itself still holds and is tested. | Cosmetic — dead enum value. Removing it needs a native-enum `DROP TYPE` migration, so it's schema-touching; **note in GOTCHAS, do not fold into v15's plain fixes — bundle with a version that already touches migrations** (e.g. v16). |

**Confirmed drift — `list_jobs` N+1, no pagination.** `backend/app/routers/jobs.py:60-65` issues 1 +
N queries (one `track_counts()` per job via `job_to_dict`), no `LIMIT` on the jobs query either;
`routers/tracks.py:41`'s `list_tracks` has the same unbounded-query shape. Untested by query-count
(`test_list_and_get_job_include_track_counts` checks correctness only). **Already scoped to v15.**

`_ensure_spotify_client()` singleton guard: **holds** — every `SpotifyClient()`/`.init()` call site
is inside the guard itself; `expand()` and `download_one()` both call the guard before touching
spotdl.

## v06 — Retry Engine

| Bullet | Verdict | Evidence | Severity/Routing |
|---|---|---|---|
| Shortened-ladder + forced `AudioProviderError` walks the full ladder and settles at the final step, retrying forever | met (mechanism), superseded (tooling) | No `FAULT_INJECT` hook was ever built as the plan named; verification instead used `docker compose cp` scripts calling `download_track`/`dispatch_due_tracks` directly against real Postgres — full ladder walked and settled, documented in `docs/GOTCHAS.md:539-541`. Unit-tested in `test_retry.py`. | Cosmetic — plan named a hook that doesn't exist; actual verification is equally rigorous. Update plan wording only if convenient. |
| 5 consecutive `AudioProviderError`s trip the breaker; `dispatch_due_tracks` dispatches nothing while tripped; success resets it | met | `retry.py:48-53,81-85`; `beat.py:65-68` (no query at all while tripped); unit + real-stack evidence. | — |
| Restarting `worker-dl`/`beat` mid-wait resumes at the correct `scheduled_at`, no duplicate dispatch, verified via SQL | met | The one bullet that genuinely required and got a real restart test: `docs/GOTCHAS.md:545-549`. | — |
| A `LookupError` track moves to `lookup_failed` and is never touched again | met | `retry.py:60-63`; `beat.py:74` structurally excludes `lookup_failed` from the dispatch query; unit + real-stack evidence. | — |

**Invariant — no `eta`/`countdown` for backoff: holds.** Only two `.delay()` call sites exist in
`backend/app/`, both plain dispatch, no `apply_async`/`countdown`/`eta` anywhere. All backoff is
`tracks.scheduled_at`, polled by beat.

**Ladder/breaker numbers vs. CLAUDE.md: exact match** — 15m→1h→4h→12h→24h ladder
(`config.py:7`, `DEFAULT_LADDER_SECONDS`) and 5-strike/30m→2h→6h breaker (`retry.py:13-14`), both
unit-tested for escalation and capping.

## v07 — Proxy Rotation

| Bullet | Verdict | Evidence | Severity/Routing |
|---|---|---|---|
| A track fails direct, waits out its ladder step, then succeeds via a proxy on the next attempt | met | `download.py:64-75`; real-stack with 5 live credentialed proxies, `docs/GOTCHAS.md:609-617`. | — |
| A failing proxy gets `cooldown_until` and is skipped until it elapses | met | `proxies.py:124-168`; real-stack confirmed. | — |
| Editing `proxies.txt` + restart adds/disables entries without resetting historical health stats on re-add | met | `sync_from_file()` soft-disables/re-enables without touching counters; real-stack confirmed. | — |
| No proxy available → track still attempted directly, doesn't stall | met | `pick_proxy()` returning `None` falls through to a direct attempt; real-stack confirmed. | — |

**Invariant — every logged/persisted proxy URL through `redact()`: holds**, with an independent
second layer. `redact()` (`proxies.py:47-50`) is used at every log/persist call site found by grep;
`logging_config.py:22-26` additionally regex-redacts `user:pass@` from every JSON log record as a
safety net. **This invariant exists because it was violated once** — `docs/GOTCHAS.md:609-629`
documents a real credential leak caught only by a live-proxy run after a fully-mocked pass had
already been called done, the direct origin of the project's "mocked verification is not
verification" rule.

## v08 — Live Progress (SSE)

| Bullet | Verdict | Evidence | Severity/Routing |
|---|---|---|---|
| `curl -N` shows live intermediate `progress` values as a real download proceeds, not just start/end | met | `events.py:77-90` wired to spotdl's real progress callback; real-stack run showed 0→25→40→70×many→95→100 (`docs/GOTCHAS.md:691-697`). | — |
| Stream survives ≥5 min idle without dropping, direct and through a local tunnel, heartbeat confirmed | met | 15s heartbeat (`stream.py:18,33-38`); a real 320s idle connection emitted 21 heartbeats with zero drops, both directly and tunneled (`docs/GOTCHAS.md:697-699`). | — |
| Killing the API mid-stream and restarting it: reconnecting client resumes with **no client-side code changes needed** | partially met, later proven false | Server-side resume verified for real. The "no client-side changes needed" clause was explicitly untestable at v08 (no frontend existed yet) and was **proven false by v12**: an API restart behind nginx returns a 502, which permanently kills `EventSource` per spec — a manual backoff-reconnect handler had to be added (`+page.svelte:44-78`). | Already closed by v12's fix; the gap is only that v08's own doc was never corrected to say so. No v15 action beyond a GOTCHAS note. |

SSE design (flat `spotdl:events` channel, no user scoping) matches exactly what v08's single-user
scope asked for — correctly out of scope for this audit's per-v1 comparison (v2/v17 owns per-user
scoping).

## v09 — Frontend

| Bullet | Verdict | Evidence | Severity/Routing |
|---|---|---|---|
| Full flow works in a real browser **through the Cloudflare Tunnel**: login → submit → live states, no manual refresh | partially met | Functional flow fully real-verified (`docs/GOTCHAS.md:919-925`). The "through the tunnel" clause was explicitly declined at v09 and deferred to v12 (`docs/GOTCHAS.md:935-938`), and v12's own test plan also never actually ticked it ("pending host-side dashboard configuration, not verifiable from the dev PC"). | Minor — a conscious, user-directed deferral (avoiding public exposure pre-hardening), not an oversight. No action needed. |
| A `waiting` track shows a visibly ticking countdown matching `scheduled_at` | met | `Countdown.svelte` wired in `QueueTable.svelte:178-180`; real-stack 3-second wait confirmed ticking + reload survival. | — |
| Reloading mid-download resumes correct live state (REST-refetch + SSE-resume contract) | met | `queue.ts:88-92` `loadAll()` called on mount and every SSE reconnect (`+page.svelte:61-66`); real-stack confirmed. | — |
| Logging out clears session and redirects; `/` while logged out redirects to `/login` without ever rendering queue data | met | `+page.svelte:39-42`, `+layout.ts:22-24`; real-stack confirmed. | — |

**Frontend-route invariant (SvelteKit exports + nginx `location` block, per route): holds for all 3
current routes** (`/`, `/login`, `/settings`) — each has an explicit `location =` block in
`frontend/nginx.conf`. Historical note: this invariant was itself violated from v09 through v12
(`/login` 404'd on every hard navigation) before v12's same-origin nginx fix — the exact incident
that turned this into a stated project invariant. **Cosmetic drift found:** `frontend/nginx.conf:69-70`'s
comment still says "exactly two routes exist... both prerendered," stale since v13 added
`/settings`. **Routed to v15** (one-line comment fix).

## v10 — Queue Controls

| Bullet | Verdict | Evidence | Severity/Routing |
|---|---|---|---|
| Cancelling a job stops non-terminal tracks from dispatch; a track mid-download still finishes but is discarded, ends `cancelled` | met | `jobs.py:96-120`; discard logic in `download.py:103-121`; real-stack mid-download cancel confirmed (mp3 written, state stayed `cancelled`, no ledger row). | — |
| Retry-now on `waiting` dispatches within one beat tick, but held if breaker tripped | met | `tracks.py:63-98`; real-stack: a 12h-out track reset to due, held by `breaker_held`, dispatched on release. | — |
| Pause stops all dispatch immediately; resume picks back up without duplicate dispatch | met | `beat.py:63-68`; real-stack: paused across 5 real beat ticks with zero invocations, resumed with `attempt_count` advancing by exactly one. | — |
| Manual breaker release clears countdown immediately; a subsequent failure re-trips at the next escalation step, not reset to 30m | met | `worker.py:57-68`; real-stack confirmed re-trip at the second (~2h) step. | — |

Extra note: two real SSE/frontend race bugs (stray `downloading` events overwriting `cancelled` on
the wire; a client-side replay bug) were caught and fixed within this version itself — not open
gaps, but worth knowing if `applyTrackEvent` or the SSE republish path is touched again.

## v11 — Priority

| Bullet | Verdict | Evidence | Severity/Routing |
|---|---|---|---|
| Bumping a job's priority causes its tracks to dispatch first on the next beat tick | met | `jobs.py:136-149`; `beat.py:70-79` orders by `priority DESC, scheduled_at ASC`; **the specifically-flagged "bump endpoint untested" gap (CLAUDE.md/GOTCHAS) is now confirmed closed** — both a unit test (`test_jobs.py:186`) and a documented real-stack rerun against the actual `bump_job()` function exist. | — |
| Priority has no effect on tracks still waiting out ladder delay — only reorders among currently-due tracks | met | `beat.py:74`'s `scheduled_at <= now` filter applies before priority ordering; real-stack confirmed a high-priority not-yet-due track stayed untouched. | — |

## v12 — Deploy Hardening

| Bullet | Verdict | Evidence | Severity/Routing |
|---|---|---|---|
| `docker compose down && up -d` and a host reboot leave `waiting` tracks' schedule untouched, dispatch resumes correctly | met, one clause unverifiable from source | The real durability gap (tracks `downloading` at kill time) is fixed via Celery ack/redelivery settings + a `_reclaim_stale_tracks` beat sweep, unit-tested and locally verified. **No recorded evidence of a literal host reboot** — only `down`/`up` + simulated staleness. | Minor — mechanism is host-restart-agnostic by construction; a real reboot log is a nice-to-have, not a gap. v15-sized if pursued, not required. |
| `docker compose ps` shows healthy/unhealthy accurately when a worker is killed inside its container | met, one clause unverifiable from source | Healthchecks defined for every service except `beat` (deliberate — single foreground PID-1 process, documented rationale). No explicit "killed a worker, watched `ps` flip unhealthy" log entry exists beyond the healthcheck definitions and their debugging history. | Minor — trivial to close with one real test if pursued; not required. |
| Public Cloudflare Tunnel hostname serves the app with no ports manually forwarded | met, superseded implementation detail | Shipped via dashboard-managed `TUNNEL_TOKEN`, not the plan's originally-specified repo-tracked `cloudflared/config.yml`. Deliberate substitution, already documented in GOTCHAS/CLAUDE.md. All service ports bind `127.0.0.1` only. | Note-only, already reconciled. |
| A restored `pg_dump` backup on a scratch database reconstructs the full schema and data correctly | met | `scripts/pg_backup.sh`; real verified restore into a scratch container reconstructed all 7 tables with matching real row counts. | — |

Additionally verified: `worker-dl` still `--concurrency=1 --prefetch-multiplier=1` (holds); backend
container runs non-root (holds) — **`frontend/Dockerfile` (nginx:1.27-alpine) has no explicit `USER`
directive**, so nginx's master process runs as root by Docker's default (never previously flagged;
not a regression against any stated requirement, just non-uniform). Structured JSON logging: holds,
with its own redaction tests. Backup/restore: holds.

## v13 — Settings UI

| Bullet | Verdict | Evidence | Severity/Routing |
|---|---|---|---|
| A proxy added via UI is picked by `pick_proxy()` on the next eligible attempt, with health stats updating live like file-sourced proxies | partially met | Pooling itself is fully source-agnostic and correct (`create_proxy` stamps `MANUAL`, `pick_proxy`/`record_proxy_result` don't filter by source). **The "live" half fails**: the settings page fetches proxies once on mount, no polling or SSE subscription exists for proxy stats — a stat only refreshes on a full reload or a self-triggered toggle. No test exercises `pick_proxy` against a `MANUAL` row. | Minor, new finding — **routed to v15**: add lightweight polling (or an SSE proxy-event) to the settings page, plus one regression test with a `MANUAL`-source fixture. |
| Changing global output format/bitrate in UI affects the next download without a restart | met | `AppSettings` DB row + `get_downloader`'s cache key includes format/bitrate/output_dir/template/proxy, so a change misses cache and rebuilds. | — |
| `proxies.txt` and UI-added proxies coexist without overwriting each other | met | `sync_from_file()` only touches `source==FILE` rows; `create_proxy()` always stamps `MANUAL` and 409s on collision instead of merging; delete branches by source. | — |
| Confirmed as last planned version — final reconciliation pass over `plan/` and `CLAUDE.md` | not met at v13's own merge; being satisfied now | v13's own PR commits are scoped to v13's feature gotchas, not a roadmap-wide pass. The actual reconciliation (plan-folder split, CLAUDE.md restructure) happened under this v14 branch's commits `b4ec25f`/`b83762b`. The bullet's premise ("last planned version") is also now moot since master v2 exists. | Not a fix — the bullet is being retroactively satisfied by v14 itself. |

---

## Locked decisions (`plan/master-v1/00-master-plan.md`)

14 rows audited. **No locked decision found silently violated.**

| # | Decision | Verdict | Notes |
|---|---|---|---|
| 1 | Python 3.12, FastAPI + Celery | Honored | — |
| 2 | Celery + Redis (Redis dockerized) | Honored | — |
| 3 | PostgreSQL, non-dockerized on Debian 12 host | Honored | — |
| 4 | SvelteKit + TypeScript | Honored | — |
| 5 | SSE now, WebSocket later | Honored | No WS code exists; a WS-ready comment only |
| 6 | Cloudflare Tunnel only, no port forwarding | Honored | All services bind `127.0.0.1` only |
| 7 | Proxy login, own session cookie, VB-AUTH never reaches browser | Honored | — |
| 8 | Per-track ladder + global circuit breaker | Honored | — |
| 9 | Proxies: file first, UI management as final version | Honored | — |
| 10 | Direct first → wait ladder → then proxy | Honored | — |
| 11 | Output config: env first, UI override final version | Partially honored (documented exception) | `output_dir` deliberately has no DB column — reasoning is in the model docstring, not a silent drift |
| 12 | Dedup: DB table keyed on Spotify track ID + disk reconciliation | Honored | — |
| 13 | Extra levers off by default, hooks present | Honored but unwired | Confirms the pacing-hook drift already known — `pacing_min_sec`/`pacing_max_sec` are never read anywhere |
| 14 | Docker Compose stack on Debian 12 | Honored | Compose service list matches the architecture diagram exactly |

## Architecture invariants

6 invariants audited. **All 6 hold**, verified with real command output
(`docker compose config`) where relevant, not static inspection alone.

| Invariant | Verdict |
|---|---|
| No Celery `eta`/`countdown` for backoff; `tracks.scheduled_at` is the sole schedule source of truth | Holds |
| `worker-dl` runs `--concurrency=1 --prefetch-multiplier=1` | Holds (confirmed in both dev-override and prod-overlay resolved configs) |
| Every spotdl entry point goes through `_ensure_spotify_client()` | Holds |
| Every logged/persisted proxy URL goes through `proxies.redact()` | Holds (plus an independent regex safety net in `logging_config.py`) |
| Every enum column uses `values_callable`; every enum-creating migration's `downgrade()` has `DROP TYPE` | Holds |
| Every frontend route has both SvelteKit `ssr`/`prerender` exports and its own nginx `location` block | Holds for all 3 current routes (was violated v09→v12, the incident that created this invariant) |

---

## Remediation list

Every gap found above is routed below. Nothing found rises to "needs its own version" — the whole
list fits inside v15's already-planned scope, which is itself the second half of what this audit
exists to confirm.

| # | Finding | Source | Routing |
|---|---|---|---|
| 1 | `PACING_MIN_SEC`/`PACING_MAX_SEC` have zero consumers | v04 (known before audit) | **v15** — already scoped |
| 2 | `list_jobs` N+1, no pagination on jobs or tracks listing | v05 (known before audit) | **v15** — already scoped |
| 3 | `README.md` claims separate dev/prod databases; contradicts current `CLAUDE.md`/`.env.dev.example` | v01 (new) | **v15** — one-paragraph doc fix |
| 4 | Settings-page proxy stats don't update live (no polling/SSE); no test covers `pick_proxy` with a `MANUAL`-source row | v13 (new) | **v15** — add polling + one regression test |
| 5 | `frontend/nginx.conf`'s comment claims "exactly two routes," stale since v13 added `/settings` | v09 (new) | **v15** — one-line comment fix |
| 6 | `TrackState.FAILED` is dead code — declared and referenced in a retry-set, never written by any code path since v06 | v05/v09 (new) | Note in `docs/GOTCHAS.md` now; **defer removal to a version that already touches migrations** (native enum `DROP TYPE`), e.g. v16 — not a v15 plain fix |
| 7 | A literal playlist-URL expansion was never run against the real stack (only track/album/artist) | v04 (new) | **v15** — one real playlist submission, logged |
| 8 | Album-scale re-submission (`skipped_duplicate` for every track) was never run against the real stack, only single-track | v05 (new) | **v15** — one real album re-submission, logged |
| 9 | A literal host reboot (vs. `docker compose down/up` + simulated staleness) was never logged for durability | v12 (new) | **v15**, optional — mechanism is host-restart-agnostic by construction; nice-to-have only |
| 10 | "Killed a worker, watched `docker compose ps` flip unhealthy" was never explicitly logged beyond the healthcheck definitions | v12 (new) | **v15**, optional — trivial to close, not required |
| 11 | `frontend/Dockerfile` (nginx) has no explicit `USER` directive, unlike the backend — non-uniform non-root posture | v12 (new) | **v15**, optional — not a violation of any stated requirement, just inconsistent |

Bullets already correctly marked `superseded` (v04's pending-tracks bullet, v05's `failed`-state
bullet, v08's "no client-side changes needed" claim, v12's tunnel-config-file detail, v13's
"last planned version" premise) need no remediation — they describe intentional, already-documented
evolution, not gaps.

---

## Verification

- 52/52 "Done when" bullets audited across all 14 v1 plan files — counted via `awk` against each
  file's own `## Done when` section, matching every sub-audit's own tally exactly.
- 14/14 locked-decision rows audited; 6/6 architecture invariants audited.
- Every finding above carries file:line evidence, a test name, or an explicit "no consumer found" /
  "no matching code found" — gathered by seven parallel read-only audit agents, each grounded via
  `graphify query`/`explain` before falling back to direct grep/read, per project convention.
- No application code, test, or config file was modified to produce this report.
