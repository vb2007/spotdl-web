# v48 — Master v4 Hardening & Close

Branch: `dev-v4-hardening` → PR into `main`
Version: `4.48.0`

## Scope

The production close for master v4, in the same role v13, v22 and v31 played. Each of v32–v47
verified its own slice. The failures that survive are the ones *between* slices:

- v34, v35 and v44 add read paths that could drop an owner filter;
- v35 rewrites attempt numbering that v41, v44 and v36 all read;
- v45 binds keys to markup that v47 polished;
- v46 translated strings that v41–v45's e2e selectors and help overlay depend on;
- every release since v33 went through its new pipeline, which proves or disproves it.

## Tasks

1. **The cross-user separation sweep.** Run `pytest backend/tests/test_ownership.py`, plus the
   archive, retention and admin-gating suites (`test_jobs.py`, `test_settings_retention.py`,
   `test_proxies_router.py`, `test_worker.py`, `test_settings_router.py`, and v44's stats gating),
   **and** `scripts/verify_separation_sse.sh` against a running stack. Cover v34's hydration
   filters, v35's `counts_by_state` and attempts detail, v44's stats (admin-only, no identities),
   v45's shortcut preference and v46's language preference, including **direct-id** endpoints. Non-owner gets 404.
2. **The e2e suite on both projects**, plus the full keyboard-only journey set (including the
   Hungarian QWERTZ emulation) and v46's `hu` smoke project, against the local stack. Then a **read-only smoke** against production (log in with a real test identity, load
   each route), by browser, not curl.
3. **Pipeline record.** Review every Publish & Deploy run since v33: any failure, any rollback, and
   whether each sent its Matrix message. Note any `:?` variable added since and how preflight
   treated it.
4. **Alerting record.** List which v36 alert categories fired for real in production since v36,
   and whether any was noise (tune the defaults if so, within the existing settings).
5. **v31's open questions, observed on the dev database.** Run a real album end to end with normal
   pacing, and confirm every `COMPLETED` track's file exists at its `output_path`. This closes or
   re-opens v31's "file missing after COMPLETED" and the v21 empty-`DOWNLOADS_DIR` observation.
   Watch the ladder delays against `LADDER_SECONDS` for the v31 ladder anomaly. Record the outcome
   in GOTCHAS either way, as closed or still-open with the new evidence.
6. **Doc reconciliation.**
   - `CLAUDE.md`: status, roadmap position, and any changed invariant (v33 rollback semantics,
     v36 alerting, v45 keyboard). Keep it under about 250 lines, editing lines rather than
     appending.
   - `docs/GOTCHAS.md`: index entries for v32–v48.
   - `docs/DEPLOYMENT.md`, `docs/LOCAL_DEV.md` and `docs/RELEASE_PIPELINE.md`: match reality.
   - `PRODUCT.md`: the keyboard requirement (Hungarian QWERTZ first) and the `hu`/`en` i18n are
     now met, so record how.
7. **The library sweep's v39 findings** (amendment A6, F34; an explicit exception to "Out of
   scope", since this is v28 behavior). (a) The sweep error log lists the same path twice:
   deduplicate it. (b) A sweep archives settled jobs of *every* user, and the report doesn't say
   so: decide with the owner whether that stays (then the report states the count) or is scoped,
   and record the decision. A scoping change re-runs the cross-user sweep.
8. **The closing re-read.** Go through every "Done when" bullet across `plan/master-v4/v32`–`v47`
   fresh, against the merged code and the evidence in each PR. Anything that can't be re-evidenced
   now gets re-verified, or listed as a known gap in this PR.

## Out of scope

- New features. Anything found that isn't a regression is logged for a future master, and not
  fixed here unless it is a real defect in a v4 change (or task 7's F34, by owner decision).

## Done when

- [ ] Cross-user sweep: every listed pytest suite passes, and `verify_separation_sse.sh` passes
      against a running stack (output). A non-owner direct-id request to each v4 endpoint returns
      404 (listed per endpoint).
- [ ] The e2e suite plus the keyboard journeys pass on desktop and mobile (output). The production
      read-only smoke passes in a real browser (screenshots).
- [ ] The pipeline record is in the PR: a table of runs since v33, with outcome and notification
      sent.
- [ ] The alerting record is in the PR, and any default tuning is justified.
- [ ] Real album run on dev: per-track file existence checked (`ls`/`stat` against every
      `output_path`). The v31 questions are recorded in GOTCHAS as closed or still-open, with the
      evidence.
- [ ] F34: the sweep error log has no duplicate paths (a sweep with a known failing file, before
      and after), and the cross-user archiving decision is recorded in the PR and GOTCHAS, with the
      report showing the count if it stays.
- [ ] CLAUDE.md is at or under about 250 lines (`wc -l`), with its roadmap and invariants current.
      GOTCHAS index entries exist for v32–v48.
- [ ] The closing re-read is done: every v32–v47 Done-when bullet listed with a pointer to its
      evidence, or re-verified, or declared a known gap.
- [ ] `pytest`, `npm run lint`, `npm run check`, `npm run build` and `npm run test:e2e` pass. Both
      version files read `4.48.0`. `uv lock` is in sync. `graphify update .` has been run.
