# spotdl-web — Master Plan v4

> This is the master v4 roadmap, approved by the owner and committed **verbatim** as the project's
> permanent record. It gets the same treatment `plan/master-v1/`, `plan/master-v2/` and
> `plan/master-v3/00-master-plan.md` got, for the same reason: the roadmap must never be quietly
> reinterpreted after the fact. Individual version plans (`plan/master-v4/v32-*.md` …
> `v48-*.md`) expand the roadmap table below with implementation detail. `CLAUDE.md` carries the
> durable summary every future session reads first. `IMPLEMENTATION_PROMPT.md` in this folder is
> the template prompt handed to each version's implementation agent.
>
> Master v1–v3 plans are never edited again.

## Context

Master v3 (v23–v31.1, PRs #28–#41, all merged) fixed the download outage. It added attempt
history, usernames, ID3 integrity, direct file downloads, library sort & move, IPv4/IPv6
escalation, and a proxy rung that finally routes through a proxy. The app is deployed at
`spotdl.vb2007.hu` and used for real by the owner and relatives.

Master v4 has four parts, drawn from the owner's own use and from this planning session's sweep:

1. **Operational safety.** Local dev and production still share one database, which cost a real
   ledger row in v31. The release pipeline can fail in both directions, with no alert to anyone.
   That happened twice in a row on 2026-09-27.
2. **Correctness.** The "Active signal" section goes empty on a page refresh. The attempt counter
   contradicts the attempt history. A redelivered task can rewrite a completed track. The
   attempts API hides which network path was used.
3. **Visibility.** The app fails silently. Nothing tells the owner when the breaker trips, when
   YouTube changes something and every download starts failing, or when beat stops. Nothing
   shows success rates either.
4. **UI/UX.** The owner finds the UI cluttered. The clearest case is an expanded track: a single
   successful download already looks out of place, and one with five error attempts is worse.
   The owner wants a living background that follows the cursor, and complete mouse-free keyboard
   operation, which PRODUCT.md has required since v00 and which has never existed. It must be
   oriented to the **Hungarian QWERTZ** layout most users type on. The UI also needs **full
   Hungarian/English i18n**, since most users are Hungarian and every string is English today.
   All UI work in v4 goes **strictly through the impeccable skill**.

**Locked for v4: production data is no longer disposable.** Three real users, real jobs and a
real dedup ledger now live in production. Destructive migrations are still *allowed* (there is no
backward-compatibility requirement for API clients), but a migration that drops or rewrites data
must state so in its plan and back up first.

---

## Verified current state

Read from the repo this session, not assumed:

| Finding | Evidence |
|---|---|
| **Dev and prod share one database** | `.env.dev.example:13` points `DATABASE_URL` at `…/spotdl_web`, the prod database. CLAUDE.md's "Development environments" section calls the split overdue after v31's local `reconcile_disk()` pruned a real prod ledger row (`docs/GOTCHAS.md` v31 section) |
| **Deploy preflight doesn't check required vars** | `.github/workflows/publish-deploy.yml:205-209` checks only that `.git`, `.env` and `proxies.txt` exist. `docker-compose.prod.yml:107,133` require `${LIBRARY_DIR:?…}` |
| **Rollback re-runs the new compose files** | `publish-deploy.yml:269-283` resets `IMAGE_TAG=$PREV` in `.env`, then runs `up -d` inside the *already-checked-out new tree* (`:241-251` moved it), so a missing variable fails the rollback identically |
| **Rollback target can be a throwaway tag** | `publish-deploy.yml:211-215` takes "previous" from whatever `IMAGE_TAG=` currently holds. `:253-257` writes `manual-<sha>` dispatch tags into `.env` regardless of `persist` |
| **Rollback across a migration can't succeed** | Migrations run implicitly in the one-shot `migrate` service (`docker-compose.yml:34-40`, `alembic upgrade head`). An older image facing a newer DB revision exits non-zero, which blocks every backend service |
| **No notification on any failure** | Only `$GITHUB_STEP_SUMMARY` (`publish-deploy.yml:291-301`). Its own `compose ps` (`:300`) hits the same interpolation error |
| **CI can't see the drift** | `ci.yml:378` copies `.env.example` to `.env` before `compose config`, so any variable present there passes. The comment at `ci.yml:355-361` claims three interpolated vars; there are more |
| **"Active signal" is SSE-only** | `frontend/src/lib/stores/queue.ts:119-129`: `liveActive` is "SSE-fed only, never REST-loaded". `incoming` (`:131-135`) is SSE plus the optimistic post-submit insert. `reload()` (`:243`) loads neither, so a hard refresh empties both until the next event |
| **Attempt counter disagrees with the history** | `retry.record_failure` increments `tracks.attempt_count` (`backend/app/services/retry.py:79-80`) and `record_success` doesn't, while every invocation writes a `track_attempts` row numbered with the pre-attempt count (`backend/app/tasks/download.py:60`). A first-try success shows "passes attempted: 0" next to one completed attempt (the owner's screenshot) |
| **`attempt_number` collides** | The breaker-hold and cancelled rows (`download.py:88-101`) don't increment, so they share a number with the next real attempt (`docs/GOTCHAS.md` v24 entry, accepted at the time) |
| **Network path is stored but hidden** | `TrackAttempt.network_path` (`backend/app/models/track_attempt.py:72`) is omitted by `track_attempt_to_dict` (`backend/app/services/serializers.py:104-113`) and absent from `frontend/src/lib/api.ts:124-133`. `TrackRow.svelte:197` can only say `via proxy`/`direct` |
| **Redelivery can rewrite a completed track** | `download.py:66` gates only on `CANCELLED`, and the dedup branch at `:117` then sets `SKIPPED_DUPLICATE` (flagged in `plan/master-v2/00-master-plan.md:253-258`, never fixed) |
| **Tag warnings render as failures** | `.attempt-error` is always `var(--fail)` (`TrackRow.svelte:199-200,408-409`), including v26's tag-repair notes on *completed* attempts (`docs/GOTCHAS.md:3307-3315`) |
| **File download buffers the whole file in memory** | `TrackRow.svelte` `handleDownload` fetches into a `Blob`, then clicks an object URL. That works, but it throws away v27's `X-Accel-Redirect` streaming on the browser side |
| **No alerting anywhere in the app** | No webhook, SMTP or chat client in `backend/app`. Beat deliberately has no healthcheck (`docker-compose.yml:170`). `/api/worker/status` exposes only the *current* breaker state (`backend/app/routers/worker.py:16-21`) |
| **No browser tests** | `frontend/package.json` has no test runner. Earlier versions used ad-hoc Playwright scripts in scratchpads. v31 recorded that v25's UI checks were never re-run in a browser |
| **Every UI string is hard-coded English** | No i18n library or message files in `frontend/`. Labels, `aria-label`s, `<svelte:head>` titles and state labels (`TrackRow.svelte`'s `STATE_LABEL`) are literals, and the backend's English `detail` strings surface directly via `ApiError.message` |
| **No keyboard support beyond native Tab** | No `keydown`, `tabindex`, `.focus()` or skip link anywhere in `frontend/src`. Every `TrackRow` is its own tab stop. Focus is lost when a row disappears. PRODUCT.md:71,101 require full keyboard operation |
| **Static amber glow** | `frontend/src/app.css:105-109`, a fixed `radial-gradient` on `body`. It is arguably at odds with DESIGN.md §2's "amber means live" rule, since it is permanent chrome in amber |
| **Expanded track detail is misaligned** | `TrackRow.svelte` grid `9rem | 1.5fr | 1fr | 1fr | 3rem` with 0.5rem padding and 0.75rem gap, so the title starts at 10.25rem, while `.detail` is indented 9rem (`:309-316`). The block lines up with neither column. Inline and full-width items mix, so lines wrap unpredictably. JobRow (flex, `:205-211`) and its tracks use different padding, with no nesting indent |
| **No type scale, one breakpoint** | DESIGN.md §3 records sizes as ad hoc per component. The only breakpoint in the tree is `max-width: 640px`. DESIGN.md §8.1 records the "matte charcoal chassis" panel as never perceptible |

---

## Locked decisions for v4

| Area | Decision |
|---|---|
| Version numbers | Slices continue at **v32**; releases are `4.32.0`, `4.33.0`, … so a slice number never means two things. Patch slices (`vNN.1`) as in v3 |
| Production data | **No longer disposable.** No API backward-compatibility requirement, but any migration that drops or rewrites data must say so in its plan and take a `pg_backup` first |
| Dev database | A **dedicated `spotdlwebtest` database** on the same Postgres server, mandatory for every agent from v32 on. The owner has already created it (named **`spotdlwebtest`**, 2026-10-01) and pointed the local `.env` at it. The app's own `migrate` service builds the schema. Local dev must refuse to boot against the production database name |
| Alert channel | **A Matrix room** on the host's own Synapse, posted to by a dedicated bot account's access token. It is the single channel for both pipeline failures (v33) and app alerts (v36). Unconfigured means alerts are off; it never means an error |
| Alerts never block work | An alert that fails to send is logged and dropped. It never fails, delays or retries a download, a deploy step's *real* outcome, or a request |
| Rollback semantics | A rollback restores the **previous successful release's commit** (compose files, scripts) **and** its image tag together. "Previous" means the last deploy that passed health with `persist=true`, recorded durably, never whatever `.env` happens to say |
| Rollback across migrations | Not automatic. If the database is ahead of the rollback image's migrations, the pipeline stops, alerts, and points at the pre-deploy `pg_backup`, rather than starting a stack that can't come up |
| UI work | **Every UI slice goes through the impeccable skill**, using the sub-commands its plan names, with desktop and mobile screenshots as evidence. An audit slice (v39) precedes every redesign slice. A polish slice (v47) closes them |
| Information density | The redesign **keeps every piece of monitoring information** the owner asked for. It changes how the information is presented, never whether it is shown |
| Browser tests | A committed Playwright suite (v37), **run locally against the real dev stack**. No CI browser job: the self-hosted runner is the production host, which also runs Matrix/Synapse and Vaultwarden |
| Keyboard | Full mouse-free operation. Single-character shortcuts must be **turn-off-able** per user (WCAG 2.1.4) and inert while focus is in a text field. Every destructive shortcut goes through a confirmation. **Bindings target Hungarian QWERTZ first**: none needs AltGr, `Y`/`Z` are never bound, keys are matched on `event.key`, and symbol keys that need Shift on Hungarian are only aliases for a letter primary |
| i18n | **Hungarian and English, full coverage.** Locale resolution: saved per-user preference, then a pre-login choice, then auto-detect from `navigator.languages`, then `en`. A language switch on `/account` (persisted) and `/login`. The backend stays language-neutral: user-facing errors carry a stable `code` the frontend translates. Track metadata, raw attempt errors, Matrix alerts and logs aren't translated |
| Not planned | Whole-job zip download. The library flip from `/mnt/raid1/media/test` to `/mnt/raid1/media/music` with its 120k-track rehearsal. Both are the owner's explicit call to defer |

---

## The pipeline incident (transcribed, since the source notes stay untracked)

On 2026-09-27, v28 (PR #36) added a new **required** variable, `LIBRARY_DIR`, to
`docker-compose.prod.yml` through Compose's `${VAR:?message}` syntax. The design was deliberate:
fail loudly rather than deploy a broken mount. v28's first automated Publish & Deploy run
(`36329447126`, `2026-09-27T15:24:43Z`) failed at interpolation, because the host `.env` had no
`LIBRARY_DIR`. The **rollback failed identically**: it re-ran `docker compose up` in the new
checkout, against the same compose file, which needed the same missing variable. The run showed red
and notified nobody. v28 never deployed, and production kept serving the stale
`manual-fe6a30d` dispatch tag.

v29's merge (PR #37, run `36339232462`, `2026-09-27T18:03:36Z`) repeated the identical failure, and
its rollback reset `IMAGE_TAG` to `manual-fe6a30d` again. The owner then added `LIBRARY_DIR` by hand.
The visible error gave no reason to check `IMAGE_TAG` as well, so the stack came up on the old
image. That image predates v29's migration `e7c1f9a4d2b6`, and Alembic correctly refused to run.

**The general bug:** any version that adds a required `.env`/compose variable breaks its own deploy
*and* its own rollback, silently, and the last image keeps running unannounced. v33 fixes every
link in that chain.

Related, intentional, and **not** a bug: production `.env` has `LIBRARY_DIR=/mnt/raid1/media/test`
on purpose, to validate v28 before ever pointing it at the real ~120k-track library. That flip is
out of v4's scope.

---

## Version roadmap

Safety first, then correctness, then visibility, then UI. One feature per version, one
`dev-<feature>` branch, one PR.

| # | Branch | Scope |
|---|---|---|
| **v32** | `dev-dev-database` | **Mandatory first.** Move local dev onto the dedicated `spotdlwebtest` database (already created by the owner and wired into `.env`). Build the schema via the `migrate` service, add a guard that refuses to boot local dev against the production database name, rewrite the docs, and make the split a CLAUDE.md rule |
| **v33** | `dev-deploy-safety` | Fix the release pipeline end to end. Preflight required variables before touching the host. Make rollback restore the previous release's commit and tag together, with durable last-known-good. Guard migrations on rollback. Send Matrix notifications on any failure. Add a CI drift check between compose `:?` variables and `.env.example`. Workflows and docs only, so no version bump |
| **v34** | `dev-live-hydration` | Fix "Active signal" and incoming jobs disappearing on refresh. Reproduce, then hydrate both from REST on every reload and stream (re)connect, in one bulk request each, owner-scoped |
| **v35** | `dev-correctness-sweep` | Bounded debt, each item with its own commit and bullet: consistent attempt counting and numbering; `network_path`, proxy, error type and duration exposed in the attempts API; the redelivery guard for completed tracks; a warning-vs-failure flag on attempt messages; a streamed file download instead of a blob; image `.pyc` hygiene; live counts for the tracks-scope state filter |
| **v36** | `dev-alerting` | Matrix alerts from the app: breaker trips, failure-class spikes (an early warning that YouTube has changed something), a stale beat heartbeat, and the library sweep's outcome. Per-category cooldown, admin toggles, a test-alert button, every message redacted |
| **v37** | `dev-e2e-harness` | A committed Playwright suite against the local stack. It covers the baseline flows the redesign must not break, including a two-identity cross-user UI check. Runs locally only |
| **v38** | `dev-moved-file-dedup` | *(Inserted 2026-10-10, see Amendments.)* A resubmitted track whose file the library sort has moved must resolve as a duplicate, never re-download, and stay downloadable to disk from its library path. `worker-dl` gets the library mount read-only, and dedup fails safe when a root looks unmounted |
| **v39** | `dev-ui-audit` | An impeccable `critique` + `audit` of every route and component, desktop and mobile. Produces `v39-ui-audit-report.md`, with ranked findings each assigned to a later slice. No component changes |
| **v40** | `dev-ambient-field` | A cursor-following blurred glow replacing the static gradient. GPU-only and rAF-eased, with an idle drift for touch, static under reduced motion, paused when the tab is hidden. Reconciled with DESIGN.md's amber rule |
| **v41** | `dev-track-detail-redesign` | Restructure the job and track expanded detail through impeccable. Same information, calmer presentation: a summary strip, an aligned grid, one action area, an attempt timeline with collapsed repeats, clamped long errors, and warnings distinct from failures |
| **v42** | `dev-dashboard-redesign` | The rest of `/`: header, submit bar, incoming, Waterfall, queue controls, job list, empty/loading/error states. Adds a real type scale, a perceptible panel material, and a tablet breakpoint |
| **v43** | `dev-secondary-surfaces` | `/settings`, `/library`, `/account`, `/login` in the same system, plus the confirmation affordances for destructive actions |
| **v44** | `dev-admin-stats` | A new admin observability page: success rate per network path and per proxy, failure classes over time, breaker-trip history, queue depth. Server-side aggregation, designed through impeccable plus dataviz |
| **v45** | `dev-keyboard-navigation` | Complete mouse-free operation on the final markup: a shortcut registry and help overlay, roving list navigation, row actions, route chords, a skip link, focus restoration, confirmations, and a per-user off switch. **Bindings designed for Hungarian QWERTZ** (no AltGr, no `Y`/`Z`, `event.key` matching) |
| **v46** | `dev-i18n` | Full Hungarian + English i18n: auto-detected locale, a per-user language switch, every string translated (including v45's help overlay), `Intl` formatting and Hungarian plurals, stable error `code`s from the backend |
| **v47** | `dev-ui-polish` | Impeccable `polish` + `harden`, re-run `audit` and score it against v39's report, then regenerate DESIGN.md from the shipped UI with `impeccable document` |
| **v48** | `dev-v4-hardening` | The production close: the cross-user sweep over v4's new surfaces, full real-stack and production verification, closing or re-deferring v31's open questions, doc reconciliation, and a re-read of every "Done when" bullet |

### Why this order

- **v32 first**, because every later slice runs real tests, and none of them should be able to
  touch production rows.
- **v33 before anything else ships.** Every later release goes through that pipeline, and v36
  adds new optional environment variables, the exact class of change that broke it.
- **v34–v35 before the redesign.** The redesign renders this data, so it should render correct
  data: a counter that matches the history, a network path that exists in the API, and a
  warning flag. Designing around a known-wrong "passes attempted: 0" would bake the bug into the
  new layout.
- **v36 next to v33**, because both share the Matrix channel. v44's breaker history reuses v36's
  trip hook.
- **v37 before any UI change**, so v40–v47 have a regression net instead of a by-eye check.
- **v38 right after v37**, because it restores a master-v3 invariant (a move never causes a
  re-download), and every day it waits is real rate-limit exposure. v37's suite is its regression
  net.
- **v39 audits before v40–v43 redesign**, so redesign scope is evidence-led, and v47 has a
  baseline to score against.
- **v44 after the redesign**, so the new page is born in the new system rather than restyled later.
- **v45 after every surface is final**, so shortcuts and focus management bind to markup that
  won't move under them.
- **v46 i18n after every UI slice and before polish.** It translates final strings (including
  v45's help overlay), and v47 then polishes against real Hungarian strings, which run longer
  than English.
- **v47 polish, then v48 close**, the same role v13, v22 and v31 played.

---

## Critical interactions to design around

- **v32 vs every later version's testing.** After v32, a local run that touches the production
  database is a bug, not a convenience. The guard must fail closed: if it can't tell, it refuses.
- **v33 vs v36.** v36 adds `MATRIX_*` variables. They must be *optional* (no `:?`), so v36 is the
  first real test of v33's preflight in the safe direction: preflight should pass, not block.
- **v34 vs the multi-user invariant.** Hydrating `liveActive`/`incoming` from REST is a new read
  path, and therefore a new chance to drop the owner filter. Admin all-users scope must be
  hydrated under the same scope switch `queue.setAllUsers` already performs. `queue.reset()` must
  clear whatever v34 adds (the v22 store-reset invariant).
- **v35's attempt-count change vs the retry ladder.** The ladder step is derived from failures.
  Whatever "attempts" comes to mean in the UI, the ladder's own input must not shift by one, or
  every waiting track's next retry moves.
- **v35's streamed download vs v27's error surface.** A plain navigation to
  `/api/tracks/{id}/file` can't show the existing inline error notice on a 404. The design must
  keep a visible error for a missing file.
- **v36 vs `proxies.redact()`.** Alert bodies quote errors, and spotdl's errors echo proxy
  credentials. Every message goes through `redact()` before it leaves the process. The same
  applies to the deploy notification, which must never echo `.env`.
- **v40 vs DESIGN.md's amber exclusivity.** A cursor glow is permanent chrome. It either stops
  being amber at rest, or the rule changes in DESIGN.md. It must not silently break the rule.
- **v41–v43 vs v37.** The redesign changes markup that the e2e selectors depend on. Selectors
  should target roles and accessible names, not CSS classes, so a restyle doesn't rewrite the
  suite.
- **v45 vs screen readers and the browser.** Single-key shortcuts conflict with assistive
  technology and with typing. They must be inert in inputs, `contenteditable` and `select`,
  must not shadow browser chords, and must be off-switchable. On Hungarian QWERTZ, AltGr arrives as
  Ctrl+Alt on Windows. A shortcut must never fire while a user types `@`, `{` or `\` via AltGr.
- **v46 vs v37/v45.** Accessible names are translated text. The e2e baseline pins `en-US`, so v46
  adds a `hu` project rather than rewriting the specs. v45's help overlay is generated from the
  registry, so its descriptions become message keys, not literals.
- **v46 vs the backend.** Translating by `detail` text would break on any wording change. Errors
  get an additive `code`, and the frontend falls back to `detail` for unknown codes.
- **v44 vs the bulk-request invariant.** Stats are aggregated in SQL in one request. No per-proxy
  or per-day request loop.

---

## Critical files

- **Dev DB**: `.env.dev.example`, `docker-compose.override.yml`, `backend/app/config.py`,
  `docs/LOCAL_DEV.md`, `CLAUDE.md` ("Development environments")
- **Pipeline**: `.github/workflows/publish-deploy.yml`, `.github/workflows/release.yml`,
  `.github/workflows/ci.yml` (`compose-config`), `.github/scripts/wait_for_stack_health.sh`,
  `docker-compose.prod.yml`, `.env.example`, `.gitignore`, `docs/RELEASE_PIPELINE.md`,
  `docs/DEPLOYMENT.md`
- **Live view**: `frontend/src/lib/stores/queue.ts` (`reload`, `liveActive`, `incoming`, `reset`,
  `setAllUsers`), `frontend/src/routes/+page.svelte` (`connectStream`),
  `backend/app/routers/jobs.py` / `tracks.py` (list filters)
- **Attempts / download**: `backend/app/tasks/download.py`, `backend/app/services/retry.py`,
  `backend/app/models/track_attempt.py`, `backend/app/services/serializers.py`,
  `frontend/src/lib/api.ts`
- **Alerting / stats**: new `backend/app/services/alerts.py`, `backend/app/tasks/beat.py`,
  `backend/app/services/retry.py` (trip point), `backend/app/services/app_settings.py`,
  `backend/app/routers/settings.py`
- **i18n**: new `frontend/messages/{en,hu}.json`, `frontend/src/app.html` (`lang`), `frontend/src/lib/api.ts`
  (`ApiError` + `code`), the backend routers' `HTTPException`s, `backend/app/services/users.py` (preference)
- **UI**: `frontend/src/app.css`, `frontend/src/DESIGN.md`, `PRODUCT.md`,
  `frontend/src/lib/components/*.svelte`, `frontend/src/routes/**/+page.svelte`,
  `frontend/nginx.conf` (any new route)

Reuse rather than rewrite: `app_settings`'s singleton get-or-create; `proxies.redact()`;
`serializers.*_to_dict`; `events.publish_*_event` (owner is a required argument); the
`RUN_DISK_RECONCILE`/`RUN_PROXY_SYNC` boot-hook gating convention; `scripts/pg_backup.sh`;
`scripts/verify_separation_sse.sh`; `.github/scripts/wait_for_stack_health.sh`; the app.css token
set and `design-tokens.json`.

---

## Verification

Every version keeps the standing rules: the real `docker compose` stack, real Postgres (the **dev**
database from v32), the real network, and each "Done when" bullet evidenced individually this
session. Version-specific requirements:

1. **v32 proves isolation by observation.** A row created locally must be absent from production
   (checked with a read-only query). A local `worker-meta` restart must log that it reconciled
   against the dev ledger. The guard must be shown refusing a production `DATABASE_URL`.
2. **v33 proves each failure mode on the real runner,** not by reading YAML. Use a throwaway
   required variable to show preflight blocks it, and a forced health failure to show rollback
   restores the previous commit *and* tag. A real Matrix message must arrive.
3. **v34 is verified with a hard reload in a real browser** for every shape: an expanding job, a
   failed-zero-track job, a downloading track, and the admin all-users scope.
4. **v35's network-path exposure is checked against a real attempt row** written by a real
   download, not a fixture.
5. **v36 fires every alert category for real** on the dev stack into a real Matrix room, and shows
   cooldown suppressing a repeat.
6. **v39–v47 are evidenced with impeccable's own output** (critique scores, audit findings) plus
   desktop and mobile screenshots. The v37 suite must stay green.
7. **v45 is verified by completing every user journey without touching the mouse**, recorded as a
   keyboard-only e2e test, with the shortcut off-switch shown working. Hungarian QWERTZ is covered
   by emulated key events plus one manual pass on a real Hungarian layout.
8. **v46 is verified in both languages**: auto-detect from three browser locales, a preference
   persisting across devices, and every route screenshotted in Hungarian.
9. **v48 re-runs the cross-user sweep** (`pytest backend/tests/test_ownership.py` plus
   `scripts/verify_separation_sse.sh`). v34, v35 and v44 add read paths, and v45 and v46 add per-user preferences.
10. **`graphify update .`** after every code-modifying version. The version is bumped in both
   `backend/pyproject.toml` and `frontend/package.json` to the identical `4.NN.0` string, except
   for a slice that touches neither `backend/` nor `frontend/` (v33), which needs no bump.

---

## Amendments

The plan above is the approved text, kept verbatim. Changes directed after approval are recorded
here rather than edited into it, so the original record stays readable.

- **2026-10-01, v32: production database name.** The plan names production's database
  `spotdl_web`, but the real one on the shared server is **`spotdlweb`** (role `spotdlweb`, which
  also owns `spotdlwebtest`); `spotdl_web` is only what `.env.example` and `docs/DEPLOYMENT.md`
  document. On the owner's direction, the dev guard refuses **both** names
  (`PRODUCTION_DATABASE_NAMES` in `backend/app/config.py`). Wherever a later plan says "production's
  `spotdl_web`", read `spotdlweb`.
- **2026-10-01, v33.1 (inserted after v33 merged, owner-directed): two v33 follow-ups.** Workflows and
  docs only, no bump, branch `dev-v33-followup`. (1) A configured Matrix send that fails is a
  warning, not a red run: Synapse shares the host and the Cloudflare zone with the runner and the
  app, so an alert outage is never isolated. (2) The owner left the rollback-after-a-migrating-
  dispatch case to the implementer, with "avoid downtime" as the goal: when the database is ahead
  of `.last-good`, the rollback now falls back to the pre-deploy commit + tag if that knows the
  schema. `.last-good` semantics (Task 3) are unchanged. CLAUDE.md's Rollback locked decision was
  edited to match.
- **2026-10-02, v34.1 + v34.2 (inserted after v34 merged, owner-directed): close every v34
  "Found, not fixed" item now rather than defer it.** Two patch slices, in order.
  **v34.1** (`dev-expansion-fixes`, `4.34.1`, backend): a job cancelled during expansion stays
  `cancelled` (the failure path used to overwrite it with `failed`); a readable error for a
  Spotify link that doesn't exist (v34's "artist expansion is broken" was a wrong test id that
  Spotify itself 404s; real discographies expand fine); long expansions get their own `expand`
  queue and a new `worker-expand` service (owner-approved, `--autoscale=2,1` for a bursty
  workload), since two concurrent discographies were measured to starve beat's 30s dispatch on
  `worker-meta`; Celery's Redis `visibility_timeout` 1h → 6h (owner-approved) so a >1h task isn't
  redelivered and run twice. **v34.2** (`4.34.2`, frontend/dev/CI): live progress kept across a
  refresh via localStorage (owner's design; progress is never stored server-side), the Vite dev
  proxy closing dead SSE streams, the double `reload()` on load/scope switch, filter changes no
  longer re-hydrating, the "3 of 2" count, the dev `STALE_TRACK_AFTER_SECONDS` default, and
  `npm run test:unit` in CI.
- **2026-10-10, v37: admin gating answers 403, not 404.** Spec 6 says a non-admin's admin API
  calls "return 404", but `require_admin` has answered 403 since v22 (whose plan pinned "expect
  403", with 18 backend assertions agreeing). The 404-not-403 rule covers a non-owner's direct-id
  access, not admin endpoints. On the owner's direction the spec asserts 403, and no backend
  change was made.
- **2026-10-10, v38 inserted (owner-directed): moved-file dedup.** v37 found that `worker-dl`
  mounts only `/downloads`, so `dedup.is_already_downloaded` can't see a file v28's sort moved
  into the library, and a resubmitted moved track downloads again. The owner directed a fix slice
  as the next version, with every later slice renumbered by one rather than a `v37.1` patch:
  the old v38–v47 are now **v39–v48** (files renamed, every reference shifted, releases
  `4.39.0`–`4.48.0`). Required behavior: no re-download for the same or another user, and the
  file stays downloadable to disk from its library path. Detail in `v38-moved-file-dedup.md`.
- **2026-10-12, v39 outcome (owner decisions on PR #56).** Answers to the four questions at the end
  of `v39-ui-audit-report.md`:
  1. **Direction: refinement** ("Keep the design for now"). v40–v43 keep the signal-receiver world,
     the IBM Plex pairing and the state-color semantics, and fix the leaks the report lists. No
     slice replaces the visual world. Narrowing mono to data and state tokens (F12, a DESIGN.md §3
     rule change) was approved along with the direction.
  2. **v39.1 inserted: the F01 mobile JobRow fix ships now** ("it shouldn't be pushed to get
     forgotten"), as its own patch slice, `dev-mobile-jobrow-fix`, `4.39.1`, rather than waiting for
     v41's redesign. Scope: the two-cause layout fix (the toggle's `16rem` basis and the bar's `100%`
     basis inside the ≤640px column stack), a mobile e2e regression check, and DESIGN.md's stale
     "confirmed at 390px" claim corrected with a dated note. v41 still redesigns the ≤640 stack.
  3. **Operator detail is admin-only** ("keep it simple for everyone who's not me"). Today every
     user sees operator-level monitoring: the worker/breaker status pill, the full state-filter and
     sort set, and per-attempt diagnostics (network path, proxy, raw error text, attempt history).
     From v41 on, that detail is shown only to the admin. Non-admins get a deliberately simpler view
     of their own jobs and tracks, still honest about state (waiting, next retry, done, not found).
     v41 (track/job detail) and v42 (header, Waterfall, QueueControls) design that simpler view
     through impeccable, and every monitoring capability stays for the admin. This is presentation
     gating on top of the existing data separation, not a new data surface: anything a non-admin
     still sees stays owner-scoped as today, and the admin-only parts must be absent from their DOM,
     not merely hidden with CSS.
  4. Writing the five surface briefs under v39 task 1 (and the resulting `4.39.0` bump) was the
     intended reading of the plan.

  5. **A2–A6 accepted** (2026-10-13, "Yes please defer all & update the docs"). Each is now written
     into its target slice's plan, so the implementer applies it without asking again:
     - **A2 → v42:** the contrast tokens (F09). `--text-dim` reaches 4.5:1 on every background,
       `--line` control borders reach 3:1 (WCAG 1.4.11), and `--signal-dim` is never used as text.
     - **A3 → v42:** the offline/reconnecting state (F05) and status honesty (F04: the Waterfall and
       header never read "idle" while tracks wait behind the breaker) are *designed* in v42. v47
       still hardens them.
     - **A4 → v43:** the confirmation list adds "release now" (breaker) and worker pause.
     - **A5 → v40:** v40's amber decision covers all chrome (F10's list), not only the body glow.
       v42 and v43 apply that one rule.
     - **A6 → v48:** F34 (the sweep error log's duplicate rows, and the sweep silently archiving
       every user's settled jobs) becomes an explicit v48 task, an exception to v48's "no fixes
       outside v4 changes" rule, since it is v28 behavior.

- **2026-10-12, v39.2 inserted (recorded retroactively on 2026-10-13): swallowed-error
  classification.** The owner ran this patch slice in another session, so it never got an entry
  here. Branch `dev-swallowed-error-classification`, `4.39.2`, PR #57, stacked on v39.1 and merged
  2026-10-12. It had no plan file; the PR body is its record. A production Scooter discography left
  19 tracks `waiting` with "spotdl returned no output file", and they tripped the breaker.
  spotdl's `search_and_download` swallows every exception. `download_one` now captures the
  swallowed one from the song tracker's `notify_error`: a search miss becomes `LookupError` and a
  yt-dlp age gate becomes `AgeRestrictedError`, both terminal `lookup_failed`; anything else stays
  a `NoOutputFileError` carrying the real reason. Owner-accepted tradeoff: a search miss is
  terminal on every rung, the proxy rung included. **It was incomplete**, see v40.1.
- **2026-10-13, v40.1 inserted (owner-directed): breaker wedge fix.** Production on `4.40.0` still
  had 16 tracks `waiting` and the breaker re-tripping at 6h after every release, blocking every
  user. v39.2's classification was right but mostly unreachable:
  - the breaker's streak only reset on a success, so one failure per release re-tripped it;
  - every enabled proxy was dead, and its `ProxyError` became a breaker-feeding `no_output`, so
    proxy-rung tracks never reached a verdict;
  - a terminal verdict through a proxy was charged to that proxy.

  Owner decisions:
  - **Fresh breaker streak per trip and on manual release.** Escalation still resets only on a
    success. CLAUDE.md's "Retry engine numbers" were edited to match.
  - **Hard failures** (age gate, no match, unavailable video) **stay terminal with no retry
    attention.** Fetching them by other means is out of scope.

  Branch `dev-breaker-wedge-fix`, `4.40.1`, between v40 and v41. Detail in
  `v40.1-breaker-wedge-fix.md`.
- **2026-10-14, v40.2 inserted (owner-directed): live desync fix.** Found while verifying v40.1
  on production. A job read `done — partial`, but the Waterfall kept its `lookup_failed` lanes for
  up to a minute (v23's grace window), and the state chips still counted it "active" until a hard
  reload (a refreshed row never moved its chip count). Frontend only. Branch
  `dev-live-desync-fix`, `4.40.2`, between v40.1 and v41. Detail in `v40.2-live-desync-fix.md`.
- **2026-10-15, v42: A2's tree-wide contrast claim, one remainder moved to v43.** v42's token
  change clears every token-caused `color-contrast` node on every route (axe-core 4.10.2: `/` in
  all its states, `/login`, `/account`, `/library` and a non-admin `/settings` report none). One
  route keeps 20 nodes that no token causes: the admin `/settings` proxy list dims a disabled
  proxy row with `opacity: 0.6`. Fixing it means designing that row's disabled state on a v43
  surface, so it moves to v43 with the rest of `/settings`. Likewise the `/settings` and
  `WorkerStatus` state toggles' `--fail-dim`/`--settled-dim` edges (F30's controls) stay v43's;
  v42 gave `/`'s destructive outlines a new ≥3:1 `--fail-edge`.
- **2026-10-16, v43: one v39 item deferred, four backend gaps found.** F20's "no cancel" for a
  running library sweep needs a backend cancel endpoint (the sweep is one Celery task with no
  stop signal), so it is deferred, not built in a UI slice. Found while hardening v43's
  confirmations, none fixed there (backend, outside the slice; candidates for v48's close):
  `cancel_job` sets CANCELLED unconditionally, so a job that finished between the UI's re-read
  and the DELETE is relabelled; there is no single-track GET (the UI re-reads a job's cancellable
  tracks, capped at 1000); a manual proxy any attempt used can't be deleted (the
  `track_attempts.proxy_id` / `tracks.used_proxy_id` foreign keys have no ON DELETE, so it's a
  500); and `retention_days` has no upper bound (a huge value overflows the hourly retention
  sweep for every user; `/account` now caps it at 36,500 days client-side).
- **2026-10-17, v44: owner decisions and one deliberate exception to v37's 403.**
  - `GET /api/admin/stats` answers a non-admin **404**, as v44's plan says ("non-admin gets 404
    (not 403)"), through its own dependency (`routers/admin.py`'s `require_admin_hidden`,
    indistinguishable from an unknown route). Every other admin endpoint keeps `require_admin`'s
    403 (the v37 amendment). Unauthenticated stays 401.
  - Owner's choices in the impeccable direction probe: the page is a **"now | over window"**
    split; **success rate = completed ÷ (completed + failed)**, "not found" counted apart; day
    buckets follow the **viewer's local day** (the page sends `utc_offset_minutes`; one offset per
    request, so across a DST change older buckets are an hour off).
  - The stats payload carries the current breaker state (`breaker.current`), so the page needs no
    second request. Releases are recorded by beat's tick on an expired pause, which now clears
    `breaker_tripped_until` (NULL and expired already read the same everywhere).
  - Owner's answers on the PR: **one connection target, one credential**: the API refuses a
    second proxy for a `host:port` already present (409), and `proxies.txt` sync skips one and
    rotates a changed credential into the existing row (folded into v44 at the owner's request,
    since it closes the identical-labels question `/stats` raised). The window covering whole
    buckets up to the current partial one ("Last 7 days" at 00:05 is 6 days and 5 minutes) stays,
    recorded in `docs/GOTCHAS.md`.
- **2026-10-18, v45: owner decisions, and one plan sentence the code doesn't bear out.**
  - **Row controls are in the Tab order only on the current, open row** (owner's choice). A
    collapsed list is exactly one Tab stop; Enter opens a job and Tab then walks its priority,
    bump, cancel or archive, its track list (one more stop) and "load more tracks", the same
    model the plan gives a track's detail actions.
  - **`e` toggles the repeats** (owner's choice). An admin's open track keeps showing its history
    as v41 designed; `e` opens a closed track, then shows every collapsed repeat, or hides them all.
    It is admin-only, since non-admins have no history. The owner also asked for a findable
    shortcut map: the plan's `h` overlay is that map, and `/account`'s new switch has a "show
    shortcuts" button next to it.
  - **"A row removed by cancel or an SSE filter update" doesn't happen in the current store.**
    `patchPageJob` and the tracks-scope patch update a row that stops matching the filter in place
    and never drop it (a cancelled job stays under a "waiting" chip until the next reload). Only
    archive, with archived jobs hidden, removes a row. `lists.ts` handles any removal, and spec 14
    evidences it with archive (next row, and the previous row when the last one goes). Cancel is
    evidenced as "focus stays on the cancelled row". Making the store drop non-matching rows is a
    store behavior change outside v45, and is left for the owner to decide. The owner's answer
    (same day): keep it as is for now.
  - **A `<select>` is not a typing target** (owner's review of PR #66). The plan lists `select`
    among the inert targets, but on the sort select that made `h`, `1`/`2` and the rest dead until
    Tab moved focus on. The shortcuts now work on a select; its own keys (arrows, Home/End, Page
    keys, Enter, Space) stay with it; only a bound letter stops picking an option by its letter. Text inputs,
    textareas and `contenteditable` stay inert as the plan says.
- **2026-10-18, v46: owner's answers on PR #68 change the locale rule and add a time format.**
  - **The browser decides the language until sign-in.** Detection is automatic; signed in, a
    language the user saved on `/account` overrides it, and signed out the browser decides again
    (a user preferring English on a Hungarian browser sees Hungarian on `/login`, English once
    signed in). This replaces the plan's step 2 ("a `localStorage` choice made on `/login`") and
    its "compact equivalent on `/login` … adopted into the profile on first login": there is no
    `/login` switch, nothing is stored in the browser, and nothing is adopted at sign-in. The
    Done-when bullet "The `/login` choice before login is honored, and adopted into a profile that
    has none" is superseded by this rule (spec 16 tests the rule instead).
  - **Formats keep the browser's region, plus a per-user time format.** Dates and numbers use the
    interface language with the browser's region (English on a Hungarian browser: 24-hour,
    "12 345"), not the bare language's conventions. `/account` gains a Time format setting
    (automatic / 12-hour / 24-hour, `user_settings.clock`, additive), by the same rules: the
    browser's region until sign-in, a pinned format after.
  - **Follow-up answers (2026-10-19):** the language also gets an "automatic" choice on
    `/account` (a saved language can be cleared, and the browser decides again); and the region
    keeps coming from the browser's *first* language tag even when the matched language is later
    in the list (owner: "if a user has that funky setting it probably wants that behaviour").

- **2026-10-19, v47: owner decisions taken during the polish pass.**
  - **DESIGN.md is refreshed in place**, not converted to impeccable's 8-section spec: the 9-section
    layout stays, with YAML token frontmatter added, prior decision records kept and dated v47
    notes where a rule changed meaning.
  - **Control labels move to Sans tree-wide** (v42's deferral of F12's last step), with in-world
    exceptions the owner chose: the console SUBMIT beside the `>` prompt, value choices (24h/7d,
    mp3), keycaps and counts stay mono.
  - **A 401 ends the session in one place:** the tab goes to `/login`, which says the session
    ended; a 5xx or network failure of `/api/auth/me` no longer signs anyone out (a "can't reach
    the server" screen retries instead).
  - **Priority and bump are admin-only** (operator detail, like v39 outcome 3); a non-admin's
    in-flight job offers cancel only. This is presentation only: v47 makes no backend change,
    so `PATCH /api/jobs/{id}/priority` and `POST /api/jobs/{id}/bump` still accept a job's
    owner. Enforcing it server-side is logged for v48 (or a later backend slice). Not chosen, so left as they are: "duplicate" → "already
    have", "disconnect" → "sign out", and reordering `/account`'s preferences.

- **2026-10-19, v48: owner decisions on F34 (task 7), and what the close found.**
  - **A library sweep archives only the sweeping admin's own settled jobs** (owner's choice over
    "keep it and show the count"). Every user's moved tracks are still repointed; another user's
    job stays unarchived for that user and their retention. The `/library` confirmation (en + hu)
    says so. CLAUDE.md records it under the v4 decisions.
  - **Ledger rows sharing a moved file follow it** (owner's choice over "deduplicate the log
    only"). The sweep groups the ledger by source file, repoints every row on a file in one commit
    before the source is touched, and reports per file, so a path appears once in the error log.
  - **Found, not fixed in v48** (pending the owner): production holds 47 ledger rows stranded by
    pre-v48 sweeps (each has a same-named sibling already in the library); the 2026-10-18 breaker
    trip produced no Matrix alert and can't be root-caused (logs gone); 4.40.2 never deployed and
    its `notify` died with it on a GitHub 429. The backend gaps v43/v47 logged for "v48's close"
    (unconditional `cancel_job`, no single-track GET, used-proxy delete 500, unbounded
    `retention_days`, server-side priority/bump) aren't v4 regressions, so they stay logged for a
    future master, per v48's "Out of scope".
