"""v52 (D2): dev-only autoreload for the Celery workers, stdlib only.

A Celery worker keeps the Python it imported at boot, so an edit under the bind-mounted
`backend/app` never reached `worker-dl`/`worker-meta`/`worker-expand` until someone restarted
them by hand (docs/GOTCHAS.md, v23 and v48). `docker-compose.override.yml` makes this script
their entrypoint, so it runs the service's own `command` unchanged as a child process, and
restarts it when a `.py` file under the watched tree changes, much as `uvicorn --reload` does for
`api`. The image has no `watchfiles` (pyproject.toml's uv override pins plain `uvicorn`, for
spotdl's sake, which drops `[standard]`'s extras), so this polls file times instead: a few
hundred files, once a second.

    python reload.py [--watch DIR] [--grace SECONDS] -- <command...>

- Only a long-running `celery ... worker` is supervised. Any other command (a one-off
  `docker compose run --rm worker-meta python ...`, an interactive shell) replaces this process
  through exec, exactly as without the wrapper: it's never restarted on an edit.
- A change restarts the worker with SIGTERM (Celery's warm shutdown: a running task finishes),
  then SIGKILL after `--grace` seconds: by default Docker's own 10 s stop grace (worker-meta's),
  and the override passes `worker-dl`'s and `worker-expand`'s `stop_grace_period` (300 s), so
  an edit waits for a download or a sweep as a `docker compose stop` would. A worker killed
  anyway leaves its task to beat's stale sweep (`task_acks_late` redelivers it only after the
  broker's visibility timeout).
- A worker exiting on its own, whenever and however (a refused config, the app/config.py v32
  guard; a syntax error an edit brought in; an OOM kill), ends this process with its status,
  so Docker's restart policy handles it as it did before v52. An edit that breaks the import
  crash-loops the container until it's fixed.
- SIGTERM/SIGINT to this process (`docker compose stop`) go to the worker, with no grace of our
  own: the service's `stop_grace_period` decides. The override runs it under `init: true`, so
  it isn't PID 1 and orphans are reaped.

Never used in production: only the dev override names it, and the image doesn't contain it.
"""

import argparse
import os
import signal
import subprocess
import sys
import time

POLL_SEC = 1.0
# A checkout or rebase rewrites many files over a moment: restart once it has settled.
SETTLE_SEC = 0.5


def log(message: str) -> None:
    print(f"dev-reload: {message}", file=sys.stderr, flush=True)


def snapshot(root: str) -> dict[str, tuple[int, int]]:
    files: dict[str, tuple[int, int]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__" and not d.startswith(".")]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            try:
                st = os.stat(path)
            except FileNotFoundError:
                continue
            files[path] = (st.st_mtime_ns, st.st_size)
    return files


def changed(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    return sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))


def stop(child: subprocess.Popen, grace: float) -> None:
    child.send_signal(signal.SIGTERM)
    try:
        child.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        log(f"still running {grace:g}s after SIGTERM; killing it")
        # The whole process group (it has its own): Celery's pool children die with their parent,
        # but a task's own subprocess (ffmpeg, say) would keep writing next to the new worker.
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()


def exit_status(code: int) -> int:
    """A child killed by signal N (Popen's -N) as a shell reports it, 128 + N: sys.exit(-15)
    would exit 241."""
    return 128 - code if code < 0 else code


def is_worker(command: list[str]) -> bool:
    return os.path.basename(command[0]) == "celery" and "worker" in command[1:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--watch", default="/app/app")
    parser.add_argument("--grace", type=float, default=10.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command to run")
    if not is_worker(command):
        os.execvp(command[0], command)

    child: subprocess.Popen | None = None
    stopping = False

    def forward(signum, _frame):
        nonlocal stopping
        stopping = True
        if child is not None and child.poll() is None:
            child.send_signal(signum)

    # Before the first child exists, so a stop that arrives at once isn't lost.
    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)

    def start() -> dict[str, tuple[int, int]]:
        nonlocal child
        # Taken before the worker imports anything: an edit from here on is newer than what it
        # runs, and one made while the previous worker was still shutting down isn't.
        state = snapshot(args.watch)
        # Its own process group: a terminal's Ctrl-C (`docker compose run -it`) reaches only this
        # process, which forwards it once. Twice would be Celery's cold shutdown.
        child = subprocess.Popen(command, process_group=0)
        # Checked after `child` is set: a stop that arrived while there was no live child to
        # forward it to is sent now, and one arriving later finds this child.
        if stopping:
            child.send_signal(signal.SIGTERM)
        return state

    state = start()
    log(f"watching {len(state)} .py files under {args.watch}")
    while True:
        try:
            code = child.wait(timeout=POLL_SEC)
        except subprocess.TimeoutExpired:
            code = None
        if code is not None:
            if not stopping:
                log(f"{command[0]} exited on its own ({code})")
            return exit_status(code)
        if stopping:
            continue
        current = snapshot(args.watch)
        diff = changed(state, current)
        if not diff:
            continue
        # Let a burst of writes finish before restarting on it.
        while True:
            time.sleep(SETTLE_SEC)
            settled = snapshot(args.watch)
            if settled == current:
                break
            diff = sorted(set(diff) | set(changed(current, settled)))
            current = settled
        shown = ", ".join(os.path.relpath(p, args.watch) for p in diff[:5])
        more = f" and {len(diff) - 5} more" if len(diff) > 5 else ""
        log(f"changed: {shown}{more}; restarting {command[0]}")
        stop(child, args.grace)
        if stopping:
            return exit_status(child.returncode)
        state = start()


if __name__ == "__main__":
    sys.exit(main())
