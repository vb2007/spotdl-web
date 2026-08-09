# v08 — Live Progress (SSE)

Branch: `dev-live-progress` → PR into `main`

## Scope

Stream live per-track progress to the browser. SSE now, per your answer, with the explicit note
that WebSocket may replace it later if needed — so the event payload format should not be tied to
SSE mechanics (framing, `Last-Event-ID`), keeping a swap cheap.

## Tasks

1. `app/services/events.py`:
   - `publish(event: dict)` — `redis.publish("spotdl:events", json.dumps(event))`. Called from
     `download_track` (v06) at each meaningful transition: `queued`, `downloading` (with spotdl's
     own progress % via the hook below), `completed`, `waiting` (with `scheduled_at`),
     `lookup_failed`, `failed`, plus job-level `expanding`/`expanded`.
   - Event shape: `{type: "track.state", track_id, job_id, state, progress?, scheduled_at?,
     error?, ts}` — a flat, provider-agnostic schema so the frontend doesn't care whether it
     arrived via SSE or (later) WebSocket.
2. Hook spotdl's own progress reporting: `Downloader.progress_handler.get_new_tracker(song)`
   exposes `notify_download_progress` style callbacks (per spotdl's `ProgressHandler` API) — wire
   these to call `events.publish` with a `progress` (0-100) field during the yt-dlp/ffmpeg phases,
   not just at start/end.
3. `GET /api/stream` (behind `require_session`) — FastAPI `StreamingResponse` /
   `EventSourceResponse`: subscribes to the Redis `spotdl:events` channel via `redis.asyncio`,
   forwards each message as an SSE `data:` line, and emits a `:heartbeat\n\n` comment every 15s so
   Cloudflare Tunnel doesn't close the connection as idle.
4. Response headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Content-Type:
   text/event-stream`.
5. Reconnection contract (documented here for v09 to implement): `EventSource` auto-reconnects on
   drop; the frontend must, on every `open` event, refetch `GET /api/jobs` + per-job tracks via
   REST to resync full state, then resume trusting the stream deltas. No `Last-Event-ID` replay is
   implemented — full-state REST refetch is simpler and sufficient at this scale.
6. `graphify update .`

## Files touched (new)

`backend/app/services/events.py`, `backend/app/routers/stream.py`; edits to
`backend/app/tasks/download.py`, `backend/app/tasks/expand.py` (publish calls).

## Done when

- `curl -N http://.../api/stream` (with a valid session cookie) shows live `track.state` events
  as a real download proceeds, including intermediate `progress` values, not just start/end.
- The stream survives at least 5 minutes idle (or between events) without dropping, both directly
  and through a local `cloudflared` tunnel — heartbeat confirmed in the raw output.
- Killing the API process mid-stream and restarting it: a reconnecting client resumes receiving
  events with no code changes needed client-side beyond the documented refetch-on-open behavior.
