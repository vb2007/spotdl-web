# v07 — Proxy Rotation

Branch: `dev-proxy-rotation` → PR into `main`

## Scope

Give the retry engine's `use_proxy` hook (v06) an actual pool to draw from. Proxies are seeded from
a plain file for now — the master plan defers UI management of proxies to the final version
(v13).

## Tasks

1. `proxies.txt` format: one proxy URL per line (`http://user:pass@host:port` or `socks5://...`,
   whatever spotdl's `proxy` option accepts directly), `#`-comments and blank lines ignored. Path
   configurable via `PROXY_FILE` env, mounted read-only into the worker container.
2. `app/services/proxies.py`:
   - `sync_from_file()` — on `worker-meta` boot: read `PROXY_FILE`, upsert each URL into `proxies`
     (`source=file`, `enabled=true` if new), and disable any `source=file` row whose URL is no
     longer in the file (soft delete via `enabled=false`, never hard-delete — preserves health
     history).
   - `pick_proxy() -> Optional[Proxy]` — among `enabled=true AND (cooldown_until IS NULL OR
     cooldown_until <= now())`, pick the one with the oldest `last_used_at` (NULLs first) — simple
     least-recently-used selection, no fancy scoring needed for a personal tool.
   - `record_proxy_result(proxy_id, success: bool)` — success: `consecutive_failures=0`,
     `last_success_at=now()`. Failure: `consecutive_failures += 1`, `cooldown_until = now() +
     backoff(consecutive_failures)` (reuse the same ladder shape as `retry.py`'s constants, e.g.
     15m/1h/4h, capped — proxies shouldn't need the full 24h track ladder since a bad proxy is
     usually just swapped for another).
3. Wire into `download_track` (v06's version): when `track.attempt_count >= 1` (i.e. the
   direct-first attempt already failed and its ladder wait has elapsed), call `pick_proxy()`. If a
   proxy is available, request a `Downloader` from `downloads.get_downloader(..., proxy=proxy.url)`
   and record `track.used_proxy_id`. If no proxy is currently out of cooldown, fall back to direct
   for this attempt rather than blocking the track indefinitely on proxy availability. After the
   attempt, call `record_proxy_result`.
4. Startup validation: on `sync_from_file()`, optionally do a cheap reachability check (e.g. TCP
   connect) per new proxy so an obviously dead entry doesn't get picked first — best-effort, not a
   hard requirement.
5. `graphify update .`

## Files touched (new)

`backend/app/services/proxies.py`, `proxies.txt.example`; edits to `backend/app/tasks/download.py`,
`docker-compose.yml` (mount `PROXY_FILE`).

## Done when

- A track that fails direct, waits out its ladder step, then succeeds via a proxy on the next
  attempt — confirmed via `tracks.used_proxy_id` and worker logs showing the proxy URL used.
- A proxy that fails gets `cooldown_until` set and is not picked again until it elapses; `pick_proxy`
  correctly skips it in favor of a healthy one.
- Editing `proxies.txt` and restarting `worker-meta` adds new entries and disables removed ones
  without touching their historical health stats if they're re-added later (re-enable, don't reset
  counters).
- No proxy available → track still gets attempted directly rather than stalling forever.
