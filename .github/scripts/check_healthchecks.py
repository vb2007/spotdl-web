#!/usr/bin/env python3
"""Fails when a rendered compose project's `celery` healthcheck imports the app or puts the broker
URL in argv (v72.1).

A healthcheck runs inside its container's memory limit. `celery -A app.tasks.celery_app inspect
ping` imports the whole app (~233 MiB against ~47 for an app-less ping), and Docker runs it every 5 s
until the first success, so it overlaps the worker's boot: on 2026-11-26 that pushed worker-meta
past its 768M limit into an OOM-restart loop once the host's swap was full (docs/GOTCHAS.md,
v72.1). `-b`/`--broker` would avoid the import but put the Redis password in argv, which `ps` on
the host shows; the URL goes in the probe's environment (CELERY_BROKER_URL) instead.

Reads `docker compose ... config --format json` on stdin, so it checks the merged services exactly
as they deploy. Stdlib-only, like check_version.py.

Usage:
    docker compose -f docker-compose.yml -f docker-compose.prod.yml config --format json \\
        | check_healthchecks.py
Exits 0 when every celery healthcheck is app-less and URL-free, 1 otherwise (each named).
"""

from __future__ import annotations

import json
import shlex
import sys

FORBIDDEN = ("-A", "--app", "-b", "--broker")


def offending_flags(test: list[str] | str) -> list[str]:
    """The forbidden celery flags in one healthcheck `test`, in the order they appear."""
    if isinstance(test, str):
        command = test
    elif test and test[0] == "CMD-SHELL":
        command = " ".join(test[1:])
    else:
        command = shlex.join(test[1:] if test and test[0] == "CMD" else test)
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    found, in_celery = [], False
    for word in words:
        if word in ("&&", "||", ";", "|"):
            in_celery = False
        elif word == "celery" or word.endswith("/celery"):
            in_celery = True
        elif in_celery and (word in FORBIDDEN or word.startswith(("--app=", "--broker=", "-A", "-b"))):
            found.append(word.split("=", 1)[0])
    return found


def main() -> int:
    services = json.load(sys.stdin).get("services", {})
    bad = []
    for name, service in sorted(services.items()):
        test = (service.get("healthcheck") or {}).get("test")
        if test and (flags := offending_flags(test)):
            bad.append(f"{name}: {', '.join(flags)}")
    if bad:
        print("celery healthchecks must be app-less, with the broker URL in the probe's environment:")
        for line in bad:
            print(f"  {line}")
        return 1
    print(f"healthchecks ok ({sum(1 for s in services.values() if s.get('healthcheck'))} checked)")
    return 0


if __name__ == "__main__":
    # Self-check of the parser on the shapes this repo uses (old and new probe).
    assert offending_flags(["CMD-SHELL", "celery -A app.tasks.celery_app inspect ping -d w@h -t 10"]) == ["-A"]
    assert offending_flags(["CMD-SHELL", 'CELERY_BROKER_URL="$REDIS_URL" celery inspect ping -d w@h']) == []
    assert offending_flags(["CMD-SHELL", 'celery -b "$REDIS_URL" inspect ping']) == ["-b"]
    assert offending_flags(["CMD", "celery", "--app=x", "inspect", "ping"]) == ["--app"]
    assert offending_flags(["CMD-SHELL", "redis-cli -a pw ping | grep -q PONG"]) == []
    sys.exit(main())
