from app.services import downloads


class _FakeSettings:
    cookie_file = None


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
