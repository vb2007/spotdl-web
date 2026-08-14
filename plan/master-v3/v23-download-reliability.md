# v23 — Download Reliability & Live-View Correctness

Branch: `dev-download-reliability` → PR into `main`
Version: `3.23.0`

## Scope

Fix the outage. Every track currently fails within seconds with `spotdl returned no output file for
this track`, is correctly re-queued by the retry ladder, and fails again — so the app downloads
essentially nothing while looking, from the UI, like a queue that's simply taking its time.

Also fixes the live-view bugs that share the same code path and the same symptom window: the
"unknown artist / unknown song" metadata gap and the appear/disappear/reappear glitch.

Ships as one version because both halves are the same failure story and want the same real-stack
verification session. Neither is large.

## Part 1 — Root-cause the download failure

**Investigate before changing anything.** The stale `yt-dlp==2026.7.4` pin
(`backend/requirements.txt:247`, last regenerated in `58d71e5` / v12 / 2026-08-02) is the leading
hypothesis — YouTube breaks extraction constantly, yt-dlp ships fixes within days, and the user's
own system yt-dlp downloads the same tracks instantly from the same host and the same public IP.

But `output_path is None` (`backend/app/tasks/download.py:186`) has at least three plausible causes
and only one is the pin:

1. **Stale yt-dlp** — extraction fails, spotdl swallows it and returns no path.
2. **A write/permission problem** — the audio downloads but can't be written where spotdl expects,
   so it reports no output. Genuinely possible: the container runs non-root (uid 1000) against a
   bind-mounted downloads directory, and `docs/DEPLOYMENT.md` already documents a `chown` step for
   exactly this failure.
3. **spotdl swallowing a real error** and returning `None` where it should have raised — in which
   case the fix is to surface the underlying error, not to bump a dependency.

Reproduction steps:

- Run a real download inside the real `worker-dl` container against a real track, with spotdl's and
  yt-dlp's own output captured (raise spotdl's `log_level`, and use the established
  `docker compose cp` + `/app/`-rooted ad-hoc script technique — **never `/tmp/`**, see
  `docs/GOTCHAS.md`'s v11 entry).
- Compare against the same track downloaded by the host's own yt-dlp, and record both versions.
- Check the resolved output path's writability *as the container user*, so cause 2 is ruled in or
  out by evidence rather than by assumption.

**A fix not traced to a proven cause is not a fix.** The retry ladder makes a still-broken download
indistinguishable from a slow one in the UI, so "it seems better now" is not a verification.

## Part 2 — Dependency policy (regardless of root cause)

- **Unpin `yt-dlp`** so rebuilds pick up extraction fixes; every other dependency stays pinned.
  Pinning the one dependency whose entire job is chasing a moving target is what produced this
  outage.
- **Regenerate `requirements.txt`** (`uv pip compile pyproject.toml -o requirements.txt`) and record
  the resolved yt-dlp version in the PR.
- **Scheduled CI freshness check** — a job that compares the yt-dlp version resolved in the built
  image against the latest release and fails (or warns loudly) when it falls behind. Extend the
  existing `ci.yml`; **do not add a second workflow file** — `docs/CI_SELF_HOSTED_RUNNER.md` says so
  and v12 already made that mistake and had to undo it.
- **Track `backend/uv.lock`** (currently untracked in the working tree) and add a CI check that the
  committed `requirements.txt` still matches `pyproject.toml`, so a dependency change can't ship
  without reaching the built image.

## Part 3 — Typed error so the breaker can see a total failure

`output_path is None` currently raises a bare `RuntimeError`, which `retry.classify_error` maps to
`TrackErrorType.OTHER`. `OTHER` shares the retry ladder but **never feeds the circuit breaker** — so
a 100% failure rate across every track in the queue never trips the breaker that exists to notice
exactly that condition.

- Introduce a dedicated exception for "spotdl completed without producing a file" and classify it
  explicitly rather than letting it fall into `OTHER`.
- Decide and document whether it feeds the breaker. It should: a run of these means downloading is
  broken system-wide, which is precisely what the breaker is for. Keep `AudioProviderError`'s
  existing behavior unchanged.
- Preserve the existing proxy-credential redaction on the error path
  (`proxies.redact()` — `docs/GOTCHAS.md` v07).

## Part 4 — Live-view metadata and the render glitch

**Metadata.** `frontend/src/lib/stores/queue.ts:717` seeds a live track's title/artists/album from
`findCachedTrackMeta`, which only searches rows the browser already fetched via REST. A track that
starts and fails before ever being fetched has nothing to seed from, so it renders as unknown — and
because tracks currently fail in seconds, that's almost every track. The metadata "appears later"
because the ladder's re-queue eventually triggers a REST refresh that fills it in.

Fix at the source: `events.publish_track_event` should carry `title`/`artists`/`album`. The worker
already holds `song_json` when it publishes, so this is available at zero extra cost, and it makes
the live view correct without depending on a prior REST fetch. Keep `findCachedTrackMeta` as the
fallback for events that predate the change or lack the fields.

**Glitch.** Investigate the download-starts / disappears / reappears behavior. The likely mechanism
is the interaction between `liveActive`'s add-on-`downloading` / remove-on-any-other-state logic and
the rapid `downloading → waiting` transition the current failure produces, possibly compounded by
`scheduleJobRefresh`'s debounce racing the SSE event. Confirm the actual sequence from a raw SSE
capture before changing the store — the v10 gotcha (stray post-cancel progress events) shows this
component has already produced one bug that looked like a rendering fault and wasn't.

## Done when

- The root cause is **proven**, with captured evidence in the PR: spotdl/yt-dlp output showing the
  failure, and the same track downloading successfully after the fix.
- The resolved yt-dlp version before and after is recorded, and a rebuild picks up newer releases.
- The CI freshness check runs and correctly flags a deliberately stale version.
- `uv.lock` is tracked; the requirements-sync check fails on a deliberately desynced
  `pyproject.toml`.
- The no-output case raises its own typed error, classifies as its own type, and a simulated run of
  them trips the breaker — verified against the real DB, not just a unit test.
- A real track's title and artist are correct in the live view **from the first `downloading`
  event**, on a browser that has never fetched that track — verified by watching the real UI, and
  by a raw `curl -N /api/stream` capture showing the fields on the wire.
- The appear/disappear/reappear glitch is gone, verified on a real download, with the mechanism
  explained in the PR rather than "fixed by refactoring".
- Full backend suite passes; `svelte-check`/`eslint`/`vite build` clean.
- Both `backend/pyproject.toml` and `frontend/package.json` read `3.23.0`.
- `graphify update .`
