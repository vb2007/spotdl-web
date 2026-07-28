"""Thin wrapper around spotdl's URL-expansion logic.

Never import spotdl.utils.search directly outside this module — this is the one place
that knows about SpotifyClient's singleton-init quirk (see _ensure_spotify_client).
"""

import threading

from spotdl.types.song import Song
from spotdl.utils.search import get_simple_songs
from spotdl.utils.spotify import SpotifyClient, SpotifyError

from app.config import get_settings

# spotdl's own publicly-shipped default Spotify app credentials (spotdl.utils.config.
# DEFAULT_CONFIG) — used whenever SPOTIFY_CLIENT_ID/SECRET aren't overridden.
_DEFAULT_CLIENT_ID = "5f573c9620494bae87890c0f08a60293"
_DEFAULT_CLIENT_SECRET = "212476d9b0f3472eaa762d90b19b0ba8"

_init_lock = threading.Lock()


def _ensure_spotify_client() -> None:
    """SpotifyClient is a process-wide singleton that raises if .init() runs twice, so
    every caller must go through this idempotent check instead of calling .init() directly."""

    try:
        SpotifyClient()
        return
    except SpotifyError:
        pass

    with _init_lock:
        try:
            SpotifyClient()
            return
        except SpotifyError:
            pass

        settings = get_settings()
        SpotifyClient.init(
            client_id=settings.spotify_client_id or _DEFAULT_CLIENT_ID,
            client_secret=settings.spotify_client_secret or _DEFAULT_CLIENT_SECRET,
        )


def expand(query: str) -> list[Song]:
    """Turn a Spotify URL (track/album/playlist/artist) or a search term into Songs."""

    _ensure_spotify_client()
    return get_simple_songs([query], use_ytm_data=False, playlist_numbering=False)
