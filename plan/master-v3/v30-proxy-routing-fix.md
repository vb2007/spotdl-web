# v30 — Proxy Routing Fix

Branch: `dev-proxy-routing-fix` → PR into `main`
Version: `3.30.0`

> **Unplanned insertion after v29.** Found during v29's own session (network-path escalation) while
> wiring the new direct-ipv4/direct-ipv6 rungs ahead of the existing proxy rung — proving each rung's
> mechanism empirically turned up evidence that the *existing* proxy rung, shipped and locked since
> v07, has never actually worked. The hardening close that was v30 is now **v31**, unchanged in
> content apart from the renumber and this version's own re-verification bullet — same treatment
> v21's insertion gave v22, and v23's gave v29/v30. See `00-master-plan.md`'s Amendments.

## Scope

Make the proxy escalation rung (attempt 3+ in the ladder, per v29's `NetworkPath.PROXY`) actually
route real network traffic through the configured proxy, for **both** HTTP stacks the download path
uses — exactly the same two-stack split v29 had to solve for IP-family forcing:

- yt-dlp's own requests (search-result extraction and the actual media download).
- ytmusicapi's separate search calls.

No new endpoints, no schema change, no ladder redesign. This is a correctness fix to a rung that
already exists and is already being selected correctly (v29 confirmed the ladder's *selection* logic
is fine — attempt 3+ does correctly call `proxies.pick_proxy` and pass a real proxy URL down). The
bug is one layer deeper: the proxy URL, once selected, never actually reaches either stack's real
connection.

## Why this exists — the proven gap

Confirmed empirically this session (v29's), against the real running local dev stack, with a real
configured proxy and real network traffic, using a `socket.socket.connect` observation technique (no
tcpdump in this sandbox, same evidentiary standard):

1. Picked a real enabled `Proxy` row from the dev database (a real credentialed proxy from
   `proxies.txt`).
2. Built a real `Downloader` via `downloads.get_downloader(..., proxy=<that proxy's url>)` — the
   exact call `download_track` makes for a real attempt-3+ track.
3. Called the real `YouTubeMusic` audio provider's `get_results(...)` (a real ytmusicapi search) with
   `socket.socket.connect` monkeypatched to record every destination address.
4. The search **succeeded** and returned real results — but the only `connect()` call observed went
   straight to a real Google IP (`142.250.130.136:443`), never to the configured proxy's address.

Root cause, read from the actually-installed spotdl 4.5.2 source (not assumed):

- `Downloader.__init__` (`spotdl/download/downloader.py:230`) does exactly one thing with the
  `proxy` setting: `GlobalConfig.set_parameter("proxies", proxies)`.
- `GlobalConfig.get_parameter("proxies")` is read by exactly four call sites in the whole package:
  `providers/audio/piped.py`, `providers/audio/bandcamp.py`, `providers/audio/sliderkz.py`, and the
  three lyrics providers (`musixmatch.py`, `genius.py`) plus `utils/metadata.py`. **`ytmusic.py` —
  the only audio provider this app has ever configured (`audio_providers` defaults to
  `["youtube-music"]`, never overridden anywhere in this codebase) — is not in that list.**
  `YouTubeMusic._create_client()` hardcodes `YTMusic(language="de")` with no `proxies=` argument at
  all, and `AudioProvider.__init__` (the base class `YouTubeMusic` inherits, in `base.py`) builds its
  own `yt_dlp_options` dict with **no `"proxy"` key either** — so yt-dlp's own `YoutubeDL` instance
  for the actual media download is equally unaware any proxy was configured.
- Nothing in this app's own code sets `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` env vars (confirmed:
  `grep -rn "environ\|HTTP_PROXY" backend/app/` finds nothing relevant), so there is no accidental
  fallback path either. The proxy is simply never wired to anywhere real traffic actually flows.

**Practical implication**: since `youtube-music` is the only audio provider this app has ever run,
every "attempt via proxy" in production — since v07 shipped, through every version since — has
silently gone out **directly**, for both the search step and the actual download step. The proxy
escalation rung, a locked decision (`CLAUDE.md`'s "Proxy strategy: Direct first → wait → proxy") that
exists specifically to route around IP-based blocking/rate-limiting, has never provided that benefit.
v07's own real-proxy verification (`docs/GOTCHAS.md`'s v07 section) recorded "real downloads succeed
through a real proxy end-to-end" — that observation was real (the download did succeed), but the
*attribution* was wrong: it succeeded despite bypassing the proxy, not because of it. Nothing in that
verification actually checked which IP the connection went out on. `docs/GOTCHAS.md`'s v07 entry
needs a dated corrective note pointing here, per `CLAUDE.md`'s "correct a stale gotcha in place,
never by deletion" rule — not rewritten, since knowing the original (wrong) belief existed is itself
useful context for why this went unnoticed for so long.

**Downstream consequence worth flagging explicitly**: `proxies.record_proxy_result`'s
`consecutive_failures`/`cooldown_until`/`last_success_at` bookkeeping has, this whole time, actually
been measuring **direct-connection** health, mislabeled as proxy health. Every historical
`last_success_at`/cooldown value in any deployed database predates this fix and should be treated as
meaningless once it lands — worth a one-line callout in the PR description, not a migration (no
schema change, the columns are correctly typed for their *intended* meaning; they just haven't been
measuring it).

## Design

**yt-dlp's own stack**: reuse v29's `yt_dlp_args` mechanism rather than fighting spotdl's broken
`GlobalConfig` wiring — the same `args_to_ytdlp_options` merge logic v29 already proved safe (a flag
that's unset by bare `parse_options([])` doesn't clobber this app's own defaults, including the deno
`js_runtimes` options) extends cleanly to yt-dlp's own `--proxy <url>` flag. Concretely,
`downloads.get_downloader` needs to build one combined `yt_dlp_args` string from up to two
independent fragments — the network-path family flag (`-4`/`-6`, only for the two direct rungs) and
a proxy flag (`--proxy <url>`, only when `proxy` is not `None`) — rather than the current
either/or mapping. In practice the two are mutually exclusive under today's ladder (PROXY never
forces a family), but building the merge generally, rather than asserting that exclusivity, avoids
a second implicit coupling between this file and the ladder's own rung design. **The proxy URL needs
`shlex`-safe quoting** before going into the args string — `proxies.txt`'s accepted format
(`http(s)://[user:pass@]<IPv4>[:port]`, `proxies.py`'s `PROXY_URL_RE`) can contain characters shlex
would otherwise split on if a future format loosening ever allows them; quote defensively now rather
than assuming today's regex is forever.

**ytmusicapi's stack**: needs the same shape of fix v29 used for family-forcing — a context manager,
symmetrical to `force_family`, that patches for the duration of a single attempt rather than baking
anything into the cached `Downloader` (ytmusicapi's client is constructed fresh inside
`AudioProvider.__init__`/`YouTubeMusic._create_client()` regardless of `get_downloader`'s cache, so a
call-time patch is correct regardless of caching, exactly the same reasoning `network_path.py`'s
docstring already gives). Concretely: monkeypatch
`spotdl.providers.audio.ytmusic.YouTubeMusic._create_client` (currently a bare
`staticmethod` returning `YTMusic(language="de")`) to instead return
`YTMusic(language="de", proxies={"http": url, "https": url})` for the duration of the attempt.
`ytmusicapi.YTMusicBase.__init__`'s own `proxies` parameter is a real, already-correctly-wired
mechanism on ytmusicapi's side (verified against the installed source:
`YTMusicBase._prepare_session`/`_send_request` pass `self.proxies` straight into every
`requests.request(...)` call) — the gap is purely that spotdl never passes it through, not that
ytmusicapi lacks the capability.

Same non-reentrancy discipline as `force_family`: guard against two attempts patching this
class attribute concurrently (worker-dl's `--concurrency=1` invariant makes this safe in practice,
but the guard turns a violation into a loud `RuntimeError` instead of one attempt's proxy leaking
into another's, exactly like `network_path.py`'s existing `_active` lock).

**Composability with v29's `force_family`**: design both context managers to nest safely regardless
of whether today's ladder ever actually needs them simultaneously — don't couple this fix's
correctness to "PROXY never forces family" staying true forever.

## Interaction with v29

- `get_downloader`'s cache key already includes `proxy` (pre-existing, v07) and `network_path` (v29)
  independently — no new cache-key dimension needed; the combined `yt_dlp_args` string is still fully
  determined by those same two existing key components.
- `download.py`'s call site wraps `downloads.download_one(...)` in `network_path_svc.force_family(...)`
  today; this version adds a second, composable context manager around the same call for the proxy
  case (active only when `proxy_url is not None`, mirroring the existing `if proxy_id is not None`
  branches already in that function).

## Open questions to resolve during implementation

- Whether `--proxy`'s CLI-level quoting inside `yt_dlp_args` needs anything beyond `shlex.quote` for
  a credentialed URL (`user:pass@host:port`) — verify against a real credentialed proxy, not a bare
  one, since that's the shape every proxy in this project's real `proxies.txt` actually takes.
- Whether yt-dlp's `--proxy` flag and its own `-4`/`-6` force-family flags can coexist in the same
  `yt_dlp_args` invocation without one clobbering the other's `source_address`/`proxy` yt-dlp option
  — matters only if a future ladder redesign ever wants both on the same attempt; verify it works
  even though today's ladder doesn't exercise it, since "works" here is cheap to prove and expensive
  to assume.

## Done when

- **Real empirical proof, both stacks**: the same `socket.socket.connect`-observation technique (or
  tcpdump, if available in whatever environment this lands in) shows a real ytmusicapi search *and* a
  real yt-dlp download both connecting to the configured proxy's address — not the origin's — using a
  real credentialed proxy, not a mocked one. This is the bullet the whole version exists for; it must
  not be waved through on "the flag was passed" the same way v07's original verification was.
- The existing proxy-rotation tests (fallback-to-direct when no proxy is configured, credential
  redaction in logs/`last_error`, cooldown-on-failure, LRU rotation) still pass unmodified in
  behavior — this fix changes *whether* the proxy is used, not the selection/health-tracking logic
  around it.
- New unit tests cover: the combined `yt_dlp_args` merge (family flag + proxy flag, independently and
  together), and the ytmusicapi `_create_client` patch (activates only when a proxy is set, restores
  correctly, rejects reentry).
- `docs/GOTCHAS.md`'s v07 entry gets a dated corrective note pointing here (not rewritten) — the
  "real downloads succeed through a real proxy end-to-end" claim was true about the download, wrong
  about the attribution.
- A one-line callout in the PR description (not a migration) that pre-v30 `Proxy.last_success_at`/
  `consecutive_failures`/`cooldown_until` values reflect direct-connection health, not proxy health.
- Both version files read `3.30.0`; `graphify update .`
