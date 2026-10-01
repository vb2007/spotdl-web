#!/usr/bin/env python3
"""Sends one plain-text message to the pipeline's Matrix room (v33).

Used by the `notify` jobs in publish-deploy.yml and release.yml. Matrix client-server API:
``PUT {homeserver}/_matrix/client/v3/rooms/{room}/send/m.room.message/{txn}``, with the bot's
access token as a Bearer header. The transaction id makes the send idempotent: a retried request
with the same ``txn`` is deduplicated by the homeserver instead of posting twice, so callers pass
the run id plus the run attempt (a re-run is a new attempt and posts again, on purpose).

Configuration comes from the environment, never from arguments, so nothing secret reaches the
process list:

    MATRIX_HOMESERVER_URL   e.g. https://matrix.example.org
    MATRIX_ACCESS_TOKEN     the bot user's access token
    MATRIX_ROOM_ID          e.g. !abcdef:example.org
    MATRIX_TXN_ID           the idempotency key

Unconfigured (any of the first three empty) means alerts are off: it prints a GitHub warning and
exits 0, so a missing alert config can never turn a green run red. A configured send that fails
exits 1. Stdlib-only, like check_version.py. Never prints the token or the response body.

Usage: matrix_notify.py < message.txt
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

REQUIRED = ("MATRIX_HOMESERVER_URL", "MATRIX_ACCESS_TOKEN", "MATRIX_ROOM_ID")


def main() -> int:
    unset = [name for name in REQUIRED if not os.environ.get(name, "").strip()]
    if unset:
        print(
            f"::warning::Matrix notification skipped: {', '.join(unset)} not configured "
            "(repository secrets; see docs/DEPLOYMENT.md, 'Matrix alert bot')."
        )
        return 0

    body = sys.stdin.read().strip()
    if not body:
        print("matrix_notify: empty message, nothing sent", file=sys.stderr)
        return 1

    homeserver = os.environ["MATRIX_HOMESERVER_URL"].strip().rstrip("/")
    room = urllib.parse.quote(os.environ["MATRIX_ROOM_ID"].strip(), safe="")
    txn = urllib.parse.quote(os.environ.get("MATRIX_TXN_ID", "").strip() or str(os.getpid()), safe="")
    url = f"{homeserver}/_matrix/client/v3/rooms/{room}/send/m.room.message/{txn}"

    request = urllib.request.Request(
        url,
        data=json.dumps({"msgtype": "m.text", "body": body}).encode(),
        method="PUT",
        headers={
            "Authorization": f"Bearer {os.environ['MATRIX_ACCESS_TOKEN'].strip()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print(f"matrix_notify: sent (HTTP {response.status})")
            return 0
    except urllib.error.HTTPError as exc:
        # Matrix error bodies are {"errcode", "error"}: safe, and the only useful diagnostic.
        try:
            detail = json.loads(exc.read()).get("errcode", "")
        except (ValueError, OSError):
            detail = ""
        print(f"::error::Matrix notification failed: HTTP {exc.code} {detail}".rstrip())
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"::error::Matrix notification failed: {getattr(exc, 'reason', exc)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
