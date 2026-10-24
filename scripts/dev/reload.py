"""v52 (D2): dev-only autoreload for the Celery services, stdlib only.

A Celery worker keeps the Python it imported at boot, so an edit under the bind-mounted
`backend/app` never reached `worker-dl`/`worker-meta`/`worker-expand` until someone restarted
them by hand (docs/GOTCHAS.md, v06 and v48). `docker-compose.override.yml` makes this script
their entrypoint, so it runs the service's own `command` unchanged as a child process, and
restarts it when a `.py` file under the watched tree changes, much as `uvicorn --reload` does for
`api`. The image has no `watchfiles` (spotdl pins plain `uvicorn`, without its extras), so this
polls file times instead: a few hundred files, once a second.

    python reload.py [--watch DIR] [--grace SECONDS] -- <command...>

- A change restarts the child with SIGTERM (Celery's warm shutdown: a running task finishes),
  then SIGKILL after `--grace` seconds. The override gives `worker-dl` and `worker-expand` their
  `stop_grace_period` (300 s), so an edit waits for a download or a sweep as a `docker compose
  stop` would. A worker killed anyway leaves its task to beat's stale sweep (`task_acks_late`
  redelivers it only after the broker's visibility timeout).
- The first child exiting on its own ends this process with the same code, so a refused config
  (app/config.py's v32 guard) still stops the container, and a one-off `docker compose run`
  behaves as without the wrapper. A child restarted after an edit that then dies (a syntax
  error, say) is logged, and the next change starts it again, as `uvicorn --reload` does.
- SIGTERM/SIGINT to this process (`docker compose stop`) go to the child, with no grace of our
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
        child.kill()
        child.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--watch", default="/app/app")
    parser.add_argument("--grace", type=float, default=30.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command to run")

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

    def start() -> subprocess.Popen:
        started = subprocess.Popen(command)
        # A stop that arrived while there was no child to forward it to.
        if stopping:
            started.send_signal(signal.SIGTERM)
        return started

    child = start()
    restarted = False
    state = snapshot(args.watch)
    log(f"watching {len(state)} .py files under {args.watch}")
    while True:
        code = None
        if child is not None:
            try:
                code = child.wait(timeout=POLL_SEC)
            except subprocess.TimeoutExpired:
                pass
        else:
            time.sleep(POLL_SEC)
        if code is not None:
            if stopping or not restarted:
                if not stopping:
                    log(f"{command[0]} exited on its own ({code})")
                return code
            log(f"{command[0]} exited ({code}) after a reload; waiting for the next change")
            child = None
        if stopping:
            if child is None:
                return 0
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
        state = current
        shown = ", ".join(os.path.relpath(p, args.watch) for p in diff[:5])
        more = f" and {len(diff) - 5} more" if len(diff) > 5 else ""
        log(f"changed: {shown}{more}; restarting {command[0]}")
        if child is not None:
            stop(child, args.grace)
            if stopping:
                return child.returncode
        child = start()
        restarted = True


if __name__ == "__main__":
    sys.exit(main())
