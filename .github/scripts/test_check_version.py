#!/usr/bin/env python3
"""Tests for check_version.py (v50; v61's extension rule). Stdlib-only, like the script itself:

    python3 -m unittest discover -s .github/scripts -p 'test_*.py'

The end-to-end cases run a copy of the script inside a throwaway git repository, since it reads
the version files and the diff relative to its own location.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().with_name("check_version.py")
_spec = importlib.util.spec_from_file_location("check_version", SCRIPT)
check_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_version)

# Hermetic git: a developer's global config (signed tags or commits, hooks) never applies.
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class SemverCompareTest(unittest.TestCase):
    def test_numeric_not_lexical(self):
        self.assertTrue(check_version.is_strictly_greater("5.10.0", "5.9.0"))
        self.assertFalse(check_version.is_strictly_greater("5.9.0", "5.10.0"))

    def test_equal_is_not_greater(self):
        self.assertFalse(check_version.is_strictly_greater("5.50.0", "5.50.0"))

    def test_each_component(self):
        self.assertTrue(check_version.is_strictly_greater("6.0.0", "5.99.99"))
        self.assertTrue(check_version.is_strictly_greater("5.51.0", "5.50.3"))
        self.assertTrue(check_version.is_strictly_greater("5.50.1", "5.50.0"))
        self.assertFalse(check_version.is_strictly_greater("5.49.9", "5.50.0"))


class CheckAgainstBaseTest(unittest.TestCase):
    """A base commit at 5.50.0, then a branch commit that sets a version and touches a path."""

    BASE = "5.50.0"
    EXTENSION_BASE = "1.0.0"

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="check_version_test_"))
        self.addCleanup(shutil.rmtree, self.repo)
        (self.repo / ".github" / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPT, self.repo / ".github" / "scripts" / "check_version.py")
        (self.repo / "backend").mkdir()
        (self.repo / "frontend").mkdir()
        (self.repo / "docs").mkdir()
        (self.repo / "extension").mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "test")
        self.set_version(self.BASE)
        (self.repo / "backend" / "app.py").write_text("x = 1\n")
        (self.repo / "frontend" / "app.ts").write_text("export {};\n")
        (self.repo / "docs" / "notes.md").write_text("notes\n")
        self.set_extension_version(self.EXTENSION_BASE)
        (self.repo / "extension" / "content.js").write_text("export {};\n")
        self.commit("base")
        self.git("tag", "base")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, env=GIT_ENV, check=True, capture_output=True)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def set_version(self, version):
        (self.repo / "backend" / "pyproject.toml").write_text(
            f'[project]\nname = "app"\nversion = "{version}"\n'
        )
        (self.repo / "frontend" / "package.json").write_text(
            json.dumps({"name": "app", "version": version}) + "\n"
        )

    def set_extension_version(self, version):
        (self.repo / "extension" / "manifest.json").write_text(
            json.dumps({"manifest_version": 3, "name": "ext", "version": version}) + "\n"
        )

    def branch(self, version, touched, extension_version=None):
        self.set_version(version)
        if extension_version is not None:
            self.set_extension_version(extension_version)
        for rel in [touched] if isinstance(touched, str) else touched:
            path = self.repo / rel
            path.write_text(path.read_text() + "change\n")
        self.commit("branch")

    def run_check(self, *args):
        return subprocess.run(
            [sys.executable, ".github/scripts/check_version.py", *(args or ("base",))],
            cwd=self.repo,
            env=GIT_ENV,
            capture_output=True,
            text=True,
        )

    def test_equal_version_fails(self):
        self.branch(self.BASE, "backend/app.py")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("unchanged", result.stderr)

    def test_lower_version_fails(self):
        self.branch("5.49.0", "backend/app.py")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("strictly greater", result.stderr)

    def test_lower_patch_fails(self):
        self.git("checkout", "-q", "-b", "patched")
        self.set_version("5.50.2")
        self.commit("main at a patch release")
        self.git("tag", "-f", "base")
        self.branch("5.50.1", "backend/app.py")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("strictly greater", result.stderr)

    def test_higher_version_passes(self):
        self.branch("5.51.0", "frontend/app.ts")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "5.51.0")

    def test_patch_bump_passes(self):
        self.branch("5.50.1", "backend/app.py")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "5.50.1")

    def test_two_digit_minor_passes(self):
        self.git("checkout", "-q", "-b", "nine")
        self.set_version("5.9.0")
        self.commit("main at 5.9.0")
        self.git("tag", "-f", "base")
        self.branch("5.10.0", "backend/app.py")
        self.assertEqual(self.run_check().returncode, 0)

    def test_docs_only_diff_needs_no_bump(self):
        self.branch(self.BASE, "docs/notes.md")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)


    # v61: the extension's own version rule, independent of the app's.

    def test_extension_change_without_manifest_bump_fails(self):
        self.branch(self.BASE, "extension/content.js")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("touches extension/", result.stderr)
        self.assertIn("unchanged", result.stderr)

    def test_extension_bump_passes_without_an_app_bump(self):
        self.branch(self.BASE, "extension/content.js", extension_version="1.0.1")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        # stdout stays the app's version: release.yml reads it as the tag.
        self.assertEqual(result.stdout.strip(), self.BASE)

    def test_extension_lower_version_fails(self):
        self.branch(self.BASE, "extension/content.js", extension_version="0.9.9")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("strictly greater", result.stderr)

    def test_extension_version_is_compared_numerically(self):
        self.git("checkout", "-q", "-b", "nine")
        self.set_extension_version("1.9.0")
        self.commit("main at extension 1.9.0")
        self.git("tag", "-f", "base")
        self.branch(self.BASE, "extension/content.js", extension_version="1.10.0")
        self.assertEqual(self.run_check().returncode, 0)

    def test_extension_manifest_bump_alone_passes(self):
        self.branch(self.BASE, "docs/notes.md", extension_version="1.1.0")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_extension_non_semver_version_fails(self):
        self.branch(self.BASE, "extension/content.js", extension_version="1.1")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("semver", result.stderr)

    def test_extension_version_never_has_to_match_the_app(self):
        self.branch("5.51.0", ["backend/app.py", "extension/content.js"], extension_version="1.0.1")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "5.51.0")

    def test_app_and_extension_change_needs_both_bumps(self):
        self.branch("5.51.0", ["backend/app.py", "extension/content.js"])
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("touches extension/", result.stderr)

    def test_app_only_diff_is_unaffected_by_the_extension_rule(self):
        self.branch("5.51.0", "backend/app.py")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "5.51.0")

    def test_app_only_diff_without_app_bump_still_fails_for_the_app(self):
        self.branch(self.BASE, "frontend/app.ts")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("touches backend/ or frontend/", result.stderr)
        self.assertNotIn("extension", result.stderr)

    def test_extension_new_at_base_needs_no_bump(self):
        self.git("rm", "-q", "extension/manifest.json")
        self.commit("no extension at base")
        self.git("tag", "-f", "base")
        self.branch(self.BASE, "extension/content.js", extension_version="1.0.0")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_base_ignores_the_extension(self):
        # release.yml's call: an extension problem can never fail an app release.
        self.branch(self.BASE, "extension/content.js", extension_version="not-a-version")
        result = subprocess.run(
            [sys.executable, ".github/scripts/check_version.py"],
            cwd=self.repo,
            env=GIT_ENV,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), self.BASE)

    def test_extension_version_released_from_other_content_fails(self):
        # 1.0.1 was released (tagged) from one tree; a branch now carries 1.0.1 with other code.
        self.git("checkout", "-q", "-b", "released")
        self.set_extension_version("1.0.1")
        self.commit("released elsewhere")
        self.git("tag", "extension-v1.0.1")
        self.git("checkout", "-q", "main")
        self.branch(self.BASE, "extension/content.js", extension_version="1.0.1")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("already released as extension-v1.0.1", result.stderr)

    def test_extension_version_released_from_this_content_passes(self):
        self.branch(self.BASE, "extension/content.js", extension_version="1.0.1")
        self.git("tag", "extension-v1.0.1")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_extension_version_below_a_released_one_fails(self):
        # 1.0.10 was released (from a branch dispatch, say); a PR now carries 1.0.2.
        self.git("checkout", "-q", "-b", "released")
        self.set_extension_version("1.0.10")
        self.commit("released elsewhere")
        self.git("tag", "extension-v1.0.10")
        self.git("checkout", "-q", "main")
        self.branch(self.BASE, "extension/content.js", extension_version="1.0.2")
        result = self.run_check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("below the newest released one (extension-v1.0.10)", result.stderr)

    def test_extension_version_above_every_released_one_passes(self):
        self.git("tag", "extension-v1.0.0")
        self.git("tag", "extension-v0.9.0-rc1")
        self.branch(self.BASE, "extension/content.js", extension_version="1.0.1")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_extension_flag_prints_nothing_without_a_manifest(self):
        self.git("rm", "-q", "extension/manifest.json")
        self.commit("no extension")
        result = self.run_check("--extension")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_extension_flag_prints_the_extension_version(self):
        self.branch(self.BASE, "extension/content.js", extension_version="1.2.3")
        result = self.run_check("--extension")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1.2.3")

    def test_extension_flag_refuses_a_non_semver_version(self):
        self.branch(self.BASE, "extension/content.js", extension_version="1.2")
        result = self.run_check("--extension")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
