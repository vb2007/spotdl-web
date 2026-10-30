"""Spotify URL allowlist, normalization and server-side cascades (v53).

`parse` accepts only `open.spotify.com` track/album/artist/playlist links (an `intl-xx` locale
segment and any query such as `?si=` are dropped) and gives back the canonical
`https://open.spotify.com/<type>/<id>`. Everything else is None: search text, other hosts,
`spotify:` URIs, podcasts. Key-authenticated and extension-origin job creates accept nothing
else (`routers/jobs.py`).

`resolve_cascade` turns a track into its album or artist, or an album into its artist, from
Spotify's own metadata (never from the page the extension saw). It runs in the request, as one
metadata call bounded by CASCADE_TIMEOUT_SECONDS, because an ambiguous artist must come back to
the client as a 409 with the candidates to choose from; a cascade resolved later, during
expansion, would have no one to ask.

`is_short_link`/`resolve_short_link` (v65) turn the `spotify.link/<code>` link Spotify's
mobile share sheet often hands out into the link it stands for, by asking Spotify's own short
link host (never following a redirect to anywhere else), and accept the answer only if `parse`
does.
"""

import concurrent.futures
import logging
import re
import threading
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from app.models import JobSourceType

logger = logging.getLogger(__name__)

SPOTIFY_HOST = "open.spotify.com"
_TYPES = {
    "track": JobSourceType.TRACK,
    "album": JobSourceType.ALBUM,
    "artist": JobSourceType.ARTIST,
    "playlist": JobSourceType.PLAYLIST,
}
# Spotify ids are 22 base-62 characters.
_ID_RE = re.compile(r"^[0-9A-Za-z]{22}$")
# The locale segment Spotify puts before the type for a non-English page: `intl-hu`, `intl-pt`,
# `intl-zh-hant`.
_INTL_RE = re.compile(r"^intl-[a-z]{2,3}(?:-[a-z0-9]{2,8})?$", re.IGNORECASE)

CASCADE_TIMEOUT_SECONDS = 10
# Bounds the metadata calls running at once. A call that outlives its request's timeout keeps
# its thread until spotdl gives up on its own (its client retries for up to about 90s), so a
# call that would only queue behind busy ones is refused at once instead (`_slots`).
_CASCADE_WORKERS = 4
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=_CASCADE_WORKERS, thread_name_prefix="cascade"
)
_slots = threading.BoundedSemaphore(_CASCADE_WORKERS)
# Spotify's "Various Artists" pseudo-artist, a compilation's only artist: its discography is
# every compilation on Spotify, never what an album's "artist" cascade means.
VARIOUS_ARTISTS_ID = "0LyfQWJT6nXafLPZqxe9Of"


@dataclass(frozen=True)
class SpotifyRef:
    type: str
    id: str

    @property
    def url(self) -> str:
        return f"https://{SPOTIFY_HOST}/{self.type}/{self.id}"

    @property
    def source_type(self) -> JobSourceType:
        return _TYPES[self.type]


def parse(text: str) -> SpotifyRef | None:
    """The track/album/artist/playlist `text` links to on open.spotify.com, or None."""
    text = text.strip()
    if any(c.isspace() for c in text):
        return None
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    if (parts.hostname or "").lower() != SPOTIFY_HOST:
        return None
    if parts.username is not None or parts.password is not None or port is not None:
        return None
    segments = [s for s in parts.path.split("/") if s]
    if segments and _INTL_RE.match(segments[0]):
        segments = segments[1:]
    if len(segments) != 2:
        return None
    kind, spotify_id = segments
    if kind not in _TYPES or not _ID_RE.match(spotify_id):
        return None
    return SpotifyRef(kind, spotify_id)


class CascadeInvalid(Exception):
    """The cascade doesn't apply to this kind of link (an album's album, a playlist's artist),
    or this link has no artist to cascade to (a compilation's "Various Artists")."""

    def __init__(self, reason: str = "type") -> None:
        super().__init__(reason)
        self.reason = reason


class CascadeNotFound(Exception):
    """Spotify has no such track or album."""


class CascadeUnavailable(Exception):
    """The metadata call failed or ran out of time (`reason` "failed"), or every metadata
    worker is busy (`reason` "busy")."""

    def __init__(self, reason: str = "failed") -> None:
        super().__init__(reason)
        self.reason = reason


def storable(text: str) -> bool:
    """Whether Postgres can store `text` and it can be UTF-8 encoded: no NUL, no lone surrogate."""
    return not any(c == "\x00" or 0xD800 <= ord(c) <= 0xDFFF for c in text)


class CascadeAmbiguous(Exception):
    def __init__(self, candidates: list[dict[str, str]]) -> None:
        super().__init__("more than one artist")
        self.candidates = candidates


# Which link types each cascade starts from.
CASCADE_SOURCES = {"album": {"track"}, "artist": {"track", "album"}}


def _fetch(ref: SpotifyRef) -> dict:
    # The one place outside expansion.py that talks to Spotify; it still goes through the
    # singleton guard (CLAUDE.md's invariant).
    from spotdl.utils.spotify import SpotifyClient

    from app.services.expansion import _ensure_spotify_client

    _ensure_spotify_client()
    client = SpotifyClient()
    return client.track(ref.id) if ref.type == "track" else client.album(ref.id)


def resolve_cascade(ref: SpotifyRef, cascade: str) -> SpotifyRef:
    """The album or artist `ref` cascades to. Raises CascadeInvalid, CascadeNotFound,
    CascadeUnavailable or CascadeAmbiguous (more than one artist: the client picks)."""
    if ref.type not in CASCADE_SOURCES.get(cascade, set()):
        raise CascadeInvalid
    if not _slots.acquire(blocking=False):
        logger.warning("cascade: every metadata worker is busy; refusing")
        raise CascadeUnavailable("busy")
    try:
        future = _executor.submit(_fetch, ref)
    except BaseException:
        _slots.release()
        raise
    # The slot is held until the call itself ends, not the request's wait for it.
    future.add_done_callback(lambda _: _slots.release())
    try:
        meta = future.result(timeout=CASCADE_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError as exc:
        logger.warning("cascade: %s %s metadata timed out", ref.type, ref.id)
        raise CascadeUnavailable from exc
    except KeyError as exc:
        # spotdl's scraping client indexes straight into Spotify's answer, so an id Spotify
        # doesn't know surfaces as a bare KeyError (expansion.expand's same case).
        raise CascadeNotFound from exc
    except Exception as exc:
        logger.warning("cascade: %s %s metadata failed: %s", ref.type, ref.id, type(exc).__name__)
        raise CascadeUnavailable from exc

    try:
        if cascade == "album":
            album_id = meta["album"]["id"]
            if not _ID_RE.match(album_id or ""):
                raise CascadeUnavailable
            return SpotifyRef("album", album_id)
        artists: dict[str, str] = {}
        for artist in meta["artists"]:
            artist_id = artist.get("id") or ""
            if (
                _ID_RE.match(artist_id)
                and artist_id != VARIOUS_ARTISTS_ID
                and artist_id not in artists
            ):
                artists[artist_id] = artist.get("name") or ""
        various = any((a.get("id") or "") == VARIOUS_ARTISTS_ID for a in meta["artists"])
    except (KeyError, TypeError, AttributeError) as exc:
        raise CascadeUnavailable from exc
    if not artists:
        if various:
            raise CascadeInvalid("various_artists")
        raise CascadeUnavailable
    if len(artists) > 1:
        raise CascadeAmbiguous(
            [{"name": name, "url": SpotifyRef("artist", artist_id).url} for artist_id, name in artists.items()]
        )
    return SpotifyRef("artist", next(iter(artists)))


# v65: Spotify's short links. `spotify.link` is what the share sheet hands out; it can answer
# with a hop to `spotify.app.link` (its link service's own host) before the real link.
SHORT_LINK_HOSTS = {"spotify.link", "spotify.app.link"}
_SHORT_CODE_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
SHORT_LINK_TIMEOUT_SECONDS = 5
SHORT_LINK_MAX_HOPS = 2
# Bounds the resolves at once, as `_slots` does the cascades: a request that would only queue
# behind busy ones is refused at once.
_short_link_slots = threading.BoundedSemaphore(4)


class ShortLinkUnresolved(Exception):
    """Spotify's short link host didn't point at a track/album/artist/playlist link: an expired or
    made-up code, or a link to something else (a podcast)."""


class ShortLinkUnavailable(Exception):
    """The short link host couldn't be reached or ran out of time (`reason` "failed"), or every
    resolve slot is busy (`reason` "busy")."""

    def __init__(self, reason: str = "failed") -> None:
        super().__init__(reason)
        self.reason = reason


def _short_link(text: str) -> str | None:
    """`text` as a short link on one of SHORT_LINK_HOSTS (https, a bare code path), or None."""
    text = text.strip()
    if any(c.isspace() for c in text):
        return None
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() != "https" or (parts.hostname or "").lower() not in SHORT_LINK_HOSTS:
        return None
    if parts.username is not None or parts.password is not None or port is not None:
        return None
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) != 1 or not _SHORT_CODE_RE.match(segments[0]):
        return None
    return f"https://{parts.hostname.lower()}/{segments[0]}"


def is_short_link(text: str) -> bool:
    return _short_link(text) is not None


def resolve_short_link(text: str) -> SpotifyRef:
    """The link a `spotify.link` short link stands for. Raises ShortLinkUnresolved or
    ShortLinkUnavailable (ValueError for text that isn't a short link at all).

    The host answers a plain HTTP client with a redirect to the real link and a browser with a
    page that redirects by script, so this asks as httpx (its own user agent) and reads the
    `Location` itself: only a hop to another short link host is followed, and the end of the
    chain must be a link `parse` accepts. An expired code answers 200 with a landing page."""
    url = _short_link(text)
    if url is None:
        raise ValueError("not a Spotify short link")
    if not _short_link_slots.acquire(blocking=False):
        logger.warning("short link: every resolve slot is busy; refusing")
        raise ShortLinkUnavailable("busy")
    try:
        with httpx.Client(follow_redirects=False, timeout=SHORT_LINK_TIMEOUT_SECONDS) as client:
            for _ in range(SHORT_LINK_MAX_HOPS):
                try:
                    response = client.get(url)
                except httpx.HTTPError as exc:
                    logger.warning("short link: %s unreachable: %s", url, type(exc).__name__)
                    raise ShortLinkUnavailable from exc
                if not response.is_redirect:
                    # The host refusing or throttling us says nothing about the link: retryable.
                    if response.status_code >= 500 or response.status_code in (403, 408, 429):
                        raise ShortLinkUnavailable
                    raise ShortLinkUnresolved
                location = response.headers.get("location")
                if not location:
                    raise ShortLinkUnresolved
                target = urljoin(url, location)
                ref = parse(target)
                if ref is not None:
                    return ref
                hop = _short_link(target)
                if hop is None:
                    raise ShortLinkUnresolved
                # Rebuilt from what was checked, its query kept (the code alone answers
                # differently), so the host asked is the one validated.
                query = urlsplit(target).query
                url = f"{hop}?{query}" if query else hop
    finally:
        _short_link_slots.release()
    raise ShortLinkUnresolved
