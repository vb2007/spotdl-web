import pytest
from spotdl.providers.audio.base import AudioProviderError

from app.models import NetworkPath, TrackErrorType
from app.services import downloads, retry


class _FakeSettings:
    cookie_file = None
    youtube_player_clients = "android,web,mweb"


class _FakeTracker:
    def __init__(self):
        self.errors = []

    def notify_error(self, message, traceback, finish=False):
        self.errors.append(traceback)


class _FakeProgressHandler:
    def get_new_tracker(self, song):
        return _FakeTracker()


class _FakeDownloader:
    instances = []

    def __init__(self, options):
        self.options = options
        self.progress_handler = _FakeProgressHandler()
        _FakeDownloader.instances.append(self)

    def search_and_download(self, song):
        return (song, "fake-path")


class _SwallowingDownloader(_FakeDownloader):
    """Mirrors spotdl's real search_and_download: any exception inside it is handed to the
    song's tracker and swallowed, and the caller only ever sees a `None` path."""

    def __init__(self, exc):
        super().__init__(options={})
        self.exc = exc

    def search_and_download(self, song):
        tracker = self.progress_handler.get_new_tracker(song)
        tracker.notify_error("traceback text", self.exc, True)
        return (song, None)


def _chained(outer, cause):
    try:
        try:
            raise cause
        except Exception as inner:
            raise outer from inner
    except Exception as exc:
        return exc


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


def test_download_one_reraises_a_search_miss_spotdl_swallowed(monkeypatch):
    monkeypatch.setattr(downloads, "_ensure_spotify_client", lambda: None)
    downloader = _SwallowingDownloader(LookupError("No results found for song: Scooter - B.O.B."))

    with pytest.raises(LookupError, match="No results found") as excinfo:
        downloads.download_one("a-song", downloader)

    assert not isinstance(excinfo.value, downloads.AgeRestrictedError)
    assert retry.classify_error(excinfo.value) == TrackErrorType.LOOKUP


def test_download_one_turns_a_swallowed_age_gate_into_a_terminal_error(monkeypatch):
    monkeypatch.setattr(downloads, "_ensure_spotify_client", lambda: None)
    # The real shape: spotdl's AudioProviderError chained from yt-dlp's DownloadError.
    exc = _chained(
        AudioProviderError("YT-DLP download error - https://www.youtube.com/watch?v=bKBHz_K76us"),
        RuntimeError(
            "ERROR: [youtube] bKBHz_K76us: Sign in to confirm your age. Use --cookies-from-browser"
        ),
    )

    with pytest.raises(downloads.AgeRestrictedError, match="Age-restricted") as excinfo:
        downloads.download_one("a-song", _SwallowingDownloader(exc))

    assert retry.classify_error(excinfo.value) == TrackErrorType.LOOKUP


def test_download_one_keeps_a_bot_check_on_the_retry_ladder_with_its_reason(monkeypatch):
    monkeypatch.setattr(downloads, "_ensure_spotify_client", lambda: None)
    exc = _chained(
        AudioProviderError("YT-DLP download error - https://www.youtube.com/watch?v=x"),
        RuntimeError("ERROR: [youtube] x: Sign in to confirm you're not a bot\nmore detail"),
    )

    with pytest.raises(retry.NoOutputFileError) as excinfo:
        downloads.download_one("a-song", _SwallowingDownloader(exc))

    message = str(excinfo.value)
    assert message.startswith("spotdl returned no output file for this track (")
    assert "AudioProviderError: YT-DLP download error" in message
    assert "Sign in to confirm you're not a bot" in message
    assert "more detail" not in message
    assert retry.classify_error(excinfo.value) == TrackErrorType.NO_OUTPUT


def test_download_one_turns_a_dead_proxy_into_a_transport_error(monkeypatch):
    """v40.1, production's exact failure: ytmusicapi couldn't reach music.youtube.com
    through the proxy (raised while building the client, before any search). It used to
    become a breaker-feeding NoOutputFileError."""
    from requests.exceptions import ProxyError as RequestsProxyError

    monkeypatch.setattr(downloads, "_ensure_spotify_client", lambda: None)
    exc = RequestsProxyError(
        "HTTPSConnectionPool(host='music.youtube.com', port=443): Max retries exceeded with "
        "url: / (Caused by ProxyError('Unable to connect to proxy', ConnectTimeoutError()))"
    )

    with pytest.raises(retry.ProxyTransportError, match="the proxy was unreachable") as excinfo:
        downloads.download_one("a-song", _SwallowingDownloader(exc))

    assert retry.is_proxy_transport_error(excinfo.value)
    assert retry.classify_error(excinfo.value) == TrackErrorType.OTHER


def test_download_one_checks_the_proxy_before_any_video_marker(monkeypatch):
    """A dead proxy says nothing about the video, even if some other text on the chain
    happens to look like a hard failure."""
    monkeypatch.setattr(downloads, "_ensure_spotify_client", lambda: None)
    exc = _chained(
        AudioProviderError("YT-DLP download error - url"),
        RuntimeError("ERROR: Unable to connect to proxy; video has been removed?"),
    )

    with pytest.raises(retry.ProxyTransportError):
        downloads.download_one("a-song", _SwallowingDownloader(exc))


@pytest.mark.parametrize(
    "ytdlp_text",
    [
        "Sign in to confirm your age. This video may be inappropriate for some users.",
        "This video is age-restricted and only available on YouTube",
        "SIGN IN TO CONFIRM YOUR AGE",
    ],
)
def test_download_one_recognises_every_age_gate_wording(monkeypatch, ytdlp_text):
    monkeypatch.setattr(downloads, "_ensure_spotify_client", lambda: None)
    exc = _chained(AudioProviderError("YT-DLP download error - url"), RuntimeError(f"ERROR: [youtube] x: {ytdlp_text}"))

    with pytest.raises(downloads.AgeRestrictedError) as excinfo:
        downloads.download_one("a-song", _SwallowingDownloader(exc))

    assert retry.classify_error(excinfo.value) == TrackErrorType.LOOKUP


@pytest.mark.parametrize(
    "ytdlp_text",
    [
        "Private video. Sign in if you've been granted access to this video",
        "This video is private",
        "This video has been removed by the uploader",
        "This video has been removed for violating YouTube's Terms of Service",
        "This video is no longer available because the YouTube account associated with this video has been terminated.",
        "Join this channel to get access to members-only content like this video",
    ],
)
def test_download_one_makes_an_unavailable_video_terminal(monkeypatch, ytdlp_text):
    monkeypatch.setattr(downloads, "_ensure_spotify_client", lambda: None)
    exc = _chained(AudioProviderError("YT-DLP download error - url"), RuntimeError(f"ERROR: [youtube] x: {ytdlp_text}"))

    with pytest.raises(downloads.UnavailableVideoError, match="Unavailable on YouTube") as excinfo:
        downloads.download_one("a-song", _SwallowingDownloader(exc))

    assert ytdlp_text[:20] in str(excinfo.value)
    assert retry.classify_error(excinfo.value) == TrackErrorType.LOOKUP


@pytest.mark.parametrize(
    "ytdlp_text",
    [
        # Bot-check and rate-limit wording: network-dependent, must stay on the ladder.
        "Sign in to confirm you're not a bot",
        "Video unavailable. This content isn't available, try again later.",
        "Video unavailable",
        "HTTP Error 429: Too Many Requests",
        "HTTP Error 403: Forbidden",
        # Geo-blocking depends on the egress IP: another rung can change it.
        "The uploader has not made this video available in your country",
        "This video is not available from your location due to geo restriction",
    ],
)
def test_download_one_keeps_rate_limit_wording_on_the_ladder(monkeypatch, ytdlp_text):
    monkeypatch.setattr(downloads, "_ensure_spotify_client", lambda: None)
    exc = _chained(AudioProviderError("YT-DLP download error - url"), RuntimeError(f"ERROR: [youtube] x: {ytdlp_text}"))

    with pytest.raises(retry.NoOutputFileError) as excinfo:
        downloads.download_one("a-song", _SwallowingDownloader(exc))

    assert retry.classify_error(excinfo.value) == TrackErrorType.NO_OUTPUT


def test_download_one_chains_the_swallowed_error_it_replaces(monkeypatch):
    """download_track needs the original to recognise a dropped proxy connection."""
    from requests.exceptions import ConnectionError as RequestsConnectionError

    monkeypatch.setattr(downloads, "_ensure_spotify_client", lambda: None)
    original = RequestsConnectionError("('Connection aborted.', ConnectionResetError(104))")

    with pytest.raises(retry.NoOutputFileError) as excinfo:
        downloads.download_one("a-song", _SwallowingDownloader(original))

    assert excinfo.value.__cause__ is original
    assert retry.is_proxy_transport_error(excinfo.value, via_proxy=True)
    assert not retry.is_proxy_transport_error(excinfo.value)


def test_download_one_returns_none_when_spotdl_reported_no_error(monkeypatch):
    """Paths like a failed song reinit return None without notifying the tracker --
    nothing to raise, so the caller's own `output_path is None` handling still applies."""
    monkeypatch.setattr(downloads, "_ensure_spotify_client", lambda: None)

    class _SilentNone(_FakeDownloader):
        def search_and_download(self, song):
            return (song, None)

    assert downloads.download_one("a-song", _SilentNone(options={})) == ("a-song", None)


def test_download_one_restores_the_cached_downloaders_progress_handler(monkeypatch):
    monkeypatch.setattr(downloads, "_ensure_spotify_client", lambda: None)
    downloader = _SwallowingDownloader(LookupError("No results found"))

    with pytest.raises(LookupError):
        downloads.download_one("a-song", downloader)

    assert "get_new_tracker" not in vars(downloader.progress_handler)


def test_get_supported_output_options_reflects_the_real_installed_spotdl():
    # Not mocked -- this is the whole point of v13's fix: introspect the real installed
    # spotdl's argparse choices instead of hardcoding a list that could silently drift.
    options = downloads.get_supported_output_options()

    assert set(options["formats"]) == {"mp3", "flac", "ogg", "opus", "m4a", "wav"}
    assert "320k" in options["bitrates"]
    assert "auto" in options["bitrates"]
    assert "disable" in options["bitrates"]
