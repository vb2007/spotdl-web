#!/usr/bin/env python3
"""Copies stdin to stdout with every value from an env file masked as *** (v33).

`docker compose` echoes `.env` content in some errors: an interpolated value
(`invalid containerPort: <value>`), an unparseable value (`Invalid template: "<value>"`), even a
whole malformed line (`unexpected character ... in variable name "<line>"`). The deploy job
runs it over the output that can carry such errors before anything has validated them: the
preflight's render, the rollback's migration guard (the previous commit's files) and the
Summary's `compose ps`. The deploy step's own `pull`/`up` run only after the preflight has
rendered the same files against the same .env.

Masks, for each non-comment line: the value as written and as Compose reads it (quotes
stripped, an inline ` #` comment dropped), and, for a line that isn't `KEY=value` at all, the
whole line and each of its tokens. Strings shorter than 3 characters are left alone (masking
`1` or `no` everywhere would garble the message without hiding anything). Stdlib-only.

Usage: redact_env.py ENV_FILE < text
"""

from __future__ import annotations

import re
import sys

ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=(.*)$")


def secrets(env_file: str) -> list[str]:
    found: set[str] = set()
    for line in open(env_file):
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = ENV_LINE_RE.match(line)
        if m:
            candidates = [m.group(1).strip(), m.group(1).split(" #", 1)[0].strip()]
        else:
            # A malformed line: compose quotes it back with `"` escaped as `\"`, and may cut
            # it anywhere, so every token goes too, not just the whole line.
            whole = line.strip()
            candidates = [whole, whole.replace('"', '\\"'), *whole.split()]
        for v in candidates:
            for form in (v, v.strip("'\"")):
                if len(form) >= 3:
                    found.add(form)
    # Longest first, so a value containing a shorter one is masked whole.
    return sorted(found, key=len, reverse=True)


def main() -> int:
    try:
        values = secrets(sys.argv[1])
    except (IndexError, OSError) as exc:
        # Can't read the env file: print nothing rather than risk printing it unmasked.
        print(f"redact_env: {exc}; output suppressed", file=sys.stderr)
        return 1
    text = sys.stdin.read()
    for v in values:
        text = text.replace(v, "***")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
