# Implementation prompt template (master v4)

Copy everything below the line into a fresh implementation session. **Change only the `VERSION`
line.** Everything else derives from it.

---

```
VERSION: v32
```

You are implementing **exactly one** spotdl-web version slice: the one named on the `VERSION`
line above. Everything you need to locate it derives from that one value:

- **Plan file:** the single file matching `plan/master-v4/<VERSION>-*.md`. Read it in full before
  anything else.
- **Branch:** the `Branch:` line in that file's header (`dev-<name>`).
- **Version string:** the `Version:` line in that file's header (`4.NN.0`, or the explicit
  "no bump" rule it states).
- **Roadmap context:** `plan/master-v4/00-master-plan.md`, especially its Locked decisions,
  Critical interactions and Amendments.

## 0. Rules

- **Read `CLAUDE.md` first and follow every rule in it.** Where this prompt and CLAUDE.md
  disagree, CLAUDE.md wins. Stop and say so.
- **Implement this version's plan only.** Don't start the next version. Don't fold in adjacent
  cheap fixes, optional items or "while I'm here" improvements, even good ones. Log them in the
  PR under "Found, not fixed" instead.
- If the plan contradicts itself, or contradicts the real code, **apply the plan literally,
  document the conflict in the PR, and ask** before going further. Don't silently reinterpret.
- If a plan precondition isn't met (for example v32's dev database doesn't exist yet, v38's
  direction isn't approved, or a field v40 needs is missing from the API), **stop and ask**.
  Don't work around it.

## 1. Context: graphify first, strictly

- Gather codebase context **with graphify, not exploration agents or blind grepping**:
  `graphify query "<question>"`, `graphify path "<A>" "<B>"`, `graphify explain "<concept>"`.
  Use `graphify-out/wiki/index.md` for broad navigation if it exists. Use
  `graphify-out/GRAPH_REPORT.md` only when query/path/explain aren't enough. Grep only after
  graphify has oriented you, or to edit specific lines.
- Read the relevant `docs/GOTCHAS.md` sections **via its topic index**, not end to end. Verify
  that any file or function a gotcha names still exists before acting on it.
- Read the last merged PR touching the same area (`gh pr list --state merged`, then
  `gh pr view <n>`) to match how changes there were structured and evidenced.

## 2. Branch and environment

- `git checkout main && git pull`, then `git checkout -b <Branch from the plan header>`. All work
  is branched from `main`, and the PR goes to `main`.
- **From v32 on, the local stack uses the dedicated dev database (`spotdlwebtest`), with no
  exceptions.** If local `.env` points at the production database, stop. Never touch production
  rows from local dev.
- Use test identities, **never** the real `ADMIN_EMAIL` account. At least one identity must log
  in through the **real upstream** `vb2007.hu-api` (local `host.docker.internal:3000` if it's
  running, otherwise `https://api.vb2007.hu`). Use the direct-session-mint fallback only if
  neither is reachable, and then say so explicitly.
- **Minimize SSH to the production host.** It runs other real services. Develop and verify on the
  local stack. When a host action is genuinely needed, batch it into as few round trips as
  possible.

## 3. Implement, committing as you go

- Work in small logical steps, and **commit each one separately** with a traceable message:
  `<VERSION>: <what this step does>`. For multi-item slices, use the plan's own labels (for example
  `v35: (c) gate redelivery of completed tracks`). Never one squash commit for the whole slice.
- Follow the surrounding code's style: comment density, naming, idiom. Reuse the helpers the
  master plan's "Reuse rather than rewrite" list names.
- Keep every CLAUDE.md invariant: no Celery `eta`/`countdown`, `worker-dl --concurrency=1`,
  `_ensure_spotify_client()`, `proxies.redact()` on everything logged or persisted,
  `values_callable` plus `DROP TYPE` for enums, SvelteKit exports **and** an nginx `location` per
  route, `!override` for compose lists, no per-row request loops, owner-scoped queries with 404
  for non-owners, and `queue.reset()` covering any new store state.
- **UI slices (v38–v46): use the impeccable skill, strictly.** Load it, run its Setup
  (`context.mjs`), and use the sub-commands the plan names. Record each one's output in the PR.
  Capture desktop **and** mobile screenshots before and after, from real dev data. v43 also loads
  the dataviz skill before any chart.
- **Keyboard (v44 on):** bindings target the **Hungarian QWERTZ** layout first. Nothing may need
  AltGr, `Y`/`Z` are never bound, match on `event.key`, and AltGr (Ctrl+Alt on Windows) never
  fires a shortcut. Any new interactive element added after v44 must be keyboard-reachable and
  registered in the shortcut registry if it gets a key.
- **Strings (v45 on):** every new user-visible string goes into **both** `en` and `hu` message
  files (never a literal), and every new user-facing backend error gets a stable `code`. The
  build's key-parity check must pass.
- Any change touching the network path, proxy or IP family must verify the **real connection
  destination** (`socket.socket.connect` observation or tcpdump), never trust a flag.

## 4. Version bump

- Set `backend/pyproject.toml`'s `version` and `frontend/package.json`'s `version` to the
  **identical** string from the plan header. Bump **both**, even if only one side changed. There
  is one shared app version. Skip only when the plan header says "no bump" (the slice touches
  neither `backend/` nor `frontend/`).
- Run `uv lock` in `backend/` after the bump and **before pushing**. Commit it as
  `<VERSION>: sync uv.lock with the version bump to <version>`. CI's `deps-sync` fails otherwise.
- `python3 .github/scripts/check_version.py origin/main` must pass locally.

## 5. Checks, all of them, against the real stack

Run every one. Paste the summarized output into the PR.

- Backend: `pytest` (the full suite, not just new tests), including the cross-user sweep
  `pytest backend/tests/test_ownership.py` whenever queries, endpoints or events changed.
- Frontend, in `frontend/`: `npm run lint` (prettier + eslint), `npm run check` (svelte-kit sync
  + **svelte-check**), and `npm run build` (**vite build**).
- From v37 on: `npm run test:e2e` (the Playwright suite against the local stack, both projects).
- Compose: `docker compose config --quiet` for both the dev invocation and
  `-f docker-compose.yml -f docker-compose.prod.yml --profile tunnel` whenever compose or env
  files changed. Run `nginx -t` in the `web` image whenever `nginx.conf` changed.
- **The real stack:** `docker compose up` with the dev database, real Postgres, real Redis and
  the real network. Exercise the feature end to end the way a user would, in a real browser for
  anything UI. Mocked verification is not verification. If it touches SSE, raw-capture
  `curl -N /api/stream` and run `scripts/verify_separation_sse.sh`.

## 6. Re-verify against the plan, every bullet

When implementation is done, **re-read the plan file fresh, top to bottom**, then walk **every
single "Done when" bullet** and produce its own concrete evidence gathered **this session**: a
log line, command output, a query result, a screenshot or a test run.

- One scenario passing doesn't prove a differently shaped one. If a bullet lists cases, evidence
  each case.
- A bullet you can't evidence is **not done**. Either finish it, or report it plainly as not done,
  with the reason. Never round up.
- Also check the plan's "Out of scope" section: confirm you didn't do any of it.

## 7. Blind review

Dispatch a **blind review subagent** with fresh context. Give it **only**:

- the plan file path,
- `CLAUDE.md`, and
- the output of `git diff main...HEAD`.

Give it none of your reasoning, notes or conclusions. Ask it to find correctness bugs, invariant
violations (CLAUDE.md's lists), cross-user leaks, missed Done-when bullets and out-of-scope
changes, and to report each with file:line and a concrete failure scenario.

- Verify each finding yourself before acting. Fix the real ones as
  `<VERSION>: fix fresh-eyes review findings` commits.
- **When a bug class is found, sweep the whole touched file (and its siblings) for the same
  class**, not just the reported line.
- Repeat with a **new** blind reviewer until a round comes back clean, or only with findings you've
  verified as false positives (list them with the reason in the PR).
- After fixes, re-run section 5's checks and any Done-when bullet the fixes touched.

## 8. Knowledge upkeep

- `graphify update .` after the code changes (AST-only, no API cost), and commit the result if
  `graphify-out/` is tracked.
- New findings, surprises and war stories go in `docs/GOTCHAS.md`, under a `<VERSION>` heading,
  with a one-line entry in its topic index. Correct stale gotchas in place with a dated note.
  Never delete them.
- If scope moved (an item deferred, a version inserted or renumbered), record it under
  `plan/master-v4/00-master-plan.md`'s **Amendments**. Never edit the approved text above it.
- Update `CLAUDE.md` **only** if a rule, locked decision, invariant or roadmap position changed.
  Edit the existing line, keep it under about 250 lines, and never append a session summary.
- If the slice adds a required `.env`/compose variable (`${VAR:?}`), list it under a **Deploy
  notes** heading in the PR, and add it to `.env.example`.

## 9. Pull request

- Push the branch and open **one PR into `main`**, titled `<VERSION>: <slice title>`.
- The body follows the established format (see PRs #36, #40):
  - **Summary:** what changed and why, in a few bullets.
  - **Per-bullet evidence:** every "Done when" bullet, verbatim, each followed by its evidence.
  - **Review rounds:** what each blind review found and what was fixed.
  - **Found, not fixed:** anything out of scope you noticed.
  - **Deploy notes:** new env vars, migrations (and whether they rewrite data, which needs a
    `pg_backup`), and manual host steps, or "none".
  - The attribution line the harness specifies, last.
- Wait for CI (`gh pr checks`) and fix anything red. **Don't merge.** The owner merges.
- Finish with a short report to the owner: PR link, what's done, anything not done or uncertain,
  and any question that blocks the next version.
