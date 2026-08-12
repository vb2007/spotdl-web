# v22 — Multi-User Hardening & Real-Stack Verification

Branch: `dev-multi-user-hardening` → PR into `main`

## Scope

The version that makes master v2 real rather than merely merged: end-to-end verification with two
actual accounts on the actual deployment, the production migration, and reconciliation of every doc
that v14–v20 made stale.

This exists as its own version because v17–v20 each verify *their own* slice, and data separation
is a property that emerges across all of them. A cross-user leak is most likely to appear exactly
where two versions meet — a v18 search parameter that forgets v17's owner filter, or a v20 store
that caches another user's rows from an admin toggle. Nothing in the per-version checks looks there.

## Why data separation is treated as a security property

Three real people share one deployment. "User B can see user A's jobs" is not a cosmetic bug — it
is the failure this whole master version exists to prevent, and it fails *silently*: the UI looks
correct to everyone until someone notices a stranger's album in their list. Silent failures need
adversarial verification, not confirmation that the happy path works.

So this version's tests are written to **try to break separation**, not to demonstrate it holding.

## Tasks

1. **Adversarial cross-user sweep.** With two real allowlisted accounts on the real stack, attempt
   to reach A's data as B through every surface enumerated below. Written as a repeatable script
   (`scripts/verify_separation.sh` or a pytest module against a running stack) so it can be re-run
   after any future version, not as a one-off manual session.
2. **Production migration.** Apply v16's destructive schema change on the Debian host. Because it
   drops job/track history by design (locked v2 decision — the DB is POC data), take a `pg_dump`
   first with `scripts/pg_backup.sh` regardless, and confirm the restore works *before* migrating.
   The dedup ledger and the files on disk survive; verify a previously-downloaded track still
   resolves as `skipped_duplicate` post-migration rather than re-downloading.
3. **Real second user.** Add the second account's email to `ALLOWED_EMAILS` on the host, confirm
   `users` row creation on first login, and that they are not admin.
4. **Doc reconciliation** — everything v14–v20 invalidated:
   - `CLAUDE.md`: v14–v22 gotchas sections; correct any v1 claim the audit found false (v12's
     correction of v09's nginx note is the precedent for how to word these).
   - `docs/DEPLOYMENT.md`: `ADMIN_EMAIL`, the second user, the migration step.
   - `docs/LOCAL_DEV.md`: seeding a second local user for multi-user testing.
   - `.env.example` / `.env.dev.example`: every new var.
   - `PRODUCT.md`: it describes a single-user tool; that is no longer true.
   - `frontend/src/DESIGN.md`: v20's new components and the rollup-badge treatment.
5. **CI**: add the separation test to `.github/workflows/ci.yml` if it can run without a live stack
   (against the pytest Postgres fixture); otherwise document explicitly in the workflow file why it
   is manual-only, rather than leaving a silent coverage gap. `docs/CI_SELF_HOSTED_RUNNER.md`'s own
   advice applies — extend the existing job, do not add a second workflow file (v12 made exactly
   this mistake and had to undo it).
6. `graphify update .` — full rebuild, not incremental, since v16–v20 changed most of the backend.

## The sweep — every surface, explicitly

For each, the expected result is **no data belonging to A, and 404 rather than 403** on direct-id
access so existence isn't confirmed:

| Surface | Attempt as B |
|---|---|
| Job list | `GET /api/jobs` with every filter/sort/search combination v18 offers |
| Track list | `GET /api/tracks`, including `q=` matching A's track titles exactly |
| Direct job | `GET /api/jobs/{A's id}`, `GET /api/jobs/{A's id}/tracks` |
| Job mutations | `DELETE`, `PATCH .../priority`, `POST .../bump` on A's job |
| Track mutations | `DELETE /api/tracks/{A's id}`, `POST /api/tracks/{A's id}/retry` |
| Archive | `POST /api/jobs/archive` / `unarchive` with A's job ids in the body |
| Retention | `GET`/`PATCH /api/settings/retention` targeting A |
| Admin endpoints | every `settings`/`proxies`/`worker` mutation (expect 403) |
| Admin toggle | `all_users=true` as a non-admin (expect it ignored, own rows only) |
| SSE | `curl -N /api/stream` as B, captured raw across a full real download belonging to A |
| SSE admin pattern | confirm B cannot subscribe to the admin pattern channel |

## Done when

- The full sweep passes with **zero** foreign rows or ids on any surface, evidenced by the captured
  output of each check — not by a summary claim. The SSE capture in particular is pasted/attached,
  since it's the surface with no REST-level equivalent and the one that leaked by default before
  v17.
- The separation script is committed and re-runnable, and re-running it is added to CLAUDE.md's
  workflow rules as a required step for any future version touching queries, endpoints, or events.
- The production migration completed on the real host: all services healthy afterward, a real
  download completes end to end, and a previously-downloaded track still dedups instead of
  re-downloading.
- Both real users can log in on the deployed instance, each sees only their own queue, and the
  admin's all-users toggle works there (not only locally).
- Every doc in task 4 is updated; no doc still describes spotdl-web as single-user.
- A final read-through of `plan/master-v2/` confirms every "Done when" bullet across v14–v22 was
  actually checked with its own evidence — the same closing pass v13 did for master v1, and the
  reason two real gaps were caught there rather than shipped.
