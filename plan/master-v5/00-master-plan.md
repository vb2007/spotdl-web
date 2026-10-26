# spotdl-web — Master Plan v5

> This is the master v5 roadmap, approved by the owner and committed **verbatim** as the project's
> permanent record, with the same treatment masters v1–v4 got. Individual version plans
> (`plan/master-v5/v49-*.md` … `v69-*.md`) expand the roadmap below. `IMPLEMENTATION_PROMPT.md`
> in this folder is the template prompt for every v5 implementation agent. `CLAUDE.md` carries
> the durable summary. Master v1–v4 plans are never edited again. Where this plan corrects one of
> them, it says so here.

## Context

Masters v1–v4 (v00–v48, PRs #1–#71) are complete. 4.48.0 is deployed at `spotdl.vb2007.hu` and in
daily use. **Master v5 is meant to be the last master for a while**, so it should leave nothing
known-broken behind. It has four parts:

1. **Close every open issue.** Over 48 versions, GOTCHAS, PR bodies ("Found, not fixed"), plan
   amendments and CI history accumulated about 45 confirmed-open items. The ledger below gives
   **every one** a slice or an explicit, re-justified "accepted" verdict. This is most of the
   master.
2. **A Firefox extension** in this repo. The owner works with Spotify and the app in split tabs and
   copy-pastes URLs between them. The extension puts a download icon next to tracks, albums,
   artists and playlists on `open.spotify.com` that queues the item directly. Right-clicking the
   icon offers cascades: a track's whole album or artist, an album's artist.
3. **An admin "other users" view.** Today's admin scope is "mine" or "all users". A third option
   shows only other users' items.
4. **Features found in this session's research,** all four confirmed by the owner:
   - watched playlists/artists, plus job-level re-run and retry;
   - job zip and M3U export;
   - a PWA with a Web Share Target;
   - personal notifications and a non-admin "my stats".

**New for v5: parallel implementation.** Up to **4 agents work side by side**, each in its own git
worktree with its own Docker stack and its own local Postgres. That takes infrastructure the repo
doesn't have yet (v50), and a protocol for keeping parallel branches mergeable (below).

**First, a clean pipeline (v49, added before this plan was merged).** The CI → Release → Publish &
Deploy chain runs on `workflow_run`, so every CI run (PR, schedule, dispatch) spawns two empty,
skipped runs, and a run on `main` can be cancelled by the next merge. Twenty more slice merges would
multiply that noise and that risk, so v49 makes every workflow run only when it has work to do,
before any other slice merges.

---

## Verified current state

Read from the repo, GitHub and CI this session (2026-10-23, `main` at `df712e2`):

| Finding | Evidence |
|---|---|
| **Fixed host ports, so two stacks can't coexist** | `docker-compose.yml:70` `127.0.0.1:8000:8000`, `:240` `127.0.0.1:5173:80`, `docker-compose.override.yml:123` `127.0.0.1:5173:5173`. No `COMPOSE_PROJECT_NAME` handling |
| **Dev Postgres is a single LAN database** | `.env.dev.example:18` → `192.168.100.200:5432/spotdlwebtest`. Branch-local Alembic migrations from parallel agents would break each other's stacks |
| **The CI chain spawns empty runs** | `release.yml:18` and `publish-deploy.yml:16` fire on `workflow_run` for *every* CI/Release completion and then skip themselves (`release.yml:39`, `publish-deploy.yml:44`): of the last 1000 runs, Release is 160 skipped / 212 and Publish & Deploy 158 skipped / 228. `ci.yml:26-28` cancels in progress on `main` too. Leftover workflows "Deploy checks" (file deleted, last run 2026-08-04) and "Backend tests" still list. One runner (`vbServer`); a CI run takes 4–9 min |
| **The version check allows going backwards** | `.github/scripts/check_version.py:92-104` fails only when `version == base_version`, never when it's lower |
| **CI pytest runs on SQLite** | `ci.yml:101-103`: "every test uses an in-memory SQLite engine". `FOR UPDATE` and native-enum casts are untestable (GOTCHAS v34.1, v35) |
| **Cookie-only auth, no API tokens, no rate limits** | `routers/auth.py:15,25-35,98-106` (`SPOTDL_SESSION`, `httponly`, `secure`, `samesite=lax`). No limiter anywhere in `backend/app` |
| **Job create accepts anything** | `routers/jobs.py:44-54` `_classify_source_type` is a substring check, and anything else becomes a `SEARCH` job |
| **Admin scope is one boolean** | `all_users` in `routers/jobs.py:85`, `routers/tracks.py:101`, `services/job_listing.py:83`, `services/track_listing.py:79,90`, `routers/stream.py:27-31`, `frontend/src/lib/stores/queue.ts:186,638-662`, `QueueControls.svelte:363-372` |
| **SSE payloads carry no owner** | `services/events.py:52`. Only the Redis channel name (`spotdl:events:{user_id}`) identifies the owner |
| **No extension, PWA manifest or service worker** | No `extension/` directory, `frontend/static/` holds only `robots.txt`, `app.html` has no manifest link |
| Owner-acted items done since v4's plan | The library was switched to `/mnt/raid1/media/music` on 2026-10-11 (GOTCHAS v38). `plan/master-v4/00-master-plan.md:92` still says "Not planned". That's corrected here, and v4's plan stays unedited |

---

## Open-items ledger

Every unfixed item found this session. **Slice** is where it gets fixed. "Accepted" items keep a
written reason and are re-confirmed by v69. Sources: GOTCHAS line numbers, PR numbers, and plan
files.

### Download / retry engine → v55 unless noted

| # | Item | Source | Slice |
|---|---|---|---|
| E1 | Broker error inside `expand_job`'s enqueue loop strands the remaining tracks in `pending` | GOTCHAS:4537, #48 | **v56** |
| E2 | The stale-track reclaim `UPDATE … WHERE id IN (snapshot)` doesn't re-check `state`, so a just-completed track is reset | GOTCHAS:4639, #51; `tasks/beat.py:55-58` | v55 |
| E3 | Reclaiming a still-running download counts one network attempt twice | GOTCHAS:4639 | v55 |
| E4 | A track reclaimed during the pacing sleep still downloads | #51; `download.py:237` | v55 |
| E5 | The `DOWNLOADING` write is unconditional, so a cancel or reclaim landing just before it is lost | #51, #60; `download.py:308` | v55 |
| E6 | A mid-download cancel publishes its event before the attempt row, with no counters | GOTCHAS:4645, #62 | v55 |
| E7 | One DB transaction idles for the whole download, and the completed row's `updated_at` is the start time | GOTCHAS:4649 | v55 |
| E8 | spotdl's own "file already exists" skip is recorded as a `completed direct-ipv4` network attempt | GOTCHAS:4649, #53 | v55 |
| E9 | A completed track keeps its old `last_error`/`last_error_type` | GOTCHAS:4650 | v55 |
| E10 | `lookup_failed` keeps a stale `scheduled_at` | v40.1:92 | v55 |
| E11 | Breaker hold writes one `held` row per track per tick (about 460 rows in one 2026-10-18 trip) | GOTCHAS:5516 | v55 |
| E12 | The forced IPv6 rung costs a whole ladder wait where IPv6 isn't routable | GOTCHAS:3925 | v55 (was accepted; a cheap routability probe makes it fixable) |

### API / state integrity → v56 unless noted

| # | Item | Source | Slice |
|---|---|---|---|
| A1 | `cancel_job` sets `CANCELLED` regardless of current state | #64, #69, #70; `jobs.py:236-262` | v56 |
| A2 | Job cancel turns `lookup_failed` tracks into `cancelled`, and `DELETE /api/tracks/{id}` allows it too, though the UI never offers it | `jobs.py:21-24`, `tracks.py:21` | v56 |
| A3 | No single-track GET; the UI re-reads up to 1000 tracks instead | #64; `TrackRow.svelte:347-354` | v56 |
| A4 | Deleting a manual proxy any attempt used returns 500 (FK has no `ondelete`) | #64; `track.py:79`, `track_attempt.py:84` | v56 |
| A5 | `retention_days` has no server upper bound, and a huge value breaks the sweep | #64; `settings.py:266` | v56 |
| A6 | Admin endpoints answer 403 vs 404 inconsistently | #52; CLAUDE.md v2 invariants | v56 |
| A7 | The API has no "breaker active" flag, so the UI trusts the client clock | #63 | v56 |
| A8 | A non-admin "retry now" skips the backoff ladder (owner decision recorded in v56) | #69 | v56 |

### Library / dedup → v57

| # | Item | Source |
|---|---|---|
| L1 | No way to cancel a running sweep (v39 F20, deferred in v43) | v43 amendment; `routers/library.py` |
| L2 | A sweep can delete a file whose destination is its own path; no library ⟂ downloads overlap validation | #70 |
| L3 | Race: worker-dl commits a ledger row between the sweep's re-read and its delete | GOTCHAS:5410 |
| L4 | `reconcile_disk` decides "unmounted" from "directory empty"; 47 rows survived only by accident | GOTCHAS:423, :5440 |
| L5 | A ledger row pointing at a hand-deleted file holds its track forever while `/downloads` is empty | GOTCHAS:4870 |
| L6 | Dedup guards only the *current* library roots | #55 |
| L7 | Disk-full partial copy could be adopted as an existing library file | #36 (re-verify against v31's `copy_verify` fix; close with evidence if already covered) |
| L8 | Six dev rows had duplicate files in `./downloads`, never investigated | #55 (investigate on a v57 stack; fix or record) |

### Alerts / observability → v59 unless noted

| # | Item | Source | Slice |
|---|---|---|---|
| O1 | A real breaker trip on 2026-10-18 never reached Matrix, root cause unknown | GOTCHAS:5516, #70 | v59 |
| O2 | Alert sends are fire-and-forget (`retry=False`, `expires=300`, shared `meta` queue) and nothing records them | `services/alerts.py:88,272-278` | v59 |
| O3 | Container logs don't survive a deploy (json-file, recreated containers) | GOTCHAS:428; `docker-compose.yml:22-25` | **v60** |
| O4 | Alerting category 5 ("worker down") skipped | #52 | v59 |
| O5 | A Redis outage logs a traceback every 60s | GOTCHAS:4696 | v59 |
| O6 | No alert history UI (out of scope in v36) | v36 | v59 |

### Pipeline / CI → v60 unless noted

| # | Item | Source | Slice |
|---|---|---|---|
| P1 | `notify` starts with `actions/checkout`, so a GitHub 429 killed deploy *and* notice together (4.40.2 undeployed for about 30h) | run 38581543804; `publish-deploy.yml:656`, `release.yml:130` | **v49** |
| P2 | The self-hosted runner sometimes never acquires scheduled jobs, so the daily cron is red | runs 10-04, 10-10, 10-13, 10-15 | v60 |
| P3 | A release changing `networks:` likely hits `guard-error` with no rollback | #44 | v60 |
| P4 | Whether `cancelled()` rollback runs after a `timeout-minutes` cut is unverified | #44 | v60 |
| P5 | A transient dockerd error in the health gate fails it at once | #44 | v60 |
| P6 | `wait_for_stack_health.sh` prints compose stderr unredacted on its error path | #44 | v60 |
| P7 | A dispatch from a pre-v33 workflow copy deletes `.last-good` | #44 | v60 |
| P8 | The pre-deploy health probe has a 0 timeout, so a slow-but-healthy stack disables the fallback | #45 | v60 |
| P9 | `check_version.py` allows the version to go backwards | this session | **v50** |
| P10 | CI pytest on SQLite only | `ci.yml:101` | **v51** |
| P11 | Every CI completion fires Release, and every Release completion fires Publish & Deploy, through `workflow_run`; both skip themselves, so the run list is mostly empty runs | 160/212 and 158/228 skipped (`gh run list -L 1000`); owner screenshots 2026-10-23 | **v49** |
| P12 | The deleted "Deploy checks" and "Backend tests" workflows still list in the Actions sidebar (their old runs keep them alive) | `gh workflow list` | **v49** |
| P13 | `cancel-in-progress: true` applies to `main` too, so a second merge can cancel the first merge's run mid-release | `ci.yml:26-28` | **v49** |
| P14 | The daily schedule re-runs the full suite on unchanged `main` (starting about 5h late) and spawns two more empty runs, when only the yt-dlp freshness check needs a schedule | `ci.yml:23,243`; run times 09:19–09:52 UTC for a `04:17` cron | **v49** |

### Frontend behavior → v62 unless noted

| # | Item | Source | Slice |
|---|---|---|---|
| F1 | A job off the loaded page can't move its status chip until reload | v40.2:40 | v62 |
| F2 | "Load more" in the same second as a status change moves a chip twice | v40.2:43, #61 | v62 |
| F3 | `refreshJobRow` treats any error as "gone" and drops the row | #61 | v62 |
| F4 | An SSE stream dropped by laptop sleep waits for the socket timeout | #69 | v62 |
| F5 | No `+error.svelte` | #68 | v62 |
| F6 | `/settings` and `/account` drop unsaved edits on navigation | #69 | v62 |
| F7 | `/account` mixes two save models | #69 | v62 |
| F8 | "Clear log" is enabled on an empty queue | #69 | v62 |
| F9 | Cross-tab identity change detected by poll, not push | #63 | v62 |
| F10 | Stale progress cache after a re-run that doesn't bump `attempt_count` | #49 | v62 |

### UI debt (impeccable) → v67 unless noted

| # | Item | Source | Slice |
|---|---|---|---|
| U1 | Admin all-users view warms the page amber from others' downloads (DESIGN §8.3) | #59, #69 | **v54** |
| U2 | `/settings` about 4000px tall on a phone (§8.4) | #69 | v67 |
| U3 | Tracks scope repeats titles (§8.5) | #69 | v67 |
| U4 | 1600-row log is about 28k DOM nodes (§8.6) | #69 | **v68** |
| U5 | Every phone job row carries a full archive button | #69 | v67 |
| U6 | Copy: "done — partial" on a one-track not-found job, Hungarian "indulásra kész" reads "done", ambiguous "no signal" | #69 | v67 |
| U7 | Unused tokens (`--signal-ink`, `--fail-dim`, `--space-7`) | #69 | v67 |
| U8 | Both languages ship in one 30KB chunk | #69 | v67 |
| U9 | English error text inside Hungarian pages not fully `lang="en"` (WCAG 3.1.2) | #68 | v67 |
| U10 | The stats chart crosshair is pointer-only | #65 | v67 |
| U11 | A drag released outside the window can strand the glow | #59 | v67 |
| U12 | The `/stats` surface brief still has `## Unresolved` | `frontend/src/.impeccable/surfaces/frontend-src-routes-stats-page-svelte.md:39` | v67 |
| U13 | 320px admin view 27px horizontal scroll | #58 (re-verify; may be fixed) | v67 |

### Dev loop / tests → v52 unless noted

| # | Item | Source | Slice |
|---|---|---|---|
| D1 | `uvicorn --reload` hangs while an SSE stream is open | GOTCHAS:5507 | v52 |
| D2 | Celery workers don't hot-reload | GOTCHAS:337 | v52 |
| D3 | A long-running Vite stops opening the confirmation dialog; root-owned `.svelte-kit/types` | GOTCHAS:679, :5244 | v52 |
| D4 | Dependency changes need `up -d --renew-anon-volumes` | GOTCHAS:150 | v52 |
| D5 | e2e spec 12 "start sweep" flaky (2/19); spec 14 load-more once; `retries: 0` | #68, v48 closing re-read | v52 |
| D6 | `localhost:5173` can resolve to another server on `[::1]` | #64 | v52 (and v50's per-slot ports) |
| D7 | `svelte-kit sync` mid-suite breaks spec 1; spec 3 needs a prior network pass | #53, #55 | v52 |
| D8 | Fixed races (`FOR UPDATE`, reclaim, enum compares) have no realistic test | GOTCHAS:4535 | **v51** |

### Docs drift → v60

| # | Item | Source |
|---|---|---|
| X1 | `README.md:6-9` says "master v2 in progress" | — |
| X2 | `docs/GOTCHAS.md` title "(master v1, v01–v13)" and its master-v2 caveat | GOTCHAS:1 |
| X3 | `.env.example:10`, `docs/DEPLOYMENT.md:562-587,365,374,795` name the prod DB `spotdl_web`; the real one is `spotdlweb` | GOTCHAS:4314 |
| X4 | `docs/DEPLOYMENT.md` callouts for new required vars not prominent (old pipeline note) | old `master-v4-pipeline-issues.md` |

### Accepted by design (stay accepted, reason restated)

| Item | Why it stays |
|---|---|
| Content-blind dedup (folder + filename) | A master-v3 invariant: a re-download at another bitrate still counts as present |
| Age-gated / not-on-YouTube-Music tracks fail terminally | Fetching them needs logged-in cookies (account-ban risk) or other providers; this is outside the app's purpose |
| No CI browser job | The self-hosted runner is the production host |
| "1000+" count caps | Bounded queries are deliberate; exact counts past 1000 aren't worth a full scan |
| `/stats` DST bucket offset | Owner decision 2026-10-17 |
| Customisable key bindings; languages beyond hu/en; SSE event replay | Explicitly out of scope; the resync-on-connect contract stays |
| A failed deploy past `migrate` doesn't auto-roll back | Documented manual downgrade; automatic data rollback is riskier than the failure |
| One extra DB query per request (split session check) | Deliberate v17 trade |
| A failed Matrix send is a warning, not a red run | v33.1 owner decision |
| A library sweep archives only the sweeping admin's own jobs | v48 owner decision (F34) |
| The store doesn't drop a row that stops matching the filter until reload | v45 owner decision ("keep it as is") |
| Production's dead file-sourced proxies | An owner action (disable in `/settings`), not code. In housekeeping |
| Rolling back across v34.1 strands the `expand` queue | Historical; no target that old is ever rolled back to |

---

## Locked decisions for v5

| Area | Decision |
|---|---|
| Version numbers | Slices continue at **v49**; releases are `5.NN.0`. Patch slices `vNN.1` as before |
| Parallel implementation | Up to **4 agents at once**, grouped into **waves**. A wave starts only after every slice of earlier waves is merged. Each slice has a fixed **slot** (1–4) and a declared **"Files owned"** list. Two same-wave slices never own the same file, apart from the shared hotspots below |
| Agent environment | Each agent has its own **git worktree** (never the shared main checkout) and its own **compose project** with its **own local Postgres container**, created and owned by the agent (owner decision). The LAN `spotdlwebtest` stays the owner's interactive dev DB. Agents don't use it |
| Real YouTube traffic from agents | `worker-dl` is **off by default** in agent stacks. A real download needs the host-wide lock `/tmp/spotdl-web-realdl.lock`, so at most one agent stack ever talks to YouTube, the same exposure as one dev stack |
| Shared hotspots | `frontend/messages/{en,hu}.json`, `docs/GOTCHAS.md`, `graphify-out/`, the Alembic head, `CLAUDE.md`, plus the per-wave co-owned files each plan declares (wave 1: `routers/jobs.py` create vs list params; wave 2: v57's single `dedup` call site in `tasks/download.py`; wave 3: `ci.yml` and `release-deploy.yml`, where v60 and v61 own separate jobs; wave 4: `JobRow.svelte`'s delimited v63/v64 blocks and `/account`'s v65/v66 blocks). These are resolved by the **rebase protocol**, never avoided by skipping a needed edit |
| CI chain | No `workflow_run` anywhere (v49): PRs run "CI"; a push to `main` runs one "Release & Deploy" run that calls the checks, the release and the deploy in-run; the schedule runs only "Nightly". Nothing cancels, and nothing creates a run that only skips |
| Merge order | The owner merges a wave in ascending slice order. CI rejects a version that isn't strictly greater than `main`'s (v50) |
| Production data | Still not disposable. A migration that drops or rewrites data says so and takes a `pg_backup` first |
| Firefox extension | Lives in `extension/`, Manifest V3, Firefox-only. It has its **own semver** in `extension/manifest.json`, independent of the app version, and CI forces a bump when `extension/` changes (v61). Distributed as an AMO-signed **unlisted** XPI on a GitHub release, with a self-hosted `update_url` |
| Extension auth | **The existing session cookie first** (seamless when logged in to the app in the same Firefox). Only if that fails, a per-user **API key** from `/account`. Keys can only submit jobs and read their own submission status. They never unlock admin endpoints or any other surface |
| Extension submissions | Server-side allowlist: `open.spotify.com` track/album/artist/playlist URLs only (no `SEARCH`) for key-authenticated and extension-origin requests. Cascades (track → album/artist, album → artist) are resolved **server-side** from Spotify metadata, never scraped from the DOM |
| Admin scope | `view = mine \| all \| others`, admin-only. A non-admin is always `mine`. The `all_users` parameter stays as an alias for `all` |
| UI work | Every UI slice goes through the impeccable skill. Hungarian QWERTZ keyboard rules and both message files apply to every new element, including the extension's own UI (`_locales/en`, `_locales/hu`) |

---

## Parallel execution model

### Wave 0: why v49 and v50 come first

- **v49 cleans the CI chain**, so every later slice's PR and merge produce exactly the runs that do
  work, and a merge burst at the end of a wave can't cancel a release. It touches only `.github/`
  and docs and needs **no local stack**.
- **v50 builds the isolation.** Today two stacks on one machine collide on host ports
  `8000`/`5173`. They would share one dev database whose Alembic head every branch moves, and four
  `worker-dl`s would quadruple YouTube exposure from one IP. It runs on the owner's **default dev
  stack**, since the slot tooling doesn't exist yet.
- The two share no file, so they run **in parallel**. **v49 is merged first**; v50 rebases onto it.
  No other slice starts before both are merged.

### Slots

| Slot | Compose project | API port | Web port | Postgres |
|---|---|---|---|---|
| 1 | `spotdlweb-s1` | 8001 | 5174 | container `postgres` in that project, volume `spotdlweb-s1_pgdata` |
| 2 | `spotdlweb-s2` | 8002 | 5175 | same pattern |
| 3 | `spotdlweb-s3` | 8003 | 5176 | same pattern |
| 4 | `spotdlweb-s4` | 8004 | 5177 | same pattern |
| (owner) | default | 8000 | 5173 | LAN `spotdlwebtest` |

`scripts/agent_stack.sh <slot> up|down|env|psql|realdl` (built in v50) is the single entry point.

### Waves

| Wave | Slices (slot) | Theme | Depends on |
|---|---|---|---|
| 0 | v49 (—, no stack) · v50 (default stack) | CI chain, parallel stacks | — (v49 merged first) |
| 1 | v51 (1) · v52 (2) · v53 (3) · v54 (4) | Test infra, dev loop, extension API, others view | wave 0 |
| 2 | v55 (1) · v56 (2) · v57 (3) · v58 (4) | Engine races, API gaps, library hardening, the extension | wave 1 (v58 needs v53) |
| 3 | v59 (1) · v60 (2) · v61 (3) · v62 (4) | Alert delivery, pipeline resilience, extension release, frontend store fixes | wave 2 (v61 needs v58) |
| 4 | v63 (1) · v64 (2) · v65 (3) · v66 (4) | Watch jobs, export, PWA/share, personal notifications | wave 3 |
| 5 | v67 (1) · v68 (2) | UI debt (impeccable), list virtualization | wave 4 |
| 6 | v69 (1) | Hardening close | wave 5 |

### Rebase protocol (every agent, before the final push and again if `main` moves while the PR is open)

1. `git fetch origin && git rebase origin/main`.
2. **Alembic:** if `main` gained a migration, re-parent this branch's migration
   (`down_revision` → main's head). `alembic heads` must print exactly one head. Run
   `upgrade head` → `downgrade -1` → `upgrade head` on the slot's DB.
3. **Message JSONs, GOTCHAS, CLAUDE.md:** keep both sides' entries. Re-run the frontend key-parity
   check.
4. **graphify-out:** take `main`'s, then run `graphify update .` and commit.
5. **Version:** if `main`'s version is already ≥ this slice's, **stop and ask the owner**. Never
   pick a new number on your own.
6. Re-run every check from the prompt's checks section on the rebased branch, plus the Done-when
   bullets the rebase could have touched.

---

## Version roadmap

| # | Wave | Branch | Scope |
|---|---|---|---|
| **v49** | 0 | `dev-ci-chain` | P1, P11–P14: no `workflow_run`; "CI" on PRs, one in-run "Release & Deploy" on `main` (checks → release → deploy → curl-only notify), "Nightly" for the yt-dlp check; nothing cancels; delete the skipped and leftover-workflow run history. Workflows and docs only, so no bump |
| **v50** | 0 | `dev-parallel-stacks` | Env-driven ports and project name; opt-in `docker-compose.agent.yml` with a local Postgres per project; `scripts/agent_stack.sh`; `worker-dl` behind a `realdl` profile plus the host-wide lock; strict-greater version check; docs |
| **v51** | 1 | `dev-pytest-postgres` | pytest on real Postgres in CI (service container) and locally (slot DB); race-test helpers; port the SQLite-only "lock was requested" tests to real concurrency |
| **v52** | 1 | `dev-dev-loop` | D1–D7: SSE-safe API reload, Celery autoreload, Vite/`.svelte-kit` hygiene, anon-volume renew, e2e flake fixes and retry policy |
| **v53** | 1 | `dev-extension-api` | API keys (hashed, `/account` UI), Bearer auth on submit + `/api/auth/me` only, server-side cascades, Spotify-URL allowlist, rate limits on login/submit, "already queued / in library" hint, cookie-from-extension spike |
| **v54** | 1 | `dev-scope-others` | `view=mine\|all\|others` end to end (REST, counts, hydration, SSE filter, store, control, keyboard, i18n), plus U1 |
| **v55** | 2 | `dev-engine-races` | E2–E12 |
| **v56** | 2 | `dev-api-gaps` | A1–A8, E1 |
| **v57** | 2 | `dev-library-hardening` | L1–L8 |
| **v58** | 2 | `dev-firefox-extension` | `extension/`: icons on tracks/albums/artists/playlists, an in-page cascade menu, cookie-then-key submit, options/popup, en/hu, fixture tests, a real `web-ext run` pass |
| **v59** | 3 | `dev-alert-delivery` | O1, O2, O4, O5, O6: reproduce the lost alert, a Postgres alert outbox with retries, worker-down, log throttling, alert history on `/stats` |
| **v60** | 3 | `dev-pipeline-resilience` | P1–P8, O3, X1–X4. Workflows, compose logging and docs only, so no bump |
| **v61** | 3 | `dev-extension-release` | AMO unlisted signing, a GitHub release with the XPI, `updates.json`, CI lint/tests, extension version check, install docs |
| **v62** | 3 | `dev-frontend-store-fixes` | F1–F10 |
| **v63** | 4 | `dev-watch-jobs` | Watched playlist/artist jobs (scheduled re-expand, new tracks only), "re-run expansion", "retry all failed" |
| **v64** | 4 | `dev-job-export` | Streamed zip of a job's present files, plus an `.m3u8` |
| **v65** | 4 | `dev-pwa-share-target` | Installable PWA, a Web Share Target → `/share`, a login round-trip |
| **v66** | 4 | `dev-personal-notifications` | Browser notifications when own jobs settle; a non-admin "my stats" |
| **v67** | 5 | `dev-ui-debt` | U2, U3, U5–U13, plus an impeccable audit of every surface v53–v66 added |
| **v68** | 5 | `dev-log-virtualization` | U4: virtualized job/track lists that keep keyboard, focus, live patching and load-more intact |
| **v69** | 6 | `dev-v5-hardening` | The production close: the cross-user sweep over every new surface, the full e2e plus an extension pass, a production smoke, ledger re-confirmation, docs, the closing re-read |

### Why this order

- **v49 and v50 first:** a clean pipeline for every later merge, and the isolation nothing parallel
  can run without. v49 merges first, because each later slice's precondition is a green
  "Release & Deploy" run on `main`.
- **Wave 1 is the foundation for later waves:**
  - v51 gives v55/v56/v57 real Postgres to prove their race fixes against;
  - v52 removes the dev-loop friction four agents would hit four times over;
  - v53 is the contract v58 builds on;
  - v54 is self-contained and settles the queue store before v62 changes it again.
- **Wave 2 is correctness plus the extension.** v55, v56 and v57 split the backend by module
  (download/beat · routers/expand · library/dedup). v58 lives entirely in `extension/`.
- **Wave 3** separates delivery and ops (v59 backend alerts, v60 workflows and docs, v61 extension
  CI) from the frontend store (v62).
- **Wave 4's features** come after the fixes, so they're built on a correct engine and store.
- **Wave 5's UI work comes last**, so impeccable audits the final surfaces. Virtualization
  rebuilds the list once everything that renders into it exists.
- **v69 closes**, as v13, v22, v31 and v48 did.

---

## Critical interactions to design around

- **v49's chain vs later workflow edits.** v51 (the `pytest` job), v60 (notify internals, health
  gate) and v61 (extension release) all edit workflows after v49. None may reintroduce
  `workflow_run`, a `cancel-in-progress` on `main`, or a workflow that starts only to skip. v61's
  signing runs as a job of "Release & Deploy", gated on the extension version rising.
- **v50's overlay vs the v32 guard.** Agent DBs are local and named per slot (for example
  `spotdlweb_s1`). The guard keeps refusing production names. The overlay must **never** be
  applicable in production: prod's compose invocation never includes it, and `SPOTDL_ENV=dev`
  stays mandatory.
- **v53's API keys vs data separation.** A key authenticates as its user, so every query stays
  owner-scoped. A key on any admin endpoint answers as a non-admin would, even when the key's user
  is an admin. Admin power needs the cookie session. The key itself is a secret: hashed at rest,
  shown once, never logged (`redact` covers it).
- **v53's cookie path vs CSRF.** If the spike shows the extension's background fetch carries
  `SPOTDL_SESSION`, then a cross-site POST becomes possible in principle from *any* extension the
  user installs. Mitigation: extension-origin submissions must send an `X-Spotdl-Client:
  extension` header (a non-simple header forces CORS preflight from web pages, which the API
  doesn't allow cross-origin), and they're limited to the job-create allowlist.
- **v54 vs v62 vs v68 in `queue.ts`.** Three slices in three different waves touch the store.
  Each later one rebases onto the merged earlier one; the waves exist for exactly this.
- **v55 and v56 vs `tasks/`.** v55 owns `tasks/download.py` and `tasks/beat.py` (reclaim). v56 owns
  `tasks/expand.py`. v59 later touches `beat.py`'s alert watchdog; different function, a later
  wave.
- **v57's sweep cancel vs the ledger invariants.** A cancelled sweep stops between files, never
  mid-file. Every file already moved keeps its repointed ledger row (the master-v3 invariant).
- **v58's DOM injection vs Spotify's DOM changing.** Selectors come from `data-testid`/ARIA
  wherever possible, and are isolated in one `selectors.js` with fixture tests. A selector miss
  degrades to "no icon", never a page error. The `/track/`, `/album/`, `/artist/`, `/playlist/`
  link in or near the element is the identity source, never text.
- **v63's watched jobs vs dedup and the breaker.** Re-expansion queues only tracks not already in
  the job or the ledger. While the breaker is tripped, a re-expansion may run (metadata only), but
  its new tracks wait like any other.
- **v64's zip vs file availability.** Membership is keyed on the file existing at its recorded
  path, the same rule as v27. Archived jobs stay exportable. Streaming must not hold a DB
  transaction open.
- **v65's share target vs auth.** A share opens `/share?url=…`. If the user isn't logged in, the
  URL survives the login round-trip, and only an allowlisted Spotify URL is ever submitted.
- **v67/v68 vs v45's keyboard model and v37's e2e selectors.** Virtualization must keep the roving
  tabindex by row **id**, `End`/`Shift+G` load-more, and focus restoration. Off-screen rows don't
  exist in the DOM, so selectors and the help overlay can't assume they do.

---

## Critical files

- **Parallel infra:** `docker-compose.yml`, `docker-compose.override.yml`, new
  `docker-compose.agent.yml`, new `scripts/agent_stack.sh`, `.env.dev.example`,
  `frontend/playwright.config.ts`, `.github/scripts/check_version.py`, `docs/LOCAL_DEV.md`
- **Engine:** `backend/app/tasks/{download,beat,expand}.py`, `backend/app/services/{retry,dedup,library}.py`
- **API:** `backend/app/routers/{jobs,tracks,auth,proxies,settings,library,stream}.py`,
  `backend/app/services/{job_listing,track_listing,sessions,users}.py`
- **Alerts:** `backend/app/services/alerts.py`, `backend/app/routers/admin.py`
- **Frontend:** `frontend/src/lib/stores/queue.ts`, `frontend/src/lib/api.ts`,
  `frontend/src/lib/components/*`, `frontend/src/routes/**`, `frontend/messages/*.json`,
  `frontend/src/lib/keyboard/bindings.ts`, `frontend/nginx.conf`
- **Pipeline:** `.github/workflows/{ci,release,publish-deploy}.yml`, new
  `.github/workflows/{release-deploy,nightly}.yml` (v49), `.github/scripts/*`
- **Extension:** new `extension/` (manifest, background, content, options, popup, `_locales`,
  tests), a new workflow for signing

Reuse rather than rewrite: `require_session`/`current_session`; `app_settings`'s singleton;
`proxies.redact()`/`redact_text`; `serializers.*_to_dict`; `events.publish_*_event` (owner
required); `expansion._ensure_spotify_client()`; `retry.record_attempt`; `archive.archive_jobs`;
`library.copy_verify`; the keyboard registry (`frontend/src/lib/keyboard/`); the Paraglide
messages; `scripts/verify_separation_sse.sh`; `wait_for_stack_health.sh`.

---

## Verification

The standing rules apply to every slice: a real stack (now the agent's own slot stack), real
Postgres, the real network, and each Done-when bullet evidenced individually this session.
v5-specific:

0. **v49 proves the chain on a scratch branch** (stubbed publish/deploy): one run per PR push, one
   successful "Release & Deploy" per `main` push even in a 3-push burst, none skipped or cancelled,
   and a notice that survives an unavailable checkout. The run history is cleaned (counts before
   and after).
1. **v50 proves isolation by running two slot stacks at once.** Both stay healthy, their databases
   are independent, a migration applied on one is absent on the other, and the realdl lock refuses
   a second holder.
2. **Race fixes (v55–v57) are proven on real Postgres** with v51's concurrency helpers, never only
   with a mocked "lock requested" assertion.
3. **The extension (v58) is proven in real Firefox on real `open.spotify.com`** (`web-ext run`):
   - every target type gets an icon;
   - every cascade queues the right job on the slot stack;
   - the cookie path and the key fallback each work once, with the cookie path verified
     empirically, not assumed.
4. **v61 proves the signed XPI installs in release Firefox** and auto-updates from `updates.json`.
5. **Every new read path re-runs the cross-user sweep:** v53 keys, v54 others view, v63 watched
   jobs, v64 export, v65 share, v66 my-stats.
6. **UI slices** keep using impeccable, and keep the e2e suite green on desktop, mobile and `hu`.

---

## Owner housekeeping (not agent work)

These came up in PR deploy notes and were never confirmed as done. They're tracked here so
they don't get lost. v69 asks about each.

- [ ] Dismiss the two GitGuardian false-positive incidents (#52, commit `1bbb4cd`).
- [ ] Confirm production `.env` has `MATRIX_*` set (app alerts are off otherwise) (#52).
- [ ] Run `scripts/moved_file_redownloads.sql` against production and note the counts (#55).
- [ ] Remove `v48smoke@example.com` from production `ALLOWED_EMAILS` (#70).
- [ ] Disable the dead file-sourced proxies in `/settings` (#60).
- [ ] Add the AMO API credentials (`AMO_JWT_ISSUER`, `AMO_JWT_SECRET`) as repository secrets
      before v61.
- [ ] vb2007.hu-api still shares `~/.docker/config.json` on the runner (#71). That fix belongs in
      the other repo.
- [x] Delete the untracked root notes `master-v4-pipeline-issues.md`/`workflow-logs.txt`. Done
      by the planning session, at the owner's request.

---

## Amendments

The plan above is the approved text, kept verbatim. Changes directed after approval are recorded
here.

- **2026-10-24, v49: a `redeploy` input on "Release & Deploy" (owner's decision).** With the chain
  in-run, a merge deploys only the release it cuts, so an unbumped merge no longer re-deploys the
  current release. Before v49 it did, which put the release back after a `manual-*` dispatch and
  shipped workflow-side fixes. The owner chose to keep both through
  `gh workflow run "Release & Deploy" -f redeploy=true`: on `main`, with the version already
  tagged, `plan` skips the release and the deploy runs on the tag's commit in release mode. The
  `plan` job gains `redeploy`/`commit` outputs beside `release` (v61 still adds `extension`).

- **2026-10-24: admin-managed user access inserted as v69 (owner's request); the close moves to
  v70.** The admin adds login addresses in the app, and the person can sign in right away, with
  no `.env` edit or redeploy.
  - **What exists today:** `ALLOWED_EMAILS` is env-only (`config.py:75`, checked at
    `routers/auth.py:114`), boot requires `ADMIN_EMAIL` in it (`config.py:198-212`), and adding a
    user means editing the host `.env` (`docs/DEPLOYMENT.md:655-663`). An open `/api/stream`
    checks its session only at connect.
  - **Owner decisions (locked for v5):**
    - The allowlist becomes a **DB table**, imported once from `ALLOWED_EMAILS` (plus
      `ADMIN_EMAIL`) and then managed in an admin-only `/users` page. The env list is ignored
      after the import. `ADMIN_EMAIL` stays in env, is always allowed, and can't be removed.
    - Removing an address cuts the person off **at once**: their sessions, open streams and API
      keys. Their jobs and files stay, and re-adding restores the same account.
  - **Placement:** `v69-user-access.md`, wave 5 / slot 3, beside v67 and v68. Waves 1–4 are full,
    and it builds on v53's keys, v56's admin rule (A6) and v62's cross-tab identity (F9).
    - It gets its own `/users` route, so it never touches v67's `/settings` rework, and it runs
      its own impeccable pass.
    - Wave 5's co-owned hotspots gain `stores/queue.ts` (v68 windowing, v69's revoke block) and
      `frontend/e2e/` (v69 adds one spec; v68 owns the rest).
  - **Renumbering:** the close is now `v70-v5-hardening.md` (`5.70.0`), and every reference to
    "v69" as the close in the text above means v70 (the ledger's re-confirmation, the housekeeping
    questions, the Waves and Roadmap rows). Its cross-user sweep and production smoke cover v69,
    and so does Verification item 5.
  - **Critical interaction:** the admin's stream pattern-subscribes to `spotdl:events:*`, so a
    revocation published there would log out the admin's own tab. Revocation uses a separate
    `spotdl:control:{user_id}` channel, and the stream's periodic session re-check uses a
    short-lived DB session (v31's idle-in-transaction bug).
  - **Housekeeping:** `v48smoke@example.com` can be removed in `/users` once v69 is deployed.

- **2026-10-23, v50: a slot's e2e run needs a seeded history, and `worker-dl`.** The plan expected
  slot verification to lean on "tracks already present". The Playwright suite leans on much more
  of the owner's long-lived `spotdlwebtest`: ledger rows for every track a default run submits,
  three pages of admin jobs, a twelve-track album and a network-path attempt. A fresh slot
  database has none of it. v50 adds `scripts/agent_seed.py` (run by `agent_stack.sh <slot> seed`,
  and by `e2e` before the suite), which recreates it with stand-in files. The suite also needs
  `worker-dl` running (seeded jobs settle there, and setup and teardown query it), so
  `agent_stack.sh <slot> e2e` holds the realdl lock for the run: e2e runs on different slots are
  serialized, though a default run makes no network attempt. A spec that comes to lean on more
  dev data must extend the seed.

- **2026-10-25, v52: released as `5.53.1`, not `5.52.0`.** Wave 1 merged v53 (`5.53.0`) before
  v52, and CI's `check_version` requires a version strictly greater than `main`'s, so v52 can't
  ship as `5.52.0`. The owner left the choice to the v52 session. `5.53.1` keeps every later
  slice's planned `5.NN.0` (`5.54.0` would have taken v54's), at the cost of the patch number a
  `v53.1` would have used: such a slice, if one is ever inserted, takes `5.53.2`.

- **2026-10-25, v69: what a removal does to the person's downloads (owner's decision).** The
  2026-10-24 entry left this open: as written, the person's queued tracks would have kept
  downloading, since nothing in the dispatch path looks at the allowlist.
  - **The rule:** a job that has already started keeps downloading to the end, so no album or
    artist is left with gaps in the archive. A job that hasn't started doesn't start. The unit is
    the job, for albums, playlists and artists alike.
  - **Held, not cancelled:** an unstarted job is held (`jobs.held_at`, rollup lifecycle `held`).
    The admin can still cancel it, and adding the address again resumes it.
  - **Watched jobs (v63)** of a removed owner aren't re-expanded, started or not, since new tracks
    are new work.
  - **How:**
    - the removal and `download_track` serialize on the job row, so nothing starts after the hold;
    - a gate in `download_track` drains messages already in the broker without an attempt.

    `v69-user-access.md` carries the tasks, the files (`tasks/{download,expand,beat}.py`,
    `services/rollup.py`, `models/job.py`, `i18n/labels.ts`) and the Done-when evidence.

- **2026-10-26, v54.1: an unreleased premiere is terminal, released as `5.54.1` (owner's
  request).** Production had a track whose matched YouTube video is a premiere 102 days out
  (`Premieres in 102 days`). It went round the ladder as a breaker-feeding `no_output`, on every
  rung, proxy included. The owner asked for it to be handled like a track that isn't on YouTube:
  terminal `lookup_failed`, cleanly marked, never looped, as a separate patch PR.
  `downloads.NotYetReleasedError` (a `LookupError`, beside the age-gate and unavailable-video
  ones) covers it, with no schema or UI change. `5.54.1` sits between v54 and v55, so wave 2 keeps
  its planned `5.NN.0` versions.

- **2026-10-26, v54.2: real source quality, released as `5.54.2` (owner's request).** The owner
  found every download was a "320k" MP3. No YouTube stream is above ~130–160k without Premium, so
  those were re-encodes ~2.5× the size, with a false bitrate. Since late September they also came
  from a 360p video's ~96k AAC (format 18): v31.1's forced player clients had lost every
  audio-only stream. Owner decisions:
  - **Output:** Opus at a new default quality "best" (YouTube's stream kept as is, no re-encode).
    The settings dropdowns offer only what the source can back: opus|m4a|mp3, and best|160k|128k|
    96k|64k. A data migration moves the stored mp3/320k to opus/best.
  - **Source:** `YOUTUBE_PLAYER_CLIENTS` defaults to yt-dlp's own `default`.
  - **Slot 5:** `agent_stack.sh` gains it for out-of-wave patch slices, so one can be verified
    while a wave holds 1–4. Wave agents keep 1–4.
  - **Existing library files** (production: 2,303, 24.7 GB, all from the ~96–128k AAC source)
    can't be converted back. Re-downloading them as Opus is a **separate "library upgrade" slice
    after wave 2** (it touches v55's `tasks/download.py` and v57's library code). It needs an
    explicit exception to the "nothing is ever deleted on the library" invariant: replace only a
    ledger-recorded, app-downloaded file (the app's YouTube comment tag), never anything else.
    That slice's plan states it, and the owner approves it there.

- **2026-10-26, v55: what the engine slice did where its plan text and the code differed.**
  Recorded for the owner to confirm in review; none moves an item to another slice.
  - **E5's guard is "the state found on entry", not literally `state = 'queued'`.** A message
    is also sent for a `pending` track (expand_job's first dispatch) and redelivered for a
    `downloading` one; a literal `queued` guard would never download a new job's first track.
    For every beat dispatch the guard reads `queued`, as written. With the track's newest
    attempt number it forms the invocation's claim (E4 reuses it), and review round 1 extended
    it to the hold and the dedup resolution, the same race class.
  - **E10's migration also clears existing leftovers.** `d9b3e5f7a1c2` nulls `scheduled_at` on
    every `lookup_failed` row, a data rewrite the plan didn't name. It's covered by the
    deploy's pre-migrate `pg_backup` and listed under the PR's Deploy notes.
  - **E11's collapse doesn't shrink a single trip's rows.** One trip holds each queued track
    once (beat dispatches nothing while tripped), so the 2026-10-18 trip's ~460 rows were most
    likely ~460 tracks. The collapse is the plan's (consecutive identical holds of one track);
    it shrinks repeated trips, a pause and the unmounted-root hold. The attempts API returns
    `hold_count` (a one-line `serializers.py` addition), but the timeline (frontend, not v55's)
    still renders a collapsed row as a single `held`, so "held ×N" now needs the frontend to
    read `hold_count`. Open for the owner: accept, or schedule that frontend follow-up.
  - **E12 records the skip in the row's note, not in `network_path`.** The row keeps the path
    really used (proxy, or forced IPv4 with no proxy up), so the column stays truthful and no
    enum value or migration is needed; the note reads "IPv6 isn't routable from this worker;
    skipped the direct IPv6 rung".
