"""`/api/links/resolve` (v65): what a shared Spotify link stands for, before anything is queued.

The `/share` page (the PWA's share target) shows the type and id it would queue and waits for
a confirm. A full `open.spotify.com` link it reads itself; a `spotify.link` short link, the
form Spotify's mobile share sheet often hands out, needs Spotify's short link host to say what
it points at, and that is this endpoint. Cookie session only (`require_session`): an API key
submits and reads `me`, nothing else (v53). It creates nothing; the page then submits the
canonical link to `POST /api/jobs` like any other.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.routers.auth import require_session
from app.routers.jobs import MAX_SUBMIT_LENGTH
from app.services import rate_limit, spotify_urls

router = APIRouter(prefix="/api/links", tags=["links"])


class ResolveLinkRequest(BaseModel):
    url: str


@router.post("/resolve")
def resolve_link(
    payload: ResolveLinkRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """The canonical link, type and id a Spotify link (full or short) stands for. 422
    `url_not_spotify` for anything else, 422 `short_link_unresolved` for a short link that
    points nowhere usable, 503 `short_link_unavailable` when Spotify's host can't answer."""
    user_id = user.id
    # The short link call can take seconds: never with a transaction idling open across it
    # (v31's idle-in-transaction lesson).
    db.commit()
    rate_limit.hit_link_resolve(user_id)
    url = payload.url
    if len(url) > MAX_SUBMIT_LENGTH:
        # Job create's bound, so a huge body isn't walked before its 422.
        raise ApiError(
            422,
            "submit_too_long",
            f"A link or search is at most {MAX_SUBMIT_LENGTH} characters",
            {"max": MAX_SUBMIT_LENGTH},
        )
    ref = spotify_urls.parse(url) if spotify_urls.storable(url) else None
    if ref is None:
        if not (spotify_urls.storable(url) and spotify_urls.is_short_link(url)):
            raise ApiError(
                422, "url_not_spotify", "Only open.spotify.com track, album, artist or playlist links"
            )
        try:
            ref = spotify_urls.resolve_short_link(url)
        except spotify_urls.ShortLinkUnresolved:
            raise ApiError(
                422,
                "short_link_unresolved",
                "Spotify's short link doesn't point at a track, album, artist or playlist",
            ) from None
        except spotify_urls.ShortLinkUnavailable as exc:
            raise ApiError(
                503,
                "short_link_unavailable",
                "Spotify's short link service didn't answer; try again shortly",
                {"reason": exc.reason},
            ) from None
    return {"url": ref.url, "type": ref.type, "id": ref.id}
