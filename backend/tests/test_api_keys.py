"""v53: per-user API keys -- lifecycle, owner scoping, and the rule that a key reaches job
create and `GET /api/auth/me` only, never an admin route, even an admin's key."""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.routing import APIRoute

from app.main import app
from app.models import ApiKey
from app.routers import jobs as jobs_router
from app.services import api_keys
from extension_support import bearer, fake_redis  # noqa: F401 (fixtures)

pytestmark = pytest.mark.usefixtures("fake_redis", "_more_identities")


@pytest.fixture()
def _more_identities(monkeypatch):
    # A key re-checks the allowlist on every use, so the extra identities these tests mint
    # sessions for directly must be on it too.
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(
        settings, "allowed_emails", [*settings.allowed_emails, "a@example.com", "b@example.com", "other@example.com"]
    )


def _as(client, cookie: dict[str, str]):
    client.cookies.clear()
    client.cookies.update(cookie)
    return client


def _create_key(client, label="Firefox") -> dict:
    response = client.post("/api/account/api-keys", json={"label": label})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_shows_the_key_once_and_lists_it_by_prefix_only(authenticated_client, db_session):
    created = _create_key(authenticated_client, "  Laptop Firefox  ")
    raw = created["key"]
    assert raw.startswith(f"sdw_{created['prefix']}_")
    assert len(created["prefix"]) == 8
    assert created["label"] == "Laptop Firefox"

    listed = authenticated_client.get("/api/account/api-keys").json()
    assert listed["max_active"] == api_keys.MAX_ACTIVE_KEYS
    assert [k["id"] for k in listed["keys"]] == [created["id"]]
    assert "key" not in listed["keys"][0]
    assert raw not in authenticated_client.get("/api/account/api-keys").text

    # Never stored raw: only the SHA-256 of the whole key.
    row = db_session.get(ApiKey, uuid.UUID(created["id"]))
    assert row.hash == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in (row.hash, row.prefix, row.label)


@pytest.mark.parametrize(
    "label",
    [
        "",
        "   ",
        "x" * (api_keys.LABEL_MAX_LENGTH + 1),
        "a\u0000b",
        "tab\there",
        "a\ud800",
        "c1\x85x",
        "bidi\u202e",
        "x\u200fy",
        "x\u061cy",
        "x\u2028y",
        "\u200b",
        "lr4\u200b",
        "\ufeff",
        "\u2060",
        "\u3164",
        "\U000e0041",
        "\u0301",
        "x\u180ey",
        "x\ufff9y",
    ],
)
def test_create_refuses_a_blank_or_long_label(authenticated_client, label):
    # Raw JSON: httpx can't encode a lone surrogate itself, but a JSON escape carries one.
    body = json.dumps({"label": label})
    response = authenticated_client.post(
        "/api/account/api-keys", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "api_key_label_invalid"
    expected = "length" if label.strip() == "" or len(label) > api_keys.LABEL_MAX_LENGTH else "character"
    assert response.json()["params"]["reason"] == expected


@pytest.mark.parametrize(
    "label",
    [
        "Laptop 🦊",
        "👨\u200d👩\u200d👧",
        "Tükörfúró gép",
        "日本語",
        "ok-1_2.3",
        # Round 6: newer than Python's Unicode tables (🫩, Emoji 16), private use (macOS's
        # Apple logo), a subdivision flag (🏴 + tag characters).
        "Fáradt \U0001fae9",
        "MacBook \uf8ff",
        "\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f England",
    ],
)
def test_ordinary_labels_are_kept(authenticated_client, label):
    assert _create_key(authenticated_client, label)["label"] == label


def test_create_stops_at_the_active_key_limit_and_a_revoke_frees_a_slot(authenticated_client):
    keys = [_create_key(authenticated_client, f"k{i}") for i in range(api_keys.MAX_ACTIVE_KEYS)]
    over = authenticated_client.post("/api/account/api-keys", json={"label": "one more"})
    assert over.status_code == 409
    assert over.json()["code"] == "api_key_limit_reached"

    assert authenticated_client.delete(f"/api/account/api-keys/{keys[0]['id']}").status_code == 200
    _create_key(authenticated_client, "one more")


def test_me_with_a_key_reports_only_who_it_belongs_to(client, admin_client, admin_user):
    raw = _create_key(admin_client)["key"]
    client.cookies.clear()
    response = client.get("/api/auth/me", headers=bearer(raw))
    assert response.status_code == 200
    assert response.json() == {"email": "admin@example.com", "username": None, "is_admin": True}


def test_revoked_key_gets_401_and_disappears_from_the_list(client, authenticated_client):
    cookie = dict(authenticated_client.cookies)
    created = _create_key(authenticated_client)
    client.cookies.clear()
    assert client.get("/api/auth/me", headers=bearer(created["key"])).status_code == 200

    revoked = _as(client, cookie).delete(f"/api/account/api-keys/{created['id']}")
    assert revoked.status_code == 200
    assert revoked.json()["id"] == created["id"]
    assert client.get("/api/account/api-keys").json()["keys"] == []

    client.cookies.clear()
    response = client.get("/api/auth/me", headers=bearer(created["key"]))
    assert response.status_code == 401
    assert response.json()["code"] == "api_key_invalid"
    assert created["key"] not in response.text and created["prefix"] not in response.text
    # Revoking twice is a 404: there's no active key by that id any more.
    again = _as(client, cookie).delete(f"/api/account/api-keys/{created['id']}")
    assert again.status_code == 404


@pytest.mark.parametrize(
    "header",
    [
        "Bearer sdw_00000000_notarealkey",
        "Bearer not-even-shaped-like-a-key",
        "Basic dXNlcjpwYXNz",
        "Bearer ",
    ],
)
def test_an_unknown_or_malformed_credential_is_401(client, header):
    client.cookies.clear()
    response = client.get("/api/auth/me", headers={"Authorization": header})
    assert response.status_code == 401


def test_cookie_is_tried_before_the_key(client, authenticated_client, session_cookie):
    other_raw = _create_key(_as(client, session_cookie("other@example.com")))["key"]
    mine = session_cookie("allowed@example.com")
    response = _as(client, mine).get("/api/auth/me", headers=bearer(other_raw))
    assert response.json()["email"] == "allowed@example.com"
    # The cookie path keeps its full answer (the app shell's preferences).
    assert "keyboard_shortcuts" in response.json()


def test_an_invalid_cookie_falls_back_to_the_key(client, authenticated_client):
    raw = _create_key(authenticated_client)["key"]
    response = _as(client, {"SPOTDL_SESSION": "stale"}).get("/api/auth/me", headers=bearer(raw))
    assert response.status_code == 200
    assert response.json()["email"] == "allowed@example.com"


def test_last_used_at_is_written_at_most_once_a_minute(client, authenticated_client, db_session):
    created = _create_key(authenticated_client)
    client.cookies.clear()
    client.get("/api/auth/me", headers=bearer(created["key"]))
    row = db_session.get(ApiKey, uuid.UUID(created["id"]))
    first = row.last_used_at
    assert first is not None

    client.get("/api/auth/me", headers=bearer(created["key"]))
    db_session.refresh(row)
    assert row.last_used_at == first

    row.last_used_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    db_session.commit()
    client.get("/api/auth/me", headers=bearer(created["key"]))
    db_session.refresh(row)
    assert row.last_used_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) - timedelta(seconds=30)


# --- cross-user ---------------------------------------------------------------------------


def test_a_user_never_sees_or_revokes_another_users_keys(client, session_cookie):
    cookie_a = session_cookie("a@example.com")
    cookie_b = session_cookie("b@example.com")
    key_a = _create_key(_as(client, cookie_a), "A's key")
    key_b = _create_key(_as(client, cookie_b), "B's key")

    listed_b = _as(client, cookie_b).get("/api/account/api-keys").json()["keys"]
    assert [k["id"] for k in listed_b] == [key_b["id"]]

    revoke = _as(client, cookie_b).delete(f"/api/account/api-keys/{key_a['id']}")
    assert revoke.status_code == 404
    assert revoke.json()["code"] == "api_key_not_found"
    # Indistinguishable from an id that doesn't exist at all.
    assert _as(client, cookie_b).delete(f"/api/account/api-keys/{uuid.uuid4()}").json() == revoke.json()
    # A's key still works.
    client.cookies.clear()
    assert client.get("/api/auth/me", headers=bearer(key_a["key"])).json()["email"] == "a@example.com"


def test_an_admin_cookie_cant_see_or_revoke_another_users_key(client, session_cookie):
    key_a = _create_key(_as(client, session_cookie("a@example.com")))
    admin = session_cookie("admin@example.com", is_admin=True)
    assert _as(client, admin).get("/api/account/api-keys").json()["keys"] == []
    assert _as(client, admin).delete(f"/api/account/api-keys/{key_a['id']}").status_code == 404


def test_a_key_cant_manage_keys(client, authenticated_client):
    created = _create_key(authenticated_client)
    client.cookies.clear()
    headers = bearer(created["key"])
    assert client.get("/api/account/api-keys", headers=headers).status_code == 401
    assert client.post("/api/account/api-keys", json={"label": "x"}, headers=headers).status_code == 401
    assert client.delete(f"/api/account/api-keys/{created['id']}", headers=headers).status_code == 401


def test_a_users_key_sees_only_their_own_jobs_through_create(client, session_cookie, monkeypatch):
    """A key's only read is the job it just created (or its own unfinished duplicate): B's
    key re-submitting A's link gets a new job of B's own, never A's."""
    monkeypatch.setattr(jobs_router.expand_job, "delay", lambda job_id: None)
    url = "https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy"
    key_a = _create_key(_as(client, session_cookie("a@example.com")))["key"]
    key_b = _create_key(_as(client, session_cookie("b@example.com")))["key"]
    client.cookies.clear()
    job_a = client.post("/api/jobs", json={"url": url}, headers=bearer(key_a)).json()
    job_b = client.post("/api/jobs", json={"url": url}, headers=bearer(key_b))
    assert job_b.status_code == 201
    assert job_b.json()["id"] != job_a["id"]
    assert job_b.json()["owner_email"] == "b@example.com"
    assert job_b.json()["hint"] is None
    # B's key reads B's own job, never A's (404, like a non-owner), and lists nothing.
    assert client.get("/api/jobs", headers=bearer(key_b)).status_code == 401
    assert client.get(f"/api/jobs/{job_b.json()['id']}", headers=bearer(key_b)).status_code == 200
    foreign = client.get(f"/api/jobs/{job_a['id']}", headers=bearer(key_b))
    assert foreign.status_code == 404
    assert foreign.json()["code"] == "job_not_found"
    assert client.get(f"/api/jobs/{job_a['id']}", headers=bearer(key_a)).json()["id"] == job_a["id"]
    # Nor the tracks of A's job, or B's own: a key reads the job, nothing under it.
    assert client.get(f"/api/jobs/{job_b.json()['id']}/tracks", headers=bearer(key_b)).status_code == 401


def test_an_admins_key_reads_only_the_admins_own_jobs(client, session_cookie, admin_client, monkeypatch):
    """An admin's cookie reads anyone's job; an admin's key only the admin's own."""
    monkeypatch.setattr(jobs_router.expand_job, "delay", lambda job_id: None)
    admin_cookie = dict(admin_client.cookies)
    raw = _create_key(admin_client)["key"]
    user_job = _as(client, session_cookie("a@example.com")).post(
        "/api/jobs", json={"url": "https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy"}
    ).json()
    client.cookies.clear()
    own = client.post(
        "/api/jobs", json={"url": "https://open.spotify.com/album/4OHNH3sDzIxnmUADXzv2kT"}, headers=bearer(raw)
    ).json()
    assert client.get(f"/api/jobs/{own['id']}", headers=bearer(raw)).status_code == 200
    assert client.get(f"/api/jobs/{user_job['id']}", headers=bearer(raw)).status_code == 404
    assert _as(client, admin_cookie).get(f"/api/jobs/{user_job['id']}").status_code == 200


# --- a key never grants admin, or anything else ------------------------------------------

# The two routes a key may use. Everything else in the app must refuse a key.
KEY_ROUTES = {("POST", "/api/jobs"), ("GET", "/api/jobs/{job_id}"), ("GET", "/api/auth/me")}
# Routes that need no credential at all.
PUBLIC_ROUTES = {("GET", "/api/health"), ("POST", "/api/auth/login")}


def _api_routes(routes=None) -> list[APIRoute]:
    """Every APIRoute in the app. FastAPI (0.141+) keeps an included router as a lazy
    `_IncludedRouter` wrapper (no prefix of its own here: every router carries its prefix), so
    this descends into each one's `original_router`."""
    found = []
    for route in app.routes if routes is None else routes:
        if isinstance(route, APIRoute):
            found.append(route)
        elif hasattr(route, "original_router"):
            found.extend(_api_routes(route.original_router.routes))
    return found


def _all_routes() -> list[tuple[str, str]]:
    return [(m, r.path) for r in _api_routes() for m in sorted(r.methods - {"HEAD", "OPTIONS"})]


def _depends_on(route: APIRoute, target) -> bool:
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if dep.call is target:
            return True
        stack.extend(dep.dependencies)
    return False


def _admin_routes() -> list[tuple[str, str]]:
    from app.routers.admin import require_admin_hidden as stats_gate
    from app.routers.auth import require_admin, require_admin_hidden

    found = []
    for route in _api_routes():
        # v56 (A6): require_admin answers a non-admin 403, require_admin_hidden 404 (and
        # admin.py keeps its own copy of the latter for /api/admin/stats).
        if any(_depends_on(route, gate) for gate in (require_admin, require_admin_hidden, stats_gate)):
            found.extend((m, route.path) for m in sorted(route.methods - {"HEAD", "OPTIONS"}))
    return found


def _fill(path: str) -> str:
    out = path
    while "{" in out:
        start, end = out.index("{"), out.index("}")
        out = out[:start] + str(uuid.uuid4()) + out[end + 1 :]
    return out


def test_the_route_lists_are_complete():
    # Guards the parametrizations below against silently testing nothing.
    assert len(_admin_routes()) >= 10
    assert set(_admin_routes()) <= set(_all_routes())
    assert KEY_ROUTES | PUBLIC_ROUTES <= set(_all_routes())
    assert len(_all_routes()) >= 40


@pytest.mark.parametrize("method,path", _admin_routes())
def test_an_admins_key_gets_no_admin_answer_on_any_admin_route(client, admin_client, method, path):
    raw = _create_key(admin_client)["key"]
    client.cookies.clear()
    # A valid admin key (it works where a key may), refused here.
    assert client.get("/api/auth/me", headers=bearer(raw)).json()["is_admin"] is True
    response = client.request(method, _fill(path), headers=bearer(raw), json={})
    # Not authenticated at all: a key is no credential here, so it never reaches the
    # admin check, and certainly never passes it.
    assert response.status_code == 401, (method, path, response.status_code, response.text)
    assert response.json()["code"] == "not_authenticated"


@pytest.mark.parametrize(
    "method,path",
    [r for r in _all_routes() if r not in KEY_ROUTES | PUBLIC_ROUTES],
)
def test_a_key_is_refused_on_every_route_but_submit_and_me(client, admin_client, method, path):
    raw = _create_key(admin_client)["key"]
    client.cookies.clear()
    assert client.get("/api/auth/me", headers=bearer(raw)).status_code == 200
    response = client.request(method, _fill(path), headers=bearer(raw), json={})
    assert response.status_code == 401, (method, path, response.status_code, response.text)


def test_the_admins_cookie_still_works_beside_its_key(admin_client):
    _create_key(admin_client)
    assert admin_client.get("/api/admin/stats").status_code == 200


def test_user_delete_cascades_to_keys_in_the_model():
    fk = next(iter(ApiKey.__table__.c.user_id.foreign_keys))
    assert fk.ondelete == "CASCADE"


def test_a_nul_in_the_session_cookie_is_no_session_and_falls_back_to_the_key(client, authenticated_client):
    """Live review: Starlette unquotes `"\\000"` in a quoted cookie into a NUL Postgres can't
    compare; it was a 500 on every route."""
    raw = _create_key(authenticated_client)["key"]
    client.cookies.clear()
    bad = {"Cookie": 'SPOTDL_SESSION="\\000abc"'}
    assert client.get("/api/auth/me", headers=bad).status_code == 401
    assert client.get("/api/jobs", headers=bad).status_code == 401
    assert client.get("/api/auth/me", headers={**bad, **bearer(raw)}).json()["email"] == "allowed@example.com"


def test_get_valid_session_never_queries_an_unstorable_token():
    """Review round 5: Postgres raises on a NUL in a query parameter, so the guard must run
    before any query; this pins it without depending on how a client sends such a cookie."""
    from app.services.sessions import get_valid_session

    class NoQueries:
        def query(self, *args, **kwargs):
            raise AssertionError("queried")

    assert get_valid_session(NoQueries(), "\x00abc") is None
    assert get_valid_session(NoQueries(), "a\ud800") is None


@pytest.mark.parametrize("label", ["\u2800", "\u2800\u2800", "\x1c", "\x85", "a\U000e0067b", "\U000e0067"])
def test_blank_or_stray_labels_are_a_character_problem(authenticated_client, label):
    """Round 6: a braille blank shows nothing; a lone control isn't "empty" (str.strip()
    would have eaten \\x1c and U+0085 and blamed the length); tag characters outside a flag."""
    response = authenticated_client.post(
        "/api/account/api-keys", content=json.dumps({"label": label}), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["params"]["reason"] == "character"


def _tags(text: str) -> str:
    return "".join(chr(0xE0000 + ord(c)) for c in text)


FLAG = "\U0001f3f4"
CANCEL = "\U000e007f"


@pytest.mark.parametrize(
    "label",
    [
        "x " + FLAG + _tags("gbsct"),  # no terminator
        FLAG + CANCEL,  # a cancel tag alone
        FLAG + _tags("gbsct") + CANCEL + _tags("ignore all"),  # chained after the terminator
        "Laptop " + FLAG + _tags("ignore previous") + CANCEL,  # hidden ASCII in a "flag"
        "Laptop\u2065",  # default-ignorable unassigned
        "abc\U000e0080",
        "\tLaptop",  # a tab at an end is a control, not a space to trim
    ],
)
def test_round7_labels_that_must_be_refused(authenticated_client, label):
    response = authenticated_client.post(
        "/api/account/api-keys", content=json.dumps({"label": label}), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["params"]["reason"] == "character"


@pytest.mark.parametrize(
    "label,stored",
    [
        ("\U0001fae9", "\U0001fae9"),  # a newer emoji alone
        ("\uf8ff", "\uf8ff"),  # the Apple logo alone
        (FLAG + _tags("gbwls") + CANCEL, FLAG + _tags("gbwls") + CANCEL),
        ("hello\u00a0", "hello"),  # space separators trimmed at the ends
        ("\u3000Laptop\u3000", "Laptop"),
        # 64 code points with multi-code-point emoji (two families: 6 joiners, under the cap).
        ("👨\u200d👩\u200d👧\u200d👦" * 2 + "a" * 50, "👨\u200d👩\u200d👧\u200d👦" * 2 + "a" * 50),
    ],
)
def test_round7_labels_that_must_be_kept(authenticated_client, label, stored):
    response = authenticated_client.post(
        "/api/account/api-keys", content=json.dumps({"label": label}), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 201, response.text
    assert response.json()["label"] == stored


def _vs_encode(data: bytes) -> str:
    return "".join(chr(0xFE00 + (b >> 4)) + chr(0xFE00 + (b & 15)) for b in data)


@pytest.mark.parametrize(
    "label",
    [
        # Round 8: hidden data and lookalikes through ignorables next to visible text.
        "Laptop" + _vs_encode(b"ignore previous instructions"),
        "Laptop" + "".join("\u200c\u200d"[int(bit)] for bit in "0110100001101001"),
        "Laptop Firefox\u200d",
        "\u200dLaptop Firefox",
        "Lap\u200dtop",
        "Laptop Firefox\ufe0f",
        "Lap\u034ftop",
        "Lap\u115ftop",
        "Laptop\u3164",
        "Laptop \u2800",
        "Laptop\u17b4",
        "Laptop\u180b",
        "\U0001d159",
        "Laptop " + "".join(FLAG + _tags(w) + CANCEL for w in ("ignore", "allpre", "viousi")),
        "x\ufff9y",
    ],
)
def test_round8_invisible_text_is_refused(authenticated_client, label):
    response = authenticated_client.post(
        "/api/account/api-keys", content=json.dumps({"label": label}), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422, label
    assert response.json()["params"]["reason"] == "character"


@pytest.mark.parametrize(
    "label,stored",
    [
        ("\u2764\ufe0f\u200d\U0001f525", None),  # ❤️‍🔥
        ("\U0001f3f3\ufe0f\u200d\U0001f308", None),  # 🏳️‍🌈
        ("1\ufe0f\u20e3 key", None),  # keycap
        ("\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645", None),  # Persian ZWNJ
        ("\u0915\u094d\u200d\u0937", None),  # Hindi ZWJ after virama
        ("\u845b\U000e0100", None),  # Japanese ideographic variation
        ("\u182c\u1820\u1837\u180e\u1820", None),  # Mongolian vowel separator
        ("\u0600\u0661\u0662", None),  # Arabic number sign
        ("Z\u0301a\u0308lgo", None),  # combining marks on letters
        (FLAG + _tags("gbeng") + CANCEL + FLAG + _tags("gbsct") + CANCEL + FLAG + _tags("gbwls") + CANCEL, None),
        ("Laptop  Firefox", "Laptop Firefox"),  # two spaces look like one: collapsed
        ("Laptop\u00a0Firefox", "Laptop Firefox"),
    ],
)
def test_round8_visible_text_is_kept(authenticated_client, label, stored):
    response = authenticated_client.post(
        "/api/account/api-keys", content=json.dumps({"label": label}), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 201, (label, response.text)
    assert response.json()["label"] == (stored or label)


@pytest.mark.parametrize(
    "label",
    [
        # Round 9: joiners where no script needs them, and payloads past the ignorable cap.
        "K\u0151\u200d\u00e9r",
        "\u041a\u200c\u043b\u044e\u0447",
        "\u6771\u200d\u4eac",
        "\U0001f600\u200d\U0001f600" * 0 + "Lap\u0301\u200c\u0301top",
        "".join("\u6f22" + chr(0xE0100 + b) for b in b"ignore previous instructions"),
        "\u0430" + "".join(("\u200c" if bit == "0" else "\u200d") + "\u0430" for bit in "0110100001101001"),
        "".join("\u2605" + ("\ufe0e" if i % 2 else "\ufe0f") for i in range(12)),
    ],
)
def test_round9_hidden_or_needless_ignorables_are_refused(authenticated_client, label):
    response = authenticated_client.post(
        "/api/account/api-keys", content=json.dumps({"label": label}), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422, label
    assert response.json()["params"]["reason"] == "character"


@pytest.mark.parametrize(
    "label",
    [
        "\u0d05\u0d35\u0d28\u0d4d\u200d",  # Malayalam chillu (old encoding)
        "\u0d05\u0d35\u0d28\u0d4d\u200d \u0d35",
        "\u0c95\u0ccd\u200d",  # Kannada
        "\u09b0\u200d\u09cd\u09af",  # Bengali ya-phala
        "\u0dc1\u0dca\u200d\u0dbb\u0dd3",  # Sinhala
        "\u203c\ufe0f",  # ‼️
        "\u2049\ufe0f",
        "\u2139\ufe0f",  # ℹ️
        "\u3030\ufe0f",
        "Laptop \u203c\ufe0f",
        "\U0001f469\U0001f3fd\u200d\U0001f4bb",  # skin tone before ZWJ
        "\U0001f642\u200d\u2194\ufe0f",  # 🙂‍↔️
        "\U0001f441\ufe0f\u200d\U0001f5e8\ufe0f",  # 👁️‍🗨️
        "\U0001f469\u200d\u2764\ufe0f\u200d\U0001f48b\u200d\U0001f468",  # 4 ignorables
    ],
)
def test_round9_legitimate_input_is_kept(authenticated_client, label):
    response = authenticated_client.post(
        "/api/account/api-keys", content=json.dumps({"label": label}), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 201, (label, response.text)


def test_more_than_the_ignorable_cap_is_refused_even_in_emoji(authenticated_client):
    """Nine families hold 27 joiners: past MAX_IGNORABLES, the bound on what invisible
    characters could encode, even where each one is in a valid context."""
    label = "👨\u200d👩\u200d👧\u200d👦" * 3  # 9 joiners
    response = authenticated_client.post("/api/account/api-keys", json={"label": label})
    assert response.status_code == 422
    assert response.json()["params"]["reason"] == "character"
