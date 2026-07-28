# v00 — Planning

Branch: `dev-planning` → PR into `main`

## Scope

Establish the durable planning artifacts before any code is written. This version produces no
application code — only documents and the initial knowledge graph.

## Tasks

1. Write `plan/00-master-plan.md` — the full master roadmap (context, locked decisions, verified
   auth-API and spotdl-API findings, architecture, state machine, retry engine, repo layout,
   version table, workflow rules, verification strategy). Committed verbatim as approved.
2. Write one `plan/vNN-*.md` per version (`v00` … `v13`, this file included), each expanding its
   row of the roadmap table with concrete implementation detail: files to create/modify, schema
   fields, endpoint signatures, and a "Done when" acceptance check.
3. Rewrite `CLAUDE.md` at the project root so every future session loads, without re-deriving them:
   - the locked decisions table
   - the auth API contract (`vb2007.hu-api`) and its two gotchas (hardcoded cookie domain, public
     register endpoint)
   - the spotdl 4.5.2 API surface actually used
   - the architecture diagram and the Celery-ETA-is-unsafe rule
   - the track state machine and retry ladder/breaker numbers
   - the version roadmap table and workflow rules (graphify-first, one-feature-at-a-time,
     branch/PR discipline)
4. Run the initial graphify build: `graphify update .` (or a fresh `graphify .` if no graph exists
   yet) so `graphify-out/` exists from the start and every subsequent version can run
   `graphify query "…"` instead of raw exploration.
5. Commit everything on `dev-planning`, push, open a PR into `main`.

## Files touched

- `plan/00-master-plan.md` (new)
- `plan/v00-planning.md` … `plan/v13-settings-ui.md` (new)
- `CLAUDE.md` (rewritten)
- `graphify-out/` (generated, not hand-written)

## Done when

- All 15 plan files exist and are internally consistent with each other and with `CLAUDE.md`.
- `CLAUDE.md` contains no reference to information that only exists in this chat session — a fresh
  session reading only `CLAUDE.md` + `plan/` must be able to continue the project.
- `graphify-out/graph.json` exists.
- PR opened `dev-planning` → `main`.
