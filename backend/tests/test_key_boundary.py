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


def _route_lists(router) -> list:
    """A router's routes, plus the ones FastAPI serves after them (`_low_priority_routes`, where
    `.frontend()` registers a static mount, review round 1)."""
    return list(router.routes) + list(getattr(router, "_low_priority_routes", []))


def _wrappers(routes=None) -> list:
    """Every included-router wrapper (FastAPI 0.141+'s lazy `_IncludedRouter`), nested ones too."""
    found = []
    for route in _route_lists(app.router) if routes is None else routes:
        if hasattr(route, "original_router"):
            found.append(route)
            found.extend(_wrappers(_route_lists(route.original_router)))
    return found


def _leaves(routes=None) -> list:
    """Every route object in the app. FastAPI keeps an included router as a lazy
    `_IncludedRouter` wrapper (no prefix of its own here: every router carries its prefix, which
    `test_no_router_is_included_with_a_prefix_or_dependencies` pins), so this descends into each
    one's `original_router`, low-priority routes included."""
    found = []
    for route in _route_lists(app.router) if routes is None else routes:
        if hasattr(route, "original_router"):
            found.extend(_leaves(_route_lists(route.original_router)))
        else:
            found.append(route)
    return found


def _api_routes() -> list[APIRoute]:
    return [route for route in _leaves() if isinstance(route, APIRoute)]


def _methods(route: APIRoute) -> list[str]:
    """The methods to test: HEAD only beside GET answers what GET does, and OPTIONS only beside
    another method (CORS preflight); a route serving only HEAD or OPTIONS keeps it (review round
    4: a `@router.head` route had nothing tested)."""
    methods = set(route.methods)
    if "GET" in methods:
        methods.discard("HEAD")
    if methods - {"OPTIONS"}:
        methods.discard("OPTIONS")
    return sorted(methods)


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


def test_no_router_is_included_with_a_prefix_or_dependencies():
    """The walk reads each route's own path and dependencies. An `include_router(prefix=...,
    dependencies=...)` keeps those on the wrapper instead (`include_context`), where the checks
    below wouldn't see them: a gate or a prefix added that way must be moved onto the router, or
    this file taught to read it (review round 1)."""
    included = [
        (w.original_router.prefix, w.include_context.prefix, list(w.include_context.dependencies))
        for w in _wrappers()
    ]
    assert len(included) >= 10
    assert [i for i in included if i[1] or i[2]] == []


# Every name the key machinery goes by: the model, its modules, its hash, the lookup, the bearer
# parse and the dependency. Matched by spelling anywhere (a name, an attribute, an import, a
# keyword), whatever imports it, so a new place touching the machinery can't avoid naming one.
KEY_NAMES = {"ApiKey", "api_keys", "api_key", "hash", "_hash", "authenticate", "_bearer_token", "require_session_or_api_key"}

# Where `app/` names any of them today, as (file, scope, name). The scope is the enclosing
# function or class, dotted when nested ("<module>" at top level); a definition's decorators,
# defaults and annotations count as its own.
KEY_INVENTORY = {
    ('models/__init__.py', '<module>', 'ApiKey'),
    ('models/api_key.py', 'ApiKey', 'hash'),
    ('routers/account_keys.py', '<module>', 'api_keys'),
    ('routers/account_keys.py', 'create_api_key', 'api_keys'),
    ('routers/account_keys.py', 'list_api_keys', 'api_keys'),
    ('routers/account_keys.py', 'revoke_api_key', 'api_keys'),
    ('routers/auth.py', '<module>', 'ApiKey'),
    ('routers/auth.py', '<module>', 'api_keys'),
    ('routers/auth.py', 'Principal', 'ApiKey'),
    ('routers/auth.py', 'Principal', 'api_key'),
    ('routers/auth.py', 'me', 'api_key'),
    ('routers/auth.py', 'me', 'require_session_or_api_key'),
    ('routers/auth.py', 'require_session_or_api_key', '_bearer_token'),
    ('routers/auth.py', 'require_session_or_api_key', 'api_keys'),
    ('routers/auth.py', 'require_session_or_api_key', 'authenticate'),
    ('routers/jobs.py', '<module>', 'require_session_or_api_key'),
    ('routers/jobs.py', 'create_job', 'api_key'),
    ('routers/jobs.py', 'create_job', 'require_session_or_api_key'),
    ('routers/jobs.py', 'get_job', 'api_key'),
    ('routers/jobs.py', 'get_job', 'require_session_or_api_key'),
    ('services/allowlist.py', '<module>', 'ApiKey'),
    ('services/allowlist.py', 'remove', 'ApiKey'),
    ('services/api_keys.py', '<module>', 'ApiKey'),
    ('services/api_keys.py', 'active_keys', 'ApiKey'),
    ('services/api_keys.py', 'authenticate', 'ApiKey'),
    ('services/api_keys.py', 'authenticate', '_hash'),
    ('services/api_keys.py', 'authenticate', 'hash'),
    ('services/api_keys.py', 'create_key', 'ApiKey'),
    ('services/api_keys.py', 'create_key', '_hash'),
    ('services/api_keys.py', 'create_key', 'hash'),
    ('services/api_keys.py', 'key_to_dict', 'ApiKey'),
    ('services/api_keys.py', 'revoke_key', 'ApiKey'),
}


def _key_inventory() -> set[tuple[str, str, str]]:
    import ast
    from pathlib import Path

    import app as app_package

    root = Path(app_package.__file__).parent
    found = set()

    def walk(node, rel, scope):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                walk(child, rel, child.name if scope == "<module>" else f"{scope}.{child.name}")
                continue
            name = None
            if isinstance(child, ast.Name):
                name = child.id
            elif isinstance(child, ast.Attribute):
                name = child.attr
            elif isinstance(child, ast.keyword):
                name = child.arg
            elif isinstance(child, ast.alias):
                name = child.asname or child.name.split(".")[-1]
                found.update((rel, scope, part) for part in child.name.split(".") if part in KEY_NAMES)
            if name in KEY_NAMES:
                found.add((rel, scope, name))
            walk(child, rel, scope)

    for path in sorted(root.rglob("*.py")):
        rel = str(path.relative_to(root))
        walk(ast.parse(path.read_text(), filename=str(path)), rel, "<module>")
    return found


def test_the_key_machinery_is_touched_only_where_it_was():
    """Deny-by-default for how a key is *read*. The behavioural walk below can only send the
    carriers a client uses today, so this pins every place that names the key machinery at
    all. A change (a new dependency in auth.py hashing a header, a new helper in the key
    service, a route reaching `services.api_keys` some new way) fails here until someone checks
    that it reads a key only through `require_session_or_api_key` on a key route, and updates
    the inventory. Review rounds 1-5 found the narrower scans before this one each missed an
    ordinary spelling. Out of reach, by the owner's decision: code written to hide a name from
    a scan (`getattr` on a built string, say)."""
    now = _key_inventory()
    assert not now - KEY_INVENTORY, f"new places name the key machinery: {sorted(now - KEY_INVENTORY)}"
    assert not KEY_INVENTORY - now, f"gone (update KEY_INVENTORY): {sorted(KEY_INVENTORY - now)}"


def test_every_route_has_a_method_to_test():
    assert [r.path for r in _api_routes() if not _methods(r)] == []


@pytest.mark.parametrize(
    "methods,tested",
    [
        ({"GET", "HEAD"}, ["GET"]),
        ({"HEAD"}, ["HEAD"]),
        ({"OPTIONS"}, ["OPTIONS"]),
        ({"POST", "OPTIONS"}, ["POST"]),
        ({"GET", "HEAD", "OPTIONS"}, ["GET"]),
    ],
)
def test_the_methods_a_route_is_tested_with(methods, tested):
    """HEAD is dropped only beside GET, OPTIONS only beside another method (review round 5:
    nothing in the app serves HEAD alone today, so this pins `_methods` itself)."""
    route = APIRoute("/x", lambda: None, methods=list(methods))
    route.methods = set(methods)
    assert _methods(route) == tested


def test_no_middleware_answers_on_its_own():
    """A middleware runs before any route, so one that answered a request (an
    `@app.middleware("http")` endpoint) would serve it with no gate and no route object for the
    walk to see. The app has CORS only (review round 2)."""
    assert [m.cls.__name__ for m in app.user_middleware] == ["CORSMiddleware"]


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


@pytest.mark.parametrize("carriers", ["bearer", "every-carrier"])
@pytest.mark.parametrize("holder", ["admin", "user"])
@pytest.mark.parametrize("method,path", DENIED)
def test_a_key_is_refused_on_every_other_route(request, client, holder, carriers, method, path):
    """Behavioral, deny-by-default: every route outside the key and public ones answers a key
    401 `not_authenticated`, admin routes included (a key is no credential there, so it never
    reaches the admin check, let alone passes it). Once as the plain `Bearer`, once with every
    way a client carries it today or says it's the extension, at the same time (`X-Spotdl-Client`,
    a `moz-extension://` origin, `X-Api-Key`, `?key=`/`?api_key=`), so a dependency that accepts
    a key only on one of them fails too (review rounds 2-3)."""
    raw = _key(request, holder)
    headers, url = bearer(raw), _fill(path)
    if carriers == "every-carrier":
        headers |= {"X-Spotdl-Client": "extension/1.0.2", "Origin": "moz-extension://a1b2c3", "X-Api-Key": raw}
        url += f"?key={raw}&api_key={raw}"
    response = client.request(method, url, headers=headers, json={})
    assert response.status_code == 401, (method, path, response.status_code, response.text)
    if method != "HEAD":  # a HEAD answer has no body (review round 5)
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
