#!/usr/bin/env python3
"""Check that backend and frontend versions agree, and (given a base ref) that any diff
touching backend/ or frontend/ actually bumped the version.

Stdlib-only, same style as junit_to_summary.py — this runs before any project dependency is
installed, so it can't assume tomllib/packaging/anything beyond the interpreter itself.

Usage:
    check_version.py            # just check backend/frontend agree on a valid semver
    check_version.py <base-ref> # also fail if backend/ or frontend/ changed since <base-ref>
                                 # without the version changing (path-aware: a docs-only diff
                                 # is not forced to bump)

Prints the resolved version to stdout on success — release.yml reuses this as the single
source of the version string rather than a second, possibly-disagreeing parser.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "backend" / "pyproject.toml"
PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
VERSION_LINE_RE = re.compile(r'(?m)^version\s*=\s*"([^"]+)"')
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def read_backend_version(text: str, source: str) -> str:
    match = VERSION_LINE_RE.search(text)
    if not match:
        raise SystemExit(f"check_version: no version= line found in {source}")
    return match.group(1)


def read_frontend_version(text: str, source: str) -> str:
    data = json.loads(text)
    version = data.get("version")
    if not version:
        raise SystemExit(f'check_version: no "version" key found in {source}')
    return version


def git_show(ref: str, rel_path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{rel_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else None


def changed_paths(base: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else None

    backend_version = read_backend_version(PYPROJECT.read_text(), str(PYPROJECT))
    frontend_version = read_frontend_version(PACKAGE_JSON.read_text(), str(PACKAGE_JSON))

    if backend_version != frontend_version:
        print(
            f"check_version: version drift — backend/pyproject.toml has {backend_version!r}, "
            f"frontend/package.json has {frontend_version!r}. Both must carry the same version.",
            file=sys.stderr,
        )
        return 1

    version = backend_version
    if not SEMVER_RE.match(version):
        print(
            f"check_version: {version!r} is not a plain major.minor.patch semver string",
            file=sys.stderr,
        )
        return 1

    if base:
        changed = changed_paths(base)
        touches_app_code = any(p.startswith(("backend/", "frontend/")) for p in changed)
        if touches_app_code:
            base_pyproject = git_show(base, "backend/pyproject.toml")
            base_version = (
                VERSION_LINE_RE.search(base_pyproject).group(1)
                if base_pyproject and VERSION_LINE_RE.search(base_pyproject)
                else None
            )
            if base_version == version:
                print(
                    f"check_version: this diff touches backend/ or frontend/ but the version "
                    f"({version}) is unchanged since {base}. Bump backend/pyproject.toml and "
                    f"frontend/package.json to the same new version before this PR is "
                    f"merge-ready (see CLAUDE.md's versioning rule).",
                    file=sys.stderr,
                )
                return 1

    print(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
