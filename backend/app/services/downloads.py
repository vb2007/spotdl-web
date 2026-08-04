"""Thin wrapper around spotdl's download machinery.

Never construct a `Downloader` outside this module — building one initializes every
audio/lyrics provider, so it must be cached per (format, bitrate, output_dir,
output_template, proxy) rather than built per track (see get_downloader).
"""

import threading
from pathlib import Path

from spotdl.download.downloader import Downloader
from spotdl.types.options import DownloaderOptions
from spotdl.types.song import Song

from app.config import get_settings
from app.services.expansion import _ensure_spotify_client

# format/bitrate/output_dir/output_template are now sourced from the DB-backed
# app.services.app_settings (v13), passed in by the caller -- keeping them in the cache
# key (rather than a separate version counter) is what makes a settings change actually
# invalidate the right cached Downloader instances.
_downloader_cache: dict[tuple[str, str, str, str, str | None], Downloader] = {}
_cache_lock = threading.Lock()


def get_downloader(
    format: str,
    bitrate: str,
    output_dir: str,
    output_template: str,
    proxy: str | None = None,
) -> Downloader:
    key = (format, bitrate, output_dir, output_template, proxy)
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
            options["proxy"] = proxy

        downloader = Downloader(options)
        _downloader_cache[key] = downloader
        return downloader


def download_one(song: Song, downloader: Downloader) -> tuple[Song, Path | None]:
    """Must be called from a plain sync context — search_and_download raises
    DownloaderError if a asyncio event loop is already running in this thread."""

    # search_and_download "reinitializes" the song (re-fetches missing metadata like
    # genres/album_id/track_number, common for album/playlist-expanded songs) via a live
    # SpotifyClient — worker-dl is a separate process from worker-meta and never
    # otherwise initializes one, so every such reinit failed with "Spotify client not
    # created" until this call was added (caught during real album-download testing).
    _ensure_spotify_client()
    return downloader.search_and_download(song)
