"""v56 (A6): one rule for what an admin route answers a non-admin, over every admin route.

- **404** (`require_admin_hidden`, no `code`, exactly an unknown route's answer) where the path
  names an id, so neither the route nor the id is confirmed, plus the two pages v36/v44 hid.
- **403** `admin_required` (`require_admin`) for the admin actions whose path names no id
  (settings, worker controls, the proxy list, the library sweep), where it confirms nothing.

`ADMIN_ROUTES` is that table, the one in v56's PR. A new admin route fails
`test_every_admin_route_is_in_the_table` until it is classified here."""

import uuid

import pytest
from fastapi.routing import APIRoute

from app.main import app
from app.models import Job, JobSourceType, JobState, Proxy, ProxySource
from app.routers import admin as admin_router
from app.routers.auth import require_admin, require_admin_hidden

ADMIN_ROUTES: dict[tuple[str, str], int] = {
    ("PATCH", "/api/jobs/{job_id}/priority"): 404,
    ("POST", "/api/jobs/{job_id}/bump"): 404,
    ("PATCH", "/api/proxies/{proxy_id}"): 404,
    ("DELETE", "/api/proxies/{proxy_id}"): 404,
    ("GET", "/api/admin/stats"): 404,
    ("POST", "/api/settings/alerts/test"): 404,
    ("GET", "/api/proxies"): 403,
    ("POST", "/api/proxies"): 403,
    ("GET", "/api/settings/output"): 403,
    ("GET", "/api/settings/output/options"): 403,
    ("PATCH", "/api/settings/output"): 403,
    ("GET", "/api/settings/library"): 403,
    ("PATCH", "/api/settings/library"): 403,
    ("GET", "/api/settings/alerts"): 403,
    ("PATCH", "/api/settings/alerts"): 403,
    ("GET", "/api/library/sort/status"): 403,
    ("POST", "/api/library/sort"): 403,
    ("POST", "/api/worker/pause"): 403,
    ("POST", "/api/worker/resume"): 403,
    ("POST", "/api/worker/breaker/release"): 403,
}

_GATES = {require_admin: 403, require_admin_hidden: 404, admin_router.require_admin_hidden: 404}


def _api_routes(routes=None) -> list[APIRoute]:
    # Included routers are lazy wrappers (FastAPI 0.141+); see test_api_keys.py's twin.
    found = []
    for route in app.routes if routes is None else routes:
        if isinstance(route, APIRoute):
            found.append(route)
        elif hasattr(route, "original_router"):
            found.extend(_api_routes(route.original_router.routes))
    return found


def _gate_status(route: APIRoute) -> int | None:
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if dep.call in _GATES:
            return _GATES[dep.call]
        stack.extend(dep.dependencies)
    return None


def _gated_routes() -> dict[tuple[str, str], int]:
    found = {}
    for route in _api_routes():
        status = _gate_status(route)
        if status is not None:
            for method in route.methods - {"HEAD", "OPTIONS"}:
                found[(method, route.path)] = status
    return found


def test_every_admin_route_is_in_the_table():
    """Each route's gate (its dependency) gives the status the table says, and no admin
    route is missing from it."""
    assert _gated_routes() == ADMIN_ROUTES


def test_the_rule_404s_exactly_where_the_path_names_an_id():
    hidden_pages = {("GET", "/api/admin/stats"), ("POST", "/api/settings/alerts/test")}
    for (method, path), status in ADMIN_ROUTES.items():
        expected = 404 if "{" in path or (method, path) in hidden_pages else 403
        assert status == expected, (method, path)


def _fill(path: str, ids: dict[str, str]) -> str:
    return path.format(**ids)


@pytest.mark.parametrize(("method", "path"), list(ADMIN_ROUTES))
def test_a_non_admin_gets_the_rules_answer(authenticated_client, db_session, owner, method, path):
    """Over every admin route, with real ids: the non-admin's own job, and a proxy that
    exists. A 404 is an unknown route's (no `code`); a 403 carries `admin_required`."""
    job = Job(
        user_id=owner.id,
        source_url="https://open.spotify.com/track/x",
        source_type=JobSourceType.TRACK,
        state=JobState.EXPANDED,
    )
    proxy = Proxy(url="http://203.0.113.5:3128", source=ProxySource.MANUAL, enabled=True)
    db_session.add_all([job, proxy])
    db_session.commit()

    response = authenticated_client.request(
        method, _fill(path, {"job_id": str(job.id), "proxy_id": str(proxy.id)}), json={}
    )

    assert response.status_code == ADMIN_ROUTES[(method, path)], response.text
    if response.status_code == 404:
        assert response.json() == {"detail": "Not Found"}
        # The same answer as a path that doesn't exist at all.
        assert authenticated_client.request(method, "/api/no-such-route", json={}).json() == response.json()
    else:
        assert response.json()["code"] == "admin_required"


@pytest.mark.parametrize(("method", "path"), [route for route, status in ADMIN_ROUTES.items() if "{" in route[1]])
def test_an_id_routes_404_is_the_same_for_a_real_id_and_a_random_one(
    authenticated_client, db_session, owner, method, path
):
    job = Job(
        user_id=owner.id,
        source_url="https://open.spotify.com/track/x",
        source_type=JobSourceType.TRACK,
        state=JobState.EXPANDED,
    )
    proxy = Proxy(url="http://203.0.113.5:3128", source=ProxySource.MANUAL, enabled=True)
    db_session.add_all([job, proxy])
    db_session.commit()
    real = authenticated_client.request(method, _fill(path, {"job_id": str(job.id), "proxy_id": str(proxy.id)}), json={})
    random_id = str(uuid.uuid4())
    made_up = authenticated_client.request(method, _fill(path, {"job_id": random_id, "proxy_id": random_id}), json={})

    assert (real.status_code, real.json()) == (made_up.status_code, made_up.json())


# Their handlers reach outside the database (a Matrix send, a Celery enqueue); their own
# suites (test_settings_router, test_library_router) cover an admin getting through.
_OUTSIDE_EFFECTS = {("POST", "/api/settings/alerts/test"), ("POST", "/api/library/sort")}


@pytest.mark.parametrize(("method", "path"), [route for route in ADMIN_ROUTES if route not in _OUTSIDE_EFFECTS])
def test_an_admin_passes_every_gate(admin_client, method, path):
    """The gate lets an admin through: whatever the handler answers next, it isn't the
    gate's (a made-up id is the handler's own 404 with its own `code`)."""
    random_id = str(uuid.uuid4())
    response = admin_client.request(method, _fill(path, {"job_id": random_id, "proxy_id": random_id}), json={})

    assert response.status_code != 403
    assert response.json() != {"detail": "Not Found"}
