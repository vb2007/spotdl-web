"""Credentialed-URL redaction for free-form text (v31, moved here from proxies.py in v36).

Stdlib-only on purpose: app/services/alerts.py's watchdog runs in its own small process,
and importing proxies.py there would pull in spotdl/ytmusicapi (~150 MB measured) just for
one regex. `proxies.redact_text` re-exports this, so callers keep using that name.
"""

import re

# v31: broader than PROXY_URL_RE (which anchors a whole, already-known-good, IPv4-only
# proxy string) -- this scans free-form text for anything shaped like a *credentialed*
# URL, host included (a hostname, not just an IPv4 literal -- proxies.txt/manual-add
# entries are IPv4-only, but sync_from_file() doesn't enforce that, so a hostname-based
# proxy already exists as a legitimate shape elsewhere in this codebase's own tests).
# Requires an actual `user:pass@` to be present -- a bare URL with nothing to redact
# (the overwhelmingly common case: spotdl/yt-dlp errors rarely echo a proxy URL at all)
# must never be rewritten, or this would mangle harmless URLs (a YouTube watch link,
# say) that happen to appear in an error message. Used to replace download_track's old
# exact-substring guard (`if proxy_url in error_message`), which only caught a leak when
# the message embedded that literal `proxy_url` string byte-for-byte -- see
# docs/GOTCHAS.md's v30 entry for the case that guard could miss (a re-wrapped or
# differently-formatted exception).
_EMBEDDED_CREDENTIALED_URL_RE = re.compile(
    r"(https?://)[^\s:@/]+:[^\s:@/]+@([\w.-]+)(?::(\d{1,5}))?"
)


def redact_text(text: str) -> str:
    """Redacts every credentialed-URL-shaped substring found anywhere in `text`, not
    just an exact match against one known proxy URL. Safe to call unconditionally
    (including on text with no embedded credentialed URL at all, which it returns
    unchanged) -- apply this to any exception message before it's logged or persisted
    (`tracks.last_error`, `track_attempts.error_message`), the same way `redact()`
    already applies to a proxy URL that's being logged directly and in full."""

    def _sub(match: "re.Match[str]") -> str:
        scheme, host, port = match.group(1), match.group(2), match.group(3)
        return f"{scheme}{host}:{port}" if port else f"{scheme}{host}"

    return _EMBEDDED_CREDENTIALED_URL_RE.sub(_sub, text)
