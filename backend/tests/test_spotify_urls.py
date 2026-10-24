"""v53: the Spotify allowlist's parser and the cascade resolver (spotdl mocked here; the real
metadata calls are evidenced against the slot stack)."""

import pytest

from app.services import spotify_urls
from app.services.spotify_urls import SpotifyRef

ID = "4aawyAB9vmqN3uQ7FjRGTy"


@pytest.mark.parametrize(
    "text,expected",
    [
        (f"https://open.spotify.com/album/{ID}", SpotifyRef("album", ID)),
        (f"https://open.spotify.com/track/{ID}?si=abc123", SpotifyRef("track", ID)),
        (f"https://open.spotify.com/intl-hu/track/{ID}?si=abc", SpotifyRef("track", ID)),
        (f"https://open.spotify.com/intl-pt/artist/{ID}", SpotifyRef("artist", ID)),
        (f"https://open.spotify.com/intl-zh-hant/playlist/{ID}", SpotifyRef("playlist", ID)),
        (f"  https://OPEN.spotify.com/playlist/{ID}/  ", SpotifyRef("playlist", ID)),
        (f"http://open.spotify.com/album/{ID}#frag", SpotifyRef("album", ID)),
        (f"https://open.spotify.com/album/{ID}?si=x&utm_source=copy-link", SpotifyRef("album", ID)),
    ],
)
def test_parse_accepts_and_normalizes_spotify_links(text, expected):
    assert spotify_urls.parse(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "daft punk one more time",
        "",
        f"spotify:track:{ID}",
        f"spotify:album:{ID}",
        f"https://example.com/track/{ID}",
        f"https://open.spotify.com.evil.example/track/{ID}",
        f"https://evil.example/?u=https://open.spotify.com/track/{ID}",
        f"https://user:pass@open.spotify.com/track/{ID}",
        f"https://open.spotify.com:8443/track/{ID}",
        f"https://open.spotify.com/episode/{ID}",
        f"https://open.spotify.com/show/{ID}",
        "https://open.spotify.com/track/short",
        f"https://open.spotify.com/track/{ID}/extra",
        f"https://open.spotify.com/user/someone/playlist/{ID}",
        f"https://open.spotify.com/intl-hu/intl-de/track/{ID}",
        f"ftp://open.spotify.com/track/{ID}",
        f"https://open.spotify.com/track/{ID} https://open.spotify.com/album/{ID}",
        f"https://www.youtube.com/watch?v={ID}",
        "https://[::1/track",
    ],
)
def test_parse_refuses_everything_else(text):
    assert spotify_urls.parse(text) is None


def test_ref_url_and_source_type():
    ref = SpotifyRef("artist", ID)
    assert ref.url == f"https://open.spotify.com/artist/{ID}"
    assert ref.source_type.value == "artist"


ALBUM = "4OHNH3sDzIxnmUADXzv2kT"
ARTIST_1 = "0C0XlULifJtAgn6ZNCW2eu"
ARTIST_2 = "0TnOYISbd1XYRBk9myaseg"


def _stub(monkeypatch, meta=None, exc=None):
    calls = []

    def fake_fetch(ref):
        calls.append(ref)
        if exc is not None:
            raise exc
        return meta

    monkeypatch.setattr(spotify_urls, "_fetch", fake_fetch)
    return calls


def test_track_cascades_to_its_album(monkeypatch):
    calls = _stub(monkeypatch, {"album": {"id": ALBUM}, "artists": [{"id": ARTIST_1, "name": "A"}]})
    assert spotify_urls.resolve_cascade(SpotifyRef("track", ID), "album") == SpotifyRef("album", ALBUM)
    assert calls == [SpotifyRef("track", ID)]


@pytest.mark.parametrize("kind", ["track", "album"])
def test_a_single_artist_cascades_to_that_artist(monkeypatch, kind):
    _stub(monkeypatch, {"artists": [{"id": ARTIST_1, "name": "The Killers"}]})
    assert spotify_urls.resolve_cascade(SpotifyRef(kind, ID), "artist") == SpotifyRef("artist", ARTIST_1)


def test_several_artists_are_ambiguous_with_candidates(monkeypatch):
    _stub(
        monkeypatch,
        {"artists": [{"id": ARTIST_1, "name": "One"}, {"id": ARTIST_2, "name": "Two"}, {"id": ARTIST_1, "name": "One"}]},
    )
    with pytest.raises(spotify_urls.CascadeAmbiguous) as caught:
        spotify_urls.resolve_cascade(SpotifyRef("track", ID), "artist")
    assert caught.value.candidates == [
        {"name": "One", "url": f"https://open.spotify.com/artist/{ARTIST_1}"},
        {"name": "Two", "url": f"https://open.spotify.com/artist/{ARTIST_2}"},
    ]


@pytest.mark.parametrize(
    "kind,cascade",
    [("album", "album"), ("artist", "album"), ("playlist", "album"), ("artist", "artist"), ("playlist", "artist")],
)
def test_a_cascade_that_doesnt_apply_is_invalid_without_a_metadata_call(monkeypatch, kind, cascade):
    calls = _stub(monkeypatch, {})
    with pytest.raises(spotify_urls.CascadeInvalid):
        spotify_urls.resolve_cascade(SpotifyRef(kind, ID), cascade)
    assert calls == []


def test_an_unknown_id_is_not_found(monkeypatch):
    _stub(monkeypatch, exc=KeyError("uri"))
    with pytest.raises(spotify_urls.CascadeNotFound):
        spotify_urls.resolve_cascade(SpotifyRef("track", ID), "album")


@pytest.mark.parametrize("meta", [{}, {"album": None}, {"album": {"id": "bad"}}, {"artists": []}])
def test_unexpected_metadata_is_unavailable(monkeypatch, meta):
    _stub(monkeypatch, meta)
    cascade = "album" if "album" in meta or not meta else "artist"
    with pytest.raises(spotify_urls.CascadeUnavailable):
        spotify_urls.resolve_cascade(SpotifyRef("track", ID), cascade)


def test_a_failing_or_slow_metadata_call_is_unavailable(monkeypatch):
    _stub(monkeypatch, exc=RuntimeError("network"))
    with pytest.raises(spotify_urls.CascadeUnavailable):
        spotify_urls.resolve_cascade(SpotifyRef("track", ID), "album")

    import threading

    release = threading.Event()
    monkeypatch.setattr(spotify_urls, "_fetch", lambda ref: release.wait(5))
    monkeypatch.setattr(spotify_urls, "CASCADE_TIMEOUT_SECONDS", 0.1)
    try:
        with pytest.raises(spotify_urls.CascadeUnavailable):
            spotify_urls.resolve_cascade(SpotifyRef("track", ID), "album")
    finally:
        release.set()
