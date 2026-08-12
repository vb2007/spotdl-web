#!/usr/bin/env python3
"""Render a pytest junit-xml file as a GitHub Actions job summary (markdown).

Stdlib-only on purpose - this runs in ci.yml's `summary` job, which deliberately doesn't set
up the full backend venv, just enough Python to parse XML.
"""

import sys
import xml.etree.ElementTree as ET


def main(junit_path: str) -> int:
    tree = ET.parse(junit_path)
    root = tree.getroot()
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]

    total = sum(int(s.get("tests", 0)) for s in suites)
    failures = sum(int(s.get("failures", 0)) for s in suites)
    errors = sum(int(s.get("errors", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    time = sum(float(s.get("time", 0)) for s in suites)
    passed = total - failures - errors - skipped

    status_emoji = "✅" if failures == 0 and errors == 0 else "❌"
    print(f"## {status_emoji} Backend test results")
    print()
    print("| Total | Passed | Failed | Errors | Skipped | Duration |")
    print("|---|---|---|---|---|---|")
    print(f"| {total} | {passed} | {failures} | {errors} | {skipped} | {time:.2f}s |")

    broken = []
    for suite in suites:
        for case in suite.findall("testcase"):
            failure = case.find("failure")
            error = case.find("error")
            node = failure if failure is not None else error
            if node is None:
                continue
            name = f"{case.get('classname')}::{case.get('name')}"
            message = (node.get("message") or node.text or "").strip().splitlines()[0:1]
            broken.append((name, message[0] if message else "", "failure" if failure is not None else "error"))

    if broken:
        print()
        print("### Failed tests")
        print()
        print("| Test | Kind | Message |")
        print("|---|---|---|")
        for name, message, kind in broken:
            escaped = message.replace("|", "\\|")
            print(f"| `{name}` | {kind} | {escaped} |")

    return 1 if (failures or errors) else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: junit_to_summary.py <path-to-junit.xml>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
