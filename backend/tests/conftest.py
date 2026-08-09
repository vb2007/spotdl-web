import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("ALLOWED_EMAILS", "allowed@example.com")

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
from app.models import AppSettings, DownloadedTrack, Job, Proxy, Track, UserSession, WorkerState


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
    UserSession.__table__.create(engine)
    Job.__table__.create(engine)
    Proxy.__table__.create(engine)
    Track.__table__.create(engine)
    DownloadedTrack.__table__.create(engine)
    WorkerState.__table__.create(engine)
    AppSettings.__table__.create(engine)
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
