from app.services import downloads


class _FakeSettings:
    download_output_dir = "/downloads"
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


def test_get_downloader_caches_per_format_bitrate_proxy(monkeypatch):
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    first = downloads.get_downloader("mp3", "320k")
    second = downloads.get_downloader("mp3", "320k")

    assert first is second
    assert len(_FakeDownloader.instances) == 1


def test_get_downloader_builds_new_instance_for_different_key(monkeypatch):
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    mp3 = downloads.get_downloader("mp3", "320k")
    flac = downloads.get_downloader("flac", "320k")
    proxied = downloads.get_downloader("mp3", "320k", proxy="http://proxy:8080")

    assert mp3 is not flac
    assert mp3 is not proxied
    assert len(_FakeDownloader.instances) == 3


def test_get_downloader_builds_output_template_from_settings_dir(monkeypatch):
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    downloader = downloads.get_downloader("mp3", "320k")

    assert downloader.options["output"] == "/downloads/{artists} - {title}.{output-ext}"
    assert downloader.options["format"] == "mp3"
    assert downloader.options["bitrate"] == "320k"
    assert "proxy" not in downloader.options


def test_get_downloader_sets_proxy_only_when_given(monkeypatch):
    monkeypatch.setattr(downloads, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(downloads, "Downloader", _FakeDownloader)

    downloader = downloads.get_downloader("mp3", "320k", proxy="http://proxy:8080")

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
