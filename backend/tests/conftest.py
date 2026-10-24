"""The suite runs on real Postgres (v51). Before it, every test ran on in-memory SQLite, which
ignores `FOR UPDATE`, has no native enums and compares differently, so a fixed race could only
be "proven" by asserting that a lock was requested.

Each run creates its own database on the server `TEST_DATABASE_URL` names, builds the schema with
Alembic (`upgrade head`, so every migration runs on every run) and drops it at the end. Two runs
at once (two slots, or CI beside a slot) never share a database. `scripts/agent_stack.sh <slot>
pytest` sets `TEST_DATABASE_URL` to the slot's own Postgres; CI sets it to the job's service
container. Isolation is per test: `db_session` rolls everything back (the default), and
`committed_db` truncates instead, for the real-concurrency tests (`tests/concurrency.py`) whose
sessions must see each other's commits.

The SQLite engine path is gone, not kept behind a flag (decision recorded in docs/LOCAL_DEV.md).
"""

import os
import uuid

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.config import PRODUCTION_DATABASE_NAMES, check_not_production_database

# The database name must carry this marker, so the suite never runs on a database that wasn't
# made for it; production's names (app/config.py's v32 guard) are refused on top of that.
TEST_DATABASE_MARKER = "test"
# libpq lets these query keys pick the database or the server, over the URL's path and host.
# The per-run database replaces the path, so either would point the run, and its closing DROP,
# somewhere else.
_DATABASE_SELECTING_KEYS = ("dbname", "service", "host", "hostaddr", "port")
# The servers a run may create databases on: a slot's own container (`postgres`, inside its
# compose project) and a loopback one (CI's service container, a local `docker run`). Never the
# LAN server: it is production's (`spotdlwebtest` lives beside `spotdlweb`), and its test marker
# alone would let a run CREATE and DROP databases there.
_ALLOWED_HOSTS = ("postgres", "localhost", "127.0.0.1", "::1")
# libpq reads these from the environment for whatever the URL leaves out, and each can send the
# connection to another server than the URL's host (a hostaddr wins over the host).
_SERVER_SELECTING_ENV = ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")
# Room for "_" + 12 hex characters inside Postgres's 63-byte identifier limit.
_MAX_STEM = 40
# A server holding any of these is production's, whatever address reached it: on the production
# host (the CI runner) its Postgres answers on loopback too. `spotdlwebtest`, the owner's dev
# database, lives on that same server.
_PRODUCTION_SERVER_DATABASES = (*PRODUCTION_DATABASE_NAMES, "spotdlwebtest")


def _test_database_urls() -> tuple[str, str]:
    """(server URL on its maintenance database, this run's own database URL), from
    TEST_DATABASE_URL. Raises ValueError naming the database only, never the URL (it carries
    the password)."""
    raw = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not raw:
        raise ValueError(
            "TEST_DATABASE_URL is not set. Run the suite with `scripts/agent_stack.sh <slot> "
            "pytest`, or point TEST_DATABASE_URL at a disposable Postgres server (docs/LOCAL_DEV.md)"
        )
    # v32's guard, with the dev marker forced on: an unparseable URL, one naming no database
    # and one naming production's database are all refused.
    try:
        check_not_production_database(raw, "dev")
    except ValueError as exc:
        raise ValueError(f"TEST_DATABASE_URL is refused by app/config.py's production-database guard: {exc}") from None
    try:
        url = make_url(raw)
    except (ArgumentError, ValueError):  # unreachable after the guard; kept fail-closed
        raise ValueError("TEST_DATABASE_URL can't be parsed") from None
    for name in _SERVER_SELECTING_ENV:
        if os.environ.get(name):
            raise ValueError(f"{name} is set, and libpq would let it pick the server; unset it")
    for key in _DATABASE_SELECTING_KEYS:
        if key in url.query:
            raise ValueError(f"TEST_DATABASE_URL must name its server and database in the URL, not with ?{key}=")
    if TEST_DATABASE_MARKER not in url.database.lower():
        raise ValueError(
            f"TEST_DATABASE_URL names the database {url.database!r}, which has no "
            f"{TEST_DATABASE_MARKER!r} marker in its name; the suite runs only on a test database"
        )
    host = (url.host or "").lower()
    if host not in _ALLOWED_HOSTS:
        raise ValueError(
            f"TEST_DATABASE_URL names the server {url.host!r}; the suite creates databases only on "
            f"a slot's own Postgres or a loopback one ({', '.join(_ALLOWED_HOSTS)})"
        )
    # On the production host (the CI runner), loopback's default port is production's own
    # Postgres. A disposable one is published on a port Docker picks, so name it.
    if host != "postgres" and url.port in (None, 5432):
        raise ValueError(
            "TEST_DATABASE_URL on a loopback host needs its port, and not 5432 (on the production "
            "host that is production's Postgres): `docker port <container> 5432` prints it"
        )
    # Postgres truncates identifiers past 63 bytes, which would merge two runs' names.
    if len(url.database.encode()) > _MAX_STEM:
        raise ValueError(f"TEST_DATABASE_URL's database name is over {_MAX_STEM} bytes")
    run_database = f"{url.database}_{uuid.uuid4().hex[:12]}"
    run_url = url.set(database=run_database).render_as_string(hide_password=False)
    # alembic/env.py hands the URL to Alembic's configparser, which reads `%` as interpolation:
    # it would crash and print the whole URL, password included.
    if "%" in run_url:
        raise ValueError(
            "TEST_DATABASE_URL needs %-escaping (a special character in the password or a "
            "query value), which Alembic's config can't take; use a plainer one"
        )
    return url.set(database="postgres").render_as_string(hide_password=False), run_url


try:
    MAINTENANCE_DATABASE_URL, RUN_DATABASE_URL = _test_database_urls()
    _REFUSAL = None
except ValueError as exc:
    MAINTENANCE_DATABASE_URL = RUN_DATABASE_URL = None
    _REFUSAL = str(exc)

# Every engine the app builds (app.db's, alerts' watchdog, Alembic's) reads DATABASE_URL, so it
# is set unconditionally: nothing the suite runs can reach any other database. A refused run
# gets an address that can't resolve, and pytest_configure stops it before any test.
os.environ["DATABASE_URL"] = RUN_DATABASE_URL or "postgresql+psycopg://refused@refused.invalid/refused_test"
# libpq sends this as a startup option, which outranks a role's or the database's own TimeZone:
# the suite compares aware datetimes (the run's database is set to UTC too).
os.environ["PGTZ"] = "UTC"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SESSION_SECRET", "test-secret")
# Two addresses: ADMIN_EMAIL must be allowlisted too (config.py's v17 validator), and
# most ownership/admin-gating tests need a non-admin *and* an admin identity available.
os.environ.setdefault("ALLOWED_EMAILS", "allowed@example.com,admin@example.com")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")

import logging
import signal
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

import concurrency
from app.db import Base, engine, get_db
from app.main import app
from app.models import User
from app.routers import auth as auth_router
from app.services.sessions import create_session

_BACKEND = Path(__file__).resolve().parents[1]


def pytest_configure(config):
    # --help and --markers configure pytest without running anything.
    if _REFUSAL is not None and not (config.option.help or config.option.markers):
        raise pytest.UsageError(f"refusing to run the suite: {_REFUSAL}")


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _report(session, line: str) -> None:
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        # After the last test, the progress line ("...  [100%]") is still open.
        if reporter._tw.width_of_current_line:
            reporter.write("\n")
        reporter.write_line(f"test database: {line}")


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


_CREATED = pytest.StashKey[str]()


def _maintenance_engine():
    return create_engine(MAINTENANCE_DATABASE_URL, isolation_level="AUTOCOMMIT", poolclass=NullPool)


def _drop(name: str) -> None:
    engine.dispose()
    with _maintenance_engine().connect() as conn:
        conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {_quoted(name)} WITH (FORCE)")


def pytest_sessionstart(session):
    """Creates this run's database and migrates it to head, before any test (or collection)
    runs. The migrations Alembic ran are printed, so a CI log shows them."""
    url = make_url(RUN_DATABASE_URL)
    try:
        with _maintenance_engine().connect() as conn:
            production = conn.execute(
                text("SELECT datname FROM pg_database WHERE lower(datname) = ANY(:names)"),
                {"names": [n.lower() for n in _PRODUCTION_SERVER_DATABASES]},
            ).scalars().first()
            if production is not None:
                raise pytest.UsageError(
                    f"refusing to run the suite: the server at {url.host}:{url.port or 5432} holds "
                    f"{production!r}, so it is production's; use a slot's or a disposable one"
                )
            conn.exec_driver_sql(f"CREATE DATABASE {_quoted(url.database)}")
            session.config.stash[_CREATED] = url.database
            # Every session on it reads timestamps in UTC, whatever the server's own TimeZone:
            # the suite compares aware datetimes, and a disposable server needn't be UTC.
            conn.exec_driver_sql(f"ALTER DATABASE {_quoted(url.database)} SET timezone TO 'UTC'")
            # A lock a broken test leaves held (a connection nothing here watches) fails the
            # next test that needs it, instead of hanging the run. Well above the race tests'
            # own waits (concurrency.TIMEOUT).
            conn.exec_driver_sql(f"ALTER DATABASE {_quoted(url.database)} SET lock_timeout TO '30s'")
    except DBAPIError as exc:
        # pytest skips sessionfinish when sessionstart raises: drop what was created here.
        if session.config.stash.get(_CREATED, None) is not None:
            _drop(url.database)
        # The driver's message names host and port, never the password.
        raise pytest.UsageError(f"can't create the test database {url.database}: {exc.orig}") from None
    # SIGTERM (a `kill`) would end the run without sessionfinish, leaving the database behind;
    # as a KeyboardInterrupt, pytest unwinds and drops it like a Ctrl-C does. (A stopped `api`
    # container SIGKILLs it instead: that one is left, docs/LOCAL_DEV.md.)
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    _report(session, f"created {url.database} on {url.host}:{url.port or 5432}")
    # No ini file: alembic/env.py runs fileConfig() on one, which would disable every logger
    # the app has already created (and with them, every caplog assertion).
    alembic_config = Config()
    alembic_config.set_main_option("script_location", str(_BACKEND / "alembic"))
    migration_log = logging.getLogger("alembic.runtime.migration")
    collect = _Collect()
    level = migration_log.level
    migration_log.addHandler(collect)
    migration_log.setLevel(logging.INFO)
    try:
        command.upgrade(alembic_config, "head")
    except BaseException:
        # pytest skips sessionfinish when sessionstart raises: drop it here, or it's left behind.
        _drop(url.database)
        raise
    finally:
        migration_log.removeHandler(collect)
        migration_log.setLevel(level)
    for line in collect.lines:
        if line.startswith("Running upgrade"):
            _report(session, f"alembic upgrade head: {line}")


# trylast: after an interrupt, pytest tears the interrupted test's fixtures down in its own
# sessionfinish; dropping the database before that would make their teardown fail noisily.
@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    name = session.config.stash.get(_CREATED, None)
    if name is not None:
        _drop(name)
        _report(session, f"dropped {name}")


def _ignore_isolation_level(connection) -> None:
    """`app.db.begin_snapshot` switches its session to REPEATABLE READ, which Postgres allows
    only at a transaction's start. A rollback-isolated test runs inside one outer transaction,
    so the switch is dropped here: with no concurrent writer it reads the same rows either
    way. The snapshot itself is proven by a `committed_db` test, where it really happens."""
    real = connection.execution_options

    def execution_options(**options):
        options.pop("isolation_level", None)
        return real(**options) if options else connection

    connection.execution_options = execution_options


@pytest.fixture()
def db_session():
    """One outer transaction per test, rolled back at the end. The code under test commits and
    rolls back freely: each of those ends a SAVEPOINT inside it instead.

    Any other connection the test opens on app.db's engine fails it (an engine of its own, like
    the alerts watchdog's, isn't watched): that is a SessionLocal the
    test forgot to patch, which reads past the test's uncommitted rows and commits for real,
    outside the rollback, into every later test."""
    connection = engine.connect()
    transaction = connection.begin()
    _ignore_isolation_level(connection)
    session = Session(bind=connection, join_transaction_mode="create_savepoint", autoflush=False)
    strays = []

    def _stray(dbapi_connection, connection_record, connection_proxy):
        strays.append(connection_record)

    event.listen(engine, "checkout", _stray)
    try:
        yield session
    finally:
        event.remove(engine, "checkout", _stray)
        session.close()
        transaction.rollback()
        connection.close()
    # A Gate or Thread needs committed_db (one connection can't race itself), which releases them.
    leftovers = concurrency.release_all()
    if strays:
        # What the stray connection committed is outside the rollback: clear it for the next test.
        _end_other_sessions()
        _truncate_all()
    assert not leftovers, f"the test's threads (tests/concurrency.py belongs with committed_db): {leftovers}"
    assert not strays, (
        f"the test opened {len(strays)} connection(s) of its own on the run's database, outside "
        "db_session's rollback: patch the SessionLocal it reached, or use committed_db"
    )


def _end_other_sessions() -> None:
    """Terminates every other session on the run's database: one a failed test left open (its
    traceback keeps the Session alive) would hold its locks and block every later test, with
    no timeout on a plain db_session statement. The pool's dead connections are replaced on
    their next checkout (app.db's engine pings first)."""
    with engine.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        )
        conn.commit()
    engine.dispose()


def _truncate_all() -> None:
    tables = ", ".join(_quoted(t.name) for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        # A session a test left open would otherwise hang the run here, holding its locks.
        conn.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
        conn.exec_driver_sql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
        # Put back what the migrations seed (the initial schema's worker_state row), so the
        # next test starts from the same database a fresh `upgrade head` leaves.
        conn.execute(
            text(
                "INSERT INTO worker_state (id, breaker_trip_count, consecutive_failures, paused) "
                "VALUES (1, 0, 0, false)"
            )
        )


@pytest.fixture()
def committed_db(request, monkeypatch):
    """A sessionmaker on this run's database whose sessions really commit, so several of them
    (and the threads in tests/concurrency.py) see each other's writes and locks, the way two
    workers or two requests do. Every table is truncated afterwards. It depends on `monkeypatch`
    so it is torn down first: a thread a failed test left parked resumes with the test's stubs
    still in place, never the real publish or Celery send. Use it only where a test
    needs that; `db_session` is faster and the default."""
    if "db_session" in request.fixturenames:
        # Its teardown truncates and ends every other session, which db_session's open outer
        # transaction can't survive. A race test calls the endpoint or task function directly
        # with a committed session (see test_jobs.py's), not through `client`.
        pytest.fail(
            "committed_db can't be combined with db_session or a fixture built on it "
            "(client, authenticated_client, admin_client, owner, make_user, session_cookie, "
            "count_queries)",
            pytrace=False,
        )
    # app.db.SessionLocal's own settings, so the code under test behaves as it does in a worker.
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield factory
    finally:
        problems = concurrency.release_all()
        _end_other_sessions()
        _truncate_all()
        assert not problems, f"the test's threads: {problems}"


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


_SAVEPOINT_STATEMENTS = ("SAVEPOINT ", "RELEASE SAVEPOINT ", "ROLLBACK TO SAVEPOINT ")


@pytest.fixture()
def count_queries(db_session):
    """Counts SQL statements executed inside a `with` block, for asserting a query count
    directly (v15's N+1 regression guard) rather than inferring it from timing.

    Listens on db_session's own connection -- the `client` fixture overrides get_db with this
    exact session, so every statement a request issues passes through here. This is the
    repo's first query-counting helper; there was previously no way to assert this at all.
    The SAVEPOINTs that stand in for the code's commits under the rollback isolation (v51)
    aren't counted: they aren't the code's own statements."""
    engine = db_session.get_bind()

    @contextmanager
    def _count():
        statements: list[str] = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            if not statement.startswith(_SAVEPOINT_STATEMENTS):
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", _record)
        try:
            yield statements
        finally:
            event.remove(engine, "before_cursor_execute", _record)

    return _count
