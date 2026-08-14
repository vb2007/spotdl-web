# v29 — Network-Path Escalation (IPv4 / IPv6)

Branch: `dev-network-path-escalation` → PR into `main`
Version: `3.29.0`

> **Unplanned insertion after v28.** Added during v3 on evidence from v23's root-cause session (see
> `00-master-plan.md`'s Amendments). The hardening close that was v29 is now **v30**, unchanged in
> content — same treatment v21's insertion gave v22.

## Scope

Add the other IP family as a real escalation rung in the retry ladder, before proxy.

## Why this exists — the proven gap

v23's investigation established, on real traffic:

- This project's public IPv4 was reputation-flagged by YouTube for an entire session — `yt-dlp -4`
  failed and `-6` succeeded, repeatedly, across multiple tracks. Not a one-off blip.
- **All five configured proxies failed identically.** The app's existing "direct → wait out the
  ladder → then proxy" escalation, which is the locked v1 mitigation of last resort, provably does
  **not** cover this failure mode. Cheap datacenter proxy IPs appear to get the same bot-check
  treatment.
- Docker's default bridge network has no IPv6 route, so every container is forced onto IPv4 with no
  fallback — the one path that worked was the one the containers can't take.

The owner's dev PC shares the same public IPv4 and IPv6 addresses as the production host (same home
connection), and IPv6 downloads were confirmed working there both in the local CLI and in local
Docker. So IPv6 viability for this network is established; what remains unverified is the
production Docker daemon's configuration and its blast radius.

This matters because the app's entire premise is dodging rate limits over an unbounded time
horizon. A mitigation ladder with a proven hole in it is worth closing while it's cheap, rather than
discovering it as a second outage.

## Prerequisite check — do this first, and stop if it fails

The production Docker daemon is **shared with other real services** (Matrix/Synapse, Vaultwarden).
Enabling daemon-level IPv6 affects them, not just this app.

Before building anything:

1. Confirm the production host has working IPv6 connectivity to YouTube (not just an address —
   actual reachability).
2. Determine whether `ip6tables: true` in `/etc/docker/daemon.json` is safe for the other services
   on that daemon, and what a rollback looks like. Docker's IPv6 support historically changes
   firewall behavior in ways that can surprise unrelated containers.

**If either answer is no, stop and report rather than pressing on.** A network change that breaks
Matrix or Vaultwarden to marginally improve this app's download resilience is a bad trade, and
CLAUDE.md's minimize-prod-disruption rule exists for exactly this. Falling back to "IPv6 on the dev
stack only, documented as unavailable in production" is an acceptable outcome for this version.

## Design

**New ladder rung, logically before proxy** — it's still a *direct* connection, just over the other
address family:

| Attempt | Path |
|---|---|
| 1 | direct, whatever the OS picks (today's behavior, unchanged) |
| 2 | direct, forced to the *other* family |
| 3+ | proxy, as today |

This slots in ahead of proxy because a different family on your own connection is cheaper, faster
and less suspicious than routing through a third party — consistent with the locked "direct first,
wait, then proxy" reasoning rather than replacing it.

**Forcing the family is the hard part.** Two independent HTTP stacks are in play:

- yt-dlp's own requests — `-4`/`-6` via spotdl's `yt_dlp_args` option. Verified during v23 to merge
  correctly without clobbering other settings.
- `ytmusicapi`'s separate search calls, which use a different client underneath.

v23 only forced the family at the raw socket level in testing, **not** through a flag that covers
both stacks. Establish what actually works for each before wiring it into the ladder; a rung that
only redirects half the traffic is worse than none, because it will look like it works.

`get_downloader`'s cache key must include the family, for the same reason it includes proxy — a
cached `Downloader` built for one family must never serve an attempt meant for the other.

**Recording it**: `track_attempts` already carries the nullable network-path column reserved by v24.
Populate it (`direct-ipv4` / `direct-ipv6` / `proxy`) rather than adding a new column.

## Open questions to resolve during implementation

Deliberately not decided now — they need real measurement, not planning:

- Does production's IPv6 have better peering/reliability for this traffic than its IPv4, or is it
  merely *different*? Only "different, and currently unflagged" is proven.
- Should the app prefer IPv6 by default once available, or only escalate to it on failure? Default
  behavior change is riskier; escalation-only is the conservative start and what this plan assumes.

## Done when

- The prerequisite check is documented with its actual findings, including the other services'
  safety — or the version stops there with that recorded.
- A track forced onto each family downloads successfully, proven per family against real traffic.
- **Both HTTP stacks** honour the forced family — verified by observing actual connections
  (`ss`/`tcpdump` or equivalent), not by trusting a flag was passed. This is the bullet most likely
  to be waved through.
- The ladder escalates in the documented order, with `track_attempts` recording the path used at
  each attempt — verified by SQL across a real multi-attempt track.
- `get_downloader`'s cache never serves a cross-family instance.
- Compose and daemon changes applied to local dev and production, with the other services on that
  daemon confirmed still healthy afterwards — explicitly checked, not assumed.
- Rollback documented in `docs/DEPLOYMENT.md`.
- Both version files read `3.29.0`; `graphify update .`
