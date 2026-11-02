"""v69: the login allowlist as a table the admin manages (`/users`), and what a removal cuts.

Downloads after a removal (holds, resumes, the race) are test_removal_holds.py's."""

import asyncio
import fnmatch
import logging
import uuid
from types import SimpleNamespace

import pytest
import redis.asyncio as aioredis
from extension_support import bearer, fake_redis  # noqa: F401 (fixture)
from sqlalchemy import select

from app.models import AllowedEmail, ApiKey, User, UserSession
from app.routers import auth as auth_router
from app.routers import stream as stream_router
from app.services import allowlist, events, job_status
from app.services.events import ADMIN_CHANNEL_PATTERN, channel_for, control_channel_for

pytestmark = pytest.mark.usefixtures("fake_redis")


class _RevokedStore:
    """The two commands allowlist's revoked-session record uses (CI's pytest has no Redis)."""

    def __init__(self):
        self.keys = {}

    def pipeline(self, transaction=False):
        return self

    def set(self, key, value, ex=None):
        self.keys[key] = (value, ex)

    def execute(self):
        return []

    def get(self, key):
        entry = self.keys.get(key)
        return entry[0].encode() if entry else None


@pytest.fixture(autouse=True)
def revoked_store(monkeypatch):
    store = _RevokedStore()
    monkeypatch.setattr(allowlist, "_redis", lambda: store)
    return store


@pytest.fixture(autouse=True)
def published(monkeypatch):
    """The control publishes and status moves a removal or an addition makes."""
    state = SimpleNamespace(control=[], statuses=[])
    monkeypatch.setattr(events, "publish_control", lambda user_id, kind: state.control.append((user_id, kind)))
    monkeypatch.setattr(job_status, "publish_changes", lambda db, ids, **kw: state.statuses.append(list(ids)))
    return state


def _upstream_ok(monkeypatch, ok=True):
    async def fake_login(email, password):
        return ok, None

    monkeypatch.setattr(auth_router.upstream_auth, "login", fake_login)


# --- is_allowed -------------------------------------------------------------------------


def test_admin_email_is_always_allowed_even_without_a_row(db_session):
    db_session.query(AllowedEmail).filter(AllowedEmail.email == "admin@example.com").delete()
    db_session.flush()
    assert allowlist.is_allowed(db_session, "  Admin@Example.COM ")


def test_a_row_allows_its_address_case_and_spaces_aside(db_session):
    assert allowlist.is_allowed(db_session, " ALLOWED@example.com")
    assert not allowlist.is_allowed(db_session, "stranger@example.com")


def test_the_migration_imported_the_env_list_normalized(db_session):
    """conftest's ALLOWED_EMAILS + ADMIN_EMAIL, as the migration's data step left them (the
    slot-DB run with a mixed-case, spaced list is in the PR's evidence)."""
    emails = set(db_session.execute(select(AllowedEmail.email)).scalars())
    assert {"allowed@example.com", "admin@example.com"} <= emails


# The migration module's file name starts with its revision id, which isn't an importable
# name; load it by path instead.
def _migration():
    import importlib.util
    from pathlib import Path

    path = next((Path(__file__).resolve().parents[1] / "alembic" / "versions").glob("b3f7d1a5c9e2_*.py"))
    spec = importlib.util.spec_from_file_location("v69_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_import_list_is_normalized(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "allowed_emails", [" Mixed@Example.COM ", "b@example.org", "", "MIXED@example.com"])
    monkeypatch.setattr(settings, "admin_email", " Boss@Example.com")
    assert _migration()._imported_addresses() == ["b@example.org", "boss@example.com", "mixed@example.com"]


# --- the admin API ----------------------------------------------------------------------


def test_add_answers_201_with_the_normalized_row(admin_client, admin_user):
    response = admin_client.post("/api/admin/allowlist", json={"email": "  New.Person@Example.COM "})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "new.person@example.com"
    assert body["added_by"] == "admin@example.com"
    assert body["last_login_at"] is None and body["username"] is None
    assert body["is_admin_email"] is False
    assert "held_jobs" not in body  # owner's decision: no held count on /users


@pytest.mark.parametrize("email", ["allowed@example.com", " ALLOWED@example.com", "admin@example.com"])
def test_a_duplicate_is_409(admin_client, email):
    response = admin_client.post("/api/admin/allowlist", json={"email": email})
    assert response.status_code == 409
    assert response.json()["code"] == "email_already_allowed"


@pytest.mark.parametrize(
    "email",
    ["", "   ", "no-at-sign", "two@@example.com", "a@b@example.com", "space in@example.com", "x@nodot",
     "@example.com", "x@.example.com", "x@example.com.", "nul\x00@example.com", "a" * 250 + "@example.com",
     "ops/team@example.com"],
)
def test_a_malformed_address_is_422(admin_client, email):
    response = admin_client.post("/api/admin/allowlist", json={"email": email})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_email"


def test_removing_admin_email_is_409(admin_client):
    response = admin_client.delete("/api/admin/allowlist/Admin@Example.com")
    assert response.status_code == 409
    assert response.json()["code"] == "cannot_remove_admin"


def test_removing_an_unknown_address_is_404(admin_client):
    response = admin_client.delete("/api/admin/allowlist/nobody@example.com")
    assert response.status_code == 404
    assert response.json()["code"] == "allowed_email_not_found"


def test_the_list_is_one_query_with_every_field(admin_client, admin_user, db_session, make_user, count_queries):
    signed_in = make_user("allowed@example.com")
    signed_in.username = "allowed"
    db_session.add(AllowedEmail(email="never@example.com", added_by=admin_user.id))
    db_session.commit()

    with count_queries() as statements:
        response = admin_client.get("/api/admin/allowlist")
    assert response.status_code == 200
    assert len([s for s in statements if "allowed_emails" in s]) == 1

    rows = {row["email"]: row for row in response.json()["items"]}
    assert response.json()["items"][0]["email"] == "admin@example.com"
    assert rows["admin@example.com"]["is_admin_email"] is True
    assert rows["allowed@example.com"]["username"] == "allowed"
    assert rows["allowed@example.com"]["last_login_at"] is not None
    assert rows["never@example.com"] == {
        **rows["never@example.com"],
        "username": None,
        "last_login_at": None,
        "added_by": "admin@example.com",
        "is_admin_email": False,
    }


def test_admin_email_is_listed_even_without_a_row(admin_client, db_session):
    db_session.query(AllowedEmail).filter(AllowedEmail.email == "admin@example.com").delete()
    db_session.commit()
    items = admin_client.get("/api/admin/allowlist").json()["items"]
    assert items[0]["email"] == "admin@example.com" and items[0]["is_admin_email"] is True
    assert items[0]["added_at"] is None


# --- boundaries -------------------------------------------------------------------------


def test_a_non_admin_gets_the_a6_answer_on_every_method(authenticated_client):
    assert authenticated_client.get("/api/admin/allowlist").json()["code"] == "admin_required"
    response = authenticated_client.post("/api/admin/allowlist", json={"email": "x@example.com"})
    assert (response.status_code, response.json()["code"]) == (403, "admin_required")
    response = authenticated_client.delete("/api/admin/allowlist/allowed@example.com")
    assert (response.status_code, response.json()) == (404, {"detail": "Not Found"})


def test_an_admins_api_key_is_refused_on_every_method(admin_client, client, db_session):
    raw = admin_client.post("/api/account/api-keys", json={"label": "ext"}).json()["key"]
    client.cookies.clear()
    for method, path, body in (
        ("GET", "/api/admin/allowlist", None),
        ("POST", "/api/admin/allowlist", {"email": "x@example.com"}),
        ("DELETE", "/api/admin/allowlist/allowed@example.com", None),
    ):
        response = client.request(method, path, json=body, headers=bearer(raw))
        assert response.status_code == 401, (method, response.text)
    # Nothing changed.
    assert db_session.get(AllowedEmail, "x@example.com") is None
    assert db_session.get(AllowedEmail, "allowed@example.com") is not None


def test_login_rejection_stays_indistinguishable(client, monkeypatch):
    _upstream_ok(monkeypatch, ok=True)
    unlisted = client.post("/api/auth/login", json={"email": "stranger@example.com", "password": "right"})
    _upstream_ok(monkeypatch, ok=False)
    wrong_password = client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "wrong"})
    assert unlisted.status_code == wrong_password.status_code == 401
    assert unlisted.json() == wrong_password.json() == {"detail": "Invalid credentials", "code": "invalid_credentials"}


def test_an_added_address_signs_in_on_its_next_attempt(admin_client, client, monkeypatch):
    _upstream_ok(monkeypatch)
    assert admin_client.post("/api/admin/allowlist", json={"email": "fresh@example.com"}).status_code == 201
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": "Fresh@Example.com", "password": "x"})
    assert response.status_code == 200
    assert response.json()["email"] == "fresh@example.com"


# --- removal ----------------------------------------------------------------------------


def test_removal_ends_sessions_revokes_keys_and_tells_the_stream(
    authenticated_client, owner, client, db_session, session_cookie, published
):
    raw = authenticated_client.post("/api/account/api-keys", json={"label": "ext"}).json()["key"]
    second = session_cookie("allowed@example.com")
    admin = session_cookie("admin@example.com", is_admin=True)

    response = client.delete("/api/admin/allowlist/Allowed@Example.com", cookies=admin)
    assert response.status_code == 204

    assert db_session.query(UserSession).filter(UserSession.user_id == owner.id).count() == 0
    assert all(key.revoked_at is not None for key in db_session.query(ApiKey).filter(ApiKey.user_id == owner.id))
    # The user's next request, from either session, and their key: all 401. v69 (live round 1):
    # a removed session says so (`access_removed`), so every tab of theirs can say why.
    gone = client.get("/api/auth/me", cookies=second)
    assert (gone.status_code, gone.json()["code"]) == (401, "access_removed")
    assert client.get("/api/jobs", cookies=second).json()["code"] == "access_removed"
    client.cookies.clear()
    assert client.get("/api/auth/me", headers=bearer(raw)).status_code == 401
    assert published.control == [(owner.id, events.CONTROL_REVOKED)]
    # The admin's own session is untouched.
    assert client.get("/api/auth/me", cookies=admin).status_code == 200
    # The user row and its data stay.
    assert db_session.get(User, owner.id) is not None


def test_re_adding_restores_the_same_user(admin_client, client, db_session, make_user, monkeypatch):
    user = make_user("allowed@example.com")
    before = user.id
    assert admin_client.delete("/api/admin/allowlist/allowed@example.com").status_code == 204
    assert admin_client.post("/api/admin/allowlist", json={"email": "allowed@example.com"}).status_code == 201
    _upstream_ok(monkeypatch)
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "x"}).status_code == 200
    assert db_session.query(User).filter(User.email == "allowed@example.com").one().id == before


def test_a_removed_address_cant_sign_in(admin_client, client, monkeypatch):
    assert admin_client.delete("/api/admin/allowlist/allowed@example.com").status_code == 204
    _upstream_ok(monkeypatch)
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": "allowed@example.com", "password": "x"})
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


# --- the stream's control channel -------------------------------------------------------


def test_the_control_channel_never_matches_the_admins_pattern():
    user_id = uuid.uuid4()
    assert not fnmatch.fnmatchcase(control_channel_for(user_id), ADMIN_CHANNEL_PATTERN)
    assert fnmatch.fnmatchcase(channel_for(user_id), ADMIN_CHANNEL_PATTERN)


class _Request:
    def __init__(self, polls):
        self.polls = polls
        self.cookies = {}

    async def is_disconnected(self):
        self.polls -= 1
        return self.polls < 0


class _PubSub:
    def __init__(self, messages):
        self.messages = list(messages)
        self.subscribed, self.psubscribed = [], []

    async def subscribe(self, channel):
        self.subscribed.append(channel)

    async def psubscribe(self, pattern):
        self.psubscribed.append(pattern)

    async def unsubscribe(self, channel):
        pass

    async def punsubscribe(self, pattern):
        pass

    async def get_message(self, **kwargs):
        if not self.messages:
            return None
        channel, data = self.messages.pop(0)
        kind = "pmessage" if self.psubscribed and channel.startswith(events.CHANNEL_PREFIX) else "message"
        return {"type": kind, "channel": channel.encode(), "data": data.encode()}

    async def aclose(self):
        pass


def _run_stream(monkeypatch, user, view, messages, status="ok", polls=10):
    pubsub = _PubSub(messages)
    monkeypatch.setattr(aioredis.Redis, "from_url", lambda url: SimpleNamespace(pubsub=lambda: pubsub, aclose=_noop))
    monkeypatch.setattr(stream_router, "_session_status", lambda request, token, user_id: status)
    sent = []

    async def run():
        async for chunk in stream_router._event_stream(_Request(polls), user, view):
            sent.append(chunk)

    asyncio.run(run())
    assert sent[:1] == [stream_router.HEARTBEAT]  # sent at once (test_stream.py)
    return pubsub, sent[1:]


async def _noop():
    pass


@pytest.mark.parametrize("view", ["mine", "all", "others"])
def test_a_revoked_message_ends_the_stream_with_its_event(monkeypatch, view):
    user = User(id=uuid.uuid4(), email="a@example.com", is_admin=view != "mine")
    messages = [
        (channel_for(user.id) if view != "others" else channel_for(uuid.uuid4()), '{"n": 1}'),
        (control_channel_for(user.id), '{"type": "revoked"}'),
        (channel_for(uuid.uuid4()), '{"n": 2}'),
    ]
    pubsub, sent = _run_stream(monkeypatch, user, view, messages)
    assert control_channel_for(user.id) in pubsub.subscribed
    assert sent == ['data: {"n": 1}\n\n', stream_router.REVOKED]


def test_an_unknown_control_message_is_ignored(monkeypatch):
    user = User(id=uuid.uuid4(), email="a@example.com", is_admin=False)
    messages = [(control_channel_for(user.id), '{"type": "other"}'), (channel_for(user.id), '{"n": 1}')]
    _, sent = _run_stream(monkeypatch, user, "mine", messages, polls=2)
    assert sent == ['data: {"n": 1}\n\n']


@pytest.mark.parametrize(("status", "last"), [("revoked", [stream_router.REVOKED]), ("ended", [])])
def test_the_recheck_ends_a_stream_whose_access_or_session_is_gone(monkeypatch, status, last):
    """The safety net: no control message arrives at all, and the periodic re-check ends it."""
    user = User(id=uuid.uuid4(), email="a@example.com", is_admin=False)
    clock = iter(range(0, 10_000, 20))
    monkeypatch.setattr(stream_router.time, "monotonic", lambda: next(clock))
    _, sent = _run_stream(monkeypatch, user, "mine", [], status=status)
    assert sent == last


def test_the_recheck_reads_the_database_on_a_session_of_its_own(client, db_session, session_cookie):
    """`_session_status` itself, on the real tables: ok, then revoked once the address is off
    the allowlist (the session gone too), and ended for a session that's gone while the
    address stays."""
    cookie = session_cookie("allowed@example.com")
    user = db_session.query(User).filter(User.email == "allowed@example.com").one()
    request = SimpleNamespace(app=client.app)
    token = cookie["SPOTDL_SESSION"]

    assert stream_router._session_status(request, token, user.id) == "ok"
    assert stream_router._session_status(request, "not-a-token", user.id) == "ended"
    db_session.query(AllowedEmail).filter(AllowedEmail.email == "allowed@example.com").delete()
    db_session.query(UserSession).filter(UserSession.user_id == user.id).delete()
    db_session.commit()
    assert stream_router._session_status(request, token, user.id) == "revoked"


# --- the startup warning ----------------------------------------------------------------


def test_the_startup_warning_counts_and_never_names_an_address(db_session, monkeypatch, caplog):
    from app.config import get_settings

    monkeypatch.setattr(
        get_settings(), "allowed_emails", ["allowed@example.com", "Secret.One@example.com", "secret.two@example.com"]
    )
    with caplog.at_level(logging.WARNING, logger="app.services.allowlist"):
        assert allowlist.warn_if_env_ignored(db_session) == 2
    [record] = [r for r in caplog.records if r.name == "app.services.allowlist"]
    message = record.getMessage()
    assert "ALLOWED_EMAILS is ignored since v69, manage users in /users" in message
    assert "2 address" in message
    assert "@" not in message


def test_no_startup_warning_when_every_env_address_is_imported(db_session, caplog):
    with caplog.at_level(logging.WARNING, logger="app.services.allowlist"):
        assert allowlist.warn_if_env_ignored(db_session) == 0
    assert not [r for r in caplog.records if r.name == "app.services.allowlist"]


def test_a_job_create_rechecks_the_allowlist(authenticated_client, db_session):
    """Review round 1: the create's insert comes seconds after its session check (a cascade's
    Spotify call). With the address off the list by then, it's refused, not created unheld."""
    db_session.query(AllowedEmail).filter(AllowedEmail.email == "allowed@example.com").delete()
    db_session.flush()
    response = authenticated_client.post("/api/jobs", json={"url": "some search text"})
    # The cookie's own check refuses it first now (live review round 2); create's locked re-check
    # is what closes the race with a removal committing after that check.
    assert response.status_code == 401
    assert response.json()["code"] == "access_removed"


def test_removing_an_unstorable_address_is_404(admin_client):
    response = admin_client.delete("/api/admin/allowlist/a%00b@example.com")
    assert response.status_code == 404
    assert response.json()["code"] == "allowed_email_not_found"


def test_a_key_create_rechecks_the_allowlist(authenticated_client, db_session):
    """Review round 2: a key created during a removal (after its session check) outlived the
    removal's revoke and worked again once the address came back."""
    db_session.query(AllowedEmail).filter(AllowedEmail.email == "allowed@example.com").delete()
    db_session.flush()
    response = authenticated_client.post("/api/account/api-keys", json={"label": "late"})
    assert response.status_code == 401
    assert db_session.query(ApiKey).count() == 0


def test_check_now_on_a_removed_owners_job_is_refused(admin_client, db_session, make_user, monkeypatch):
    """Review round 4: it answered 202 and stamped "checked now", and the run then added nothing."""
    from app.models import Job, JobSourceType, JobState
    from app.services import watch

    owner = make_user("gone@example.com")
    job = Job(user_id=owner.id, source_url="https://open.spotify.com/playlist/x", source_type=JobSourceType.PLAYLIST, state=JobState.EXPANDED)
    db_session.add(job)
    db_session.commit()
    monkeypatch.setattr(watch, "claim_run", lambda job_id: (_ for _ in ()).throw(AssertionError("claimed")))
    response = admin_client.post(f"/api/jobs/{job.id}/reexpand")
    assert response.status_code == 409
    assert response.json()["code"] == "job_not_reexpandable"
    assert response.json()["params"] == {"reason": "owner_removed"}
    assert db_session.get(Job, job.id).last_expanded_at is None


def test_a_removal_announces_each_held_job(admin_client, db_session, make_user, monkeypatch):
    """Review round 4: an admin's open row re-reads its status on `job.state`."""
    from app.models import Job, JobSourceType, JobState, Track, TrackState
    from app.services import events

    sent = []
    monkeypatch.setattr(events, "publish_job_event", lambda user_id, job_id, state, **kw: sent.append((user_id, job_id, state)))
    user = make_user("allowed@example.com")
    job = Job(user_id=user.id, source_url="https://open.spotify.com/album/x", source_type=JobSourceType.ALBUM, state=JobState.EXPANDED)
    db_session.add(job)
    db_session.flush()
    db_session.add(Track(job_id=job.id, spotify_track_id="t1", song_json={}, state=TrackState.QUEUED))
    db_session.commit()
    assert admin_client.delete("/api/admin/allowlist/allowed@example.com").status_code == 204
    assert sent == [(user.id, job.id, "expanded")]


def test_an_ended_session_that_wasnt_removed_stays_not_authenticated(client, session_cookie, revoked_store):
    cookie = session_cookie("allowed@example.com")
    assert client.post("/api/auth/logout", cookies=cookie).status_code == 200
    gone = client.get("/api/auth/me", cookies=cookie)
    assert (gone.status_code, gone.json()["code"]) == (401, "not_authenticated")


def test_the_revoked_record_lives_as_long_as_a_session_could(admin_client, client, session_cookie, revoked_store, db_session):
    from app.services.sessions import SESSION_IDLE_TIMEOUT

    session_cookie("allowed@example.com")
    assert admin_client.delete("/api/admin/allowlist/allowed@example.com").status_code == 204
    user = db_session.query(User).filter(User.email == "allowed@example.com").one()
    assert list(revoked_store.keys.values()) == [(str(user.id), int(SESSION_IDLE_TIMEOUT.total_seconds()))]
    # Keyed by a hash, never the token itself.
    assert all(len(key.rsplit(":", 1)[1]) == 64 for key in revoked_store.keys)


def test_access_removed_ends_once_the_address_is_back_and_never_reaches_the_extension(
    client, session_cookie, revoked_store
):
    """Review round 5: the extension's cookie-then-key fallback knows only `not_authenticated`
    (and must try its key on a dead cookie); and once the address is added back, an old cookie is
    an ordinary ended session."""
    admin = session_cookie("admin@example.com", is_admin=True)
    cookie = session_cookie("allowed@example.com")
    assert client.delete("/api/admin/allowlist/allowed@example.com", cookies=admin).status_code == 204
    assert client.get("/api/auth/me", cookies=cookie).json()["code"] == "access_removed"
    from_extension = client.get("/api/auth/me", cookies=cookie, headers={"X-Spotdl-Client": "extension/1.0.2"})
    assert (from_extension.status_code, from_extension.json()["code"]) == (401, "not_authenticated")
    assert client.post("/api/admin/allowlist", json={"email": "allowed@example.com"}, cookies=admin).status_code == 201
    assert client.get("/api/auth/me", cookies=cookie).json()["code"] == "not_authenticated"


def test_a_row_deleted_outside_users_refuses_the_live_session_too(client, session_cookie, db_session):
    """Live review round 2: a row deleted by hand ends no session; every cookie request (and the
    stream) now refuses it like a removal, so the page doesn't reconnect its stream forever."""
    cookie = session_cookie("allowed@example.com")
    db_session.query(AllowedEmail).filter(AllowedEmail.email == "allowed@example.com").delete()
    db_session.commit()
    for path in ("/api/auth/me", "/api/jobs", "/api/stream"):
        response = client.get(path, cookies=cookie)
        assert (response.status_code, response.json()["code"]) == (401, "access_removed"), path
    from_extension = client.get("/api/auth/me", cookies=cookie, headers={"X-Spotdl-Client": "extension/1.0.2"})
    assert from_extension.json()["code"] == "not_authenticated"


def test_a_refused_request_never_extends_an_off_list_session(client, session_cookie, db_session):
    """Review round 7: the `last_seen_at` touch is kept only once the allowlist check passed."""
    from datetime import datetime, timedelta, timezone

    cookie = session_cookie("allowed@example.com")
    session = db_session.query(UserSession).filter(UserSession.token == cookie["SPOTDL_SESSION"]).one()
    old = datetime.now(timezone.utc) - timedelta(days=3)
    session.last_seen_at = old
    db_session.query(AllowedEmail).filter(AllowedEmail.email == "allowed@example.com").delete()
    db_session.commit()
    for path in ("/api/jobs", "/api/auth/me"):
        assert client.get(path, cookies=cookie).status_code == 401
    db_session.expire_all()
    assert db_session.get(UserSession, session.id).last_seen_at == old
    # And an allowed one still is extended.
    db_session.add(AllowedEmail(email="allowed@example.com"))
    db_session.commit()
    assert client.get("/api/jobs", cookies=cookie).status_code == 200
    db_session.expire_all()
    assert db_session.get(UserSession, session.id).last_seen_at > old
