"""Thin wrapper around spotdl's download machinery.

Never construct a `Downloader` outside this module — building one initializes every
audio/lyrics provider, so it must be cached per (format, bitrate, proxy) rather than
built per track (see get_downloader).
"""

import threading
from pathlib import Path

from spotdl.download.downloader import Downloader
from spotdl.types.options import DownloaderOptions
from spotdl.types.song import Song

from app.config import get_settings
from app.services.expansion import _ensure_spotify_client

# spotdl's own default output filename template (spotdl.utils.config.DEFAULT_CONFIG
# ["output"]), joined with our configurable output directory. Per-template UI override
# is deferred to v13 — today only the directory is configurable.
_OUTPUT_TEMPLATE = "{artists} - {title}.{output-ext}"

_downloader_cache: dict[tuple[str, str, str | None], Downloader] = {}
_cache_lock = threading.Lock()


def get_downloader(format: str, bitrate: str, proxy: str | None = None) -> Downloader:
    key = (format, bitrate, proxy)
    if key in _downloader_cache:
        return _downloader_cache[key]

    with _cache_lock:
        if key in _downloader_cache:
            return _downloader_cache[key]

        settings = get_settings()
        options: DownloaderOptions = {
            "format": format,
            "bitrate": bitrate,
            "output": str(Path(settings.download_output_dir) / _OUTPUT_TEMPLATE),
            "cookie_file": settings.cookie_file,
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
