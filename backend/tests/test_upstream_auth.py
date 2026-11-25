"""v71: `upstream_auth` against upstream v3's answers (tests/fixtures/upstream_auth.json), through
`httpx.MockTransport`, so the real request/response handling runs (v25's approach): the typed
login result, the anchored `__Host-VB-AUTH`/`__Host-VB-MFA` cookie reads, the username fetch and
logout, the second step's answers and the Redis challenge store."""

import json
import logging
import time
from pathlib import Path

import httpx
import pytest
import redis

from app.services import upstream_auth
from extension_support import FakeRedis

UPSTREAM = json.loads((Path(__file__).parent / "fixtures" / "upstream_auth.json").read_text())


def _install_transport(monkeypatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []
    real_client_cls = httpx.AsyncClient

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def _client_with_mock_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(record)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client_with_mock_transport)
    return seen


def _answer(status: int, body=None, cookies=(), headers=()) -> httpx.Response:
    return httpx.Response(
        status, json=body, headers=[*(("set-cookie", c) for c in cookies), *headers]
    )


def _login_answer(monkeypatch, response: httpx.Response | Exception):
    def handler(request):
        if isinstance(response, Exception):
            raise response
        return response

    return _install_transport(monkeypatch, handler)


# --- login: one typed result ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_200_is_ok_with_the_session_read_by_its_exact_cookie_name(monkeypatch):
    seen = _login_answer(
        monkeypatch,
        _answer(
            200,
            {"message": "Login successful with user x."},
            cookies=(
                "X__Host-VB-AUTH=wrong; Path=/",
                "VB-AUTH=old-name; Path=/",
                "__Host-VB-AUTH=tok123; Path=/; HttpOnly; Secure",
                "VB-DEVICE=device; Path=/",
            ),
        ),
    )

    result = await upstream_auth.login("a@b.com", "pw")

    assert result == upstream_auth.Ok("tok123")
    assert result.session == "tok123"
    assert [r.url.path for r in seen] == ["/auth/login"]
    assert json.loads(seen[0].content) == {"email": "a@b.com", "password": "pw"}


@pytest.mark.asyncio
async def test_a_200_with_only_the_old_cookie_name_still_signs_in_without_a_session(monkeypatch):
    """The v2.6 rename's shape: the login works, the username can't be fetched (logged)."""
    _login_answer(monkeypatch, _answer(200, {}, cookies=("VB-AUTH=old; Domain=localhost",)))

    assert await upstream_auth.login("a@b.com", "pw") == upstream_auth.Ok(None)


@pytest.mark.asyncio
async def test_a_202_is_mfa_required_with_the_challenge_and_upstreams_methods(monkeypatch):
    _login_answer(
        monkeypatch,
        _answer(202, UPSTREAM["mfa_required"], cookies=("__Host-VB-MFA=uid.secret; Path=/; HttpOnly; Secure",)),
    )

    result = await upstream_auth.login("a@b.com", "pw")

    assert result == upstream_auth.MfaRequired(("email", "totp", "passkey", "recovery"), "uid.secret")


@pytest.mark.asyncio
async def test_a_202_without_its_challenge_cookie_is_unavailable(monkeypatch):
    _login_answer(monkeypatch, _answer(202, UPSTREAM["mfa_required"]))

    assert await upstream_auth.login("a@b.com", "pw") == upstream_auth.Unavailable()


@pytest.mark.asyncio
async def test_the_pinned_suspended_answer_is_suspended(monkeypatch):
    _login_answer(monkeypatch, _answer(403, UPSTREAM["account_suspended"]))

    assert await upstream_auth.login("a@b.com", "pw") == upstream_auth.Suspended()


@pytest.mark.parametrize(
    "response",
    [
        _answer(403, UPSTREAM["invalid_credentials"]),
        _answer(403, {"error": "Something else entirely"}),
        _answer(403),
        _answer(400, {"error": "You must provide an E-mail address and a password."}),
        # The suspended sentence anywhere but at the start is not the suspended answer.
        _answer(403, {"error": "Note: This account is suspended"}),
    ],
)
@pytest.mark.asyncio
async def test_any_other_403_or_400_is_invalid(monkeypatch, response):
    _login_answer(monkeypatch, response)

    assert await upstream_auth.login("a@b.com", "pw") == upstream_auth.Invalid()


@pytest.mark.parametrize(
    ("response", "retry_after"),
    [
        (_answer(429, UPSTREAM["too_many_failures"], headers=(("Retry-After", "840"),)), 840),
        (_answer(429, {"error": "x"}, headers=(("Retry-After", "120"),)), 120),
        (_answer(429), 60),
    ],
)
@pytest.mark.asyncio
async def test_a_429_is_rate_limited_with_its_wait(monkeypatch, response, retry_after):
    _login_answer(monkeypatch, response)

    assert await upstream_auth.login("a@b.com", "pw") == upstream_auth.RateLimited(retry_after)


@pytest.mark.parametrize(
    "response",
    [_answer(500), _answer(502), _answer(503), httpx.ConnectError("refused"), httpx.ReadTimeout("slow")],
)
@pytest.mark.asyncio
async def test_a_5xx_or_a_transport_error_is_unavailable(monkeypatch, response):
    _login_answer(monkeypatch, response)

    assert await upstream_auth.login("a@b.com", "pw") == upstream_auth.Unavailable()


@pytest.mark.parametrize(
    ("methods", "proxied"),
    [
        (("email", "totp", "passkey", "recovery"), ["email", "totp", "recovery"]),
        (("totp", "passkey", "recovery"), ["totp", "recovery"]),
        (("passkey", "recovery"), ["recovery"]),
        (("passkey",), []),
        (("sms", "totp"), ["totp"]),
    ],
)
def test_the_proxied_methods_drop_passkey_and_keep_upstreams_order(methods, proxied):
    assert upstream_auth.proxied_methods(methods) == proxied


def test_a_results_repr_never_shows_a_token():
    assert "tok123" not in repr(upstream_auth.Ok("tok123"))
    assert "uid.secret" not in repr(upstream_auth.MfaRequired(("totp",), "uid.secret"))


# --- finish: the username, then the upstream logout ------------------------------------------------


@pytest.mark.asyncio
async def test_finish_fetches_the_username_then_logs_the_upstream_session_out(monkeypatch):
    def handler(request):
        if request.url.path == "/user":
            return _answer(200, {"username": "cooluser", "email": "a@b.com"})
        return _answer(200, {"message": "Logged out successfully."})

    seen = _install_transport(monkeypatch, handler)

    assert await upstream_auth.finish("tok123") == "cooluser"
    assert [(r.method, r.url.path) for r in seen] == [("GET", "/user"), ("POST", "/auth/logout")]
    assert all(r.headers["cookie"] == "__Host-VB-AUTH=tok123" for r in seen)


@pytest.mark.parametrize(
    "user_answer",
    [
        _answer(403),
        _answer(500),
        _answer(200, None),
        _answer(200, []),
        _answer(200, 42),
        _answer(200, "a string"),
        _answer(200, {"username": ""}),
        _answer(200, {"username": 7}),
        httpx.ConnectError("refused"),
    ],
)
@pytest.mark.asyncio
async def test_a_failed_username_fetch_is_none_and_still_logs_out(monkeypatch, user_answer):
    def handler(request):
        if request.url.path == "/user":
            if isinstance(user_answer, Exception):
                raise user_answer
            return user_answer
        return _answer(200, {})

    seen = _install_transport(monkeypatch, handler)

    assert await upstream_auth.finish("tok123") is None
    assert [r.url.path for r in seen] == ["/user", "/auth/logout"]


@pytest.mark.asyncio
async def test_a_failed_logout_never_fails_the_finish(monkeypatch):
    def handler(request):
        if request.url.path == "/user":
            return _answer(200, {"username": "cooluser"})
        raise httpx.ConnectError("refused")

    _install_transport(monkeypatch, handler)

    assert await upstream_auth.finish("tok123") == "cooluser"


@pytest.mark.asyncio
async def test_finish_without_a_session_asks_nothing(monkeypatch):
    seen = _install_transport(monkeypatch, lambda r: _answer(200, {}))

    assert await upstream_auth.finish(None) is None
    await upstream_auth.logout(None)
    assert seen == []


# --- the second step -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_sends_the_stored_challenge_and_reads_the_session(monkeypatch):
    seen = _install_transport(
        monkeypatch, lambda r: _answer(200, {"message": "ok"}, cookies=("__Host-VB-AUTH=tok9; Path=/",))
    )

    assert await upstream_auth.verify("uid.secret", "totp", "123456") == upstream_auth.Ok("tok9")
    assert seen[0].url.path == "/auth/mfa/verify"
    assert seen[0].headers["cookie"] == "__Host-VB-MFA=uid.secret"
    assert json.loads(seen[0].content) == {"method": "totp", "code": "123456"}


def _ended(reason: str | None) -> httpx.Response:
    body = dict(UPSTREAM["challenge_ended"])
    if reason is not None:
        body["reason"] = reason
    return _answer(403, body)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (_answer(400, UPSTREAM["wrong_code"]), upstream_auth.CodeRejected(3)),
        (_answer(400, {**UPSTREAM["wrong_code"], "attemptsLeft": 0}), upstream_auth.CodeRejected(0)),
        (_answer(400, {"error": "You must provide the code."}), upstream_auth.CodeRejected(None)),
        (_answer(400, {"attemptsLeft": True}), upstream_auth.CodeRejected(None)),
        (_ended("noChallenge"), upstream_auth.ChallengeEnded("noChallenge")),
        (_ended("triesUsedUp"), upstream_auth.ChallengeEnded("triesUsedUp")),
        (_ended("expired"), upstream_auth.ChallengeEnded("expired")),
        (_ended("ended"), upstream_auth.ChallengeEnded("ended")),
        (_ended("<script>"), upstream_auth.ChallengeEnded("ended")),
        (_ended(None), upstream_auth.ChallengeEnded("ended")),
        (_answer(429, UPSTREAM["too_many_failures"]), upstream_auth.RateLimited(840)),
        (_answer(500), upstream_auth.Unavailable()),
        (_answer(404), upstream_auth.Unavailable()),
    ],
)
@pytest.mark.asyncio
async def test_verify_maps_every_upstream_answer(monkeypatch, response, expected):
    _install_transport(monkeypatch, lambda r: response)

    assert await upstream_auth.verify("uid.secret", "totp", "000000") == expected


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (_answer(202, {"message": "sent"}), upstream_auth.Sent()),
        (_answer(400, {"error": "E-mail MFA isn't on"}), upstream_auth.MethodOff()),
        (_answer(503, {"error": "The e-mail couldn't be sent"}), upstream_auth.MailUnavailable()),
        (_answer(503, {"reason": "mailBudget", "retryAfter": 3600}), upstream_auth.MailUnavailable()),
        (
            _answer(429, {"error": "wait", "reason": "resendCooldown", "retryAfter": 42}),
            upstream_auth.RateLimited(42, "resendCooldown"),
        ),
        (
            _answer(429, {"error": "limit", "reason": "mfaEmailLimit", "retryAfter": 3000}),
            upstream_auth.RateLimited(3000, "mfaEmailLimit"),
        ),
        (_ended("expired"), upstream_auth.ChallengeEnded("expired")),
        (_answer(500), upstream_auth.Unavailable()),
    ],
)
@pytest.mark.asyncio
async def test_send_email_code_maps_every_upstream_answer(monkeypatch, response, expected):
    seen = _install_transport(monkeypatch, lambda r: response)

    assert await upstream_auth.send_email_code("uid.secret") == expected
    assert (seen[0].url.path, seen[0].headers["cookie"]) == ("/auth/mfa/email", "__Host-VB-MFA=uid.secret")


@pytest.mark.asyncio
async def test_no_token_reaches_a_log_line(monkeypatch, caplog):
    """Every warning path of the proxy, with tokens in play: none of them is logged."""
    caplog.set_level(logging.DEBUG)

    def handler(request):
        if request.url.path == "/auth/login":
            return _answer(202, {"methods": "not a list"}, cookies=("__Host-VB-MFA=uid.mfasecret",))
        if request.url.path == "/user":
            return _answer(500, {"echo": request.headers["cookie"]})
        raise httpx.ConnectError(f"refused, sent {request.headers.get('cookie')}")

    _install_transport(monkeypatch, handler)

    await upstream_auth.login("a@b.com", "pw-secret")
    await upstream_auth.finish("sessionsecret")
    await upstream_auth.verify("uid.mfasecret", "totp", "123456")
    await upstream_auth.send_email_code("uid.mfasecret")

    assert caplog.records
    for secret in ("mfasecret", "sessionsecret", "pw-secret"):
        assert secret not in caplog.text


# --- the challenge store -------------------------------------------------------------------------


class StoreRedis(FakeRedis):
    """FakeRedis plus the `SET ... EX` the challenge store uses."""

    def set(self, key, value, ex=None):
        self.values[key] = value
        if ex:
            self.expires[key] = time.monotonic() + ex
        return True


class DeadRedis:
    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise redis.ConnectionError("down")

        return fail


def test_a_stored_challenge_loads_back_until_dropped_under_a_hashed_key(monkeypatch):
    fake = StoreRedis()
    monkeypatch.setattr(upstream_auth, "_redis", lambda: fake)

    challenge_id = upstream_auth.store_challenge("uid.secret", "a@b.com")

    assert len(challenge_id) >= 40
    assert upstream_auth.load_challenge(challenge_id) == ("uid.secret", "a@b.com")
    (key,) = fake.values
    assert challenge_id not in key and key.startswith(upstream_auth.CHALLENGE_PREFIX)
    assert fake.ttl(key) == upstream_auth.CHALLENGE_TTL_SECONDS == 600
    assert upstream_auth.load_challenge("another-id") is None

    upstream_auth.drop_challenge(challenge_id)
    assert upstream_auth.load_challenge(challenge_id) is None


def test_the_challenge_store_fails_closed_on_a_redis_error(monkeypatch):
    monkeypatch.setattr(upstream_auth, "_redis", lambda: DeadRedis())

    with pytest.raises(upstream_auth.ChallengeStoreError):
        upstream_auth.store_challenge("uid.secret", "a@b.com")
    with pytest.raises(upstream_auth.ChallengeStoreError):
        upstream_auth.load_challenge("some-id")
    upstream_auth.drop_challenge("some-id")  # best effort: it expires anyway


def test_the_cookie_values_are_redacted_in_text_and_in_the_log_formatter():
    """The net under the proxy's own care: `redact_text` and the JSON log formatter both drop the
    values (quoted or not), keeping the names."""
    from app.logging_config import _redact
    from app.services.redaction import redact_text

    line = 'Cookie: __Host-VB-AUTH=sess.1; __Host-VB-MFA="uid.2"; SPOTDL_MFA=id3, sdw_ABCDEFGH_key4'
    for redacted in (redact_text(line), _redact(line)):
        assert all(secret not in redacted for secret in ("sess.1", "uid.2", "id3", "key4"))
        assert "__Host-VB-AUTH=[redacted]" in redacted and "SPOTDL_MFA=[redacted]" in redacted
