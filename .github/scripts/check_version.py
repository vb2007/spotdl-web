#!/usr/bin/env python3
"""Check that backend and frontend versions agree, and (given a base ref) that any diff
touching backend/ or frontend/ actually bumped the version.

v61: an independent second rule for the Firefox extension. Its version lives in
extension/manifest.json and never has to match the app's: a diff touching extension/ must raise
it above the base's, and a diff that doesn't touch extension/ is never asked to.

Stdlib-only, same style as junit_to_summary.py — this runs before any project dependency is
installed, so it can't assume tomllib/packaging/anything beyond the interpreter itself.

Usage:
    check_version.py            # just check backend/frontend agree on a valid semver
    check_version.py <base-ref> # also fail if backend/ or frontend/ changed since <base-ref>
                                 # without the version rising above <base-ref>'s (path-aware:
                                 # a docs-only diff is not forced to bump), and the same for
                                 # extension/ and the extension's own version
    check_version.py --extension # print the extension's version (nothing if there's no
                                 # extension/manifest.json): release-deploy.yml, extension-release.yml

Prints the resolved app version to stdout on success — release.yml reuses this as the single
source of the version string rather than a second, possibly-disagreeing parser. The extension
rule never changes what's printed; `--extension` prints the extension's version instead.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "backend" / "pyproject.toml"
PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
EXTENSION_MANIFEST_REL = "extension/manifest.json"
EXTENSION_MANIFEST = REPO_ROOT / EXTENSION_MANIFEST_REL
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


def read_extension_version(text: str, source: str) -> str:
    data = json.loads(text)
    version = data.get("version")
    if not version:
        raise SystemExit(f'check_version: no "version" key found in {source}')
    return version


def semver_tuple(version: str) -> tuple[int, int, int]:
    """`major.minor.patch` as a tuple of ints, so versions compare numerically (5.10.0 > 5.9.0),
    with the stdlib alone. Callers check SEMVER_RE first."""
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def is_strictly_greater(version: str, base_version: str) -> bool:
    return semver_tuple(version) > semver_tuple(base_version)


def git_show(ref: str, rel_path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{rel_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else None


def git_rev(rev: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", rev],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def git_lines(args: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return [line for line in result.stdout.splitlines() if line]


def changed_paths(base: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def check_extension(base: str | None, changed: list[str]) -> int:
    """v61: the extension's own rule, independent of the app's. A diff touching extension/ must
    raise extension/manifest.json's version strictly above the base's. No manifest at the base
    (the extension is new there) asks for no bump; no manifest here at all is fine too, since
    then there's no extension to version. Only a diff touching extension/ is checked at all, so
    the extension can never fail an app release (release.yml runs this without a base)."""
    if not base or not any(p.startswith("extension/") for p in changed):
        return 0
    if not EXTENSION_MANIFEST.exists():
        return 0
    version = read_extension_version(EXTENSION_MANIFEST.read_text(), str(EXTENSION_MANIFEST))
    if not SEMVER_RE.match(version):
        print(
            f"check_version: the extension's version ({version!r}, {EXTENSION_MANIFEST_REL}) is "
            f"not a plain major.minor.patch semver string",
            file=sys.stderr,
        )
        return 1
    base_manifest = git_show(base, EXTENSION_MANIFEST_REL)
    if base_manifest is None:
        return 0
    base_version = read_extension_version(base_manifest, f"{base}:{EXTENSION_MANIFEST_REL}")
    if base_version == version:
        print(
            f"check_version: this diff touches extension/ but the extension's version "
            f"({version}) is unchanged since {base}. Bump {EXTENSION_MANIFEST_REL}'s version "
            f"(the extension's own semver, independent of the app's; see docs/EXTENSION.md, "
            f"'Cutting an extension release').",
            file=sys.stderr,
        )
        return 1
    if SEMVER_RE.match(base_version) and not is_strictly_greater(version, base_version):
        print(
            f"check_version: the extension's version ({version}) isn't above {base}'s "
            f"({base_version}). It must be strictly greater: rebase onto {base} and raise "
            f"{EXTENSION_MANIFEST_REL}'s version past it.",
            file=sys.stderr,
        )
        return 1
    # Below a released version (an `extension-v*` tag, which CI's full-history checkout fetches;
    # a dispatch can release from a branch): Release & Deploy's plan would never release it, so
    # the change would never ship.
    released = [
        tag.removeprefix("extension-v")
        for tag in git_lines(["tag", "--list", "extension-v*"])
        if SEMVER_RE.match(tag.removeprefix("extension-v"))
    ]
    newest = max(released, key=semver_tuple, default=None)
    if newest and semver_tuple(version) < semver_tuple(newest):
        print(
            f"check_version: the extension's version ({version}) is below the newest released one "
            f"(extension-v{newest}), so this change would never ship. Raise "
            f"{EXTENSION_MANIFEST_REL}'s version past it.",
            file=sys.stderr,
        )
        return 1
    # A version already released (its `extension-v*` tag) from other extension/ content would be "already released" to Release & Deploy's
    # plan, and this code would never ship. Same content (the release was made from this very
    # tree, a proof before merge) is fine.
    tag = f"extension-v{version}"
    released_tree = git_rev(f"refs/tags/{tag}^{{commit}}:extension")
    if released_tree and released_tree != git_rev("HEAD:extension"):
        print(
            f"check_version: the extension's version ({version}) was already released as {tag} "
            f"from other extension/ content, so this change would never ship. Raise "
            f"{EXTENSION_MANIFEST_REL}'s version past every released one.",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    if sys.argv[1:] == ["--extension"]:
        # No extension at all prints nothing (Release & Deploy's plan then releases none).
        if not EXTENSION_MANIFEST.exists():
            return 0
        version = read_extension_version(EXTENSION_MANIFEST.read_text(), str(EXTENSION_MANIFEST))
        if not SEMVER_RE.match(version):
            print(
                f"check_version: the extension's version ({version!r}) is not a plain "
                f"major.minor.patch semver string",
                file=sys.stderr,
            )
            return 1
        print(version)
        return 0

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

    changed = changed_paths(base) if base else []
    if base:
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
            # v50: and it must rise. Parallel slices merge in any order, so a branch can carry
            # a version main has already passed; releasing it would cut a tag that goes
            # backwards.
            if (
                base_version
                and SEMVER_RE.match(base_version)
                and not is_strictly_greater(version, base_version)
            ):
                print(
                    f"check_version: the version ({version}) isn't above {base}'s "
                    f"({base_version}). It must be strictly greater: {base} moved past this "
                    f"slice, so rebase onto it and ask the owner for the version to use.",
                    file=sys.stderr,
                )
                return 1

    if check_extension(base, changed):
        return 1

    print(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
