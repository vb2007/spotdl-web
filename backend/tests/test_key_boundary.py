"""v70: the API key boundary, deny-by-default (master v5's locked "Extension auth" decision).

A key (`Authorization: Bearer sdw_...`, v53) may submit a job, read its own jobs back and ask
who it is. Every other route must refuse it, and the key routes must treat it as the non-admin
it always is, even when its user is the admin.

Deny-by-default: the routes below are read from the app itself, so a route added later is
checked the moment it exists. Only the three key routes and the two public ones are named here;
a new route nobody thought about keys for fails `test_a_key_is_refused_on_every_other_route`
unless it refuses a key, and a route FastAPI's dependency system can't see (a plain Starlette
`Route`, a `Mount`, a websocket) fails `test_no_route_escapes_the_walk` outright.

Moved here from v53's `test_api_keys.py` and widened: v53 walked only `APIRoute`s and tried only
an admin's key."""

import uuid

import pytest
from fastapi.routing import APIRoute
from starlette.routing import Route

from app.main import app
from app.routers.auth import require_session_or_api_key
from extension_support import bearer, fake_redis  # noqa: F401 (fixtures)

pytestmark = pytest.mark.usefixtures("fake_redis")

# The routes a key may use (v53, owner's decision: create, its own jobs read back for the
# extension's "how is my submission doing", and `me`).
KEY_ROUTES = {("POST", "/api/jobs"), ("GET", "/api/jobs/{job_id}"), ("GET", "/api/auth/me")}
# Routes that need no credential at all.
PUBLIC_ROUTES = {("GET", "/api/health"), ("POST", "/api/auth/login")}
# FastAPI's own schema and docs pages (plain Starlette routes): no data, the same to anyone,
# and outside nginx's `/api/` location.
FRAMEWORK_ROUTES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def _leaves(routes=None) -> list:
    """Every route object in the app. FastAPI (0.141+) keeps an included router as a lazy
    `_IncludedRouter` wrapper (no prefix of its own here: every router carries its prefix), so
    this descends into each one's `original_router`."""
    found = []
    for route in app.routes if routes is None else routes:
        if hasattr(route, "original_router"):
            found.extend(_leaves(route.original_router.routes))
        else:
            found.append(route)
    return found


def _api_routes() -> list[APIRoute]:
    return [route for route in _leaves() if isinstance(route, APIRoute)]


def _methods(route: APIRoute) -> list[str]:
    return sorted(route.methods - {"HEAD", "OPTIONS"})


def _all_routes() -> list[tuple[str, str]]:
    return [(m, r.path) for r in _api_routes() for m in _methods(r)]


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

    # v56 (A6): require_admin answers a non-admin 403, require_admin_hidden 404 (and admin.py
    # keeps its own copy of the latter for /api/admin/stats).
    gates = (require_admin, require_admin_hidden, stats_gate)
    return [(m, r.path) for r in _api_routes() if any(_depends_on(r, g) for g in gates) for m in _methods(r)]


def _fill(path: str) -> str:
    out = path
    while "{" in out:
        start, end = out.index("{"), out.index("}")
        out = out[:start] + str(uuid.uuid4()) + out[end + 1 :]
    return out


DENIED = sorted(r for r in _all_routes() if r not in KEY_ROUTES | PUBLIC_ROUTES)


@pytest.fixture()
def _identities(db_session):
    # A key re-checks the allowlist on every use (v69: the allowlist table).
    from app.models import AllowedEmail

    db_session.merge(AllowedEmail(email="other@example.com"))
    db_session.flush()


def _key(request, holder: str) -> str:
    """A working key of the admin's or of a plain user's, with the client's cookie jar emptied
    afterwards, so the key is the request's only credential."""
    owner_client = request.getfixturevalue("admin_client" if holder == "admin" else "authenticated_client")
    created = owner_client.post("/api/account/api-keys", json={"label": "Firefox"})
    assert created.status_code == 201, created.text
    owner_client.cookies.clear()
    raw = created.json()["key"]
    me = owner_client.get("/api/auth/me", headers=bearer(raw))
    # The key works where a key may, so a 401 below is the route refusing it, not a dead key.
    assert me.status_code == 200, me.text
    assert me.json()["is_admin"] is (holder == "admin")
    return raw


def test_no_route_escapes_the_walk():
    """A route that isn't an `APIRoute` (a Starlette `Route`, a `Mount`, a websocket) runs no
    FastAPI dependency, so no session or key gate, and the parametrized checks below can't
    see it. Only FastAPI's own docs pages may be one."""
    escaped = [
        (type(route).__name__, getattr(route, "path", repr(route)))
        for route in _leaves()
        if not isinstance(route, APIRoute)
        and not (type(route) is Route and route.path in FRAMEWORK_ROUTES)
    ]
    assert escaped == []


def test_the_route_lists_are_complete():
    # Guards the parametrizations below against silently testing nothing (a FastAPI upgrade
    # once hid every included router from a plain `app.routes` walk).
    assert len(_all_routes()) >= 60
    assert len(_admin_routes()) >= 10
    assert set(_admin_routes()) <= set(DENIED)
    assert KEY_ROUTES | PUBLIC_ROUTES <= set(_all_routes())
    assert len(DENIED) == len(_all_routes()) - len(KEY_ROUTES | PUBLIC_ROUTES)


def test_only_the_key_routes_accept_a_key():
    """Structural: the one dependency that reads a key sits on exactly the key routes. A new
    route that takes `require_session_or_api_key` fails here before it ships."""
    accepting = {(m, r.path) for r in _api_routes() if _depends_on(r, require_session_or_api_key) for m in _methods(r)}
    assert accepting == KEY_ROUTES


@pytest.mark.parametrize("holder", ["admin", "user"])
@pytest.mark.parametrize("method,path", DENIED)
def test_a_key_is_refused_on_every_other_route(request, client, holder, method, path):
    """Behavioral, deny-by-default: every route outside the key and public ones answers a key
    401 `not_authenticated`, admin routes included (a key is no credential there, so it never
    reaches the admin check, let alone passes it)."""
    raw = _key(request, holder)
    response = client.request(method, _fill(path), headers=bearer(raw), json={})
    assert response.status_code == 401, (method, path, response.status_code, response.text)
    assert response.json()["code"] == "not_authenticated", (method, path, response.text)


@pytest.mark.usefixtures("_identities")
def test_an_admins_key_reads_only_its_own_jobs(request, client, session_cookie, monkeypatch):
    """The read key route treats an admin's key as a non-admin: another user's job is a 404,
    exactly as for a non-owner, though the admin's cookie reads it."""
    from app.routers import jobs as jobs_router

    monkeypatch.setattr(jobs_router.expand_job, "delay", lambda *a, **k: None)
    other = client.post(
        "/api/jobs",
        json={"url": "https://open.spotify.com/album/1A2GTWGtFfWp7KSQTwWOyo"},
        cookies=session_cookie("other@example.com"),
    )
    assert other.status_code == 201, other.text
    # `admin_client` is this same `client`, and `_key` empties its jar: keep the cookie first.
    admin_cookie = dict(request.getfixturevalue("admin_client").cookies)
    raw = _key(request, "admin")
    assert client.get(f"/api/jobs/{other.json()['id']}", headers=bearer(raw)).status_code == 404
    assert client.get("/api/jobs", headers=bearer(raw)).status_code == 401
    assert client.get(f"/api/jobs/{other.json()['id']}", cookies=admin_cookie).status_code == 200


@pytest.mark.parametrize("holder", ["admin", "user"])
def test_a_key_submits_only_spotify_links_even_the_admins(request, client, holder, monkeypatch):
    """The create key route: a key gets the extension's allowlist (v53), whoever holds it;
    search text is the web UI's, through the cookie."""
    from app.routers import jobs as jobs_router

    monkeypatch.setattr(jobs_router.expand_job, "delay", lambda *a, **k: None)
    raw = _key(request, holder)
    refused = client.post("/api/jobs", json={"url": "daft punk one more time"}, headers=bearer(raw))
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "url_not_spotify"
    queued = client.post(
        "/api/jobs", json={"url": "https://open.spotify.com/track/0DiWol3AO6WpXZgp0goxAV"}, headers=bearer(raw)
    )
    assert queued.status_code == 201, queued.text
