import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SESSION_SECRET", "test-secret")
# Two addresses: ADMIN_EMAIL must be allowlisted too (config.py's v17 validator), and
# most ownership/admin-gating tests need a non-admin *and* an admin identity available.
os.environ.setdefault("ALLOWED_EMAILS", "allowed@example.com,admin@example.com")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import (
    AppSettings,
    DownloadedTrack,
    Job,
    Proxy,
    Track,
    TrackAttempt,
    User,
    UserSession,
    UserSettings,
    WorkerState,
)
from app.routers import auth as auth_router
from app.services.sessions import create_session


# SQLite (used for fast in-process tests, see v02/v03 gotchas) has no native JSONB type —
# render it as plain JSON so Track.__table__.create() doesn't fail; a no-op against real
# Postgres/psycopg, which never goes through this compiler.
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # User must exist before UserSession/Job, both of which FK into it.
    User.__table__.create(engine)
    UserSession.__table__.create(engine)
    Job.__table__.create(engine)
    Proxy.__table__.create(engine)
    Track.__table__.create(engine)
    TrackAttempt.__table__.create(engine)
    DownloadedTrack.__table__.create(engine)
    WorkerState.__table__.create(engine)
    AppSettings.__table__.create(engine)
    UserSettings.__table__.create(engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    # base_url must be https:// — the session cookie is Secure, and httpx's cookie jar
    # (correctly) refuses to send Secure cookies back over plain http.
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(client: TestClient, monkeypatch, email: str) -> None:
    async def fake_login(email_: str, password: str) -> tuple[bool, str | None]:
        return True, None

    monkeypatch.setattr(auth_router.upstream_auth, "login", fake_login)
    response = client.post("/api/auth/login", json={"email": email, "password": "x"})
    assert response.status_code == 200


@pytest.fixture()
def authenticated_client(client: TestClient, monkeypatch) -> TestClient:
    """The shared `client`, logged in as a plain (non-admin) user via the real login
    endpoint -- replaces what used to be six byte-for-byte identical local `_login`
    helpers (v16). For a *second* identity live in the same test, use `session_cookie`
    instead of a second call to this: a second `/login` on the same `client` would just
    overwrite this cookie in its shared jar, not add a second session alongside it."""
    _login(client, monkeypatch, "allowed@example.com")
    return client


@pytest.fixture()
def owner(authenticated_client: TestClient, db_session) -> User:
    return db_session.query(User).filter(User.email == "allowed@example.com").one()


@pytest.fixture()
def admin_client(client: TestClient, monkeypatch) -> TestClient:
    _login(client, monkeypatch, "admin@example.com")
    return client


@pytest.fixture()
def admin_user(admin_client: TestClient, db_session) -> User:
    return db_session.query(User).filter(User.email == "admin@example.com").one()


@pytest.fixture()
def make_user(db_session):
    """Direct DB insert, no login round trip -- for task-level tests (beat/download/
    expand) that need *a* valid owner to satisfy jobs.user_id's NOT NULL constraint but
    have no session/client in play at all."""

    def _make(email: str, *, is_admin: bool = False) -> User:
        user = db_session.query(User).filter(User.email == email).one_or_none()
        if user is None:
            user = User(email=email, is_admin=is_admin)
            db_session.add(user)
            db_session.flush()
        return user

    return _make


@pytest.fixture()
def session_cookie(db_session, make_user):
    """Mints a session directly via `services.sessions.create_session`, bypassing
    `/login` entirely -- the documented v15 fallback (docs/GOTCHAS.md) for a test that
    needs a *second* live identity on the same `client`: passed as that one request's
    `cookies=` kwarg, it overrides the client's own jar for that call only, so it never
    clobbers whatever `authenticated_client`/`admin_client` already logged in as."""

    def _make(email: str, *, is_admin: bool = False) -> dict[str, str]:
        user = make_user(email, is_admin=is_admin)
        session = create_session(db_session, user.id)
        db_session.commit()
        return {"SPOTDL_SESSION": session.token}

    return _make


@pytest.fixture()
def count_queries(db_session):
    """Counts SQL statements executed inside a `with` block, for asserting a query count
    directly (v15's N+1 regression guard) rather than inferring it from timing.

    Listens on db_session's own Engine -- the `client` fixture overrides get_db with this
    exact session, so every statement a request issues passes through here. This is the
    repo's first query-counting helper; there was previously no way to assert this at all."""
    engine = db_session.get_bind()

    @contextmanager
    def _count():
        statements: list[str] = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", _record)
        try:
            yield statements
        finally:
            event.remove(engine, "before_cursor_execute", _record)

    return _count
