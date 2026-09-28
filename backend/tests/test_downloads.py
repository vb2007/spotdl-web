from app.models import NetworkPath
from app.services import downloads


class _FakeSettings:
    cookie_file = None
    youtube_player_clients = "android,web,mweb"


class _FakeDownloader:
    instances = []

    def __init__(self, options):
        self.options = options
        _FakeDownloader.instances.append(self)

    def search_and_download(self, song):
        return (song, "fake-path")


def setup_function():
    downloads._downloader_cache.clear()
    _FakeDownloader.instances.clear()


def test_get_downloader_caches_per_format_bitrate_output_and_proxy(monkeypatch):
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    first = downloads.get_downloader("mp3", "320k", "/downloads", "{title}.{output-ext}")
    second = downloads.get_downloader("mp3", "320k", "/downloads", "{title}.{output-ext}")

    assert first is second
    assert len(_FakeDownloader.instances) == 1


def test_get_downloader_builds_new_instance_for_different_key(monkeypatch):
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    mp3 = downloads.get_downloader("mp3", "320k", "/downloads", "{title}.{output-ext}")
    flac = downloads.get_downloader("flac", "320k", "/downloads", "{title}.{output-ext}")
    proxied = downloads.get_downloader(
        "mp3", "320k", "/downloads", "{title}.{output-ext}", proxy="http://proxy:8080"
    )
    other_dir = downloads.get_downloader("mp3", "320k", "/elsewhere", "{title}.{output-ext}")
    other_template = downloads.get_downloader("mp3", "320k", "/downloads", "{artists} - {title}.{output-ext}")

    assert len({id(d) for d in (mp3, flac, proxied, other_dir, other_template)}) == 5
    assert len(_FakeDownloader.instances) == 5


def test_get_downloader_builds_output_from_given_dir_and_template(monkeypatch):
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    downloader = downloads.get_downloader("mp3", "320k", "/downloads", "{artists} - {title}.{output-ext}")

    assert downloader.options["output"] == "/downloads/{artists} - {title}.{output-ext}"
    assert downloader.options["format"] == "mp3"
    assert downloader.options["bitrate"] == "320k"
    assert "proxy" not in downloader.options


def test_get_downloader_always_disables_rich_tui(monkeypatch):
    # simple_tui defaults to False in spotdl, which builds a rich Live display — harmless
    # with a single cached Downloader, but rich only allows one Live per process, and v07
    # can construct a second, differently-keyed Downloader (direct, then per-proxy) within
    # one worker-dl process's lifetime. Caught via real-stack testing, see CLAUDE.md.
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    downloader = downloads.get_downloader("mp3", "320k", "/downloads", "{title}.{output-ext}")

    assert downloader.options["simple_tui"] is True


def test_get_downloader_sets_proxy_only_when_given(monkeypatch):
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    downloader = downloads.get_downloader(
        "mp3", "320k", "/downloads", "{title}.{output-ext}", proxy="http://proxy:8080"
    )

    assert downloader.options["proxy"] == "http://proxy:8080"


def test_get_downloader_builds_new_instance_for_different_network_path(monkeypatch):
    # v29: a Downloader built with `-4` baked into yt_dlp_args must never be reused for a
    # `-6` (or unforced) attempt -- see get_downloader's own docstring comment.
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    unforced = downloads.get_downloader("mp3", "320k", "/downloads", "{title}.{output-ext}")
    ipv4 = downloads.get_downloader(
        "mp3", "320k", "/downloads", "{title}.{output-ext}", network_path=NetworkPath.DIRECT_IPV4
    )
    ipv6 = downloads.get_downloader(
        "mp3", "320k", "/downloads", "{title}.{output-ext}", network_path=NetworkPath.DIRECT_IPV6
    )

    assert len({id(d) for d in (unforced, ipv4, ipv6)}) == 3
    assert len(_FakeDownloader.instances) == 3


def test_get_downloader_sets_yt_dlp_args_for_forced_family(monkeypatch):
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    ipv4 = downloads.get_downloader(
        "mp3", "320k", "/downloads", "{title}.{output-ext}", network_path=NetworkPath.DIRECT_IPV4
    )
    ipv6 = downloads.get_downloader(
        "mp3", "320k", "/downloads", "{title}.{output-ext}", network_path=NetworkPath.DIRECT_IPV6
    )

    assert ipv4.options["yt_dlp_args"] == "-4 --extractor-args youtube:player_client=android,web,mweb"
    assert ipv6.options["yt_dlp_args"] == "-6 --extractor-args youtube:player_client=android,web,mweb"


def test_get_downloader_sets_only_player_client_for_proxy_or_unforced(monkeypatch):
    # A proxy attempt's destination is a literal IPv4 host (proxies.PROXY_URL_RE) --
    # forcing a family for it would be meaningless, so PROXY with no proxy URL given
    # (like None) omits the family flag rather than baking in a redundant/wrong one.
    # yt_dlp_args itself is never absent though (v31.1) -- the player-client override
    # always applies, regardless of family/proxy forcing.
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    unforced = downloads.get_downloader("mp3", "320k", "/downloads", "{title}.{output-ext}")
    proxied = downloads.get_downloader(
        "mp3", "320k", "/downloads", "{title}.{output-ext}", network_path=NetworkPath.PROXY
    )

    expected = "--extractor-args youtube:player_client=android,web,mweb"
    assert unforced.options["yt_dlp_args"] == expected
    assert proxied.options["yt_dlp_args"] == expected


def test_get_downloader_sets_proxy_flag_in_yt_dlp_args_when_proxy_given(monkeypatch):
    # v30: yt-dlp's own requests (search-result extraction and the actual media download)
    # need their own --proxy flag -- spotdl's `options["proxy"]` never reaches them (only
    # piped/bandcamp/sliderkz/lyrics providers read GlobalConfig's proxies parameter).
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    downloader = downloads.get_downloader(
        "mp3",
        "320k",
        "/downloads",
        "{title}.{output-ext}",
        proxy="http://203.0.113.5:8080",
        network_path=NetworkPath.PROXY,
    )

    assert downloader.options["yt_dlp_args"] == (
        "--proxy http://203.0.113.5:8080 --extractor-args youtube:player_client=android,web,mweb"
    )


def test_get_downloader_shlex_quotes_a_credentialed_proxy_in_yt_dlp_args(monkeypatch):
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    downloader = downloads.get_downloader(
        "mp3",
        "320k",
        "/downloads",
        "{title}.{output-ext}",
        proxy="http://user:pass@203.0.113.5:8080",
        network_path=NetworkPath.PROXY,
    )

    assert downloader.options["yt_dlp_args"] == (
        "--proxy http://user:pass@203.0.113.5:8080 "
        "--extractor-args youtube:player_client=android,web,mweb"
    )
    # Round-trips through shlex.split the same way spotdl's own base.py consumes it.
    import shlex

    assert shlex.split(downloader.options["yt_dlp_args"]) == [
        "--proxy",
        "http://user:pass@203.0.113.5:8080",
        "--extractor-args",
        "youtube:player_client=android,web,mweb",
    ]


def test_get_downloader_reads_player_client_list_from_settings(monkeypatch):
    # v31.1: configurable, not hardcoded -- YOUTUBE_PLAYER_CLIENTS needs to be retunable
    # without a redeploy the same way LADDER_SECONDS/PACING_*_SEC already are, since
    # yt-dlp/YouTube's own client-blocking behavior is a moving target.
    class _CustomSettings(_FakeSettings):
        youtube_player_clients = "tv,ios"

    monkeypatch.setattr(downloads, "get_settings", lambda: _CustomSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    downloader = downloads.get_downloader("mp3", "320k", "/downloads", "{title}.{output-ext}")

    assert downloader.options["yt_dlp_args"] == "--extractor-args youtube:player_client=tv,ios"


def test_get_downloader_combines_family_and_proxy_flags(monkeypatch):
    # Today's ladder never actually needs both on the same attempt (PROXY never forces a
    # family), but the merge is built generally rather than asserting that exclusivity --
    # see v30's plan doc.
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    downloader = downloads.get_downloader(
        "mp3",
        "320k",
        "/downloads",
        "{title}.{output-ext}",
        proxy="http://203.0.113.5:8080",
        network_path=NetworkPath.DIRECT_IPV4,
    )

    assert downloader.options["yt_dlp_args"] == (
        "-4 --proxy http://203.0.113.5:8080 --extractor-args youtube:player_client=android,web,mweb"
    )


def test_download_one_delegates_to_search_and_download(monkeypatch):
    monkeypatch.setattr(downloads, "_ensure_spotify_client", lambda: None)
    downloader = _FakeDownloader(options={})

    result = downloads.download_one("a-song", downloader)

    assert result == ("a-song", "fake-path")


def test_download_one_ensures_spotify_client_before_downloading(monkeypatch):
    calls = []
    monkeypatch.setattr(downloads, "_ensure_spotify_client", lambda: calls.append(True))
    downloader = _FakeDownloader(options={})

    downloads.download_one("a-song", downloader)

    assert calls == [True]


def test_get_supported_output_options_reflects_the_real_installed_spotdl():
    # Not mocked -- this is the whole point of v13's fix: introspect the real installed
    # spotdl's argparse choices instead of hardcoding a list that could silently drift.
    options = downloads.get_supported_output_options()

    assert set(options["formats"]) == {"mp3", "flac", "ogg", "opus", "m4a", "wav"}
    assert "320k" in options["bitrates"]
    assert "auto" in options["bitrates"]
    assert "disable" in options["bitrates"]
