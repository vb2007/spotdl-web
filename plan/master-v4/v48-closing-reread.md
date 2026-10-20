# v48 closing re-read: every "Done when" bullet of v32–v47

Task 8 of `v48-v4-hardening.md`. Every "Done when" bullet in `plan/master-v4/v32`–`v47` (and the
patch slices with a checklist of their own: v39.1, v39.2, v45.1) was re-read on 2026-10-19
against its merged PR and the code on `main` (867ed7d), with the master plan's Amendments
applied. Each bullet is listed with its status and a pointer to its evidence.

**Statuses:** EVIDENCED (the PR holds concrete evidence; "+code" = also re-confirmed on `main`) ·
RE-CHECKABLE IN CODE (confirmed statically now) · NEEDS LIVE RE-VERIFY · GAP · SUPERSEDED (by an
Amendment).

**Totals:** 172 bullets. 162 evidenced, 6 confirmed in code, 2 superseded, 0 needing a separate
live check (v48's own runs re-cover the e2e-backed ones: the full strict Playwright suite on all
three projects, and `scripts/verify_separation_sse.sh`, both green on the v48 branch), and
**2 gaps**, both waiting on an owner answer rather than on work. _(2026-10-20: both answered on
the v48 PR and closed on this branch; see the notes under each.)_

- **v40, "no style recalculation per frame … only composite work":** PR #59 reported it as partly
  met (a one-element style update plus a commit per frame) and asked the owner to accept that or
  switch to WAAPI. No answer is recorded. The cost is written into DESIGN.md and GOTCHAS as the
  design, so it was accepted only by merging. _(2026-10-20, owner: "using the web animations api
  won't hurt". The glow now runs on WAAPI: the glide after the pointer stops is composite-only
  (51 main-thread frames → 1 style update), while each retarget during continuous movement still
  costs a few 1-element style updates, about the old per-frame cost. Recorded in DESIGN.md §5 and
  the GOTCHAS v48 section.)_
- **v47, "prior decision records preserved":** PR #69 folded DESIGN.md's older dated blockquotes
  into prose, losing most of their dates, and asked whether to restore them. No answer is
  recorded. _(2026-10-20, owner: "Restore the dates." 22 records' dates restored inline from the
  pre-v47 file (`df36405`); none were unrecoverable.)_

The three sections below were produced by three independent reviewers, one per range.


## v48 task 8: closing re-read, v32–v36

Scope: every "Done when" bullet in `plan/master-v4/v32`–`v36`, checked against the merged PRs (#43, #44, #45, #46, #47, #48, #49/#50, #51, #52, including PR comments) and against the code on `origin/main` (867ed7d) today. I also read the `## Amendments` section of `00-master-plan.md`.

Checks run this session (read-only):
- **Backend tests**, from `backend/` on the working tree (HEAD 186b184 = main + v48 commit 7, which touches only `tasks/library.py` and its test):
  - full `uv run pytest`: **586 passed**;
  - `tests/test_config.py`: 19 passed;
  - `tests/test_ownership.py`: 21 passed;
  - every named v35/v36 test listed below passed individually (`-rA`).
- **`uv lock --check`**: in sync.
- **Frontend**: `npx vitest run src/lib/stores/queue.test.ts`: 35 passed.
- **Static greps** on `origin/main`, cited per row.
- **Not run**: the docker stack, e2e, `verify_separation_sse.sh`, production, the runner.

Statuses: EVIDENCED · RE-CHECKABLE IN CODE · NEEDS LIVE RE-VERIFY · GAP · SUPERSEDED. "+code" means the PR evidence exists and I also re-confirmed the claim on main today.

---

### v32: dev database (PR #43)

Amendment applies: production's DB is `spotdlweb`, not `spotdl_web`. The guard refuses both names.

| Bullet | Status | Pointer/notes |
|---|---|---|
| Local `docker compose up` succeeds against the empty `spotdlwebtest`, and `migrate` exits 0, with `alembic current` at head | EVIDENCED | #43: "`spotdlwebtest\|0`" tables before; migrate ExitCode `0`; "`alembic current` → `e7c1f9a4d2b6 (head)`". |
| Isolation proven by observation: a local job id is absent in prod, and the reverse | EVIDENCED | #43: dev job `e03eba54…` → prod count `0` (owner's read-only query on `spotdlweb`). Prod job `e2806146…` → `spotdlwebtest\|0`. |
| Local `worker-meta` restart reconciles **dev** ledger rows; prod `downloaded_tracks` count unchanged | EVIDENCED | #43: "`reconcile_disk: checked 1 ledger rows`" vs dev `1`. Prod `12` before and after. |
| Guard refuses: prod `DATABASE_URL` → every backend service and `migrate` exit non-zero; unparseable URL also refuses | EVIDENCED +code | #43 shows exit codes for migrate/api/worker-meta/worker-dl/beat on `spotdlweb`, `spotdl_web`, unparseable and nameless URLs. Still holds: `backend/app/config.py:16` `PRODUCTION_DATABASE_NAMES = ("spotdlweb", "spotdl_web")`; `alembic/env.py:22` re-checks. `docker-compose.override.yml` puts `SPOTDL_ENV: dev` on api, migrate, worker-dl, worker-meta, beat, **and `worker-expand`**. `worker-expand` was added in v34.1, after v32, and it is covered. |
| Prod compose invocation carries no dev marker (`config` grep) | EVIDENCED +code | #43: `config \| grep -c SPOTDL_ENV` → `0`. Today `SPOTDL_ENV` appears only in `docker-compose.override.yml` (none in `docker-compose.yml`/`.prod.yml`). |
| ≥1 test identity logged in through the real upstream; a second identity exists | EVIDENCED | #43: "`HTTP Request: POST https://api.vb2007.hu/auth/login`". Identities: v32admin/v32user/spotdlwebtestv22. |
| `alembic downgrade base` then `upgrade head` completes on dev, or broken downgrades are in GOTCHAS | EVIDENCED | #43: "All 11 downgrades ran … then all 11 upgrades", exit 0. Since then 9 more revisions landed. Statically, each has a non-empty `downgrade()`, and the enum ones drop their type (`c4e8a2f1d9b7` `DROP TYPE breaker_event_kind`; `a35c0e1f7b21` drops `track_attempt_outcome_old`). v35/v36 PRs round-tripped their own migrations. A full base↔head round trip over today's chain hasn't been re-run (optional live check, see summary). |
| Unit tests cover the guard (4 cases) | EVIDENCED +code | #43: `test_config.py` 19 passed. Re-run today: 19 passed. |
| `.env.dev.example`, `LOCAL_DEV.md`, CLAUDE.md, GOTCHAS updated | EVIDENCED | #43: commits `66e9496`, `525997b`, `59d293c`. `.env.dev.example:14` still documents the marker. |
| pytest/lint/check/build pass; versions `4.32.0`; `uv lock` in sync; graphify run | EVIDENCED | #43: "`379 passed`", svelte-check 0/0, build ✔, `check_version` → `4.32.0`. The version has since moved on by design (main = `4.47.0`). |

### v33: deploy safety (PRs #44, #45, #46 = v33.1)

Amendment v33.1 applies: (1) a failed Matrix send is a warning with exit 0, and (2) the rollback falls back to the pre-deploy commit+tag when the DB is ahead of `.last-good`.

Since #46, only v34.1 (`7189e3d`, adding `worker-expand`) has touched `publish-deploy.yml`/`release.yml`/`.github/scripts/` on main. The working tree's uncommitted `publish-deploy.yml` edit (job-private `DOCKER_CONFIG`) is v48-branch work, not on main.

| Bullet | Status | Pointer/notes |
|---|---|---|
| Preflight blocks a missing variable before mutation (`V33_PROBE`); HEAD and `IMAGE_TAG` unchanged | EVIDENCED +code | #44, run 36860971991: "`V33_PROBE (not set)` … Nothing on the host was changed". HEAD `a85061a…` and `IMAGE_TAG=4.32.0` shown before and after. `check_required_env.py` is still wired into `publish-deploy.yml`. |
| Rollback restores commit and tag together; stack healthy | EVIDENCED | #44, run 36861560233: "`Rollback succeeded: commit a85061a…, IMAGE_TAG=4.32.0`", compose ps healthy. Re-run on v33.1 code: run 36885975474 (#45). The v33.1 fallback **extends** this bullet and doesn't replace it (`publish-deploy.yml:475-487`). The fallback branch was evidenced only by the local decision table in #45; it can't be exercised on the host without putting prod's DB ahead. |
| `.last-good` written only on a healthy `persist=true` deploy; unchanged after `manual-*` or failed runs | EVIDENCED +code | Unchanged half: #44 Summary "`.last-good: absent`" on every manual/failed run. Written half: #44 comment, run 36875684508, "`Wrote …/.last-good: IMAGE_TAG=4.32.0`". #46 comment, run 36900385167: `.last-good` = `4.33.1`. Code: `publish-deploy.yml:545` `if: success() && needs.resolve.outputs.persist == 'true'`. |
| Migration guard stops a doomed rollback (local, dev DB) and prints the backup path | EVIDENCED +code | #44: "`IMAGE_TAG=3.28.0` … database is AHEAD … pre-deploy pg_backup: …dump, rc=3". `.github/scripts/migration_guard.sh:20,87` still exits 3. |
| Matrix message for a failed run, a successful real deploy and a `release.yml` failure; notify exits 0 with secrets unset | EVIDENCED | Failed run: #44 room export, run 36852251370. Release failure: run 36852300403. Secrets unset: run 36847351824, "`Matrix notification skipped … not configured`", notify success. Successful deploy: #44/#46 comment, run 36900385167. That one is owner-confirmed text ("✅ spotdl-web deployed 4.33.1 to production"), not a screenshot. v33.1 reinterpretation: `matrix_notify.py:47,86-92` warning + exit 0. |
| CI drift check fails on a missing `.env.example` key and passes on main | EVIDENCED +code | Red CI run 36847355082: "`V33_PROBE (not set)`". Green on the PR. `ci.yml:344,377-380` (`compose-config` job) still runs it. |
| `wait_for_stack_health.sh` fails fast on a compose interpolation error | EVIDENCED +code | #44 local output: "`docker compose failed, not a health wait` … rc=2 after 0s". Code: `.github/scripts/wait_for_stack_health.sh:39,52,57` (`exit 2`). The script lives under `.github/scripts/`, not `scripts/`. |
| No step prints secret values (grep every run's logs) | EVIDENCED | #44: 13 log files, every secret count `0`, plus `redact_env.py` demonstrated. Not re-run since. Workflows are unchanged on main except v34.1's service addition. |
| Docs updated; graphify run | EVIDENCED | #44: RELEASE_PIPELINE/DEPLOYMENT/GOTCHAS/CLAUDE.md, plus a "v33: graphify update" commit. #46 ran the graphify update that #45 skipped. |

### v34: live hydration (PR #47; follow-ups v34.1 #48, v34.2 #49 re-landed as #50)

Amendment v34.1/v34.2 applies: every "Found, not fixed" item was closed, including progress kept across a reload and the Vite SSE fix.

| Bullet | Status | Pointer/notes |
|---|---|---|
| Each shape (a–d) reproduced **before** the fix; root cause in GOTCHAS | EVIDENCED | #47 "Pre-fix runs" for (a)–(d), e.g. (c) "`ACTIVE SIGNAL 0 LANES`". GOTCHAS: `docs/GOTCHAS.md:4366` "v34 live-hydration gotchas". |
| After the fix each shape survives a hard reload (screenshots per shape) | EVIDENCED | #47 covers (a), (b) and (d). (c)'s progress read `0%` after the reload in #47 ("⚠️ The lane reads `0%` until the next tick"), which the v34.2 amendment closed: #50 "painted `25%` at 154 ms … never showed `0%`". Screenshots were kept locally, not attached; the PR body has the text observations. Code: `frontend/src/lib/stores/progressCache.ts` exists on main. |
| A stream reconnect (restart `api`) re-hydrates the same way, with no duplicates | EVIDENCED | #47 did it through the prod nginx image (Vite proxy couldn't): "`Echoes … 0%` → `70%`, one lane, 3 incoming unchanged". v34.2 fixed the Vite proxy and re-evidenced it: #50 "1 page / 1 / 1 resync, with incoming rows 4 → 4". |
| Race test: SSE `downloading → completed` during hydration doesn't resurrect (unit test plus one live attempt) | EVIDENCED +code | #47 live Playwright: "`after stale snapshot lanes: 0`". Unit test `queue.test.ts:165` "race: downloading -> completed … never resurrects the track"; vitest today: 35/35 passed. |
| Admin all-users: hydrate under both scopes and switch back and forth, no leakage (two identities) | EVIDENCED +code | #47 mine→all→mine→all→reload table. #50 scope switch with MutationObserver, no other user's rows. Unit tests `queue.test.ts:262,293,342`. |
| Logout then a second identity on the same tab: no flash (`queue.reset()`) | EVIDENCED +code | #47 MutationObserver: "`leakedFromA: []`". Unit tests `queue.test.ts:247,326`. `storeEpoch` is bumped in `reset`/`setAllUsers` (`queue.ts:640-651`). |
| Cross-user REST: `test_ownership.py` passes (plus cases for new filters); `verify_separation_sse.sh` passes | EVIDENCED | #47: 16 passed, no new filter; SSE "4/4 PASS". Today `test_ownership.py`: 21 passed. The SSE script wasn't re-run (needs a stack); later PRs (#50, #51) re-ran it. |
| One bulk request per store per reload | EVIDENCED +code | #47 request log. #50 table: hard reload `1 \| 1 \| 1 \| 1` (the double reload fixed in v34.2). Code: `queue.ts:387` `Promise.all([reloadPage(), hydrateLive()])`. `queue.ts:408-419` sends one `listJobsPage` and one `listTracksPage`, each with `limit: 1000`. |
| pytest/lint/check/build; `4.34.0`; `uv lock`; graphify | EVIDENCED | #47: "`379 passed`", check 0/0, build ✔, test:unit 13, `check_version` → `4.34.0`. `npm run test:unit` is in CI since v34.2 (`ci.yml:449`). |

### v35: correctness sweep (PR #51)

Amendment v39 #3 applies: from v41 on, operator detail (attempt counts, network path, attempt history) is admin-only. This narrows (a) and (b)'s "UI shows …" to the admin view on today's main.

| Bullet | Status | Pointer/notes |
|---|---|---|
| (a) First-try download shows attempts=1/failures=0; 2 failures + success shows 3/2; numbers unique across a breaker hold; backfill checked on dev rows with downgrade | EVIDENCED +code | #51: "Take on Me" `attempts_made 1, failure_count 0`; "Eye of the Tiger" 3/2; "Billie Jean" rows 1..5 including a `held` row; backfill over 1,906 rows, 0 dups, `downgrade -1` OK. Passed today: `test_two_failures_then_success_counts_three_attempts_and_two_failures` and `test_breaker_hold_gets_its_own_attempt_number_and_keeps_attempt_one_direct`. **Drift (by amendment):** the UI counts now render only for admins (`TrackRow.svelte:566` `{#if isAdmin && track.state !== 'skipped_duplicate'}`); the API still returns both (`serializers.py:99-100`). |
| (a) Ladder pinning for 0–6 failures, including held and cancelled rows | EVIDENCED +code | #51 names `test_ladder_step_ignores_held_and_cancelled_rows[0..6]`. All 7 params plus `test_next_delay_is_pinned_for_every_failure_count` passed today. |
| (b) `GET /api/tracks/{id}/attempts` returns `network_path`, redacted proxy label, `error_type`, duration on real rows; UI shows the path | EVIDENCED +code | #51: `"network_path": "proxy", "proxy_label": "http://64.137.96.74:6641"`, creds grep 0 hits. Code: `services/serializers.py:107-134` (only the `proxies.redact()` form leaves). UI path is admin-only now (`TrackRow.svelte:577` "last path", attempt history gated on `isAdmin`, lines 207/608), per Amendment v39 #3. |
| (c) Re-sent `download_track` for a COMPLETED track changes nothing (unit test plus real `celery call`) | EVIDENCED +code | #51: before/after identical, "`ignoring redelivered message`", stream 50/50 events. `test_redelivered_message_for_a_finished_track_is_a_noop[completed\|skipped_duplicate]` passed today. |
| (d) Tag-repair note stored as a warning and renders non-red; real failures still red | EVIDENCED +code | #51: `"warning_message": "tag warning: cover art missing…"`, computed `rgb(127,168,217)` vs fail `rgb(229,89,92)` (screenshots local only). **Rendering changed since:** v41 (F14) renders it as a neutral "note" tag (`TrackRow.svelte:668-671`, CSS `.note`/`.note-text` at 1223-1246 using `--text-primary`/`--text-muted`), no longer `--waiting`. Still non-red, so the claim holds, but the PR's colour evidence is stale and the note is admin-only now. |
| (e) Large file downloads with flat tab memory, checksum matches; deleted file shows notice; works via Vite fallback and nginx | EVIDENCED +code | #51 table: 54 MB "Echoes", sha256 match, RSS +6 MB / +5 MB vs +57 / +54 for the old Blob flow, `HEAD` 200 both paths, missing file → "File not found", only `HEAD` sent. Code still: `TrackRow.svelte:446-462` HEAD probe (`api.ts:747`) then `<a download>`; `routers/tracks.py:227` `methods=["GET","HEAD"]`; `vite.config.ts:96-98`. v38 later changed where a moved file is served from; v38's own PR covers that path. |
| (f) No root-owned `__pycache__` in a freshly built running `worker-dl` | EVIDENCED +code | #51: "`count=0` root-owned … image-root-owned=0 image-any=0". `backend/Dockerfile:8` `ENV PYTHONDONTWRITEBYTECODE=1`, `:66` strips every `__pycache__`. |
| (g) Tracks-scope state counts match the DB, update after an action, owner-scoped | EVIDENCED +code | #51: DB `completed 5, waiting 1` = API; chips updated in 1,031 ms; B saw `{}`. `test_tracks_scope_counts_by_state_are_owner_scoped` passed today; `counts_by_state` is in `routers/jobs.py`, `services/track_listing.py`, `QueueControls.svelte`. |
| `test_ownership.py` passes, plus `verify_separation_sse.sh` | EVIDENCED | #51: "17 passed", "`verify_separation_sse: all checks passed.`". Today 21 passed (the SSE script wasn't re-run). |
| pytest/lint/check/build; `4.35.0`; `uv lock`; graphify | EVIDENCED | #51: "pytest 414 passed; … vitest 26 passed", `check_version` → `4.35.0`, `uv.lock` and graphify committed. |

### v36: app alerting (PR #52)

| Bullet | Status | Pointer/notes |
|---|---|---|
| Category **1** fires once for real: a trip from a lowered threshold and induced `AudioProviderError`s | EVIDENCED (with flagged deviation) | #52 room 22:03:13 "Circuit breaker tripped … trip #1", released 22:33:59. **Deviation** (flagged in the PR, not recorded in Amendments): the threshold was *not* lowered (`BREAKER_TRIP_THRESHOLD=5` is a constant), and the failures were real `no_output` via `YOUTUBE_PLAYER_CLIENTS=android_vr`, not raw `AudioProviderError`. Both feed the breaker. The hook is still on main: `services/retry.py:186` `alerts.enqueue_after_commit`. v40.1 later changed the breaker streak semantics; the PR evidence predates that, but the trip path still enqueues. |
| Category **2**: a spike from a broken `YOUTUBE_PLAYER_CLIENTS` | EVIDENCED | #52 room 22:03:51 "Failure spike: the last 5 download attempts all failed with no_output". `alerts.failure_spike` is at `alerts.py:330`. |
| Category **3**: stopping `beat` | EVIDENCED | #52: `docker compose stop beat` → room 22:07:52 "Beat looks dead: no dispatch tick for 181s". |
| Category **4**: a real sweep against the test library copy | EVIDENCED +code | #52 room 22:12:31 "Library sweep finished: 13/13 …" and the "finished with errors" variant. `tasks/library.py` still enqueues `CATEGORY_LIBRARY` (main; also line 251 on the v48 working tree after the F34 change). |
| Category 5: implemented, or its skip recorded | EVIDENCED | Skip recorded: `docs/GOTCHAS.md:4677` "Category 5 (worker down) skipped". |
| Cooldown: a second identical trigger sends nothing; still nothing after a `worker-meta` restart | EVIDENCED +code | #52: "`beat_stale alert suppressed (cooldown, fingerprint stale)`" after the 22:09:12Z restart; the room has one message per round. Breaker trips use per-trip fingerprints, so the cooldown is evidenced on spike and beat-stale only. Code: Redis `SET NX EX` at `alerts.py:219`. |
| Never blocks: unreachable homeserver; a real download completes on time; failure logged once | EVIDENCED | #52: `MATRIX_HOMESERVER_URL=http://10.255.255.1`; downloads took 13s/11s/14s; "`library alert not sent: ConnectTimeout`" logged once. |
| Off when unconfigured: stack boots, startup log says off, v33 preflight passes | EVIDENCED +code | #52: "`Matrix alerts are off (… unset)`"; simulated preflight exit 0. Today the MATRIX vars are still not `${VAR:?}` (only commented in `.env.example:101-103`); log line at `alerts.py:142`. |
| Redaction: a proxy URL with credentials arrives redacted (unit test plus one real message) | EVIDENCED +code | #52 room 21:30:25 "`proxy http://203.0.113.9:8080 (redaction check 2)`", 0 secret hits. These passed today: `test_body_is_redacted_before_it_leaves_the_process`, `test_enqueue_redacts_before_the_text_reaches_the_broker`, `test_library_alert_texts`. |
| Test-alert button delivers for an admin; a non-admin gets 404 (two real sessions) | EVIDENCED +code | #52: v36user `{"detail":"Not Found"}[404]`, v36admin `{"sent":true}[200]`, UI click → room 22:16:43. Still 404: `routers/settings.py:222` `Depends(_require_admin_hidden)`. That fits the v37 amendment, whose 403 rule covers the other admin endpoints. `test_test_alert_is_404_for_a_non_admin` and `test_test_alert_delivers_for_an_admin` passed today. |
| Token never in any log line or API response | EVIDENCED | #52: `grep -cF <token>` = 0 across all six service logs and the settings/worker GET bodies, re-run on the final code. |
| pytest/lint/check/build; `4.36.0`; `uv lock`; graphify | EVIDENCED | #52: "`460 passed`", check 0/0, build ✔, test:unit 26, `check_version` → `4.36.0`, graphify committed. |

---

### Totals

50 bullets: **EVIDENCED 50** (25 of them also re-confirmed in code or tests on main today), RE-CHECKABLE IN CODE 0, NEEDS LIVE RE-VERIFY 0, GAP 0, SUPERSEDED 0.

### Claims that changed meaning since they were evidenced (none contradicted)

- **v35 (a)/(b), by amendment.** Attempt counts, network path and attempt history are admin-only in the UI (`TrackRow.svelte:566,608`), per Amendment v39 #3 and v41. The API is unchanged.
- **v35 (d), by redesign.** The warning style changed in v41 F14 from `--waiting` blue to a neutral "note" tag. It is still non-red, but the PR's computed-colour evidence describes the old style.
- **v33 rollback, by amendment.** v33.1 extended the rollback with a pre-deploy fallback. That fallback was only ever evidenced locally (#45 decision table); it can't be exercised on the host without putting the prod DB ahead of `.last-good`.
- **v36 category 1, deviation not recorded.** The deviation (threshold not lowered; `no_output` instead of `AudioProviderError`) is flagged in #52 but not recorded in Amendments.

### Optional live re-checks (not required by any bullet; regression insurance)

1. **v32 bullet 7 over today's longer migration chain.** On `spotdlwebtest`, with the app services stopped: `docker compose run --rm migrate alembic downgrade base && docker compose run --rm migrate alembic upgrade head`, then `alembic current` = head. Static check: every later revision has a downgrade and drops its enum types.
2. **v34/v35's SSE separation on current code.** `scripts/verify_separation_sse.sh` against the local stack with two real identities. It was re-run in #47, #50 and #51, but not in this session.

## v48 task 8 closing re-read: v37, v38, v39, v39.1, v39.2, v40, v40.1, v40.2

Checked against `main` = `867ed7d` (v47 merge). The working tree (`dev-runner-docker-config`, `186b184`)
differs from `main` only in `backend/app/tasks/library.py` + `tests/test_library_task.py` (v48 F34),
so the test runs below are valid for every file these slices touch.

Re-run this session:
- `cd backend && uv run pytest -q`: **586 passed** (includes test_ownership, test_dedup, test_download_task,
  test_downloads, test_retry, test_worker, test_proxies).
- `cd frontend && npx vitest run src/lib/stores/queue.test.ts`: **35 passed**.
- Static greps on `main` as cited.

PRs: v37 = #53, v38 = #55, v39 = #56, v39.1 = #58, v39.2 = #57, v40 = #59, v40.1 = #60, v40.2 = #61.

Merge-topology note: #57 (v39.2) was merged into #58's branch (`dev-mobile-jobrow-fix`), not `main`, and
#58 then landed both on `main` together (merge `26900c1`). So **no `v4.39.1` tag/release exists**; tags
go `v4.39.0` → `v4.39.2`. The #58 body's "release.yml cuts 4.39.0 before 4.39.1" didn't happen as
written. Harmless (4.39.2 contains both), noted only for the record.

---

### v37: e2e harness (PR #53)

Amendment 2026-10-10 (v37): spec 6 asserts **403** for a non-admin's admin API calls, not 404. Still
true on main: `frontend/e2e/06-admin-pages.e2e.ts:223-226` (`toBe(403)`). (v44 amendment makes
`/api/admin/stats` the one 404 exception; spec 13 covers it.)

| Bullet | Status | Pointer/notes |
|---|---|---|
| `npm run test:e2e` runs all eight baseline specs green against the real local stack, on both projects | EVIDENCED | #53 "Per-bullet evidence": "18 passed (1.6m)" + teardown "zero network download attempts". Suite is now 17 specs + `network.e2e.ts`, 3 projects; specs 01–08 still exist under the same titles. The v48 `npm run test:e2e` run re-evidences it. |
| Each spec fails when its feature breaks (specs 1, 2, 5, 7 red runs) | EVIDENCED | #53: "RED 1: queue.reset() removed…", "RED 2", "RED 5", "RED 7", plus extra reds for spec 3/7. The guarded code still exists on main: `queue.reset()` in `routes/+page.svelte:307` (and `+layout.svelte:114`, `+layout.ts:65,75`), `reload()` → `hydrateLive()` at `stores/queue.ts:387`. |
| Every project pins `locale: 'en-US'` | EVIDENCED (+ re-checked) | #53 config diff. Today `frontend/playwright.config.ts`: desktop and mobile pin `en-US` (lines ~52, ~64). v46 added a third `hu` project pinned `hu-HU` (line ~73), as v46's own plan Done-when requires ("pinned `en` locale, plus a `hu` smoke project"). Reinterpreted by v46, not a regression. |
| No spec uses a CSS-class selector (`grep` for `locator('.`) | EVIDENCED (+ re-checked) | #53: "no CSS-class selectors". Re-grepped today over all 17 specs + support: `locator('.`/`locator(".`: no hits. |
| Default run makes zero YouTube downloads; `@network` spec runs on demand and passes once | EVIDENCED | #53: worker-dl log "4 tasks ~10 ms", and `@network` "✓ … @network (20.7s)" with DB row `completed, direct-ipv4`. Teardown guard still enforced: `frontend/e2e/global-teardown.ts:35` (`network_path is not null`), `:54`. Note: spec 3 needs one prior `@network` pass on a fresh dev DB (#53 "Found, not fixed"). |
| Credentials are gitignored, with the example committed | EVIDENCED (+ re-checked) | Today: `git check-ignore -v frontend/e2e/.env.e2e` → `frontend/.gitignore:17:.env.*`; `git ls-files frontend/e2e/.env.e2e.example` lists it. |
| `docs/LOCAL_DEV.md` documents the suite and why it's local-only; implementation prompt lists `npm run test:e2e` | EVIDENCED (+ re-checked) | `docs/LOCAL_DEV.md:205` "Browser end-to-end suite (v37)", `:267` "Why local-only…"; `plan/master-v4/IMPLEMENTATION_PROMPT.md:107`. |
| `npm run lint` and `npm run check` cover `e2e/`; build passes; pytest passes | EVIDENCED (+ re-checked) | #53 probe-file red for both tools, then "0 ERRORS", "460 passed". Still wired: `frontend/vite.config.ts:159` pushes `../e2e/**/*.ts` into the tsconfig include; `lint` runs `eslint .` (only gitignored paths excluded). |
| Both version files read `4.37.0`; `uv lock` in sync; graphify run | EVIDENCED | #53: `check_version.py origin/main → 4.37.0`, `uv lock --check`. Historical (now 4.47.0). |

### v38: moved-file dedup (PR #55)

Amendment 2026-10-10 (v38 inserted) defines the slice; nothing in it supersedes a bullet.

| Bullet | Status | Pointer/notes |
|---|---|---|
| The pre-fix reproduction is recorded (worker-dl `is_already_downloaded` → `None`, attempt + ledger rows) | EVIDENCED | #55: "worker-dl: is_already_downloaded -> None", attempt `completed direct-ipv4`, ledger repointed to `/downloads`. |
| `docker compose config` shows the library `:ro` on worker-dl, dev and prod; a write attempt fails | EVIDENCED (+ re-checked) | #55: `touch: cannot touch … Read-only file system (exit=1)`. Still on main: `docker-compose.yml:130` `library:/mnt/raid1/media/music:ro`, `docker-compose.override.yml:71` `./test-library:/mnt/raid1/media/music:ro`, `docker-compose.prod.yml:92` `${LIBRARY_DIR:?…}:/mnt/raid1/media/music:ro`. |
| Same moved track, **same identity** → `skipped_duplicate`, no `network_path`, ledger unchanged | EVIDENCED | #55: "job status: settled {'skipped_duplicate': 1}", ledger before = after. Code still holds: `backend/tests/test_dedup.py:87` (moved file returns library path), pytest 586 green. |
| Same moved track, **different identity** → same | EVIDENCED | #55: `v37user` job `01631e30` "settled {'skipped_duplicate': 1}". e2e `09-moved-file.e2e.ts` › "a moved track resolves as a duplicate of its library file and downloads from it" submits as the non-admin; re-run by v48's suite. |
| `GET /api/tracks/{id}/file` returns the library file, sha256 matches | EVIDENCED | #55: sha256 `8aa5c0c5…78134` for both identities, via Vite and the prod nginx image. Spec 09 checks sha256 each run. |
| Library mount removed → no re-download, task-3 error line appears | EVIDENCED (+ re-checked) | #55: 4× `held` attempts + worker-dl ERROR "…holding it as waiting rather than downloading it again". Code: `backend/app/tasks/download.py:177` (`except dedup.LedgerRootUnavailable` → `_hold`); tests `test_download_task.py:199`, `test_dedup.py:98,111,208`. |
| Task 5's query ran on dev with output in the PR, handed to the owner for production | EVIDENCED | #55 dev output (2 `repeat_network_download`). Production result recorded later: `docs/GOTCHAS.md:4843` "`scripts/moved_file_redownloads.sql` on prod returned no rows". |
| New e2e spec passes on both projects, goes red without the mount; full suite green, zero network attempts | EVIDENCED | #55: "spec 9 alone ✓ desktop ✓ mobile", "mount removed: ✘ … still waiting", "full suite 20 passed". Spec 09 re-runs in v48's suite. |
| pytest (+ new cases), test_ownership, lint, check, build; `4.38.0`; uv lock; graphify | EVIDENCED | #55: "pytest: 469 passed", "test_ownership.py: 17 passed", version/lock lines. |

### v39: UI audit (PR #56)

Amendment 2026-10-12 "v39 outcome" records the owner's answers (refinement; v39.1 inserted;
operator detail admin-only from v41; outcome 4 confirms the surface-brief reading and the 4.39.0 bump;
A2–A6 accepted 2026-10-13).

| Bullet | Status | Pointer/notes |
|---|---|---|
| impeccable's `context.mjs` was run, output / `CONTEXT_STALE` handling recorded | EVIDENCED | #56: "emitted **no `CONTEXT_STALE`**… Recorded in report §0". Report `v39-ui-audit-report.md:15` "impeccable Setup". |
| A `critique` for every surface and state, desktop + mobile, real stack, output per surface | EVIDENCED | #56: "62 screenshots…", real-upstream login line; per-surface report §3.1–3.8; snapshots `.impeccable/critique/2026-10-12T16-14-12Z__*.md` (5 routes) on main. Screenshots themselves are out of git. |
| An `audit` for the same set, output captured | EVIDENCED | #56: "13/20 (Acceptable)"; report §1, §4 (`:136`, `:375`). |
| `v39-ui-audit-report.md` exists with per-surface sections, ranked table (slice or won't-fix), direction section | EVIDENCED (+ re-checked) | Report on main: §3 per-surface, §6 ranked table (37 `F` rows, F01–F37), §8 direction. |
| Every one of the ten already-known items present with a verdict | EVIDENCED | #56: "§5… Confirmed: #1–7, #9 and #10. #8 … gone"; report `:468`. |
| `git diff main --stat` shows no component, route or style changes | EVIDENCED (+ re-checked) | #56 diff-stat quote. Re-checked `gh pr view 56 --json files`: only `.impeccable/*`, surface briefs, version files, docs, plans, CLAUDE.md, graphify-out. No `.svelte`/`.css`/`.ts`. |
| The v37 e2e suite still passes | EVIDENCED | #56: "20 passed (1.8m)… teardown: zero network download attempts". |
| Owner's direction approval requested; version handling as in header; graphify run | EVIDENCED | #56 "Owner decisions needed" section, then answers recorded (Amendment "v39 outcome"); `check_version.py → 4.39.0`. |

### v39.1: mobile JobRow fix (PR #58, no plan file)

Checklist taken from the Amendment's scope ("the two-cause layout fix…, a mobile e2e regression check,
and DESIGN.md's stale 'confirmed at 390px' claim corrected") and the PR's Checks table.

| Bullet | Status | Pointer/notes |
|---|---|---|
| Two-cause layout fix (toggle `16rem` basis; bar `100%` basis in the ≤640px column) | EVIDENCED | #58 table: toggle "256 → **23**", bar "308×**2** → 308×**8**", row "364 → **137**". v41 later redesigned the ≤640 stack (as the amendment says), so the CSS itself changed; the behavior is held by spec 10. |
| Mobile e2e regression check | EVIDENCED (+ re-checked) | #58 red run: "job toggle height Received: 256 / progress bar height Received: 2 / job row height Received: 364". `frontend/e2e/10-job-row-layout.e2e.ts` › "a job row stays compact and its progress bar visible" still asserts toggle < 80, bar ≥ 6 high and > 100 wide, row < 200 (lines 32–37); re-run by v48's suite. |
| DESIGN.md "confirmed at 390px" corrected with a dated note | RE-CHECKABLE IN CODE (done) | `frontend/src/DESIGN.md:875` "> **Correction, 2026-10-12 (v39 F01, fixed in v39.1).**" survives v47's in-place refresh. |
| Checks: e2e 22 passed, lint, check, unit 26, build, pytest 469, `4.39.1`, uv lock | EVIDENCED | #58 "Checks" table. (No `v4.39.1` tag exists; see topology note at top.) |

### v39.2: swallowed-error classification (PR #57, no plan file)

Amendment 2026-10-12 (v39.2, recorded retroactively): owner-accepted tradeoff that a search miss is
terminal on every rung; "It was incomplete, see v40.1".

| Bullet (PR "Verification") | Status | Pointer/notes |
|---|---|---|
| `pytest` 475 passed with new cases (swallowed `LookupError`, chained age gate, bot-check stays `NoOutputFileError`, silent `None`, handler restored, proxy-rung age gate terminal) | EVIDENCED (+ re-checked) | #57 "pytest: 475 passed". All still on main and green today: `tests/test_downloads.py:286,297,313,371,427,442,454`; `tests/test_download_task.py:520,548`. Code: `backend/app/services/downloads.py:138` `AgeRestrictedError`, `:156` marker, `:227-234` `notify_error` override. |
| Real stack: B.O.B. → `lookup_failed`, explicit track → `lookup_failed` (age), control → `completed`; breaker streak 0 | EVIDENCED | #57 table: "`lookup_failed` (`lookup`)… `No results found`", "`Age-restricted on YouTube`", "Shake That! … `completed`", "`consecutive_failures = 0` with no trip". |
| Non-terminal path (`NoOutputFileError` carries the real reason) | RE-CHECKABLE IN CODE (done) | #57 says explicitly "Not exercised on the stack… unit tests only". Unit-covered: `test_downloads.py:313` "keeps a bot-check on the retry ladder with its reason" (passes today). Not live-evidenced; acceptable as unit-only, since forcing a natural non-terminal failure isn't practical. |
| Post-deploy: the 19 stuck prod tracks resolve; Scooter settles `partial · 440 of 459` | SUPERSEDED / EVIDENCED via v40.1 | Amendment: "It was incomplete, see v40.1". The outcome is evidenced in #60's post-deploy bullet: "Job `6f1640ce`: 440 `completed`, 19 `lookup_failed`… `settled · partial`". |

### v40: ambient field (PR #59)

Amendment 2026-10-12 A5 → v40: the amber decision covers all chrome (F10 list).

| Bullet | Status | Pointer/notes |
|---|---|---|
| impeccable loaded, `animate` run, output recorded in the PR | EVIDENCED | #59 "impeccable" section: context.mjs, direction probe, motion thesis, `detect.mjs --json … []`, audit 12/20 → 17/20. |
| Glow follows the cursor smoothly on desktop (recording or frame sequence) | EVIDENCED | #59: "waypoint 0 [200,200] transform translate3d(-520px, 290px, 0px)… idle 2s: ticks 456 -> 456"; `ambient-follow.mp4` (out of git). |
| **Performance:** 10s profile: no long frames, no layout/style recalc per frame, only composite; idle CPU ≈ 0 | GAP (documented deviation) | #59: "**Partly met.** One clause is not met as written": each frame is a 1-element `UpdateLayoutTree` + Commit ("Not met literally"). Met: "long tasks >50ms: []", "Layout n=0", last rAF 0.88s after the last move. The PR's "Question for you" (accept the floor, or switch to WAAPI) has **no recorded owner answer** (no PR comment, no Amendment). The floor is now written into `frontend/src/DESIGN.md:555-558` and `docs/GOTCHAS.md:4957-4963` as the accepted design, so it was accepted by merge only. List as a known, documented deviation, or get one line of owner sign-off. |
| Reduced motion gives a static glow with no rAF activity | EVIDENCED (+ re-checked) | #59: "`FireAnimationFrame` **n=0**". Code: `AmbientField.svelte:48` (`prefers-reduced-motion`), `:166` (`following = finePointer && !reducedMotion`), `:187` change listener. |
| Mobile emulation: no cursor chasing; static per design | EVIDENCED | #59: `{"hoverFine":false,"following":false,…"ticks":0}` at 390×844 with taps + drag; owner chose static. |
| A hidden tab stops the loop | EVIDENCED (+ re-checked) | #59 raw-CDP log: "another tab opened (this one bg) {"hidden":true,"ticks":52,"cancels":1}… 3s later… ticks 52". Code: `AmbientField.svelte:122` (`document.hidden` guard), `:159` `sleep()`, `:188` `visibilitychange`. |
| Amber decision recorded in DESIGN.md, names every F10 site with a verdict; implementation matches | EVIDENCED (+ re-checked) | #59: "idle … rest=1 live off=0 / live … live=1 / 2nd tab on /settings: rest=1 live=0". On main: `DESIGN.md:250` "Amber on chrome: the v40 decision (v39 F10, amendment A5)" with the per-site table (`:257`ff). Implementation `routes/+layout.svelte:41-42`: `live` = `/` && `!unreachable` && `activeTracks.length > 0` && `streamLink === 'live'` (later slices tightened it with the stream/unreachable conditions; same rule, stricter). |
| Contrast re-audited at the glow's brightest point, no worse than before | EVIDENCED | #59 8-viewport table, "verdict: no worse on any viewport, any token, either tone (strict comparison)". v42 later changed the text tokens (A2); its contrast evidence belongs to v42. |
| v37 e2e suite passes on both projects | EVIDENCED | #59: "**22 passed** (desktop + mobile, specs 01–10)". |
| lint, check, build, pytest; `4.40.0`; uv lock; graphify | EVIDENCED | #59 table: "342 files, 0 errors", "475 passed", `check_version.py → 4.40.0`. |

### v40.1: breaker wedge fix (PR #60)

Amendment 2026-10-13 (v40.1): fresh streak per trip and on manual release, escalation resets only on
success; hard failures stay terminal with no retry attention.

| Bullet | Status | Pointer/notes |
|---|---|---|
| One real breaker-feeding failure at streak 4 trips and leaves streak 0; a failure after release leaves 1, no re-trip | EVIDENCED (+ re-checked) | #60: "trip_count 1 \| consecutive_failures 0" then "consecutive_failures 1… **no re-trip**". Code: `backend/app/services/retry.py:180` (`consecutive_failures = 0` on trip). Tests: `test_retry.py:129` (trips after 5), `:144` "one failure after a trip does not retrip". |
| Admin release zeroes the streak and keeps `breaker_trip_count`; non-admin gets 403 | EVIDENCED (+ re-checked) | #60: `{"breaker_tripped_until": null, "breaker_trip_count": 1, "consecutive_failures": 0}`, "non-admin gets `403`". Code: `routers/worker.py:73-90` (`require_admin`, streak = 0, trip_count untouched). Tests: `test_worker.py:52,70,139`. |
| A proxy that refuses TCP is cooled at pick time; the attempt goes out `direct-ipv4`; breaker unchanged | EVIDENCED (+ re-checked) | #60: "`pick_proxy: http://10.255.255.1:3128 didn't accept a TCP connection…`", attempt "`direct-ipv4 \| lookup`", breaker "unchanged at 4". Code: `services/proxies.py:174` `_probe_reachable`, `:298-331` `pick_proxy`. Test: `test_download_task.py:1064`. |
| Accept-then-drop proxy → `proxy`/`other`, `attempt_count` unchanged, breaker unchanged, proxy cooled; second in a row consumes the rung; next dispatch reaches a verdict | EVIDENCED (+ re-checked) | #60: "attempt 4 `proxy \| other`… `attempt_count` stays 2; attempt 5… `attempt_count` 3 (rung consumed); attempt 6… `lookup_failed`; breaker stayed at 4". Code: `retry.py:95` `is_proxy_transport_error`, `tasks/download.py:532`. Tests: `test_download_task.py:881,897,928,949,987,1011`; `test_retry.py:184,205,288`. |
| Through a working proxy, age-gated and no-match tracks → `lookup_failed`; proxy credited; breaker unchanged | EVIDENCED (+ re-checked) | #60: "`proxy \| lookup \| Age-restricted…`", "`proxy \| lookup \| No results found…`", "`last_success_at` set, no cooldown". Test: `test_download_task.py:1042` "terminal verdict via proxy credits the proxy". |
| Production's real stuck tracks end terminal on both direct rungs, no breaker increment; control completes | EVIDENCED | #60 table (3 tracks × IPv4/IPv6 rungs all `lookup`), "Control … `completed`. Breaker `0 \| 0` throughout". |
| Full `pytest` green incl. cross-user sweep files | EVIDENCED (+ re-run) | #60: "**`pytest`: 512 passed**". Today: 586 passed. |
| Post-deploy (read-only prod): after release, 16 stuck tracks terminal, `6f1640ce` `settled · partial`, no re-trip | EVIDENCED | #60: "Job `6f1640ce`: 440 `completed`, 19 `lookup_failed`, 0 non-terminal, so `settled · partial`. The breaker after that: not tripped, streak 0." |

### v40.2: live desync fix (PR #61)

Amendment 2026-10-14 (v40.2) defines the slice; nothing supersedes a bullet.

| Bullet | Status | Pointer/notes |
|---|---|---|
| A track that goes `lookup_failed` while `/` is open loses its lane within a second | EVIDENCED (+ re-checked) | #61: "`12.46 track=lookup_failed lanes=0`… same sample in which the API first reported `lookup_failed`". Code: `stores/queue.ts:35` `LANE_ENDING_STATES = …TRULY_TERMINAL_STATES, 'lookup_failed'`, used at `:1217`. Unit: `queue.test.ts:608` (green today). |
| Same run: chips move active → done-partial without reload, match a hard reload | EVIDENCED (+ re-checked) | #61: "`13.00 … active=0 partial=1`", "after hard reload {"active":"0","partial":"1"}". Code: `patchPageJob` (`queue.ts:876`) via `refreshJobRow` (`:329`), `dropPageJob` (`:347`). Unit: `queue.test.ts:636,654,667,679,686`. |
| Same run against the pre-fix `queue.ts` reproduces the bug | EVIDENCED | #61: "`10.49 track=lookup_failed lanes=1 active=1 partial=1`". Historical, needs no recheck. |
| A hand retry of a `lookup_failed` track brings its lane back and it leaves at the verdict | EVIDENCED (+ re-checked) | #61: "`5.96 track=downloading lanes=1`… `11.33 track=lookup_failed lanes=0`". Unit: `queue.test.ts:616`. |
| `vitest`, `svelte-check`, `lint` green; new tests fail against the pre-fix store | EVIDENCED (red half asserted only) | #61: "`vitest` 34/34… The three regression tests fail against the pre-fix store" (stated, no red output pasted). Today `queue.test.ts`: 35 passed. Red-against-pre-fix not re-shown this session (it would need a temporary edit to `queue.ts`). |

None of v40.2's live bullets has an e2e spec (it needs a real `lookup_failed` track, which the
zero-download default suite avoids). Unit tests carry the regression net.

---

### Totals

| Status | Count |
|---|---|
| EVIDENCED (many also re-checked on main today) | 53 (of 57 bullets) |
| RE-CHECKABLE IN CODE (confirmed this session) | 2 (v39.1 DESIGN.md note; v39.2 non-terminal path, unit only) |
| SUPERSEDED | 1 (v39.2 post-deploy → v40.1 / Amendment "It was incomplete") |
| NEEDS LIVE RE-VERIFY | 0 beyond the v48 `npm run test:e2e` run (re-covers v37 specs 01–08, v38 spec 09, v39.1 spec 10) |
| GAP | 1 (v40 performance "only composite work": documented deviation, owner answer never recorded) |

No bullet's claim is contradicted by `main` today. Drift that isn't a regression: the v37 locale
bullet now has a third `hu` project (`hu-HU`, per v46's own Done-when). v40's `live` condition is
stricter than at v40 (adds `streamLink === 'live'` and `!unreachable`). No `v4.39.1` release tag
exists because #57 merged into #58's branch.

## v48 task 8: closing re-read, v41–v47 (+ v45.1)

Method: every "Done when" bullet in `plan/master-v4/v41…v47` re-read against the PR bodies
(#62–#69, read in full) and the master plan's Amendments, then re-checked on `main` @ `867ed7d`
where the claim can be checked statically. Things re-run this session (read-only):

- `npx vitest run`: **131 passed** (6 files).
- `uv run pytest tests/test_ownership.py tests/test_stats.py tests/test_settings_keyboard.py tests/test_settings_language.py tests/test_api_error_codes.py -q`: **69 passed**.
- `node scripts/scan-literals.mjs`: "i18n: no hard-coded user-visible strings in src/." (exit 0).
- Key parity (Python over `messages/*.json`): **686 / 686**, symmetric difference empty.
- `git grep "font-size:" main` minus `var(--fs-`: only `font-size: inherit` at `routes/settings/+page.svelte:1205` and `routes/stats/+page.svelte:671`.
- Each merge commit's `backend/pyproject.toml`, `frontend/package.json` and `backend/uv.lock`: 4.41.0 (74d665f), 4.42.0 (45a6ac9), 4.43.0 (6b57ce1), 4.44.0 (2362c16), 4.45.0 (eaae5c1), 4.45.1 (fc06f36), 4.46.0 (43d9ae0), 4.47.0 (867ed7d), all three agreeing.
- CI on #62–#69: version, pytest, deps-sync (`uv lock --check`), compose-config, frontend (`lint`, `check`, `test:unit`, `build`) and GitGuardian all SUCCESS. Every PR also has `vNN: graphify update` commits.
- Screenshot evidence still on disk in earlier session scratchpads under `/tmp/claude-1000/-home-vb2007-code-spotdl-web/`: v42 `126dfcb0…/scratchpad/shots/`, v43 `d4f016b4…/scratchpad/{before,after}` (33 + 33), v44 `f508e129…/scratchpad/shots/`, v45 `9ee5fac7…/scratchpad/shots/`, v45.1 `783cf119…/scratchpad/fav.png`, v46 `ed18a996…/scratchpad/shots/final/`, v47 `1394148a…/scratchpad/v47/evidence*/`. **v41's set is not retained anywhere.**

Caveat: the working tree (branch `dev-runner-docker-config`, HEAD `186b184` = main + v48 commit 7)
was being edited by the v48 session while this ran (`messages/en.json`, `hu.json`,
`routes/library/+page.svelte` modified: the start-sweep copy for F34). The vitest run and the literal
scan read that tree; all `git grep`/`git show` checks read `main`.

Statuses: EVIDENCED · RE-CHECKABLE IN CODE (re-checked now) · NEEDS LIVE RE-VERIFY · GAP · SUPERSEDED.
"Today:" names the e2e spec/test that re-covers the bullet in v48's full Playwright run.

---

### v41: Job & track detail redesign (PR #62)

| Bullet | Status | Pointer / notes |
|---|---|---|
| impeccable was loaded, and each sub-command used is recorded with its output in the PR. | EVIDENCED | #62 "impeccable": setup (`context.mjs`), direction probe, layout, distill, clarify, typeset/colorize, detector `[]`, audit table 13→17/20 |
| Every v39 finding assigned to v41 is listed in the PR as fixed, or as deferred with a reason. | EVIDENCED | #62 bullet 2 table (F01–F37 rows). #69's final F01–F37 table confirms each of them resolved |
| All nine cases are screenshotted before (from main) and after, on desktop and mobile, from real dev data. | EVIDENCED (artifacts lost) | #62 bullet 3 lists `before-01…09` and `after-0N-*-{admin,user}` at 1440 and 390. **The image files aren't kept in git or in any surviving scratchpad**, so this rests on the PR text alone. The "before" state can't be recaptured, and v42–v47 have changed the "after" since |
| Alignment: the detail block shares the row grid (a DevTools grid-overlay screenshot), and nested tracks indent under the job. | EVIDENCED + RE-CHECKED | #62 bullet 4: "`after-alignment-grid-overlay--desktop.png`: Chrome's own grid overlay…" (file not retained). Code: `app.css:117-121` defines `--col-lead/--col-state/--col-progress/--row-nest/--cell-inset`, used in JobRow (6), TrackRow (3) and JobTrackList (2) |
| Case 2 shows collapsed repeats that expand, and a clamped long error that expands, with the full text selectable. | EVIDENCED | #62 bullet 5: measured `{"clamped":false,…"select":"text"}`, plus spec 11. Today: `11-attempt-timeline.e2e.ts` "repeated attempts collapse and expand; a clamped error expands to its full, selectable text" |
| Case 5's warning does not use the failure style (screenshot plus the computed color). | EVIDENCED + RE-CHECKED | #62 bullet 6: "noteText rgb(139,150,157) (= --text-muted)… --fail not used". Main: `TrackRow.svelte:1221-1246`. `.note-tag` is `--text-primary` on `--line-bright` and `.note-text` is `--text-muted`, with no `--fail` |
| An impeccable audit of these components shows no contrast or accessibility regressions vs v39's baseline. Every control has an accessible name. | EVIDENCED | #62 bullet 7: job list "color-contrast ×62 → none", "0 unnamed controls out of 116". Re-confirmed later by #69: axe 0 violations, 66 runs |
| The v37 e2e suite passes, with specs updated by role/name only. A new spec covers case 2's collapse and expand. | EVIDENCED (disclosed caveat) | #62 bullet 8: "26 passed (desktop + mobile, specs 01–11)". Two selectors aren't strictly role/name and are disclosed (the `@network` spec's `hasText`, spec 11's `#`+`aria-controls`). Spec 11 exists on main. Today: specs 01–11 in the v48 run |
| `npm run lint`, `npm run check` and `npm run build` pass, and `pytest` passes. Both version files read `4.41.0`. `uv lock` is in sync. `graphify update .` has been run. | EVIDENCED + RE-CHECKED | #62 bullet 9 output block. CI green on #62. 74d665f reads 4.41.0 in all three files. Three graphify commits |

### v42: Dashboard redesign (PR #63)

| Bullet | Status | Pointer / notes |
|---|---|---|
| impeccable was loaded, and its sub-commands and output recorded in the PR. | EVIDENCED | #63 "impeccable": probe, layout, distill, adapt, typeset, colorize, clarify, detector (CLI + in-browser), audit 13→18/20 |
| Every v39 finding assigned to v42 is marked fixed or deferred with a reason. | EVIDENCED | #63 bullet 2 table. The admin `/settings` contrast remainder and toggle edges moved to v43 (Amendment 2026-10-15), and #64 fixed them |
| Before and after screenshots of `/` at 390, 768, 1024 and 1440 widths: idle, receiving, incoming, failed incoming, empty, loading, error, admin all-users. Real dev data. | EVIDENCED | #63 bullet 3. Retained: `126dfcb0…/shots/after-final/` (24 = 6 states × 4 widths), `after/02-receiving--{390,768,1024,1440}`, `04-failed-incoming-admin-allusers-expanded--768`, plus `before/` |
| The contrast tokens pass: an impeccable `audit` (axe) shows no `color-contrast` violations on `/`, and the new `--text-dim`/`--line` ratios are listed in the PR. | EVIDENCED + RE-CHECKED | #63 bullet 4: "axe on `/`: 0 violations", ratio table. Main `app.css:37,39,47,68`: `--line #2b3339`, `--line-control #6a757e`, `--text-dim #808b94`, `--fail-edge #b05154`, matching the PR's table |
| Screenshots of `/` with the breaker tripped (no "idle" anywhere) and with the SSE stream dropped then recovered (the tell appears, then clears). | EVIDENCED + RE-CHECKED | #63 bullet 5: `"idle" in visible text: false`, the `10-sse-1/2/3` sequence (retained). Main `en.json` has no "idle" string and has `waterfall_holding*`. v47 re-shot the SSE drop and recovery (`h3-sse-*`, #69 bullet 4) |
| The type scale tokens exist and are the only font sizes in v42's files (grep for `font-size:` literals in those files). | RE-CHECKED | `app.css:91-96` `--fs-label…--fs-title`. A tree-wide grep on main finds only 2× `font-size: inherit` |
| The panel material decision is recorded in DESIGN.md and visible in the screenshots. | RE-CHECKED | `DESIGN.md:451` "`.panel` — the raised faceplate", `:470` "Decided 2026-10-15 (v42, F36…)" |
| Waterfall behavior is unchanged: v34's reload-hydration spec and a live receiving check pass, and there is no appear/disappear glitch. | EVIDENCED + RE-CHECKED | #63 bullet 8: a 170s glitch watch with real `track_attempts` timestamps, and spec 05 passing. Since then, v47's diff to `queue.ts` only adds `rereadFailed`, and its `Waterfall.svelte` diff is presentation only (aria-valuetext, sheen transform, columns). The grace window and hydration logic are untouched. Today: `05-reload-hydration.e2e.ts` "a hard reload still shows an incoming item" |
| Landmarks and heading outline are verified (an accessibility-tree screenshot, or an impeccable `audit`), with no regressions vs v39's baseline. | EVIDENCED + RE-CHECKED | #63 bullet 9 (headings and landmarks list, `page-has-heading-one` gone). Main: every route has `<main id="main">` + `h1` (`+page.svelte:580/622`, `account:237-238`, `library:310-311`, `login:106/137`, `settings:633-634`, `stats:159-161`) |
| The v37 e2e suite passes on both projects (selector updates by role/name only). | EVIDENCED | #63 bullet 10: "26 passed", selector changes listed |
| `npm run lint`, … `pytest` passes. Both version files read `4.42.0`. `uv lock` is in sync. `graphify update .` has been run. | EVIDENCED + RE-CHECKED | #63 bullet 11. CI green. 45a6ac9 = 4.42.0 ×3. Graphify commit present |

### v43: Secondary surfaces (PR #64)

| Bullet | Status | Pointer / notes |
|---|---|---|
| impeccable was loaded, and its sub-commands and output recorded in the PR. | EVIDENCED | #64 "impeccable": probe, layout, harden, clarify, typeset, detector, audit 19/20 |
| Every v39 finding assigned to v43 is marked fixed or deferred with a reason. | EVIDENCED | #64 bullet 2 table. F20 sweep cancel deferred (Amendment 2026-10-16, a backend endpoint is needed), still open in #69's "Backend (v48)" list |
| Before and after screenshots of all four routes at 390, 768 and 1440 widths, incl. `/settings` validation error, `/library` mid-sweep, `/login` failed login. | EVIDENCED | #64 bullet 3. Retained: `d4f016b4…/scratchpad/before` (33) and `after` (33), incl. `settings-validation--*`, `library-midsweep`, `login-failed` |
| The confirmation component guards every listed action… cancel does nothing… confirm performs it… keyboard-only run (an e2e spec). | EVIDENCED | #64 bullet 4: spec 12, strict, "40 passed, both projects, no skips". Today: `12-confirmations.e2e.ts` "clear log asks first", "job cancel and cancel track ask first", "worker pause and breaker release ask first", "remove proxy asks first", "start sweep asks first", "cancelling an incoming submission asks first" |
| Settings saves still round-trip (output, library, proxies, alerts), and admin gating is unchanged (non-admin 404 on admin APIs, e2e spec 6 green). | EVIDENCED; "404" part SUPERSEDED | Round trip: #64 bullet 5 (spec 6). Today: `06-admin-pages.e2e.ts` "/settings loads and a save round-trips; /library loads", "/settings library, alerts and proxies round-trip", "/settings and /library refuse a non-admin". The "404" was superseded by the **v37 Amendment (2026-10-10)**: admin endpoints answer 403, and spec 6 asserts 403 |
| The `/library` progress bar still animates via `transform` (computed style or Performance check). | EVIDENCED + RE-CHECKED | #64 bullet 6: live `scaleX` samples, `transition-property: transform`. Main `library/+page.svelte:408` `style:transform="scaleX(…)"`, `:570-571` `transition: transform` |
| No ad hoc `font-size` literals in v43's files. | RE-CHECKED | A tree-wide grep on main finds only the 2× `inherit` |
| An impeccable `audit` shows no regressions vs v39's baseline for these routes. | EVIDENCED | #64 bullet 8 axe table: settings/library/account/login all **0** (v39: 36/4/4/7) |
| The v37 e2e suite passes on both projects. | EVIDENCED | #64 bullet 9: `E2E_STRICT=1`, 40 passed |
| `npm run lint` … Both version files read `4.43.0`. `uv lock` is in sync. `graphify update .` has been run. | EVIDENCED + RE-CHECKED | #64 bullet 10. CI green. 6b57ce1 = 4.43.0 ×3 |

### v44: Admin stats (PR #65)

| Bullet | Status | Pointer / notes |
|---|---|---|
| The endpoint returns correct aggregates on dev. Check every metric against a hand-written SQL query on the same data (both outputs in the PR). | EVIDENCED | #65 table "Metric \| Hand SQL \| Endpoint", all matching (7d and the 24h path) |
| One request per page load and per window change (network panel). `EXPLAIN ANALYZE` shows index use on the attempts aggregation. | EVIDENCED + RE-CHECKED | #65: request lists, and `Index Scan using ix_track_attempts_finished_at` on 300k synthetic rows. The index exists (`f3a8c2d6e9b1…:51`). Today: `13-admin-stats.e2e.ts` "/stats loads with one request and switches window with one more" |
| Non-admin: `GET /api/admin/stats` returns 404, and the `/stats` nav link is absent (two real sessions). A test in `test_ownership.py` covers it. | EVIDENCED + RE-CHECKED | #65: real upstream sessions, `user: 404`, `anon: 401`. The 404 is confirmed by the v44 Amendment (2026-10-17) as a deliberate exception. Re-ran pytest: `test_ownership.py::test_admin_stats_is_admin_only_and_hidden_from_everyone_else`, `test_stats.py::test_non_admin_gets_404_not_403`, `::test_unauthenticated_gets_401` pass. Today: spec 13 "/stats is hidden from a non-admin" |
| The response contains no titles, emails, usernames or proxy URLs (grep the response body). Proxy labels are redacted. | EVIDENCED + RE-CHECKED | #65: 1,158 needles, `hits: [] markers: []`. It found and fixed the credential-less `redact()` bug. Re-ran `test_stats.py::test_endpoint_returns_counts_only`: pass |
| `breaker_events` rows are written by a real induced trip and release on dev, and appear in the chart. The migration's `downgrade()` is clean (round-trip on dev). | EVIDENCED + RE-CHECKED | #65: a real trip, beat release, escalation and admin release, with timestamps, plus the holds-table AX text. Round trip upgrade→downgrade→upgrade. Main `c4e8a2f1d9b7_add_breaker_events.py:44-49`: `drop_table` + `DROP TYPE breaker_event_kind` |
| A hard navigation to `/stats` in the built nginx image (not just the Vite dev server) returns the page, not a 404. | EVIDENCED + RE-CHECKED | #65: `/stats -> 200 text/html`, `/nosuchroute -> 404`. Main `frontend/nginx.conf:123-124` `location = /stats { try_files /stats.html =404; }`; `+layout.ts:13-14` `ssr=false`, `prerender=true` |
| impeccable and dataviz were loaded, with output recorded. Desktop and mobile screenshots of populated, low-data and empty states. | EVIDENCED | #65: impeccable new-work/seed/finish reviewer, dataviz form heuristic and `validate_palette.js` PASS. Retained: `f508e129…/shots/final-{24h,30d}-*`, `r2-*` (low data), `empty-*`. The empty state was served by route interception of the backend's own empty output (disclosed) |
| Charts have text alternatives (audit or accessibility-tree check). | EVIDENCED + RE-CHECKED | #65: axe 0 on 4 runs; AX tree `img "Failures by type, per day…"`. Main `FailureChannels.svelte:123-124` `role="img" aria-label={summary}`, tables at `:205`, `:231`. Spec 13 asserts the `img` (`:36`) and `rowheader` (`:33`) |
| The v37 e2e suite passes, plus a new spec (admin sees stats, non-admin can't). | EVIDENCED | #65: "44 passed (4.8m)", spec 13 |
| `pytest`, `npm run lint`, … Both version files read `4.44.0`. `uv lock` is in sync. `graphify update .` has been run. | EVIDENCED + RE-CHECKED | #65: pytest 545 (later 552), check/build/vitest output. CI green, including GitGuardian (resolved). 2362c16 = 4.44.0 ×3 |

### v45: Keyboard navigation (PR #66)

| Bullet | Status | Pointer / notes |
|---|---|---|
| Every journey completed without the mouse, as a single keyboard-only e2e spec per journey: log in; submit…; log out. | EVIDENCED (disclosed grouping) | #66 bullet 1, test by test. Re-checked: `14-keyboard.e2e.ts` on main has no `click(`, `.fill(` or mouse call. Grouping: submit, retry, cancel and priority share one test (one paused-worker setup), and so do login and logout. Today: spec 14, all 20+ tests (desktop + `hu`) |
| Roving tabindex: the job list is exactly one Tab stop (an e2e assertion counting Tab presses across the list). | EVIDENCED | #66 bullet 2. The tab model (controls only on the open row) is the v45 Amendment, owner's choice. Today: spec 14 "the job list is one Tab stop; an open job adds its controls and one stop for its tracks" (`tabStopsIn` `:144`, `:150`; runs on mobile too) |
| Shortcuts are inert while typing in the search, URL, priority and settings inputs (e2e: typing `j`, `x` and `?` into each changes only the input). | EVIDENCED (refined by Amendment) | #66 bullet 3. Main spec 14: priority `:483-492`, `/settings` template `:802-803`, `/account` `:838`, search + URL "shortcuts are inert while typing in the search and URL fields" (`:898`). The `<select>` exception is the v45 Amendment ("A `<select>` is not a typing target"). Priority is admin-only since v47; spec 14 runs as the admin, so the check still applies |
| Browser chords are untouched: Ctrl+F, Ctrl+L and Cmd+K-style chords reach the browser (manual check recorded). | EVIDENCED | Automated: spec 14 "browser chords reach the browser". Manual: #66 "For the owner" item 2: "✅ Manual browser chords (owner, 2026-10-18)" |
| Hungarian QWERTZ, emulated. An e2e helper dispatches the real Hungarian `key`/`code` pairs… | EVIDENCED | #66 bullet 5, `e2e/support/keyboard.ts` `huPress`. Today: spec 14 "Hungarian QWERTZ, emulated: ? and / alias, AltGr and y/z fire nothing" (`:943-985`) |
| Hungarian QWERTZ, for real. One manual pass on an actual Hungarian layout… recorded in the PR. | EVIDENCED (owner) | The agent couldn't (Xvfb ignored keymaps). #66 "For the owner" item 1: "✅ Done by the owner (2026-10-18): real Hungarian pass…, all as expected". Note: that was on 4.45.0, before v46's translated overlay and v47; since then only the emulation (spec 14, `hu` project) has re-covered it |
| No binding requires AltGr on Hungarian: the PR includes the final table with each key's Hungarian physical combination. | EVIDENCED + RE-CHECKED | #66 "Final binding table". `bindings.test.ts:31,35,39,49` (no y/z, no AltGr char, no clash) pass in today's vitest run. v47 made bump/priority admin-only (`bindings.ts:196,205,214`), and `DESIGN.md:1076` was updated to match |
| Focus restoration, each with its own e2e assertion: after cancel or archive removes the focused row, after load more, after an SSE patch…, after closing the help overlay or a confirmation, and after a route change. | EVIDENCED (cancel part reinterpreted by Amendment) | #66 bullet 8. The v45 Amendment: cancel never removes a row in the current store (owner: keep as is), so cancel is evidenced as "focus stays on the cancelled row". Today: spec 14 "archive and unarchive by keyboard; focus moves to the next row", "load more by keyboard focuses the first new row", "load more tracks in an open job…", "a reload keeps focus on the same track…", "every route through g chords; focus lands on each page's h1" |
| The shortcut toggle off disables single-key shortcuts while Tab, arrows, Enter and Esc still work. Persists across reload and a second browser. Backend owner-scoped (pytest)… | EVIDENCED + RE-CHECKED | #66 bullet 9. Re-ran `test_settings_keyboard.py`: pass. Today: spec 14 "off disables single keys, keeps Tab/arrows/Enter/Esc, persists, and is per user" |
| The help overlay lists exactly the registry's bindings, filtered by admin and route (e2e compares them), and shows the Hungarian physical combination… designed through impeccable (output + screenshot). | EVIDENCED | #66 bullet 10. Retained `9ee5fac7…/shots/final-{desktop,mobile}-help.png`. Today: spec 14 "lists exactly the registry's bindings for the ${who}, per route", "signed out, it offers only the help and Esc" |
| The skip link works (e2e), and the focus ring stays visible on every newly focusable element (impeccable `audit`, plus a screenshot of the roving focus on a row). | EVIDENCED (target changed in v47) | #66 bullet 11: axe 0, computed `outline: solid 3px`, and `final-*-focus-job-row.png` (retained). **Changed since:** v47 moved the skip link's target from `main#main` to `#queue-heading` (#69 bullet 6; spec 14 `:189-196` updated), so #66's description of the target is stale. The bullet still holds. Today: spec 14 "skip link, find a job with /, open it and move into its tracks" |
| Screen-reader sanity: rows announce name and expanded state (accessibility-tree snapshot). No `aria-hidden` focusable elements. | EVIDENCED | #66 bullet 12. Main spec 14: `.ariaSnapshot()` at `:218`, `expectNoHiddenFocusables` at `:226`, `:758`, `:1073` |
| Cross-user: the shortcut preference endpoint is covered by `test_ownership.py`. | RE-CHECKED | `test_ownership.py:278` `test_keyboard_preference_is_owner_scoped`, which passes in today's run |
| `pytest`, `npm run lint`, `npm run check`, `npm run build` and `npm run test:e2e` pass. Both version files read `4.45.0`. `uv lock` in sync. graphify. | EVIDENCED + RE-CHECKED | #66 table: pytest 559, e2e "65 passed, 19 skipped, 0 failed, strict". CI green. eaae5c1 = 4.45.0 ×3 |

### v45.1: Favicon (PR #67, no plan file; implicit Done-when from its body)

| Bullet | Status | Pointer / notes |
|---|---|---|
| The default Svelte favicon is replaced by the app's icon, inlined by Vite with no nginx change | EVIDENCED + RE-CHECKED | #67 "Verification": `link[rel=icon]` resolves to the new SVG. Main `frontend/src/lib/assets/favicon.svg` has the `#34D987` gradient (commit 77331dd), imported at `+layout.svelte:14` and used at `:235` |
| Version 4.45.1 in both files plus the locks; build passes | EVIDENCED + RE-CHECKED | fc06f36 = 4.45.1 ×3. CI green (frontend build) |

### v46: Internationalization (PR #68)

| Bullet | Status | Pointer / notes |
|---|---|---|
| No hard-coded user-visible string remains in `frontend/src`. A scripted scan… comes back empty, apart from an allowlist listed in the PR. | EVIDENCED + RE-CHECKED | #68 bullet 1: the scan was shown failing once, plus the 17-entry allowlist table. Re-ran `node scripts/scan-literals.mjs`: "no hard-coded user-visible strings in src/." It runs in `npm run lint` (`package.json` scripts) |
| The `hu` and `en` key sets are identical, and the build or lint check fails when one key is removed (shown once, then restored). | EVIDENCED + RE-CHECKED | #68 bullet 2: `hu.json is missing "track_retry_now"`, `lint exit=1`, `build exit=1`. Now: 686/686 identical. `check-messages.mjs` is wired into `lint`, `check` and `build` |
| Auto-detect: a fresh profile with browser language `hu-HU` gets Hungarian, `en-US` English, `de-DE` English (three Playwright contexts). | EVIDENCED | #68 bullet 3. Unit `detectLocale` (`i18n.test.ts:39-53`) passes today. Today: `16-i18n.e2e.ts` "auto-detect: hu-HU gets Hungarian, en-US English, de-DE falls back to English" |
| Preference wins: set Hungarian on `/account` in an English browser… persists… Another user is unaffected. Backend owner-scoped (pytest + `test_ownership.py`). | EVIDENCED + RE-CHECKED | #68 bullet 4. Re-ran `test_ownership.py::test_language_preference_is_owner_scoped` / `test_clock_preference_is_owner_scoped` and `test_settings_language.py`: pass. Today: spec 16 "preference wins: Hungarian chosen on /account follows the user, and only that user" |
| The `/login` choice before login is honored, and adopted into a profile that has none. | SUPERSEDED | **v46 Amendment (2026-10-18):** "The Done-when bullet … is superseded by this rule (spec 16 tests the rule instead)". Today: spec 16 "signed out the browser decides; a time format pinned on /account wins once signed in". `test_signing_in_saves_no_language` passes |
| `<html lang>` matches the active locale and changes on switch (DOM check). | EVIDENCED + RE-CHECKED | #68 bullet 6. Main `lib/i18n/locale.svelte.ts:71` sets `document.documentElement.lang`. Asserted in `15-hu-smoke.e2e.ts:19,51,54,66` and spec 16 |
| Dates, numbers and plurals render correctly in both languages (screenshots…, plus a unit test for the plural cases 0, 1 and 5). | EVIDENCED + RE-CHECKED | #68 bullet 7. `i18n.test.ts:197,211` (en and hu 0/1/5) and `:222` (grouping) pass today. Screenshots retained: `ed18a996…/shots/final/detail-{hu-HU,en-US}/` |
| Every `HTTPException` the UI surfaces has a `code` (an inventory table in the PR), and each renders translated in Hungarian. An unknown code falls back to `detail` (unit test). | EVIDENCED + RE-CHECKED | #68 "Error-code inventory". On main the only raw `HTTPException(` raises are the deliberate hidden 404s (`routers/admin.py:20`, `routers/settings.py:217`). `test_api_error_codes.py` passes today; `i18n.test.ts:178` (fallback) and `:280` ("every error code") pass |
| Track metadata and attempt error text are unchanged in Hungarian (screenshot). | EVIDENCED | #68 bullet 9: `final/detail-hu-HU/desktop-job-detail.png` (retained). Spec 15 asserts the title survives. v47 added `lang="en"` on the raw text (13 sites on main) |
| Every route was screenshotted in Hungarian on desktop and mobile, with no truncation or overflow… impeccable `clarify`/`audit` output was recorded. | EVIDENCED | #68 bullet 10 + "impeccable output". Retained: `final/hu-HU-admin/` (6 routes × desktop/mobile) and `hu-HU-user/` |
| The Hungarian string table is in the PR for owner review. | EVIDENCED (note) | 2 PR comments on #68, "Hungarian string table for owner review (1/2)" and "(2/2)", 667 keys. Note: main now has **686** keys. v47's 19 new strings were never put in front of the owner as a table |
| The v37 e2e suite passes in its pinned `en` locale, plus a `hu` smoke project. v45's keyboard journeys pass in both languages. | EVIDENCED (via #69) | #68's final run was "88 passed, **1 failed**, 19 skipped" (a v45 flake, rerun 8/8). The previous run was 89/0. A clean 0-failure run with the `hu` project is #69's "93 passed, 19 skipped". `playwright.config.ts` has the `hu` project running specs 14 and 15 |
| `pytest`, `npm run lint`, `npm run check` and `npm run build` pass. Both version files read `4.46.0`. `uv lock` in sync. graphify. | EVIDENCED + RE-CHECKED | #68 bullet 13. CI green. 43d9ae0 = 4.46.0 ×3 |

### v47: UI polish (PR #69)

| Bullet | Status | Pointer / notes |
|---|---|---|
| impeccable was loaded, and `polish`, `harden`, `critique`, `audit` and `document` were each run, with output recorded. | EVIDENCED | #69 bullet 1. Full reports stayed in the session scratchpad (`1394148a…/scratchpad/v47/`) |
| The before/after score table vs v39's report covers every surface. Every v39 finding row has a final status. | EVIDENCED | #69 "Before/after scores" and "Every v39 finding, final status" (F01–F37) |
| No `font-size` literal outside the token definitions (grep output). | EVIDENCED + RE-CHECKED | #69 bullet 3. Re-grep on main: only the 2× `inherit` |
| The hardening cases are each screenshotted: a long title and non-ASCII text, 1000+ jobs, the SSE drop and recovery, and session expiry. | EVIDENCED | #69 bullet 4. Retained: `v47/evidence/h1-*`, `h2-1000-jobs-head-*` (`h2-…-loaded-*` is in `evidence-round1/`), `h3-sse-dropped/recovered`, `h3-offline-*`, `h4-session-expired-*`. Session end is also covered today by `17-session-end.e2e.ts` (both tests) |
| DESIGN.md was regenerated, with prior decision records preserved and dated notes for every changed rule (diff reviewed in the PR). | **GAP (minor, owner decision open)** | YAML frontmatter is present (`DESIGN.md:1-5`), and so are the dated v47 notes (e.g. `:241`, `:323`, `:442`, `:605`). But #69 bullet 5 admits: "earlier per-version blockquotes … were folded into current-state prose … most of their dates are not [kept]". Review rounds 7 and 22 flagged it. The PR asked the owner ("If you want the dates back inline, it is a mechanical follow-up") and there's no recorded answer: no PR comment or review, no Amendment. Literal "prior decision records preserved" is only partly met |
| Every keyboard journey from v45 still passes (incl. the Hungarian QWERTZ emulation), and the v37 e2e suite passes on both projects plus v46's `hu` smoke project. | EVIDENCED | #69 bullet 6: "93 passed (9.8m), 19 skipped", with zero network downloads |
| Hungarian screenshots of every route at 390 and 1440 widths show no overflow or truncation. | EVIDENCED | #69 bullet 7: 40 captures, `scrollWidth − innerWidth = 0`. Retained `v47/evidence/r-*-hu-{390,1440}.png` (20) |
| `npm run lint`, … `pytest` passes. Both version files read `4.47.0`. `uv lock` in sync. graphify. | EVIDENCED + RE-CHECKED | #69 bullet 8. CI green. 867ed7d = 4.47.0 ×3. graphify commit 6862e3a |

---

### Totals (65 bullets: v41 9, v42 11, v43 10, v44 10, v45 14, v45.1 2, v46 13, v47 8)

| Status | Count |
|---|---|
| EVIDENCED (incl. "+ RE-CHECKED" and disclosed caveats; 33 of them also re-checked on main now) | 59 |
| RE-CHECKABLE IN CODE only (confirmed statically now) | 4: v42 type scale, v42 DESIGN.md panel record, v43 font-size literals, v45 `test_ownership` keyboard case |
| SUPERSEDED | 1: v46 `/login` choice. Also a partial: v43's "404 on admin APIs" became 403 (v37 Amendment) |
| GAP | 1: v47 DESIGN.md prior-record dates, owner answer missing |
| NEEDS LIVE RE-VERIFY | 0 strictly. Every live-only bullet was evidenced in its PR, and nothing in the code since contradicts it. The list below is what v48's full Playwright run re-covers |

### Re-covered by v48's full e2e run (no separate live check needed)
- v41 case 2 → `11-attempt-timeline.e2e.ts` (both tests)
- v42 hydration → `05-reload-hydration.e2e.ts`
- v43 confirmations → `12-confirmations.e2e.ts` (6 tests); settings round-trip → `06-admin-pages.e2e.ts` (3 tests)
- v44 → `13-admin-stats.e2e.ts` (both tests)
- v45 → `14-keyboard.e2e.ts` (desktop + `hu`; "the job list is one Tab stop…" also on mobile)
- v46 → `15-hu-smoke.e2e.ts`, `16-i18n.e2e.ts` (3 tests)
- v47 → `17-session-end.e2e.ts` (2 tests)

**v48-specific watch item:** v48 commit 7 (`186b184`, F34) changed the sweep to archive only the
sweeping admin's jobs. On `main`, the start-sweep confirmation copy (v43's F34 display half) still says
"archived, for every user" (`en.json:580-582`). The working tree being edited by the v48 session
already rewrites it ("Your own finished jobs … other users' jobs are left as they are"). Once that
lands, spec 12 "start sweep asks first" and spec 14 "run the library sweep through its confirmation"
must pass on the v48 branch. #68 also recorded spec 12's sweep test as flaky (2 in 19 runs).

### Soft notes (not gaps)
- v41's whole screenshot set (nine cases before/after and the grid overlay) survives only as PR text.
  The image files are gone.
- #66's binding table and skip-link target are now partly stale: bump/priority became admin-only in
  v47, and the skip link now lands on `#queue-heading`. DESIGN.md and spec 14 are current.
- v47's 19 new message keys (667 → 686) never went to the owner as a string table.
