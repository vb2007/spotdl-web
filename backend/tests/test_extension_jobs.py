"""v53: job create for the extension -- the Spotify allowlist for key and extension-origin
requests, canonical links, server-side cascades, the duplicate hint, and the rate limits."""

import uuid

import pytest

from app.config import get_settings
from app.models import DownloadedTrack, Job, JobState, Track, TrackState
from app.routers import auth as auth_router
from app.routers import jobs as jobs_router
from app.services import spotify_urls
from app.services.redaction import redact_text
from extension_support import api_keys_table, bearer, fake_redis  # noqa: F401 (fixtures)

pytestmark = pytest.mark.usefixtures("api_keys_table", "fake_redis")

TRACK_ID = "3n3Ppam7vgaVa1iaRUc9Lp"
ALBUM_ID = "4OHNH3sDzIxnmUADXzv2kT"
ARTIST_ID = "0C0XlULifJtAgn6ZNCW2eu"
EXTENSION = {"X-Spotdl-Client": "extension/0.1.0"}


@pytest.fixture(autouse=True)
def _no_expansion(monkeypatch):
    enqueued = []
    monkeypatch.setattr(jobs_router.expand_job, "delay", lambda job_id: enqueued.append(job_id))
    return enqueued


@pytest.fixture()
def user_key(authenticated_client, client) -> str:
    raw = authenticated_client.post("/api/account/api-keys", json={"label": "ext"}).json()["key"]
    client.cookies.clear()
    return raw


# --- allowlist ----------------------------------------------------------------------------

REFUSED = [
    "never gonna give you up",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    f"spotify:track:{TRACK_ID}",
    f"spotify:album:{ALBUM_ID}",
    f"https://open.spotify.com/episode/{TRACK_ID}",
]


@pytest.mark.parametrize("url", REFUSED)
def test_a_key_may_submit_only_spotify_links(client, user_key, db_session, url):
    response = client.post("/api/jobs", json={"url": url}, headers=bearer(user_key))
    assert response.status_code == 422
    assert response.json()["code"] == "url_not_spotify"
    assert db_session.query(Job).count() == 0


@pytest.mark.parametrize("url", REFUSED)
def test_the_extension_header_with_a_cookie_is_held_to_the_same_allowlist(authenticated_client, db_session, url):
    response = authenticated_client.post("/api/jobs", json={"url": url}, headers=EXTENSION)
    assert response.status_code == 422
    assert response.json()["code"] == "url_not_spotify"
    assert db_session.query(Job).count() == 0


@pytest.mark.parametrize(
    "url,expected",
    [
        (f"https://open.spotify.com/intl-hu/track/{TRACK_ID}?si=0123abcd", f"https://open.spotify.com/track/{TRACK_ID}"),
        (f"https://open.spotify.com/album/{ALBUM_ID}?si=zz", f"https://open.spotify.com/album/{ALBUM_ID}"),
        (f"https://open.spotify.com/intl-de/artist/{ARTIST_ID}", f"https://open.spotify.com/artist/{ARTIST_ID}"),
        (f"https://open.spotify.com/playlist/{ALBUM_ID}/", f"https://open.spotify.com/playlist/{ALBUM_ID}"),
    ],
)
def test_a_key_submission_is_stored_canonical(client, user_key, db_session, url, expected):
    response = client.post("/api/jobs", json={"url": url}, headers=bearer(user_key))
    assert response.status_code == 201
    assert response.json()["source_url"] == expected
    assert db_session.get(Job, uuid.UUID(response.json()["id"])).source_url == expected


def test_the_web_ui_cookie_still_submits_search_text(authenticated_client):
    response = authenticated_client.post("/api/jobs", json={"url": "daft punk one more time"})
    assert response.status_code == 201
    assert response.json()["source_type"] == "search"
    assert response.json()["source_url"] == "daft punk one more time"
    assert response.json()["hint"] is None


def test_the_web_ui_cookie_gets_canonical_spotify_links_too(authenticated_client):
    url = f"https://open.spotify.com/intl-hu/album/{ALBUM_ID}?si=x"
    response = authenticated_client.post("/api/jobs", json={"url": url})
    assert response.json()["source_url"] == f"https://open.spotify.com/album/{ALBUM_ID}"


# --- cascades -----------------------------------------------------------------------------


def _metadata(monkeypatch, meta):
    calls = []

    def fake_fetch(ref):
        calls.append(ref)
        return meta

    monkeypatch.setattr(spotify_urls, "_fetch", fake_fetch)
    return calls


def test_track_cascade_album_creates_the_album_job(client, user_key, monkeypatch):
    _metadata(monkeypatch, {"album": {"id": ALBUM_ID}, "artists": [{"id": ARTIST_ID, "name": "A"}]})
    response = client.post(
        "/api/jobs",
        json={"url": f"https://open.spotify.com/track/{TRACK_ID}", "cascade": "album"},
        headers=bearer(user_key),
    )
    assert response.status_code == 201
    assert response.json()["source_type"] == "album"
    assert response.json()["source_url"] == f"https://open.spotify.com/album/{ALBUM_ID}"


@pytest.mark.parametrize("kind", ["track", "album"])
def test_cascade_artist_creates_the_artist_job(client, user_key, monkeypatch, kind):
    _metadata(monkeypatch, {"artists": [{"id": ARTIST_ID, "name": "The Killers"}]})
    response = client.post(
        "/api/jobs",
        json={"url": f"https://open.spotify.com/{kind}/{ALBUM_ID}", "cascade": "artist"},
        headers=bearer(user_key),
    )
    assert response.status_code == 201
    assert response.json()["source_type"] == "artist"
    assert response.json()["source_url"] == f"https://open.spotify.com/artist/{ARTIST_ID}"


def test_an_ambiguous_artist_is_409_with_candidates_and_creates_nothing(client, user_key, monkeypatch, db_session):
    other = "0TnOYISbd1XYRBk9myaseg"
    _metadata(monkeypatch, {"artists": [{"id": ARTIST_ID, "name": "One"}, {"id": other, "name": "Two"}]})
    response = client.post(
        "/api/jobs",
        json={"url": f"https://open.spotify.com/track/{TRACK_ID}", "cascade": "artist"},
        headers=bearer(user_key),
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "cascade_ambiguous"
    assert body["params"]["candidates"] == [
        {"name": "One", "url": f"https://open.spotify.com/artist/{ARTIST_ID}"},
        {"name": "Two", "url": f"https://open.spotify.com/artist/{other}"},
    ]
    assert db_session.query(Job).count() == 0


@pytest.mark.parametrize(
    "url,cascade,status,code",
    [
        (f"https://open.spotify.com/album/{ALBUM_ID}", "album", 422, "cascade_invalid"),
        (f"https://open.spotify.com/playlist/{ALBUM_ID}", "artist", 422, "cascade_invalid"),
        (f"https://open.spotify.com/artist/{ARTIST_ID}", "artist", 422, "cascade_invalid"),
        ("search words", "album", 422, "url_not_spotify"),
    ],
)
def test_a_cascade_that_doesnt_apply_is_refused(authenticated_client, monkeypatch, url, cascade, status, code):
    calls = _metadata(monkeypatch, {})
    # The cookie web UI too: a cascade needs a Spotify link whatever the caller.
    response = authenticated_client.post("/api/jobs", json={"url": url, "cascade": cascade})
    assert response.status_code == status
    assert response.json()["code"] == code
    assert calls == []


def test_a_cascade_spotify_cant_answer_is_503(client, user_key, monkeypatch):
    def broken(ref):
        raise RuntimeError("down")

    monkeypatch.setattr(spotify_urls, "_fetch", broken)
    response = client.post(
        "/api/jobs",
        json={"url": f"https://open.spotify.com/track/{TRACK_ID}", "cascade": "album"},
        headers=bearer(user_key),
    )
    assert response.status_code == 503
    assert response.json()["code"] == "cascade_unavailable"


def test_an_unknown_cascade_value_is_a_validation_error(client, user_key):
    response = client.post(
        "/api/jobs",
        json={"url": f"https://open.spotify.com/track/{TRACK_ID}", "cascade": "playlist"},
        headers=bearer(user_key),
    )
    assert response.status_code == 422


# --- hint ---------------------------------------------------------------------------------


def test_a_resubmit_of_an_unfinished_job_returns_it_with_200(client, user_key, db_session, _no_expansion):
    url = f"https://open.spotify.com/album/{ALBUM_ID}"
    first = client.post("/api/jobs", json={"url": url}, headers=bearer(user_key))
    assert first.status_code == 201
    assert first.json()["hint"] is None

    # Still expanding: already queued.
    again = client.post("/api/jobs", json={"url": f"{url}?si=other"}, headers=bearer(user_key))
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["hint"] == "already_queued"
    assert db_session.query(Job).count() == 1
    assert _no_expansion == [first.json()["id"]]

    # Expanded with a track still waiting: still queued.
    job = db_session.get(Job, uuid.UUID(first.json()["id"]))
    job.state = JobState.EXPANDED
    track = Track(job_id=job.id, spotify_track_id=TRACK_ID, song_json={"name": "S"}, state=TrackState.WAITING)
    db_session.add(track)
    db_session.commit()
    assert client.post("/api/jobs", json={"url": url}, headers=bearer(user_key)).status_code == 200

    # Settled: a new job.
    track.state = TrackState.COMPLETED
    db_session.commit()
    settled = client.post("/api/jobs", json={"url": url}, headers=bearer(user_key))
    assert settled.status_code == 201
    assert settled.json()["id"] != first.json()["id"]


@pytest.mark.parametrize("state", [JobState.FAILED, JobState.CANCELLED])
def test_a_failed_or_cancelled_job_is_not_already_queued(authenticated_client, db_session, owner, state):
    url = f"https://open.spotify.com/album/{ALBUM_ID}"
    db_session.add(Job(source_url=url, source_type="album", state=state, user_id=owner.id))
    db_session.commit()
    assert authenticated_client.post("/api/jobs", json={"url": url}).status_code == 201


def test_an_archived_unfinished_job_is_not_already_queued(authenticated_client, db_session, owner):
    from datetime import datetime, timezone

    url = f"https://open.spotify.com/album/{ALBUM_ID}"
    db_session.add(
        Job(source_url=url, source_type="album", state=JobState.EXPANDING, user_id=owner.id, archived_at=datetime.now(timezone.utc))
    )
    db_session.commit()
    assert authenticated_client.post("/api/jobs", json={"url": url}).status_code == 201


def test_another_users_unfinished_job_is_not_already_queued(client, session_cookie, db_session, make_user):
    url = f"https://open.spotify.com/album/{ALBUM_ID}"
    other = make_user("other@example.com")
    db_session.add(Job(source_url=url, source_type="album", state=JobState.EXPANDING, user_id=other.id))
    db_session.commit()
    client.cookies.update(session_cookie("allowed@example.com"))
    response = client.post("/api/jobs", json={"url": url})
    assert response.status_code == 201
    assert response.json()["hint"] is None


def test_a_track_already_in_the_ledger_is_in_library_and_still_created(client, user_key, db_session):
    db_session.add(DownloadedTrack(spotify_track_id=TRACK_ID, file_path="/downloads/a.mp3", format="mp3"))
    db_session.commit()
    response = client.post(
        "/api/jobs", json={"url": f"https://open.spotify.com/track/{TRACK_ID}"}, headers=bearer(user_key)
    )
    assert response.status_code == 201
    assert response.json()["hint"] == "in_library"
    # An album isn't checked track by track.
    album = client.post(
        "/api/jobs", json={"url": f"https://open.spotify.com/album/{ALBUM_ID}"}, headers=bearer(user_key)
    )
    assert album.json()["hint"] is None


# --- rate limits --------------------------------------------------------------------------


@pytest.fixture()
def low_limits(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "job_create_rate_limit", 3)
    monkeypatch.setattr(settings, "job_create_rate_limit_window_seconds", 60)
    monkeypatch.setattr(settings, "login_rate_limit_failures", 2)
    monkeypatch.setattr(settings, "login_rate_limit_window_seconds", 900)
    return settings


def test_the_m_plus_first_create_is_429_with_retry_after(authenticated_client, low_limits, fake_redis):
    for i in range(3):
        assert authenticated_client.post("/api/jobs", json={"url": f"search {i}"}).status_code == 201
    response = authenticated_client.post("/api/jobs", json={"url": "search 4"})
    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert 1 <= int(response.headers["Retry-After"]) <= 60
    assert response.json()["params"]["retry_after"] == int(response.headers["Retry-After"])

    # The window ends: allowed again.
    fake_redis.values.clear()
    fake_redis.expires.clear()
    assert authenticated_client.post("/api/jobs", json={"url": "search 5"}).status_code == 201


def test_create_limit_is_per_user(client, session_cookie, low_limits):
    a = session_cookie("a@example.com")
    b = session_cookie("b@example.com")
    for i in range(3):
        client.cookies.clear()
        client.cookies.update(a)
        assert client.post("/api/jobs", json={"url": f"a {i}"}).status_code == 201
    assert client.post("/api/jobs", json={"url": "a 4"}).status_code == 429
    client.cookies.clear()
    client.cookies.update(b)
    assert client.post("/api/jobs", json={"url": "b 1"}).status_code == 201


def test_a_keys_creates_count_against_its_user_too(client, authenticated_client, low_limits):
    cookie = dict(authenticated_client.cookies)
    raw = authenticated_client.post("/api/account/api-keys", json={"label": "k"}).json()["key"]
    client.cookies.clear()
    for i in range(3):
        url = f"https://open.spotify.com/album/{ALBUM_ID[:-1]}{i}"
        assert client.post("/api/jobs", json={"url": url}, headers=bearer(raw)).status_code == 201
    client.cookies.update(cookie)
    assert client.post("/api/jobs", json={"url": "search"}).status_code == 429


def _fail_upstream(monkeypatch):
    async def fake(email, password):
        return (password == "right"), None

    monkeypatch.setattr(auth_router.upstream_auth, "login", fake)


def test_the_n_plus_first_failed_login_is_429_even_with_the_right_password(client, monkeypatch, low_limits, fake_redis):
    _fail_upstream(monkeypatch)
    for _ in range(2):
        response = client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "wrong"})
        assert response.status_code == 401
    response = client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "right"})
    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert 1 <= int(response.headers["Retry-After"]) <= 900

    # Another address isn't held back by this one's failures.
    other = client.post(
        "/api/auth/login",
        json={"email": "allowed@example.com", "password": "right"},
        headers={"X-Real-IP": "198.51.100.7"},
    )
    assert other.status_code == 200

    fake_redis.values.clear()
    fake_redis.expires.clear()
    assert client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "right"}).status_code == 200


def test_a_successful_login_clears_the_failures(client, monkeypatch, low_limits):
    _fail_upstream(monkeypatch)
    login = lambda pw: client.post("/api/auth/login", json={"email": "allowed@example.com", "password": pw})  # noqa: E731
    assert login("wrong").status_code == 401
    assert login("right").status_code == 200
    assert login("wrong").status_code == 401
    assert login("right").status_code == 200


def test_a_redis_outage_lets_requests_through(authenticated_client, monkeypatch, low_limits):
    import redis

    from app.services import rate_limit

    class Down:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise redis.ConnectionError("down")

            return fail

    monkeypatch.setattr(rate_limit, "_redis", lambda: Down())
    for i in range(5):
        assert authenticated_client.post("/api/jobs", json={"url": f"s {i}"}).status_code == 201


def test_a_zero_limit_turns_the_limiter_off(authenticated_client, monkeypatch, fake_redis):
    monkeypatch.setattr(get_settings(), "job_create_rate_limit", 0)
    monkeypatch.setattr(get_settings(), "login_rate_limit_failures", 0)
    for i in range(40):
        assert authenticated_client.post("/api/jobs", json={"url": f"s {i}"}).status_code == 201
    assert fake_redis.values == {}


# --- redaction ----------------------------------------------------------------------------


def test_redact_text_strips_an_api_keys_secret_and_keeps_its_prefix():
    raw = "sdw_0a1b2c3d_Q2xhdWRlLWtleS1zZWNyZXQtMDEyMzQ1Njc4OWFiY2RlZg_-x"
    text = f"401 for Authorization: Bearer {raw} (retrying)"
    redacted = redact_text(text)
    assert raw not in redacted
    assert "Q2xhdWRl" not in redacted
    assert "Bearer sdw_0a1b2c3d_[redacted] (retrying)" in redacted
    assert redact_text("no key here, just sdw_ and sdw_short") == "no key here, just sdw_ and sdw_short"
    # Together with the credentialed-URL pattern it already had.
    both = redact_text(f"via http://u:p@198.51.100.9:8080 with {raw}")
    assert "u:p@" not in both and raw not in both


def test_the_log_formatter_redacts_a_key_too():
    import logging

    from app.logging_config import JsonFormatter

    raw = "sdw_0a1b2c3d_" + "A" * 43
    record = logging.LogRecord("t", logging.WARNING, __file__, 1, f"saw {raw}", None, None)
    line = JsonFormatter().format(record)
    assert raw not in line
    assert "sdw_0a1b2c3d_[redacted]" in line


def test_a_login_attempt_counts_before_the_upstream_is_asked(client, monkeypatch, low_limits, fake_redis):
    """Review round 1 (M1): counted first, so parallel guesses can't all read the same count."""
    seen = []

    async def fake(email, password):
        seen.append(sum(fake_redis.values.values()))
        return False, None

    monkeypatch.setattr(auth_router.upstream_auth, "login", fake)
    for _ in range(2):
        client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "x"})
    assert seen == [1, 2]
    blocked = client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "x"})
    assert blocked.status_code == 429
    assert seen == [1, 2]  # the third never reached the upstream


def test_an_album_by_various_artists_has_no_artist_to_cascade_to(client, user_key, monkeypatch, db_session):
    """Review round 1 (M3): a compilation's only artist is the pseudo-artist."""
    _metadata(monkeypatch, {"artists": [{"id": spotify_urls.VARIOUS_ARTISTS_ID, "name": "Various Artists"}]})
    response = client.post(
        "/api/jobs",
        json={"url": f"https://open.spotify.com/album/{ALBUM_ID}", "cascade": "artist"},
        headers=bearer(user_key),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "cascade_invalid"
    assert response.json()["params"]["reason"] == "various_artists"
    assert db_session.query(Job).count() == 0


def test_various_artists_is_never_a_candidate_beside_real_artists(client, user_key, monkeypatch):
    _metadata(
        monkeypatch,
        {"artists": [{"id": spotify_urls.VARIOUS_ARTISTS_ID, "name": "Various Artists"}, {"id": ARTIST_ID, "name": "A"}]},
    )
    response = client.post(
        "/api/jobs",
        json={"url": f"https://open.spotify.com/track/{TRACK_ID}", "cascade": "artist"},
        headers=bearer(user_key),
    )
    assert response.status_code == 201
    assert response.json()["source_url"] == f"https://open.spotify.com/artist/{ARTIST_ID}"


def test_a_key_stops_working_when_its_user_leaves_the_allowlist(client, user_key, monkeypatch):
    """Review round 1 (L2): they can't sign in to revoke it, and no one else can see it."""
    assert client.get("/api/auth/me", headers=bearer(user_key)).status_code == 200
    monkeypatch.setattr(get_settings(), "allowed_emails", ["admin@example.com"])
    for response in (
        client.get("/api/auth/me", headers=bearer(user_key)),
        client.post("/api/jobs", json={"url": f"https://open.spotify.com/album/{ALBUM_ID}"}, headers=bearer(user_key)),
    ):
        assert response.status_code == 401
        assert response.json()["code"] == "api_key_invalid"
