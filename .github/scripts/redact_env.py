#!/usr/bin/env python3
"""Copies stdin to stdout with every value from an env file masked as *** (v33).

`docker compose` echoes `.env` content in some errors: an interpolated value
(`invalid containerPort: <value>`), an unparseable value (`Invalid template: "<value>"`), even a
whole malformed line (`unexpected character ... in variable name "<line>"`). The deploy job
runs it over the output that can carry such errors before anything has validated them: the
preflight's render, and the stderr of the rollback's migration guard (the previous commit's
files) and of the Summary's `compose ps`. Stdout there is left alone: it holds no .env values,
and masking would garble non-secret ones it does contain (an image tag). The deploy step's own `pull`/`up` run only after the preflight has
rendered the same files against the same .env.

Masks, for each non-comment line: the value as written and as Compose reads it (quotes
stripped, an inline ` #` comment dropped), and, for a line that isn't `KEY=value` at all, the
whole line and each of its tokens. Strings shorter than 3 characters are left alone (masking
`1` or `no` everywhere would garble the message without hiding anything). Stdlib-only.

v60: compose also echoes *part* of a value: a port spec is split on `:`, so a URL there comes
back cut short (`invalid IP address: 127.0.0.1:postgres://user:pass@host`) and matches no
whole value. So every piece of a value cut at its colons (each prefix before a `:` and each
suffix after one, 6 characters or more, so a port number doesn't garble every message) is
masked too, and any `scheme://user:pass@` is masked to `scheme://***@` whatever it came from
(P6).

Usage: redact_env.py ENV_FILE < text
"""

from __future__ import annotations

import re
import sys
import unicodedata

_GO_ESCAPES = {"\a": "\\a", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r",
               "\t": "\\t", "\v": "\\v", "\\": "\\\\", '"': '\\"'}


def go_quoted(value: str) -> str:
    """The value as Go's strconv.Quote writes it, without the quotes: how compose shows a value
    holding a tab, a control character or a non-printing one (NBSP, zero-width space) (v60)."""
    out = []
    for ch in value:
        o = ord(ch)
        if ch in _GO_ESCAPES:
            out.append(_GO_ESCAPES[ch])
        elif o < 0x20 or o == 0x7F:
            out.append(f"\\x{o:02x}")
        elif ch != " " and unicodedata.category(ch)[0] in "CZ":
            out.append(f"\\u{o:04x}" if o <= 0xFFFF else f"\\U{o:08x}")
        else:
            out.append(ch)
    return "".join(out)


ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=(.*)$")
# A colon piece that is only a URL scheme (`redis://`) or a port and path (`6379/0`): masking it
# would garble every message naming that scheme or port without hiding anything.
NOT_SECRET_PIECE_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:/*|[0-9/]+)$")
# A URL's userinfo (`user:pass@`, or a bare token before `@`), up to the first `@`.
URL_USERINFO_RE = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)[^\s/@]+@")
# A `$NAME`/`${NAME...}` inside a value: compose warns "The "NAME" variable is not set".
VAR_REF_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")
# Colon pieces are cut only from values with this few colons: there are two per colon, each up to
# the value's length, so a pathological value would cost its length times its colon count.
MAX_COLON_PARTS = 256
# A quoted value, then optionally an inline comment after the closing quote.
QUOTED_RE = re.compile(r"""^(?:"((?:[^"\\]|\\.)*)"|'([^']*)')\s*(?:#.*)?$""")
# Interpolation in a value: what's around it, and a `${X:-default}` default, are printed as is.
INTERP_RE = re.compile(r"\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*")
DEFAULT_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*:?[-?+]([^}]*)\}")
_DQ_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "$": "$"}


def compose_decoded(raw: str) -> str:
    """The value as compose reads it from .env (v60): a double-quoted one with its escapes
    applied, a single-quoted one literal, an unquoted one without its ` #` comment; `$$` is `$`
    except inside single quotes."""
    q = QUOTED_RE.match(raw)
    if q and q.group(2) is not None:
        return q.group(2)
    if q:
        out, inner, i = [], q.group(1), 0
        while i < len(inner):
            if inner[i] == "\\" and i + 1 < len(inner) and inner[i + 1] in _DQ_ESCAPES:
                out.append(_DQ_ESCAPES[inner[i + 1]])
                i += 2
            else:
                out.append(inner[i])
                i += 1
        return "".join(out).replace("$$", "$")
    return raw.split(" #", 1)[0].strip().replace("$$", "$")


def colon_pieces(value: str) -> list[str]:
    """Each prefix before a `:` and each suffix after one, as compose cuts a port spec (v60)."""
    parts = value.split(":")
    if len(parts) > MAX_COLON_PARTS:
        return []
    pieces = [p for i in range(1, len(parts)) for p in (":".join(parts[:i]), ":".join(parts[i:]))]
    return [p for p in pieces if len(p) >= 6 and not NOT_SECRET_PIECE_RE.match(p)]


def secrets(env_file: str) -> list[str]:
    found: set[str] = set()
    keys: set[str] = set()
    refs: set[str] = set()
    decoded_values: set[str] = set()
    for line in open(env_file, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = ENV_LINE_RE.match(line)
        if m:
            raw = m.group(1).strip()
            keys.add(line.split("=", 1)[0].strip().removeprefix("export").strip())
            if not raw.startswith("'"):
                refs.update(VAR_REF_RE.findall(raw.replace("$$", "")))
            decoded = compose_decoded(raw)
            if not QUOTED_RE.match(raw) or not raw.startswith("'"):
                decoded_values.add(decoded)
            candidates = [raw, raw.split(" #", 1)[0].strip(), decoded]
        else:
            # A malformed line: compose quotes it back with `"` escaped as `\"`, and may cut
            # it anywhere, so every token goes too, not just the whole line.
            whole = line.strip()
            candidates = [whole, whole.replace('"', '\\"'), *whole.split()]
        for v in candidates:
            for form in (v, v.strip("'\"")):
                # Also as compose (Go) quotes it in errors, `"` -> `\"` and `\` -> `\\`, and
                # with a double-quoted value's escapes already applied.
                for shown in (form, form.replace("\\", "\\\\").replace('"', '\\"'),
                              form.replace("\\n", "\n").replace('\\"', '"'), go_quoted(form)):
                    if len(shown) >= 3:
                        found.add(shown)
            found.update(colon_pieces(v.strip("'\"")))
    # Literal parts around an interpolation, and defaults, come back verbatim in errors.
    for v in list(decoded_values):
        for piece in [*INTERP_RE.split(v), *DEFAULT_RE.findall(v)]:
            if len(piece) >= 6 and not NOT_SECRET_PIECE_RE.match(piece):
                found.add(piece)
            found.update(colon_pieces(piece))
    # A reference to a variable nothing defines is most likely a `$` that belonged to the
    # value: compose names it in a warning, so it goes too (6 characters or more).
    found.update(r for r in refs - keys if len(r) >= 6)
    # Longest first, so a value containing a shorter one is masked whole.
    return sorted(found, key=len, reverse=True)


def main() -> int:
    try:
        values = secrets(sys.argv[1])
    except (IndexError, OSError) as exc:
        # Can't read the env file: print nothing rather than risk printing it unmasked.
        print(f"redact_env: {exc}; output suppressed", file=sys.stderr)
        return 1
    text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    for v in values:
        text = text.replace(v, "***")
    text = URL_USERINFO_RE.sub(r"\1***@", text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
