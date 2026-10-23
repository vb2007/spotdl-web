# Implementation prompt template (master v5, parallel agents)

Copy everything below the line into a fresh implementation session, one session per slice.
**Change only the `VERSION` line.** Everything else derives from it, including the slot. Up to
four sessions run at once, one per slot of the current wave (see
`plan/master-v5/00-master-plan.md`, "Waves").

---

```
VERSION: v49
```

You are implementing **exactly one** spotdl-web version slice: the one named on the `VERSION`
line above. **Up to three other agents are implementing other slices of the same wave at the same
time**, on the same machine, against the same GitHub repo. Everything below exists so you don't
collide with them.

Everything you need derives from `VERSION`:

- **Plan file:** the single file matching `plan/master-v5/<VERSION>-*.md`. Read it in full first.
- **Branch / Version / Wave / slot / Depends on:** that file's header lines. The slot (1–4) picks
  your ports, compose project and database.
- **Roadmap context:** `plan/master-v5/00-master-plan.md`. Read its Locked decisions, Parallel
  execution model (slots, waves, **rebase protocol**), Critical interactions, the ledger rows your
  slice owns, and Amendments.

## 0. Rules

- **Read `CLAUDE.md` first and follow every rule in it.** Where this prompt and CLAUDE.md
  disagree, CLAUDE.md wins. Stop and say so.
- **Preconditions.** Every slice of earlier waves, and everything in your "Depends on", must
  already be merged into `origin/main`. Check `git log origin/main` and the PR list. If not,
  **stop and ask**.
- **A clean pipeline is a precondition too** (from v51 on). The latest "Release & Deploy" run on
  `main` must be green, and no Release or Publish & Deploy run was created beside it (`gh run list
  --branch main -L 10`). If not, **stop and tell the owner**. v50 runs alongside v49, so it checks
  this when it rebases onto merged v49, and records v49's own merge run in its PR: the checks ran,
  and no other run was created.
- **Implement this version's plan only.** Don't start another slice. Don't fold in adjacent fixes
  or "while I'm here" improvements. Log them in the PR under "Found, not fixed".
- **Stay inside your plan's "Files owned" list.** Another agent owns the rest of this wave's files.
  - If you genuinely need to edit a file you don't own, keep the edit minimal and delimited, and
    explain it in the PR ("touched outside Files owned: why").
  - If it's more than a few lines, stop and ask.
  - The shared hotspots (`frontend/messages/{en,hu}.json`, `docs/GOTCHAS.md`, `graphify-out/`, the
    Alembic head, `CLAUDE.md`) may be edited by anyone and are reconciled by the rebase protocol.
- If the plan contradicts itself or the real code, **apply the plan literally, document the
  conflict in the PR, and ask.** If a precondition isn't met, **stop and ask**. Don't work around
  it.

## 1. Context: graphify first, strictly

- Gather context **with graphify, not exploration agents or blind grepping**:
  `graphify query "<question>"`, `graphify path "<A>" "<B>"`, `graphify explain "<concept>"`.
  Use `graphify-out/wiki/index.md` for broad navigation if it exists, and `GRAPH_REPORT.md` only
  when those aren't enough. Grep only after graphify has oriented you, or to edit specific lines.
  Any subagent prompt you write involving code exploration must include this rule.
- Read the relevant `docs/GOTCHAS.md` sections **via its topic index**, never end to end. Verify a
  file or function a gotcha names still exists before acting on it.
- Read the last merged PR touching your area (`gh pr list --state merged`, `gh pr view <n>`) to
  match how changes there were structured and evidenced.

## 2. Your own worktree

**Never work in the shared main checkout** (`/home/vb2007/code/spotdl-web`): other sessions use
it. Create your own worktree:

```
cd /home/vb2007/code/spotdl-web
git fetch origin
git worktree add -b <Branch> /home/vb2007/code/spotdl-web-wt/<Branch> origin/main
cd /home/vb2007/code/spotdl-web-wt/<Branch>
```

- Copy the main checkout's `.env` into the worktree as your base (`cp ../../spotdl-web/.env .`).
  `scripts/agent_stack.sh` derives the slot-specific `.env.agent` from it. **Never** put a
  production value in either file.
- Before every commit: `git branch --show-current` must print your branch. Never `git stash` (it's
  shared across worktrees of one repo).

## 3. Your own development stack

**Wave 0 runs before the slot tooling exists.**
- **v49 runs no local stack at all.** It changes only `.github/` and docs and verifies on the
  self-hosted runner, through the scratch branch its plan describes. Don't start any compose stack,
  since v50 needs the default ports.
- **v50** uses the default dev stack (`docker compose up`, ports 8000/5173, the owner's LAN
  `spotdlwebtest`). It's the only stack running in wave 0.

**Every slice from v51 on** brings up **its own** stack. It never uses the default stack, the LAN
`spotdlwebtest`, or another slot's stack:

```
scripts/agent_stack.sh <slot> env      # writes .env.agent: project spotdlweb-s<slot>, ports 800<slot>/517<3+slot>, local Postgres
scripts/agent_stack.sh <slot> up       # builds and starts it; migrate builds your local DB
scripts/agent_stack.sh <slot> ps|logs|psql
```

- **Your database is the local Postgres container in your compose project** (owner decision). You
  create, migrate, reset (`down --volumes`) and seed it yourself. It isn't shared with anyone.
- **`worker-dl` is off by default.** Most verification uses tracks already present (dedup
  resolves them instantly), seeded data, or mocked spotdl at the unit level. When a Done-when
  bullet genuinely needs **real YouTube traffic**, wrap that step:
  `scripts/agent_stack.sh <slot> realdl <command>`. It takes the host-wide lock
  `/tmp/spotdl-web-realdl.lock`, so only one agent ever talks to YouTube at a time; if another
  slot holds it, wait and retry. Never bypass the lock, and never start `worker-dl` by hand.
- **Logins:** test identities only, never the real `ADMIN_EMAIL` account. At least one identity
  logs in through the **real upstream** `vb2007.hu-api` (local `host.docker.internal:3000` if
  running, else `https://api.vb2007.hu`; register per-slot accounts such as
  `v5s<slot>admin@…`/`v5s<slot>user@…` freely). Use the direct-session-mint fallback only if
  neither is reachable, and say so explicitly.
- **Matrix:** alerts stay unconfigured in your stack unless your plan needs them (v59). Then use
  the dev room named in the plan, never production's.
- **Minimize SSH to the production host.** It runs other real services. Develop and verify on your
  stack. When a host action is genuinely needed, batch it into as few round trips as possible.
- **At the end** (after the PR is open and CI is green): `scripts/agent_stack.sh <slot> down`.
  Keep the volume until the PR merges, in case the owner asks for a re-check. Remove the worktree
  only after merge, or when the owner says so.

## 4. Implement, committing as you go

- Small logical steps, **each its own commit**, with a traceable message
  `<VERSION>: <what this step does>`. For multi-item slices use the plan's labels
  (`v56: (E2) reclaim UPDATE re-checks state`). Never one squash commit.
- Follow the surrounding code's style. Reuse the helpers the master plan's "Reuse rather than
  rewrite" list names.
- Keep every CLAUDE.md invariant: no Celery `eta`/`countdown`; `worker-dl --concurrency=1`;
  `_ensure_spotify_client()`; `proxies.redact()`/`redact_text` on everything logged or persisted;
  `values_callable` plus `DROP TYPE` for enums; SvelteKit exports **and** an nginx `location` per
  route; `!override` for compose lists; no per-row request loops; owner-scoped queries with 404
  for non-owners; and `queue.reset()` covering any new store state.
- **UI (any slice touching a user-visible surface): use the impeccable skill, strictly.** Load it,
  run its Setup (`context.mjs`), and use the sub-commands the plan names. Record each one's output
  in the PR. Capture desktop **and** mobile screenshots before and after, from real data on your
  stack. Load the dataviz skill before any chart.
- **Keyboard:** every new interactive element is keyboard-reachable. Bindings follow **Hungarian
  QWERTZ** rules: nothing needs AltGr, `Y`/`Z` are never bound, match on `event.key`, and AltGr
  (Ctrl+Alt on Windows) never fires a shortcut. Register any key in the shortcut registry, so the
  help overlay shows it.
- **Strings:** every new user-visible string goes into **both** `en` and `hu` message files (the
  extension: both `_locales`), never a literal. Every new user-facing backend error gets a stable
  `code`.
- **Network path, proxy or IP family changes:** verify the **real connection destination**
  (`socket.socket.connect` observation or tcpdump), never trust a flag.
- **Migrations:** each says in its docstring whether it rewrites data. A data rewrite needs a
  `pg_backup` note under Deploy notes. Run `upgrade` → `downgrade -1` → `upgrade` on your slot DB.

## 5. Version bump

- App slices: set `backend/pyproject.toml` and `frontend/package.json` to the **identical** version
  from the plan header. Bump **both**, even if only one side changed. Then run `uv lock` in
  `backend/` and commit it as `<VERSION>: sync uv.lock with the version bump to <version>`.
- Slices whose header says "no bump" (they touch neither `backend/` nor `frontend/`) don't bump the
  app. Extension slices bump `extension/manifest.json` as their plan says.
- `python3 .github/scripts/check_version.py origin/main` must pass locally. From v50 on it also
  requires the version to be **strictly greater** than `main`'s.

## 6. Checks, all of them, against your own stack

Run every applicable one, and paste the summarized output into the PR.

- **Backend:** `pytest`, the full suite. From v51 on it runs against Postgres: use
  `scripts/agent_stack.sh <slot> pytest`. Run the cross-user sweep
  (`pytest backend/tests/test_ownership.py` plus the gating suites CLAUDE.md lists) whenever
  queries, endpoints or events changed.
- **Frontend** (in `frontend/`): `npm run lint` (prettier + eslint), `npm run check`
  (svelte-kit sync + **svelte-check**), `npm run build` (**vite build**), `npm run test:unit` if
  present.
- **e2e:** `scripts/agent_stack.sh <slot> e2e`, the full Playwright suite on desktop, mobile and
  `hu` against **your** stack.
- **Extension** (if `extension/` changed): `web-ext lint`, the extension's tests (including the
  `_locales` key-parity check), and a real `web-ext run` pass when the plan asks for one.
- **Compose:** `docker compose config --quiet` for the default dev invocation, your slot
  invocation, and `-f docker-compose.yml -f docker-compose.prod.yml --profile tunnel`, whenever
  compose or env files changed. Run `nginx -t` in the `web` image whenever `nginx.conf` changed.
- **The real stack:** exercise the feature end to end the way a user would, in a real browser for
  anything UI. Mocked verification is not verification. For SSE, raw-capture `curl -N` on your
  slot's `/api/stream`, and run `scripts/verify_separation_sse.sh` against your slot.

## 7. Re-verify against the plan, every bullet

When implementation is done, **re-read the plan file fresh, top to bottom**, then walk **every
single "Done when" bullet** and produce its own concrete evidence gathered **this session**: a
log line, command output, a query result, a screenshot or a test run.

- One scenario passing doesn't prove a differently shaped one. If a bullet lists cases, evidence
  each case.
- A bullet you can't evidence is **not done**. Finish it, or report it plainly as not done, with
  the reason. Never round up.
- Check the plan's "Out of scope" section: confirm you did none of it. Check "Files owned": list
  anything you touched outside it.

## 8. Two reviews: self diff review, then live review

Both run as **fresh-context subagents** that get **none** of your reasoning, notes or
conclusions.

**8a. Self diff review (blind).** Give the reviewer **only**: the plan file path, `CLAUDE.md`,
the master plan's ledger rows for this slice, and the output of `git diff origin/main...HEAD`.
Ask it to find, each with file:line and a concrete failure scenario:

- correctness bugs and races;
- invariant violations (CLAUDE.md's lists);
- cross-user leaks;
- API-key boundary leaks (a key reaching anything beyond submit and `me`);
- missed Done-when bullets;
- out-of-scope changes and edits outside "Files owned";
- missing en/hu strings and keyboard gaps.

**8b. Live review.** Give a second fresh reviewer: the plan file path, your slot number, the
slot's URLs, the test identities' credentials file path, and the instruction to **drive your
running stack itself** (real browser via Playwright, curl, `psql` on the slot DB, and `web-ext
run` for extension slices). Ask it to try to break every Done-when bullet, adversarially:

- other identities;
- the keyboard only;
- `hu` and mobile viewports;
- reload mid-action, two tabs, stopping a container mid-flow.

It reports what failed, with reproduction steps. It must not edit code.

For both reviews:

- Verify each finding yourself before acting. Fix the real ones as
  `<VERSION>: fix review findings (round N): <summary>` commits.
- **When a bug class is found, sweep the whole touched file and its siblings for that class**, not
  just the reported line.
- Repeat with **new** reviewers (both kinds) until a round comes back clean, or only with findings
  verified as false positives (list them, with the reason, in the PR).
- After fixes, re-run section 6's checks and every Done-when bullet the fixes touched.

## 9. Rebase protocol (before the final push, and again whenever `main` moves while your PR is open)

Follow `00-master-plan.md`'s "Rebase protocol" exactly:

1. `git fetch origin && git rebase origin/main`.
2. **Alembic:** re-parent your migration's `down_revision` onto `main`'s head if `main` gained one.
   `alembic heads` must print exactly one head. Run `upgrade head` → `downgrade -1` →
   `upgrade head` on your slot DB.
3. **Message JSONs, GOTCHAS, CLAUDE.md:** keep both sides' entries, then re-run the key-parity
   check.
4. **graphify-out:** take `main`'s version, then `graphify update .` and commit.
5. **Version:** if `main`'s version is already ≥ yours, **stop and ask the owner**. Never pick a
   new number yourself.
6. Re-run section 6's checks on the rebased branch, plus every Done-when bullet the rebase could
   affect, then `git push --force-with-lease`.

## 10. Knowledge upkeep

- `graphify update .` after code changes. Commit the result (`graphify-out/` is tracked).
- New findings, surprises and war stories go in `docs/GOTCHAS.md` under a `<VERSION>` heading,
  with a one-line entry in its topic index. Correct stale gotchas in place with a dated note.
  Never delete them.
- Scope moved (an item deferred, split or inserted)? Record it under
  `plan/master-v5/00-master-plan.md`'s **Amendments**. Never edit the approved text above it.
- `CLAUDE.md` changes **only** if a rule, locked decision, invariant or roadmap position changed.
  Edit the existing line, keep it ≤ about 250 lines, and never append a session summary.
- A new required `.env`/compose variable (`${VAR:?}`) follows `docs/RELEASE_PIPELINE.md`'s
  "Adding a required env var" checklist and goes under the PR's **Deploy notes**.

## 11. Pull request

- Push your branch and open **one PR into `main`**, titled `<VERSION>: <slice title>`.
- **Push in batches, never once per commit.** Push when you open the PR, once per finished review
  round, and after each rebase. CI never cancels a superseded run (v49), so every push costs a full
  run on the one shared runner, queued behind the other agents' PRs.
- The body follows the established format (PRs #36, #40, #70):
  - **Summary:** what changed and why, with the ledger item ids it closes.
  - **Per-bullet evidence:** every "Done when" bullet, verbatim, each followed by its evidence.
  - **Reviews:** each self-diff and live review round, what it found, and what was fixed.
  - **Files outside "Files owned"** (or "none").
  - **Found, not fixed:** anything out of scope you noticed.
  - **Deploy notes:** new env vars, migrations (and whether they rewrite data, which needs a
    `pg_backup`), and manual host steps, or "none".
  - **Merge order note:** your wave and slot. The owner merges a wave in ascending slice order.
  - The attribution line the harness specifies, last.
- Wait for CI (`gh pr checks`; the single self-hosted runner may queue behind other agents' PRs)
  and fix anything red. **Don't merge.** The owner merges.
- If `main` moves before the owner merges, redo section 9 and push again.
- Finish with a short report to the owner: PR link, what's done, anything not done or uncertain,
  any question blocking a later slice, and your slot's state (stack down, volume kept, worktree
  path).
