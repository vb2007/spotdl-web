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
import re
import sys

# Celery's own flags that import the app (-A/--app; click also reads APP and CELERY_APP from the
# environment) or carry a URL into argv (-b/--broker, --result-backend).
_LONG = ("--app", "--broker", "--result-backend")
_SHORT = re.compile(r"-[A-Za-z]*[Ab][A-Za-z]*")  # -A, -b, and clusters such as -qA
_ENV = ("APP=", "CELERY_APP=")


def offending_flags(test: list[str] | str) -> list[str]:
    """What a healthcheck `test` must not do, in the order found. The whole test is read as one
    text, so a command nested in `sh -c` is checked too, and words split on shell separators even
    when glued (`true;celery`)."""
    text = test if isinstance(test, str) else " ".join(test)
    found = []
    # A rendered secret in any probe (e.g. a single-$ `${REDIS_URL}` that Compose filled in).
    if re.search(r"rediss?://", text):
        found.append("a redis URL")
    if re.search(r"(^|[\s/;&|'\"])celery([\s;&|'\"]|$)", text):
        for word in re.split(r"[\s;&|'\"]+", text):
            flag = word.split("=", 1)[0] + ("=" if "=" in word else "")
            if word in _LONG or word.startswith(tuple(f + "=" for f in _LONG)):
                found.append(word.split("=", 1)[0])
            elif _SHORT.fullmatch(word):
                found.append(word)
            elif flag in _ENV:
                found.append(flag)
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
    # Self-check of the parser: the old and new probes, and shapes that must not slip through.
    assert offending_flags(["CMD-SHELL", "celery -A app.tasks.celery_app inspect ping -d w@h -t 10"]) == ["-A"]
    assert offending_flags(["CMD-SHELL", 'CELERY_BROKER_URL="$REDIS_URL" celery inspect ping -d w@h -t 10']) == []
    assert offending_flags(["CMD-SHELL", 'CELERY_BROKER_URL="$$REDIS_URL" celery inspect ping -d w@$$HOSTNAME']) == []
    assert offending_flags(["CMD-SHELL", 'celery -b "$REDIS_URL" inspect ping']) == ["-b"]
    assert offending_flags(["CMD", "celery", "--app=x", "inspect", "ping"]) == ["--app"]
    assert offending_flags(["CMD", "sh", "-c", "celery -A app inspect ping"]) == ["-A"]
    assert offending_flags(["CMD-SHELL", "true;celery -qA x inspect ping"]) == ["-qA"]
    assert offending_flags(["CMD-SHELL", "APP=app.tasks.celery_app celery inspect ping"]) == ["APP="]
    assert offending_flags(["CMD-SHELL", "celery --result-backend redis://:pw@redis/0 inspect ping"]) == [
        "a redis URL",
        "--result-backend",
    ]
    assert offending_flags(["CMD-SHELL", 'CELERY_BROKER_URL="redis://:pw@redis:6379/0" celery inspect ping']) == [
        "a redis URL"
    ]
    assert offending_flags(["CMD-SHELL", 'redis-cli --no-auth-warning -a "pw" ping | grep -q PONG']) == []
    assert offending_flags(["CMD-SHELL", "curl -fsS http://localhost:8000/api/health"]) == []
    sys.exit(main())
