#!/usr/bin/env python3
"""Tests for check_version.py (v50). Stdlib-only, like the script itself:

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

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="check_version_test_"))
        self.addCleanup(shutil.rmtree, self.repo)
        (self.repo / ".github" / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPT, self.repo / ".github" / "scripts" / "check_version.py")
        (self.repo / "backend").mkdir()
        (self.repo / "frontend").mkdir()
        (self.repo / "docs").mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "test")
        self.set_version(self.BASE)
        (self.repo / "backend" / "app.py").write_text("x = 1\n")
        (self.repo / "frontend" / "app.ts").write_text("export {};\n")
        (self.repo / "docs" / "notes.md").write_text("notes\n")
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

    def branch(self, version, touched):
        self.set_version(version)
        path = self.repo / touched
        path.write_text(path.read_text() + "change\n")
        self.commit("branch")

    def run_check(self):
        return subprocess.run(
            [sys.executable, ".github/scripts/check_version.py", "base"],
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


if __name__ == "__main__":
    unittest.main()
