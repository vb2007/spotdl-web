"""Real-concurrency helpers for tests on Postgres (v51).

A race needs two real sessions on two real connections, interleaving at a chosen point: "B
commits between A's read and A's write". These helpers make that deterministic, never a sleep:

- `Gate` is a named point a thread stops at until the test opens it. Inject it where A must
  pause: as a monkeypatched function (`monkeypatch.setattr(mod, "fn", gate.wrap(mod.fn))`) or as
  a session event (`event.listen(session, "before_commit", gate, once=True)`).
- `Thread` runs one side of the race and hands its result, or its exception, back to the test.
- `blocked_or_done` tells "B is waiting on a row lock" apart from "B finished", from Postgres
  itself (`pg_stat_activity`), so a test can assert that a lock really held B off.

Use them with conftest's `committed_db` fixture, whose sessions really commit: rollback
isolation (`db_session`) keeps everything in one connection, which can't race itself.

    gate = Gate("cancel_job before its commit")
    a = Thread(run_cancel, name="cancel")      # pauses at the gate
    gate.wait_reached()
    b = Thread(run_expand, name="expand")
    assert blocked_or_done(b) == "blocked"     # B waits on A's FOR UPDATE
    gate.open()
    a.join(); b.join()
"""

import threading
import time

from sqlalchemy import Engine, text

# Long enough for a loaded CI runner, short enough that a broken interleaving fails the test
# instead of hanging the run.
TIMEOUT = 15.0
_POLL = 0.01

# Every gate and thread the current test made, so conftest's committed_db can release them when
# the test ends early (a failed assertion with a thread still parked at a gate, holding its
# transaction's locks, would otherwise block the teardown's TRUNCATE).
_gates: list["Gate"] = []
_threads: list["Thread"] = []


class InterleavingBroke(Exception):
    """The interleaving itself failed (a gate never reached or opened, a thread that never
    finished or blocked), as opposed to the race's outcome. Not an AssertionError, so an
    `xfail(raises=AssertionError)` race test can't count a broken harness as the expected
    failure."""


class Gate:
    """A point one thread stops at until the test calls `open()`. Callable with any arguments,
    so it can stand in for a hook or a session event listener directly."""

    def __init__(self, name: str, timeout: float = TIMEOUT) -> None:
        self.name = name
        self.timeout = timeout
        self._reached = threading.Event()
        self._open = threading.Event()
        _gates.append(self)

    def __call__(self, *args, **kwargs) -> None:
        self._reached.set()
        if not self._open.wait(self.timeout):
            raise InterleavingBroke(f"gate {self.name!r} was never opened")

    def wrap(self, fn):
        """`fn`, stopping at this gate before it runs."""

        def wrapped(*args, **kwargs):
            self()
            return fn(*args, **kwargs)

        return wrapped

    def wait_reached(self) -> None:
        if not self._reached.wait(self.timeout):
            raise InterleavingBroke(f"no thread reached gate {self.name!r}")

    @property
    def reached(self) -> bool:
        return self._reached.is_set()

    def open(self) -> None:
        self._open.set()


class Thread:
    """Runs `fn(*args, **kwargs)` in a daemon thread at once. `join()` returns its result or
    re-raises its exception in the test's own thread."""

    def __init__(self, fn, *args, name: str, **kwargs) -> None:
        self.name = name
        self._result = None
        self._error: BaseException | None = None

        def run():
            try:
                self._result = fn(*args, **kwargs)
            except BaseException as exc:  # handed to join(), never swallowed
                self._error = exc

        self._thread = threading.Thread(target=run, name=name, daemon=True)
        _threads.append(self)
        self._thread.start()

    @property
    def done(self) -> bool:
        return not self._thread.is_alive()

    def join(self, timeout: float = TIMEOUT):
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise InterleavingBroke(f"thread {self.name!r} still running after {timeout}s")
        if self._error is not None:
            raise self._error
        return self._result


def lock_waiters(engine: Engine | None = None) -> list[int]:
    """Backend pids in this run's database that are waiting on a lock right now. The run's
    database is its own (conftest), so every waiter is one of this test's sessions."""
    if engine is None:
        from app.db import engine
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT pid FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            ).scalars()
        )


def blocked_or_done(thread: Thread, engine: Engine | None = None, timeout: float = TIMEOUT) -> str:
    """Waits until `thread` has finished ("done") or a session in this database waits on a lock
    ("blocked"), whichever comes first. Raises if neither happens within `timeout`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if thread.done:
            return "done"
        if lock_waiters(engine):
            return "blocked"
        time.sleep(_POLL)
    raise InterleavingBroke(f"thread {thread.name!r} neither finished nor blocked on a lock in {timeout}s")


def release_all() -> list[str]:
    """Opens every gate the test made and waits for every thread it started, so none is left
    holding a transaction. Returns the names of threads still running after TIMEOUT (stuck on
    something other than a gate); their errors were the test's to report."""
    for gate in _gates:
        gate.open()
    stuck = []
    for thread in _threads:
        thread._thread.join(TIMEOUT)
        if thread._thread.is_alive():
            stuck.append(thread.name)
    _gates.clear()
    _threads.clear()
    return stuck
