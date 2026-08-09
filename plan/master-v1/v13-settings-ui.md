# v13 — Settings UI (Final)

Branch: `dev-settings-ui` → PR into `main`

## Scope

The two things deliberately deferred throughout the whole roadmap: proxy list management and
output-config overrides, both moved from file/env into the UI, backed by the DB tables that have
existed since v02/v07. This is explicitly the *last* version — everything else should already work
before this starts.

## Tasks

1. **Proxy management UI**
   - `GET /api/proxies` / `POST /api/proxies` (`{url}`, `source=manual`) / `PATCH
     /api/proxies/{id}` (`enabled` toggle) / `DELETE /api/proxies/{id}` (soft: `enabled=false`,
     matching v07's never-hard-delete stance) — all behind `require_session`.
   - Frontend page listing every proxy with health stats (`consecutive_failures`,
     `last_success_at`, `cooldown_until`, `source`), add/enable/disable controls.
   - `proxies.txt` (v07) keeps working unchanged — `source=file` rows remain file-managed;
     `source=manual` rows are UI-only and untouched by `sync_from_file()`. Both pools are drawn
     from equally by `pick_proxy()`.
2. **Output config override UI**
   - `GET /api/settings/output` / `PATCH /api/settings/output` — global defaults
     (`format`, `bitrate`, output path template) currently sourced from env (`DEFAULT_FORMAT`,
     `DEFAULT_BITRATE`, `DOWNLOAD_OUTPUT_DIR`), now stored in a `settings` table (or the existing
     `worker_state` row, extended) so they're editable without a redeploy. Env vars become the
     seed/fallback on first boot, not the permanent source.
   - Per-job override (mentioned as a possible future step in the master plan, not required for
     this version unless it's still wanted at this point) — confirm scope with the user before
     building; the locked decision was "global override in the UI," not necessarily per-job yet.
   - `app/services/downloads.get_downloader` (v05) reads these from the DB-backed settings service
     instead of `Settings` env directly, with the `(format, bitrate, proxy)` cache key still
     correct — changing global settings should invalidate the cache appropriately (e.g. bump a
     settings version counter into the cache key).
3. `graphify update .`

## Files touched (new)

`backend/app/routers/proxies.py`, `backend/app/routers/settings.py`, a `settings` table +
migration (or `worker_state` extension) if not already sufficient from v02, frontend settings
pages; edits to `backend/app/services/downloads.py` and `backend/app/services/proxies.py` to read
from the DB-backed settings instead of static env.

## Done when

- A proxy added via the UI is picked by `pick_proxy()` on the next eligible attempt, with health
  stats updating live exactly like file-sourced proxies.
- Changing the global output format/bitrate in the UI affects the *next* download without a
  container restart.
- `proxies.txt` and the UI-added proxies coexist without either overwriting the other's rows.
- This is confirmed as the last planned version — a final pass over `plan/` and `CLAUDE.md`
  reconciling anything that drifted from the original roadmap during v01–v12.
