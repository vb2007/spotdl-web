"""v65: Spotify short links (`spotify.link/<code>`) and `POST /api/links/resolve`, the `/share`
page's look-up before it queues anything. The short link host is mocked here with httpx's
MockTransport; the real host's answers are evidenced against the slot stack."""

import httpx
import pytest

from app.services import spotify_urls
from app.services.spotify_urls import SpotifyRef
from extension_support import bearer, fake_redis  # noqa: F401 (fixtures)

ID = "432nsnOM9L55tkiOFnHbI2"
# What spotify.link answered httpx's user agent for a real playlist share (2026-10-30).
REAL_LOCATION = (
    f"https://open.spotify.com/playlist/{ID}?si=s1MRgeESTQ2OK4Rn-xpXtw&pi=a-rG9J6UAVS9-1&nd=1"
    "&_branch_match_id=link-1309853438317810280"
)


@pytest.fixture()
def short_host(monkeypatch):
    """Routes the resolver's httpx client to `answers` (url -> response or exception) and
    records every url it asked for."""
    answers: dict[str, httpx.Response | Exception] = {}
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        answer = answers.get(url, httpx.Response(404))
        if isinstance(answer, Exception):
            raise answer
        return answer

    real_client = httpx.Client

    def client(**kwargs):
        assert kwargs.get("follow_redirects") is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(spotify_urls.httpx, "Client", client)
    return answers, asked


def _redirect(location: str, status: int = 307) -> httpx.Response:
    return httpx.Response(status, headers={"Location": location})


@pytest.mark.parametrize(
    "text",
    [
        "https://spotify.link/6tpneu0iVIb",
        "  https://SPOTIFY.link/6tpneu0iVIb  ",
        "https://spotify.link/6tpneu0iVIb?x=1",
        "https://spotify.app.link/6tpneu0iVIb",
    ],
)
def test_is_short_link_accepts_spotifys_short_links(text):
    assert spotify_urls.is_short_link(text)


@pytest.mark.parametrize(
    "text",
    [
        "http://spotify.link/6tpneu0iVIb",
        "https://spotify.link/",
        "https://spotify.link/a/b",
        "https://spotify.link.evil.example/6tpneu0iVIb",
        "https://evil.example/?u=https://spotify.link/6tpneu0iVIb",
        "https://user@spotify.link/6tpneu0iVIb",
        "https://spotify.link:8443/6tpneu0iVIb",
        "https://spotify.link/6tpneu0iVIb https://spotify.link/other",
        "https://spotify.link/bad%2Fcode",
        f"https://open.spotify.com/track/{ID}",
        "spotify.link/6tpneu0iVIb",
    ],
)
def test_is_short_link_refuses_everything_else(text):
    assert not spotify_urls.is_short_link(text)


def test_resolve_reads_the_redirect_without_following_it(short_host):
    answers, asked = short_host
    answers["https://spotify.link/6tpneu0iVIb"] = _redirect(REAL_LOCATION)
    assert spotify_urls.resolve_short_link("https://spotify.link/6tpneu0iVIb?x=1") == SpotifyRef("playlist", ID)
    # Asked once, for the bare code; the open.spotify.com target itself is never fetched.
    assert asked == ["https://spotify.link/6tpneu0iVIb"]


def test_resolve_follows_one_hop_to_the_link_services_own_host(short_host):
    answers, asked = short_host
    hop = "https://spotify.app.link/6tpneu0iVIb?_p=c91629c09c0b7af2e31e90fcef"
    answers["https://spotify.link/6tpneu0iVIb"] = _redirect(hop)
    answers[hop] = _redirect(f"https://open.spotify.com/intl-hu/track/{ID}?si=x", 302)
    assert spotify_urls.resolve_short_link("https://spotify.link/6tpneu0iVIb") == SpotifyRef("track", ID)
    assert asked == ["https://spotify.link/6tpneu0iVIb", hop]


def test_a_hop_is_asked_as_validated(short_host):
    # The host asked is rebuilt from the checked parts, not the raw Location (review round 1).
    answers, asked = short_host
    answers["https://spotify.link/a"] = _redirect("https://SPOTIFY.app.link/b/?_p=1")
    answers["https://spotify.app.link/b?_p=1"] = _redirect(REAL_LOCATION)
    assert spotify_urls.resolve_short_link("https://spotify.link/a") == SpotifyRef("playlist", ID)
    assert asked == ["https://spotify.link/a", "https://spotify.app.link/b?_p=1"]


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/track",
        f"https://open.spotify.com/episode/{ID}",
        f"http://spotify.link/{ID}",
        "",
    ],
)
def test_resolve_never_follows_a_redirect_anywhere_else(short_host, location):
    answers, asked = short_host
    answers["https://spotify.link/6tpneu0iVIb"] = _redirect(location)
    with pytest.raises(spotify_urls.ShortLinkUnresolved):
        spotify_urls.resolve_short_link("https://spotify.link/6tpneu0iVIb")
    assert asked == ["https://spotify.link/6tpneu0iVIb"]


def test_resolve_gives_up_after_its_hops(short_host):
    answers, asked = short_host
    answers["https://spotify.link/a"] = _redirect("https://spotify.app.link/b")
    answers["https://spotify.app.link/b"] = _redirect("https://spotify.link/c")
    answers["https://spotify.link/c"] = _redirect(REAL_LOCATION)
    with pytest.raises(spotify_urls.ShortLinkUnresolved):
        spotify_urls.resolve_short_link("https://spotify.link/a")
    assert len(asked) == spotify_urls.SHORT_LINK_MAX_HOPS


def test_an_expired_codes_landing_page_is_unresolved(short_host):
    answers, _ = short_host
    answers["https://spotify.link/h5TbcGLLkhb"] = httpx.Response(200, text="<html>Spotify</html>")
    with pytest.raises(spotify_urls.ShortLinkUnresolved):
        spotify_urls.resolve_short_link("https://spotify.link/h5TbcGLLkhb")


@pytest.mark.parametrize(
    "answer",
    [
        httpx.ConnectTimeout("slow"),
        httpx.ConnectError("down"),
        httpx.Response(502),
        # Refused or throttled: retryable, not "this link is dead" (review round 1).
        httpx.Response(429),
        httpx.Response(403),
        httpx.Response(408),
    ],
)
def test_an_unreachable_host_is_unavailable(short_host, answer):
    answers, _ = short_host
    answers["https://spotify.link/6tpneu0iVIb"] = answer
    with pytest.raises(spotify_urls.ShortLinkUnavailable) as raised:
        spotify_urls.resolve_short_link("https://spotify.link/6tpneu0iVIb")
    assert raised.value.reason == "failed"


def test_every_slot_busy_is_refused_at_once(short_host, monkeypatch):
    import threading

    monkeypatch.setattr(spotify_urls, "_short_link_slots", threading.BoundedSemaphore(1))
    spotify_urls._short_link_slots.acquire()
    with pytest.raises(spotify_urls.ShortLinkUnavailable) as raised:
        spotify_urls.resolve_short_link("https://spotify.link/6tpneu0iVIb")
    assert raised.value.reason == "busy"
    assert short_host[1] == []


def test_a_slot_is_given_back_after_a_failure(short_host):
    answers, _ = short_host
    answers["https://spotify.link/6tpneu0iVIb"] = httpx.ConnectError("down")
    for _ in range(6):
        with pytest.raises(spotify_urls.ShortLinkUnavailable):
            spotify_urls.resolve_short_link("https://spotify.link/6tpneu0iVIb")


# --- POST /api/links/resolve ---


def test_resolve_endpoint_answers_a_short_links_target(authenticated_client, short_host):
    answers, _ = short_host
    answers["https://spotify.link/6tpneu0iVIb"] = _redirect(REAL_LOCATION)
    response = authenticated_client.post("/api/links/resolve", json={"url": "https://spotify.link/6tpneu0iVIb"})
    assert response.status_code == 200, response.text
    assert response.json() == {"url": f"https://open.spotify.com/playlist/{ID}", "type": "playlist", "id": ID}


def test_resolve_endpoint_normalizes_a_full_link_without_asking_anyone(authenticated_client, short_host):
    response = authenticated_client.post(
        "/api/links/resolve", json={"url": f"https://open.spotify.com/intl-hu/album/{ID}?si=abc"}
    )
    assert response.json() == {"url": f"https://open.spotify.com/album/{ID}", "type": "album", "id": ID}
    assert short_host[1] == []


@pytest.mark.parametrize(
    "url",
    ["daft punk", "https://evil.example/x", f"spotify:track:{ID}", "https://spotify.link/a\x00b"],
)
def test_resolve_endpoint_refuses_anything_else(authenticated_client, short_host, url):
    response = authenticated_client.post("/api/links/resolve", json={"url": url})
    assert response.status_code == 422
    assert response.json()["code"] == "url_not_spotify"
    assert short_host[1] == []


def test_resolve_endpoint_refuses_a_lone_surrogate(authenticated_client, short_host):
    response = authenticated_client.post(
        "/api/links/resolve", content='{"url": "https://spotify.link/\\ud800"}', headers={"Content-Type": "application/json"}
    )
    assert (response.status_code, response.json()["code"]) == (422, "url_not_spotify")
    assert short_host[1] == []


def test_resolve_endpoint_codes_for_an_unresolved_and_an_unavailable_link(authenticated_client, short_host):
    answers, _ = short_host
    answers["https://spotify.link/dead"] = httpx.Response(200, text="landing page")
    answers["https://spotify.link/down"] = httpx.ConnectError("down")
    dead = authenticated_client.post("/api/links/resolve", json={"url": "https://spotify.link/dead"})
    assert (dead.status_code, dead.json()["code"]) == (422, "short_link_unresolved")
    down = authenticated_client.post("/api/links/resolve", json={"url": "https://spotify.link/down"})
    assert (down.status_code, down.json()["code"]) == (503, "short_link_unavailable")
    assert down.json()["params"] == {"reason": "failed"}


def test_resolve_endpoint_needs_a_session(client, short_host):
    response = client.post("/api/links/resolve", json={"url": f"https://open.spotify.com/track/{ID}"})
    assert response.status_code == 401


def test_resolve_endpoint_refuses_an_api_key(authenticated_client, short_host):
    # v53: a key submits and reads `me`, nothing else.
    created = authenticated_client.post("/api/account/api-keys", json={"label": "phone"}).json()
    authenticated_client.cookies.clear()
    response = authenticated_client.post(
        "/api/links/resolve", json={"url": f"https://open.spotify.com/track/{ID}"}, headers=bearer(created["key"])
    )
    assert response.status_code == 401


def test_resolve_endpoint_is_rate_limited_per_user(authenticated_client, owner, short_host, fake_redis, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "job_create_rate_limit", 2)
    url = {"url": f"https://open.spotify.com/track/{ID}"}
    assert [authenticated_client.post("/api/links/resolve", json=url).status_code for _ in range(2)] == [200, 200]
    over = authenticated_client.post("/api/links/resolve", json=url)
    assert (over.status_code, over.json()["code"]) == (429, "rate_limited")
    assert int(over.headers["Retry-After"]) >= 1
    # Its own bucket: the resolves left the user's job create count alone.
    assert fake_redis.get(f"spotdl:ratelimit:create:user:{owner.id}") is None

