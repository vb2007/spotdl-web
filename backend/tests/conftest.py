import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("ALLOWED_EMAILS", "allowed@example.com")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import DownloadedTrack, Job, Track, UserSession


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
    Track.__table__.create(engine)
    DownloadedTrack.__table__.create(engine)
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
