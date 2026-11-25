import json
from pathlib import Path

import httpx
import pytest

from app.config import get_settings
from app.models import AllowedEmail
from app.routers import auth
from app.services import upstream_auth
from extension_support import FakeRedis
from test_upstream_auth import DeadRedis, StoreRedis

UPSTREAM = json.loads((Path(__file__).parent / "fixtures" / "upstream_auth.json").read_text())
ALLOWED = "allowed@example.com"
OFF_LIST = "someone-else@example.com"


def _mock_upstream_login(monkeypatch, *, ok: bool, username: str | None = None) -> list[str]:
    """`login` answers Ok (or Invalid) and `finish` the username; returns the sessions finished."""
    finished: list[str] = []

    async def fake_login(email: str, password: str):
        return upstream_auth.Ok("upstream-session") if ok else upstream_auth.Invalid()

    async def fake_finish(session):
        finished.append(session)
        return username

    monkeypatch.setattr(auth.upstream_auth, "login", fake_login)
    monkeypatch.setattr(auth.upstream_auth, "finish", fake_finish)
    return finished


def test_login_success_sets_cookie_and_me_returns_email(client, monkeypatch):
    _mock_upstream_login(monkeypatch, ok=True)

    response = client.post("/api/auth/login", json={"email": ALLOWED, "password": "correct"})

    assert response.status_code == 200
    assert response.json() == {"email": ALLOWED, "username": None, "is_admin": False}
    assert "SPOTDL_SESSION" in response.cookies

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json() == {
        "email": ALLOWED,
        "username": None,
        "is_admin": False,
        "keyboard_shortcuts": True,
        "language": None,
        "clock": None,
        "job_notifications": False,
    }


def test_login_stores_and_returns_username_from_upstream(client, monkeypatch):
    finished = _mock_upstream_login(monkeypatch, ok=True, username="cooluser")

    response = client.post("/api/auth/login", json={"email": ALLOWED, "password": "correct"})

    assert response.status_code == 200
    assert response.json()["username"] == "cooluser"
    assert finished == ["upstream-session"]
    assert client.get("/api/auth/me").json()["username"] == "cooluser"


def test_login_with_failed_username_fetch_falls_back_to_email_and_still_succeeds(client, monkeypatch):
    _mock_upstream_login(monkeypatch, ok=True, username=None)

    response = client.post("/api/auth/login", json={"email": ALLOWED, "password": "correct"})

    assert response.status_code == 200
    assert response.json()["username"] is None
    assert response.json()["email"] == ALLOWED


def test_second_login_with_new_username_overwrites_stale_one(client, monkeypatch):
    """A username changed upstream must propagate on the next login."""
    _mock_upstream_login(monkeypatch, ok=True, username="oldname")
    client.post("/api/auth/login", json={"email": ALLOWED, "password": "correct"})

    _mock_upstream_login(monkeypatch, ok=True, username="newname")
    response = client.post("/api/auth/login", json={"email": ALLOWED, "password": "correct"})
    assert response.json()["username"] == "newname"

    # A later login whose username fetch fails keeps the last known-good value.
    _mock_upstream_login(monkeypatch, ok=True, username=None)
    response = client.post("/api/auth/login", json={"email": ALLOWED, "password": "correct"})
    assert response.json()["username"] == "newname"


def test_protected_route_without_session_returns_401(client):
    assert client.get("/api/auth/me").status_code == 401


def test_logout_clears_session(client, monkeypatch):
    _mock_upstream_login(monkeypatch, ok=True)
    client.post("/api/auth/login", json={"email": ALLOWED, "password": "correct"})

    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


# --- v71: the real proxy behind the router, upstream mocked at the transport ---------------------


class Upstream:
    """A mocked vb2007.hu-api: an answer per path, and every request it got."""

    def __init__(self, monkeypatch) -> None:
        self.answers: dict[str, httpx.Response | Exception] = {}
        self.seen: list[httpx.Request] = []
        real = httpx.AsyncClient

        def handler(request: httpx.Request) -> httpx.Response:
            self.seen.append(request)
            answer = self.answers.get(request.url.path, httpx.Response(404))
            if isinstance(answer, Exception):
                raise answer
            return answer

        def client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", client)

    def paths(self) -> list[str]:
        return [r.url.path for r in self.seen]


def _ok(session="sess-secret-1") -> httpx.Response:
    return httpx.Response(
        200, json={"message": "ok"}, headers=[("set-cookie", f"__Host-VB-AUTH={session}; Path=/; HttpOnly; Secure")]
    )


def _mfa(methods=("totp", "passkey", "recovery"), challenge="uid.mfa-secret-1") -> httpx.Response:
    return httpx.Response(
        202,
        json={"mfaRequired": True, "methods": list(methods)},
        headers=[("set-cookie", f"__Host-VB-MFA={challenge}; Path=/; HttpOnly; Secure")],
    )


@pytest.fixture()
def upstream(monkeypatch) -> Upstream:
    up = Upstream(monkeypatch)
    up.answers["/user"] = httpx.Response(200, json={"username": "realuser"})
    up.answers["/auth/logout"] = httpx.Response(200, json={})
    return up


@pytest.fixture()
def store(monkeypatch) -> StoreRedis:
    fake = StoreRedis()
    monkeypatch.setattr(upstream_auth, "_redis", lambda: fake)
    return fake


def _login(client, email=ALLOWED, password="correct"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _assert_no_upstream_token(response, *tokens):
    raw = response.text + "\n".join(f"{k}: {v}" for k, v in response.headers.multi_items())
    for token in ("__Host-VB-AUTH", "__Host-VB-MFA", "VB-AUTH", *tokens):
        assert token not in raw


def test_a_plain_login_fetches_the_username_and_logs_the_upstream_session_out(client, upstream, store):
    upstream.answers["/auth/login"] = _ok()

    response = _login(client)

    assert response.status_code == 200
    assert response.json()["username"] == "realuser"
    assert upstream.paths() == ["/auth/login", "/user", "/auth/logout"]
    assert upstream.seen[2].headers["cookie"] == "__Host-VB-AUTH=sess-secret-1"
    _assert_no_upstream_token(response, "sess-secret-1")


def test_an_mfa_login_keeps_the_challenge_server_side_and_answers_the_proxied_methods(client, upstream, store):
    upstream.answers["/auth/login"] = _mfa(("email", "totp", "passkey", "recovery"))

    response = _login(client)

    assert response.status_code == 200
    assert response.json() == {"mfa_required": True, "methods": ["email", "totp", "recovery"]}
    assert "SPOTDL_SESSION" not in response.cookies
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("SPOTDL_MFA=") and "HttpOnly" in cookie and "Secure" in cookie
    assert "samesite=lax" in cookie.lower() and "Max-Age=600" in cookie
    (stored,) = store.values.values()
    assert json.loads(stored) == {"upstream_mfa_token": "uid.mfa-secret-1", "email": ALLOWED}
    assert upstream.paths() == ["/auth/login"]
    _assert_no_upstream_token(response, "mfa-secret-1")


def test_a_passkey_only_challenge_is_mfa_unsupported_with_nothing_kept(client, upstream, store):
    upstream.answers["/auth/login"] = _mfa(("passkey",))

    response = _login(client)

    assert (response.status_code, response.json()["code"]) == (403, "mfa_unsupported")
    assert "set-cookie" not in response.headers
    assert store.values == {}


def test_a_challenge_store_outage_fails_the_login_closed(client, upstream, monkeypatch):
    monkeypatch.setattr(upstream_auth, "_redis", lambda: DeadRedis())
    upstream.answers["/auth/login"] = _mfa()

    response = _login(client)

    assert (response.status_code, response.json()["code"]) == (503, "login_unavailable")
    assert "set-cookie" not in response.headers


def test_a_suspended_allowed_address_is_told_so(client, upstream, store):
    upstream.answers["/auth/login"] = httpx.Response(403, json=UPSTREAM["account_suspended"])

    response = _login(client)

    assert (response.status_code, response.json()["code"]) == (403, "account_suspended")


def test_upstreams_429_is_rate_limited_with_its_wait(client, upstream, store):
    upstream.answers["/auth/login"] = httpx.Response(
        429, json=UPSTREAM["too_many_failures"], headers={"Retry-After": "840"}
    )

    response = _login(client)

    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert response.json()["params"] == {"retry_after": 840}
    assert response.headers["retry-after"] == "840"


def test_spotdls_own_login_limit_answers_rate_limited_with_its_wait(client, upstream, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_rate_limit_failures", 2)
    fake = FakeRedis()
    monkeypatch.setattr(auth.rate_limit, "_redis", lambda: fake)
    upstream.answers["/auth/login"] = httpx.Response(403, json=UPSTREAM["invalid_credentials"])

    answers = [_login(client, password="wrong") for _ in range(3)]

    assert [a.status_code for a in answers] == [401, 401, 429]
    assert answers[2].json()["code"] == "rate_limited"
    assert answers[2].json()["params"]["retry_after"] > 0


def test_an_unreachable_upstream_reads_as_a_refusal_on_the_password_step(client, upstream, store):
    upstream.answers["/auth/login"] = httpx.ConnectError("refused")

    response = _login(client)

    assert (response.status_code, response.json()["code"]) == (401, "invalid_credentials")


# --- No oracle: an off-list address with the right password reads exactly like a wrong password ---


def _wire(response) -> tuple:
    return response.status_code, response.content, sorted(response.headers.multi_items())


@pytest.mark.parametrize(
    "answer",
    [_ok, _mfa, lambda: httpx.Response(403, json=UPSTREAM["account_suspended"])],
    ids=["plain-200", "mfa-202", "suspended-403"],
)
def test_an_off_list_right_password_is_byte_identical_to_a_wrong_password(client, upstream, store, answer):
    upstream.answers["/auth/login"] = httpx.Response(403, json=UPSTREAM["invalid_credentials"])
    wrong = _login(client, email=ALLOWED, password="wrong")

    upstream.seen.clear()
    upstream.answers["/auth/login"] = answer()
    off_list = _login(client, email=OFF_LIST, password="correct")

    assert _wire(off_list) == _wire(wrong)
    assert off_list.json()["code"] == "invalid_credentials"
    assert "set-cookie" not in off_list.headers
    assert store.values == {}
    # No username fetched for it; a session it got is logged out (after the answer was sent).
    if answer is _ok:
        assert upstream.paths() == ["/auth/login", "/auth/logout"]
        assert upstream.seen[1].headers["cookie"] == "__Host-VB-AUTH=sess-secret-1"
    else:
        assert upstream.paths() == ["/auth/login"]


# --- The second step -------------------------------------------------------------------------------


def _start_mfa(client, upstream, methods=("email", "totp", "recovery")) -> None:
    upstream.answers["/auth/login"] = _mfa(methods)
    started = _login(client)
    assert started.json()["mfa_required"] is True
    upstream.seen.clear()


def _verify(client, code="123456", method="totp"):
    return client.post("/api/auth/mfa/verify", json={"method": method, "code": code})


@pytest.mark.parametrize("method", ["totp", "email", "recovery"])
def test_a_right_code_finishes_the_login_through_the_shared_tail(client, upstream, store, method):
    _start_mfa(client, upstream)
    upstream.answers["/auth/mfa/verify"] = _ok("sess-secret-2")

    response = _verify(client, "abcde-fghij" if method == "recovery" else "123456", method)

    assert response.status_code == 200
    assert response.json() == {"email": ALLOWED, "username": "realuser", "is_admin": False}
    assert "SPOTDL_SESSION" in response.cookies
    cleared = [c for c in response.headers.get_list("set-cookie") if c.startswith("SPOTDL_MFA=")]
    assert len(cleared) == 1 and "Max-Age=0" in cleared[0]
    assert upstream.paths() == ["/auth/mfa/verify", "/user", "/auth/logout"]
    assert upstream.seen[0].headers["cookie"] == "__Host-VB-MFA=uid.mfa-secret-1"
    assert json.loads(upstream.seen[0].content)["method"] == method
    assert store.values == {}
    _assert_no_upstream_token(response, "sess-secret-2", "mfa-secret-1")
    assert client.get("/api/auth/me").json()["email"] == ALLOWED


def test_a_wrong_code_answers_the_tries_left_and_keeps_the_challenge(client, upstream, store):
    _start_mfa(client, upstream)
    upstream.answers["/auth/mfa/verify"] = httpx.Response(400, json=UPSTREAM["wrong_code"])

    response = _verify(client, "000000")

    assert response.status_code == 400
    assert response.json()["code"] == "mfa_code_invalid"
    assert response.json()["params"] == {"attempts_left": 3}
    assert len(store.values) == 1


def test_the_last_wrong_code_drops_the_challenge(client, upstream, store):
    _start_mfa(client, upstream)
    upstream.answers["/auth/mfa/verify"] = httpx.Response(400, json={**UPSTREAM["wrong_code"], "attemptsLeft": 0})

    response = _verify(client, "000000")

    assert (response.status_code, response.json()["params"]) == (400, {"attempts_left": 0})
    cleared = response.headers["set-cookie"]
    assert cleared.startswith("SPOTDL_MFA=") and "Max-Age=0" in cleared
    assert store.values == {}


@pytest.mark.parametrize("reason", ["noChallenge", "triesUsedUp", "expired", "ended"])
def test_an_ended_challenge_answers_its_reason_and_is_dropped(client, upstream, store, reason):
    _start_mfa(client, upstream)
    upstream.answers["/auth/mfa/verify"] = httpx.Response(
        403, json={**UPSTREAM["challenge_ended"], "reason": reason}
    )

    response = _verify(client)

    assert response.status_code == 401
    assert response.json()["code"] == "mfa_expired"
    assert response.json()["params"] == {"reason": reason}
    cleared = response.headers["set-cookie"]
    assert cleared.startswith("SPOTDL_MFA=") and "Max-Age=0" in cleared
    assert store.values == {}


def test_no_or_an_unknown_challenge_cookie_is_mfa_expired(client, upstream, store):
    response = _verify(client)
    assert (response.status_code, response.json()["code"], response.json()["params"]) == (
        401,
        "mfa_expired",
        {"reason": "noChallenge"},
    )

    client.cookies.set("SPOTDL_MFA", "made-up-id")
    response = client.post("/api/auth/mfa/email")
    assert (response.status_code, response.json()["params"]) == (401, {"reason": "expired"})
    assert upstream.seen == []


def test_upstreams_429_on_the_second_step_is_rate_limited(client, upstream, store):
    _start_mfa(client, upstream)
    upstream.answers["/auth/mfa/verify"] = httpx.Response(429, json=UPSTREAM["too_many_failures"])

    response = _verify(client)

    assert (response.status_code, response.json()["params"]) == (429, {"retry_after": 840})


def test_spotdls_own_limit_counts_second_step_requests_per_challenge(client, upstream, store, monkeypatch):
    _start_mfa(client, upstream)
    monkeypatch.setattr(get_settings(), "login_rate_limit_failures", 2)
    monkeypatch.setattr(auth.rate_limit, "_redis", lambda: store)
    upstream.answers["/auth/mfa/verify"] = httpx.Response(400, json=UPSTREAM["wrong_code"])

    answers = [_verify(client, "000000") for _ in range(3)]

    assert [a.status_code for a in answers] == [400, 400, 429]
    assert answers[2].json()["code"] == "rate_limited"
    assert upstream.paths().count("/auth/mfa/verify") == 2


def test_an_unreachable_upstream_keeps_the_challenge(client, upstream, store):
    _start_mfa(client, upstream)
    upstream.answers["/auth/mfa/verify"] = httpx.ConnectError("refused")

    response = _verify(client)

    assert (response.status_code, response.json()["code"]) == (503, "login_unavailable")
    assert len(store.values) == 1


def test_an_address_removed_during_the_second_step_is_refused_and_logged_out(client, upstream, store, db_session):
    _start_mfa(client, upstream)
    upstream.answers["/auth/mfa/verify"] = _ok("sess-secret-3")
    removed = db_session.query(AllowedEmail).filter(AllowedEmail.email == ALLOWED).delete()
    db_session.flush()
    assert removed == 1

    response = _verify(client)

    assert (response.status_code, response.json()["code"]) == (401, "invalid_credentials")
    assert "SPOTDL_SESSION" not in response.cookies
    assert upstream.paths() == ["/auth/mfa/verify", "/auth/logout"]


def test_a_removal_at_the_locked_recheck_clears_the_cookie_and_nothing_else(client, upstream, store, monkeypatch):
    from app.services import allowlist

    _start_mfa(client, upstream)
    upstream.answers["/auth/mfa/verify"] = _ok("sess-secret-4")
    real = allowlist.is_allowed
    monkeypatch.setattr(allowlist, "is_allowed", lambda db, email, lock=False: False if lock else real(db, email))

    refused = _verify(client)

    assert (refused.status_code, refused.json()["code"]) == (401, "invalid_credentials")
    assert refused.headers["set-cookie"].startswith("SPOTDL_MFA=")
    # Only that refusal carries it: a plain wrong password still answers without a cookie.
    upstream.answers["/auth/login"] = httpx.Response(403, json=UPSTREAM["invalid_credentials"])
    wrong = _login(client, password="wrong")
    assert "set-cookie" not in wrong.headers


@pytest.mark.parametrize(
    ("answer", "status", "code", "params"),
    [
        (httpx.Response(202, json={"message": "sent"}), 200, None, None),
        (
            httpx.Response(429, json={"reason": "resendCooldown", "retryAfter": 42}),
            429,
            "rate_limited",
            {"retry_after": 42, "reason": "resendCooldown"},
        ),
        (
            httpx.Response(429, json={"reason": "mfaEmailLimit", "retryAfter": 3000}),
            429,
            "rate_limited",
            {"retry_after": 3000, "reason": "mfaEmailLimit"},
        ),
        (httpx.Response(503, json={"error": "not sent"}), 503, "mail_unavailable", None),
        (httpx.Response(400, json={"error": "off"}), 400, "mfa_method_off", None),
        (httpx.Response(403, json={"reason": "expired"}), 401, "mfa_expired", {"reason": "expired"}),
    ],
)
def test_the_email_code_send_maps_upstreams_answers(client, upstream, store, answer, status, code, params):
    _start_mfa(client, upstream)
    upstream.answers["/auth/mfa/email"] = answer

    response = client.post("/api/auth/mfa/email")

    assert response.status_code == status
    if code is None:
        assert response.json() == {"status": "sent"}
    else:
        assert response.json()["code"] == code
        assert response.json().get("params") == params
    assert upstream.seen[0].headers["cookie"] == "__Host-VB-MFA=uid.mfa-secret-1"
    _assert_no_upstream_token(response, "mfa-secret-1")


def test_no_router_keeps_a_shared_error_to_raise():
    """v71 (review round 3): a module-level exception raised again and again chains each raising
    request's traceback onto itself, keeping its frames (a password, an upstream token) alive for
    the process's life. Every error is built per raise."""
    import importlib
    import pkgutil

    import app.routers

    shared = [
        f"{info.name}.{name}"
        for info in pkgutil.iter_modules(app.routers.__path__)
        for name, value in vars(importlib.import_module(f"app.routers.{info.name}")).items()
        if isinstance(value, BaseException)
    ]
    assert shared == []
