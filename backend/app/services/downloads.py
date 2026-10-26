"""Thin wrapper around spotdl's download machinery.

Never construct a `Downloader` outside this module — building one initializes every
audio/lyrics provider, so it must be cached per (format, bitrate, output_dir,
output_template, proxy) rather than built per track (see get_downloader).
"""

import shlex
import threading
from pathlib import Path

from spotdl.download.downloader import Downloader
from spotdl.types.options import DownloaderOptions
from spotdl.types.song import Song
from spotdl.utils.arguments import create_parser

from app.config import get_settings
from app.models import NetworkPath
from app.services.expansion import _ensure_spotify_client
from app.services.retry import NoOutputFileError, ProxyTransportError, is_proxy_transport_error

# yt-dlp's own -4/-6 flags (see get_downloader below) -- confirmed against the installed
# yt_dlp source (yt_dlp/options.py) to set source_address to '0.0.0.0'/'::' and nothing else.
_YT_DLP_ARGS_BY_PATH = {
    NetworkPath.DIRECT_IPV4: "-4",
    NetworkPath.DIRECT_IPV6: "-6",
}

# format/bitrate/output_dir/output_template are now sourced from the DB-backed
# app.services.app_settings (v13), passed in by the caller -- keeping them in the cache
# key (rather than a separate version counter) is what makes a settings change actually
# invalidate the right cached Downloader instances. `network_path` (v29) joins proxy as a
# construction-time setting baked into yt_dlp_args -- a Downloader built with `-4` baked
# in must never be reused for a `-6` attempt.
_downloader_cache: dict[
    tuple[str, str, str, str, str | None, str | None], Downloader
] = {}
_cache_lock = threading.Lock()


def get_downloader(
    format: str,
    bitrate: str,
    output_dir: str,
    output_template: str,
    proxy: str | None = None,
    network_path: NetworkPath | None = None,
) -> Downloader:
    key = (
        format,
        bitrate,
        output_dir,
        output_template,
        proxy,
        network_path.value if network_path else None,
    )
    if key in _downloader_cache:
        return _downloader_cache[key]

    with _cache_lock:
        if key in _downloader_cache:
            return _downloader_cache[key]

        settings = get_settings()
        options: DownloaderOptions = {
            "format": format,
            "bitrate": bitrate,
            "output": str(Path(output_dir) / output_template),
            "cookie_file": settings.cookie_file,
            # ProgressHandler defaults to a rich Live TUI display (simple_tui=False) —
            # harmless with a single cached Downloader per process (v05/v06), but rich
            # only allows one Live display per process at all, ever. v07 is the first
            # version where a worker-dl process can construct a *second*, differently
            # keyed Downloader (direct first, then a distinct one per proxy) within its
            # lifetime, which crashed with rich.errors.LiveError until this was set —
            # caught during real-stack proxy-rotation testing, not by unit tests (the
            # unit tests fake out get_downloader entirely). Also just the right call for
            # a headless worker with no terminal to render to; progress goes through
            # progress_handler hooks (see v08), never this TUI.
            "simple_tui": True,
        }
        if proxy:
            # Reaches spotdl's GlobalConfig (piped/bandcamp/sliderkz/lyrics providers) --
            # never youtube-music, the only audio provider this app configures. Kept
            # anyway since it's harmless and genuinely proxies the lyrics providers; the
            # yt_dlp_args --proxy fragment below is what actually reaches yt-dlp's own
            # connection for the youtube-music download itself (v30).
            options["proxy"] = proxy

        # Combined from up to three independent fragments (v30, v31.1) rather than the old
        # either/or mapping: the family flag (only for the two direct rungs), a --proxy
        # flag (only when a proxy was selected), and the player-client override (always).
        # Built generally, not asserting today's ladder never wants more than one at once
        # -- see v30's plan doc.
        yt_dlp_arg_parts = []
        family_flag = _YT_DLP_ARGS_BY_PATH.get(network_path) if network_path else None
        if family_flag:
            yt_dlp_arg_parts.append(family_flag)
        if proxy:
            # shlex-quoted defensively: proxies.txt's format is a bare IPv4 host today
            # (proxies.PROXY_URL_RE), but a credentialed user:pass@host:port is already
            # accepted and a future format loosening could introduce shlex-special
            # characters -- quote now rather than assume the regex is forever.
            yt_dlp_arg_parts.append(f"--proxy {shlex.quote(proxy)}")
        # v31.1: always applied, independent of family/proxy forcing -- see
        # youtube_player_clients's own docstring in config.py for why this exists at all.
        yt_dlp_arg_parts.append(
            "--extractor-args "
            + shlex.quote(f"youtube:player_client={settings.youtube_player_clients}")
        )
        options["yt_dlp_args"] = " ".join(yt_dlp_arg_parts)

        downloader = Downloader(options)
        _downloader_cache[key] = downloader
        return downloader


def get_supported_output_options() -> dict[str, list[str]]:
    """The real, live set of --format/--bitrate values the installed spotdl accepts —
    introspected from its own argparse definition (spotdl.utils.arguments.create_parser)
    rather than a hardcoded list here that would silently drift the moment spotdl adds,
    renames, or removes a choice. create_parser() only builds argparse groups (no argv
    parsing, no I/O), so calling it purely for introspection is safe and cheap.

    Uses ArgumentParser's private _option_string_actions map -- there's no public
    argparse API for "give me this flag's choices" short of parsing --help text, and a
    KeyError here (spotdl renaming/removing --format or --bitrate) is preferable to
    silently falling back to a stale hardcoded list."""
    parser = create_parser()
    format_action = parser._option_string_actions["--format"]
    bitrate_action = parser._option_string_actions["--bitrate"]
    return {
        "formats": list(format_action.choices),
        "bitrates": list(bitrate_action.choices),
    }


class AgeRestrictedError(LookupError):
    """The matched YouTube video is age-gated ("Sign in to confirm your age"). A property
    of the video, not of this network or the moment, so no amount of waiting or proxying
    changes it -- a LookupError so it lands terminal (`lookup_failed`), which a user can
    still retry by hand once a cookie file is configured."""


class UnavailableVideoError(LookupError):
    """The matched YouTube video is private, removed, from a terminated account or members-
    only (v40.1). Like the age gate, a property of the video that no retry
    changes, so terminal (`lookup_failed`) and still retryable by hand."""


class NotYetReleasedError(LookupError):
    """The matched YouTube video is a scheduled premiere or live event that hasn't aired
    (v54.1): it has no formats until then, from any network. Production's track went round
    the ladder as a breaker-feeding `no_output` with "Premieres in 102 days" on every
    attempt. Terminal (`lookup_failed`) by the owner's call, like a video that isn't there;
    "retry now" brings it back once it has aired."""


# yt-dlp's own wording, matched case-insensitively. Distinct from its bot-check ("Sign in
# to confirm you're not a bot") and its rate-limit text ("This content isn't available,
# try again later", a bare "Video unavailable"), which *are* network-dependent and must
# stay on the retry ladder -- none of these markers is a substring of those.
_AGE_GATE_MARKERS = (
    "confirm your age",
    "age-restricted",
    "inappropriate for some users",
)
_UNAVAILABLE_MARKERS = (
    "private video",
    "video is private",
    "video has been removed",
    "account associated with this video has been terminated",
    "members-only",
)
# YouTube's playability reason for an upcoming video, which yt-dlp raises verbatim
# (`raise_no_formats(reason)`): "Premieres in 102 days", "Premiere will begin shortly",
# "This live event will begin in 3 hours".
_UPCOMING_MARKERS = (
    "premieres in",
    "premiere will begin",
    "this live event will begin",
)
# Deliberately absent: geo-blocking ("not made this video available in your country",
# yt-dlp's GeoRestrictedError). It depends on the egress IP, so the IPv6 and proxy rungs
# can still change it; it stays on the ladder.


def _chain_text_has(chain: list[BaseException], markers: tuple[str, ...]) -> bool:
    return any(marker in str(e).lower() for e in chain for marker in markers)


def _swallowed_error_to_raise(exc: BaseException) -> Exception:
    """Map the exception spotdl swallowed to what the caller should see instead of a bare
    `None` output path."""
    chain = []
    cur: BaseException | None = exc
    while cur is not None and cur not in chain:
        chain.append(cur)
        cur = cur.__cause__ or cur.__context__
    # spotdl's own message is often just "YT-DLP download error - <url>"; the reason
    # (403, bot-check, ...) is on the yt-dlp exception it chains from.
    detail = f"{type(exc).__name__}: {exc}"
    root = chain[-1]
    if root is not exc:
        root_line = str(root).strip().splitlines()[0] if str(root).strip() else ""
        detail += f" <- {type(root).__name__}: {root_line[:300]}"
    # First: a dead proxy says nothing about the video, whatever else is on the chain.
    if is_proxy_transport_error(exc):
        return ProxyTransportError(f"the proxy was unreachable ({detail})")
    if _chain_text_has(chain, _AGE_GATE_MARKERS):
        return AgeRestrictedError(f"Age-restricted on YouTube (sign-in required): {exc}")
    if _chain_text_has(chain, _UNAVAILABLE_MARKERS):
        return UnavailableVideoError(f"Unavailable on YouTube: {detail}")
    if _chain_text_has(chain, _UPCOMING_MARKERS):
        return NotYetReleasedError(f"Not released yet on YouTube: {detail}")
    if isinstance(exc, LookupError):
        return exc
    return NoOutputFileError(f"spotdl returned no output file for this track ({detail})")


def download_one(song: Song, downloader: Downloader) -> tuple[Song, Path | None]:
    """Must be called from a plain sync context — search_and_download raises
    DownloaderError if a asyncio event loop is already running in this thread.

    spotdl's search_and_download catches *every* exception (a search with no match, an
    age-gated video, a yt-dlp 403...) and returns a `None` path instead, so on its own
    every one of them looks identical. The exception it swallowed is still handed to the
    song's progress tracker (`notify_error`), so it's captured there and raised in its
    place: a LookupError/age gate as the terminal error it really is, anything else as a
    NoOutputFileError carrying the real reason."""

    # search_and_download "reinitializes" the song (re-fetches missing metadata like
    # genres/album_id/track_number, common for album/playlist-expanded songs) via a live
    # SpotifyClient — worker-dl is a separate process from worker-meta and never
    # otherwise initializes one, so every such reinit failed with "Spotify client not
    # created" until this call was added (caught during real album-download testing).
    _ensure_spotify_client()

    swallowed: list[BaseException] = []
    handler = downloader.progress_handler
    original_get_new_tracker = handler.get_new_tracker

    def capturing_get_new_tracker(tracked_song):
        tracker = original_get_new_tracker(tracked_song)
        original_notify_error = tracker.notify_error

        # spotdl names the exception argument `traceback`.
        def notify_error(message, traceback, finish=False):
            swallowed.append(traceback)
            return original_notify_error(message, traceback, finish)

        tracker.notify_error = notify_error
        return tracker

    handler.get_new_tracker = capturing_get_new_tracker
    try:
        result_song, output_path = downloader.search_and_download(song)
    finally:
        # Drop the instance override so the cached Downloader's handler is left exactly
        # as spotdl built it.
        del handler.get_new_tracker

    if output_path is None and swallowed:
        mapped = _swallowed_error_to_raise(swallowed[-1])
        if mapped is swallowed[-1]:
            raise mapped
        # Chained, so download_track can still read the original: on a proxied attempt a
        # plain connection error underneath is the proxy's failure (retry.
        # is_proxy_transport_error), which only the caller knows to look for.
        raise mapped from swallowed[-1]
    return result_song, output_path
