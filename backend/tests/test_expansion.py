import pytest
from spotdl.utils.spotify import SpotifyClient

from app.services import expansion


@pytest.fixture(autouse=True)
def _reset_spotify_client():
    original = SpotifyClient._instance
    SpotifyClient._instance = None
    yield
    SpotifyClient._instance = original


class _FakeSettings:
    spotify_client_id = None
    spotify_client_secret = None


def _fake_init(monkeypatch):
    calls = []

    def fake_init(cls, client_id, client_secret):
        calls.append((client_id, client_secret))
        cls._instance = "fake-spotify-client"

    monkeypatch.setattr(SpotifyClient, "init", classmethod(fake_init))
    return calls


def test_ensure_spotify_client_initializes_once(monkeypatch):
    monkeypatch.setattr(expansion, "get_settings", lambda: _FakeSettings())
    calls = _fake_init(monkeypatch)

    expansion._ensure_spotify_client()
    expansion._ensure_spotify_client()

    assert len(calls) == 1


def test_ensure_spotify_client_uses_default_creds_when_unset(monkeypatch):
    monkeypatch.setattr(expansion, "get_settings", lambda: _FakeSettings())
    calls = _fake_init(monkeypatch)

    expansion._ensure_spotify_client()

    assert calls == [(expansion._DEFAULT_CLIENT_ID, expansion._DEFAULT_CLIENT_SECRET)]


def test_ensure_spotify_client_prefers_configured_creds(monkeypatch):
    class _ConfiguredSettings:
        spotify_client_id = "custom-id"
        spotify_client_secret = "custom-secret"

    monkeypatch.setattr(expansion, "get_settings", lambda: _ConfiguredSettings())
    calls = _fake_init(monkeypatch)

    expansion._ensure_spotify_client()

    assert calls == [("custom-id", "custom-secret")]


def test_expand_delegates_to_get_simple_songs(monkeypatch):
    monkeypatch.setattr(expansion, "_ensure_spotify_client", lambda: None)

    captured = {}

    def fake_get_simple_songs(query, use_ytm_data=False, playlist_numbering=False):
        captured["query"] = query
        captured["use_ytm_data"] = use_ytm_data
        captured["playlist_numbering"] = playlist_numbering
        return ["song-1"]

    monkeypatch.setattr(expansion, "get_simple_songs", fake_get_simple_songs)

    result = expansion.expand("https://open.spotify.com/track/abc")

    assert result == ["song-1"]
    assert captured == {
        "query": ["https://open.spotify.com/track/abc"],
        "use_ytm_data": False,
        "playlist_numbering": False,
    }
