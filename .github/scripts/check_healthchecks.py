#!/usr/bin/env python3
"""Fails when a rendered compose project's `celery` healthcheck imports the app or puts the broker
URL in argv (v72.1).

A healthcheck runs inside its container's memory limit. `celery -A app.tasks.celery_app inspect
ping` imports the whole app (~233 MiB against ~47 for an app-less ping), and Docker runs it every 5 s
during `start_period` until the first success, so it overlaps the worker's boot: on 2026-11-26 that,
with the alert watchdog and reconcile_disk, pushed worker-meta past its 768M limit into an OOM-restart loop once the host's swap was full (docs/GOTCHAS.md,
v72.1). `-b`/`--broker` would avoid the import but put the Redis password in argv, which `ps` on
the host shows; the URL goes in the probe's environment (CELERY_BROKER_URL) instead.

Reads `docker compose ... config --format json` on stdin, so it checks the merged services exactly
as they deploy. Limits: it guards against accidents, not deliberate obfuscation (a probe that never
spells "celery", e.g. `cel''ery` or a glob, isn't matched; review is the backstop), and it sees only
the rendered environment: a Dockerfile `ENV` or a variable in the host's real `.env` (CI renders with
`.env.example`) is invisible to it. Stdlib-only, like check_version.py.

Usage:
    docker compose -f docker-compose.yml -f docker-compose.prod.yml config --format json \\
        | check_healthchecks.py
Exits 0 when every celery healthcheck is app-less and URL-free, 1 otherwise (each named).
"""

from __future__ import annotations

import json
import re
import sys

# Deny by default: a healthcheck that mentions celery anywhere must be exactly this probe, an
# app-less ping whose broker URL comes from the probe's own environment. Parsing shell for every way
# to import the app or put a URL in argv (`-Aapp`, `-b$URL`, a subshell, `env VAR=…`) is an arms race;
# a new probe shape fails here and is reviewed before this template grows.
_SAFE_CELERY = re.compile(
    r'CELERY_BROKER_URL="\$\$?REDIS_URL" celery inspect ping -d worker-[a-z]+@\$\$?HOSTNAME -t \d+ >/dev/null 2>&1'
)


def offending_flags(test: list[str] | str) -> list[str]:
    """Why a healthcheck `test` is refused, or [] when it is fine."""
    if isinstance(test, str):
        kind, command = "CMD-SHELL", test
    else:
        kind, command = (test[0], " ".join(test[1:])) if test else ("", "")
    found = []
    # A rendered secret in any probe (e.g. a single-$ `${REDIS_URL}` that Compose filled in).
    if re.search(r"rediss?://", command, re.IGNORECASE):
        found.append("a redis URL")
    if "celery" in command.lower() and not (kind == "CMD-SHELL" and _SAFE_CELERY.fullmatch(command)):
        found.append("a celery probe other than the app-less template")
    return found


# Celery's CLI and default loader read these (celery/bin/celery.py, celery/loaders): set on a probed
# service, the template would still import the app (APP, CONFIG_MODULE, LOADER: ~235 MiB, measured)
# or take a URL from somewhere other than CELERY_BROKER_URL.
_CELERY_CLI_ENV = (
    "APP",
    "CELERY_APP",
    "CONFIG_MODULE",
    "CELERY_CONFIG_MODULE",
    "LOADER",
    "CELERY_LOADER",
    "BROKER_URL",
    "CELERY_BROKER",
    "RESULT_BACKEND",
    "CELERY_RESULT_BACKEND",
)


def refused_environment(environment: dict | list | None) -> list[str]:
    """The celery CLI defaults set in a service's rendered environment."""
    if isinstance(environment, list):
        names = [item.split("=", 1)[0] for item in environment]
    else:
        names = list(environment or {})
    return [f"{name} in its environment" for name in names if name in _CELERY_CLI_ENV]


def main() -> int:
    services = json.load(sys.stdin).get("services", {})
    bad = []
    for name, service in sorted(services.items()):
        test = (service.get("healthcheck") or {}).get("test")
        flags = offending_flags(test) if test else []
        if test and "celery" in " ".join(test if isinstance(test, list) else [test]).lower():
            flags += refused_environment(service.get("environment"))
        if flags:
            bad.append(f"{name}: {', '.join(flags)}")
    if bad:
        print("healthchecks refused (see .github/scripts/check_healthchecks.py and docs/GOTCHAS.md, v72.1):")
        for line in bad:
            print(f"  {line}")
        return 1
    print(f"healthchecks ok ({sum(1 for s in services.values() if s.get('healthcheck'))} checked)")
    return 0


if __name__ == "__main__":
    # Self-check: the shipped probe (raw and rendered) passes; the old probe and every shape a review
    # found slipping past an earlier parser are refused.
    ok = 'CELERY_BROKER_URL="$$REDIS_URL" celery inspect ping -d worker-meta@$$HOSTNAME -t 10 >/dev/null 2>&1'
    assert offending_flags(["CMD-SHELL", ok]) == []
    assert offending_flags(["CMD-SHELL", ok.replace("$$", "$")]) == []
    assert offending_flags(["CMD-SHELL", 'redis-cli --no-auth-warning -a "pw" ping | grep -q PONG']) == []
    assert offending_flags(["CMD-SHELL", "curl -fsS http://localhost:8000/api/health"]) == []
    celery_only = ["a celery probe other than the app-less template"]
    for bad in (
        "celery -A app.tasks.celery_app inspect ping -d worker-meta@$HOSTNAME -t 10",
        "celery -Aapp.tasks.celery_app inspect ping -d worker-meta@$HOSTNAME -t 10",
        "(celery -A app inspect ping)",
        "$(command -v celery) -A app inspect ping",
        "`command -v celery` -A app inspect ping",
        'celery -b"$REDIS_URL" inspect ping',
        'env CELERY_BROKER_URL="$REDIS_URL" celery inspect ping -d worker-meta@$HOSTNAME -t 10',
        "APP=app.tasks.celery_app celery inspect ping",
        "python -m celery -A app inspect ping",
        ok + "; celery -A app inspect ping",
    ):
        assert offending_flags(["CMD-SHELL", bad]) == celery_only, bad
    assert offending_flags(["CMD", "sh", "-c", ok]) == celery_only
    assert offending_flags(["CMD-SHELL", ok.replace('"$$REDIS_URL"', '"redis://:pw@redis:6379/0"')]) == [
        "a redis URL",
        *celery_only,
    ]
    assert refused_environment({"APP": "app.tasks.celery_app", "REDIS_URL": "x"}) == ["APP in its environment"]
    assert refused_environment(["BROKER_URL=x", "RUN_DISK_RECONCILE=true"]) == ["BROKER_URL in its environment"]
    assert refused_environment(None) == []
    assert refused_environment({"CELERY_CONFIG_MODULE": "app.tasks.celery_app"}) == [
        "CELERY_CONFIG_MODULE in its environment"
    ]
    sys.exit(main())
