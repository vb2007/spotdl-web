#!/usr/bin/env python3
"""Checks that every variable a compose file *requires* is present in an env file (v33).

A required variable is one written with Compose's error-if-unset interpolation:
``${VAR:?message}`` (unset *or empty* is an error) or ``${VAR?message}`` (only unset is).
Compose refuses to render the whole project when one is missing, which is exactly how v28's new
``LIBRARY_DIR`` broke both its own deploy and its own rollback (plan/master-v4/00-master-plan.md,
"The pipeline incident"). Two callers, one parser:

- ``publish-deploy.yml``'s preflight, against the host's real ``.env`` before anything on the
  host moves (``--require-value``: an empty value fails ``:?`` exactly like a missing key).
- ``ci.yml``'s ``compose-config`` drift check, against ``.env.example`` / ``.env.dev.example``
  (key presence only: a template may legitimately leave a value blank for the owner to fill).

Stdlib-only, like check_version.py. Never prints an env *value*, only variable names, so it is
safe to run against a file holding real secrets.

Usage:
    check_required_env.py --env-file .env [--require-value] [--hint TEXT] COMPOSE_FILE...
Exits 0 when every required variable is satisfied, 1 when any is missing (each listed by name),
2 on a usage error (an unreadable file).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# `$${VAR:?x}` is Compose's escape for a literal `${VAR:?x}`, so a `$` right before the
# opening one means "not an interpolation"; `(?<!\$)` skips it.
REQUIRED_RE = re.compile(r"(?<!\$)\$\{([A-Za-z_][A-Za-z0-9_]*)(:?)\?")
# Compose's own .env grammar: optional `export `, KEY, optional spaces, `=`.
ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def required_vars(compose_files: list[Path]) -> dict[str, bool]:
    """Every required variable across the files -> whether an empty value also fails it."""
    found: dict[str, bool] = {}
    for path in compose_files:
        for line in path.read_text().splitlines():
            # A YAML comment can quote the syntax (docker-compose.prod.yml's header does,
            # for `${IMAGE_TAG:-latest}`); only real values interpolate.
            code = line.split(" #", 1)[0] if not line.lstrip().startswith("#") else ""
            for name, colon in REQUIRED_RE.findall(code):
                found[name] = found.get(name, False) or colon == ":"
    return found


def env_values(env_file: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        m = ENV_LINE_RE.match(line)
        if m:
            value = m.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            values[m.group(1)] = value
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument(
        "--require-value",
        action="store_true",
        help="also fail a ${VAR:?} whose key is present but empty (what Compose itself does)",
    )
    parser.add_argument("--hint", default="", help="appended to the failure message")
    parser.add_argument("compose_files", nargs="+", type=Path)
    args = parser.parse_args()

    try:
        required = required_vars(args.compose_files)
        env = env_values(args.env_file)
    except OSError as exc:
        print(f"check_required_env: {exc}", file=sys.stderr)
        return 2

    missing = []
    for name, empty_fails in sorted(required.items()):
        if name not in env:
            missing.append(f"{name} (not set)")
        elif args.require_value and empty_fails and env[name] == "":
            missing.append(f"{name} (set but empty)")

    files = ", ".join(str(p) for p in args.compose_files)
    if missing:
        print(
            f"check_required_env: {len(missing)} required variable(s) from {files} "
            f"missing in {args.env_file}:",
            file=sys.stderr,
        )
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        if args.hint:
            print(args.hint, file=sys.stderr)
        return 1

    names = ", ".join(sorted(required)) or "none"
    print(f"check_required_env: all required variables present in {args.env_file} ({names})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
