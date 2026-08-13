#!/usr/bin/env bash
# v22: proves the one property in the cross-user data-separation sweep that cannot run as
# a pytest fixture test. backend/tests/test_ownership.py already covers every REST
# surface (list isolation, direct-id 404s, admin gating, search/scope, archive/retention)
# against the in-process fixture. The SSE stream is real Redis pub/sub served over a real
# running stack -- there is no fixture substitute for "does the wire itself ever carry
# another user's ids." v17's own verification proved this once by hand with raw `curl -N`
# captures (see docs/GOTCHAS.md's v17 section); this script commits that exact technique
# so it's re-runnable after any future version touching queries, endpoints, or events,
# per CLAUDE.md's data-separation invariant.
#
# What it does: logs in as two distinct real identities (A, B), opens concurrent raw SSE
# captures (A's own channel, B's own channel, B attempting the admin all_users=true query
# param, and -- if admin credentials are supplied -- the admin's real all-users
# pattern-subscribe), has A create and cancel a real job on the real stack, and inspects
# the captured bytes:
#   - A's own capture MUST contain the job id (positive control -- proves events flow at
#     all, so a clean B capture below isn't just a broken stream).
#   - B's capture MUST NOT contain the job id anywhere (the actual property under test).
#   - B's all_users=true capture MUST NOT contain the job id either -- a non-admin passing
#     that query param must be silently ignored server-side, not honored.
#   - the admin capture (if provided), MUST contain the job id (reverse-direction proof
#     that the all-users pattern-subscribe genuinely works, not just that it's inert).
#
# Usage (against a running stack, local by default):
#   SPOTDL_WEB_USER_A_EMAIL=a@example.com SPOTDL_WEB_USER_A_PASSWORD=... \
#   SPOTDL_WEB_USER_B_EMAIL=b@example.com SPOTDL_WEB_USER_B_PASSWORD=... \
#     ./scripts/verify_separation_sse.sh
#
# Env vars:
#   SPOTDL_WEB_BASE_URL           default: http://localhost:8000
#   SPOTDL_WEB_USER_A_EMAIL / _PASSWORD   required -- must already be in ALLOWED_EMAILS
#   SPOTDL_WEB_USER_B_EMAIL / _PASSWORD   a DIFFERENT, non-admin user than A -- required
#                                          unless SPOTDL_WEB_USER_B_TOKEN is set instead
#   SPOTDL_WEB_USER_B_TOKEN       alternative to the email/password pair above: an
#                                          already-minted SPOTDL_SESSION token for a second
#                                          non-admin identity (e.g. via the direct-session
#                                          -mint fallback documented in docs/GOTCHAS.md/
#                                          CLAUDE.md, for when no second real-login-capable
#                                          identity is available). Real login for at least
#                                          one identity (A) is still exercised regardless.
#   SPOTDL_WEB_ADMIN_EMAIL / _PASSWORD    optional -- if set, must be a real admin
#                                          identity, distinct from A and B; enables the
#                                          reverse-direction pattern-subscribe check
#   SPOTDL_WEB_TEST_TRACK_URL     default: a single well-known Spotify track (small,
#                                  fast to expand) -- override if the default ever stops
#                                  resolving
#   SPOTDL_WEB_CAPTURE_SECONDS    how long each curl -N stays open (default: 40). Must
#                                  comfortably exceed the ~2s pre-sleep + up to 15s of
#                                  expansion-wait polling + the cancel + a 3s settle sleep
#                                  (~20s worst case) with real margin left over, or a slow
#                                  expand can silently truncate the capture window before
#                                  the events it's waiting for ever land
set -euo pipefail

BASE_URL="${SPOTDL_WEB_BASE_URL:-http://localhost:8000}"
TEST_TRACK_URL="${SPOTDL_WEB_TEST_TRACK_URL:-https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT}"
CAPTURE_SECONDS="${SPOTDL_WEB_CAPTURE_SECONDS:-40}"

: "${SPOTDL_WEB_USER_A_EMAIL:?set SPOTDL_WEB_USER_A_EMAIL}"
: "${SPOTDL_WEB_USER_A_PASSWORD:?set SPOTDL_WEB_USER_A_PASSWORD}"
if [ -z "${SPOTDL_WEB_USER_B_TOKEN:-}" ]; then
  : "${SPOTDL_WEB_USER_B_EMAIL:?set SPOTDL_WEB_USER_B_EMAIL, or SPOTDL_WEB_USER_B_TOKEN instead}"
  : "${SPOTDL_WEB_USER_B_PASSWORD:?set SPOTDL_WEB_USER_B_PASSWORD, or SPOTDL_WEB_USER_B_TOKEN instead}"
fi

WORKDIR="$(mktemp -d)"
trap 'jobs -p | xargs -r kill 2>/dev/null; rm -rf "$WORKDIR"' EXIT

# Extracts the session token straight out of a raw Set-Cookie header rather than using
# curl's own cookie-jar (-c/-b) mechanism -- the cookie is unconditionally `Secure`
# (auth.py's _set_session_cookie), which a spec-compliant cookie jar refuses to replay
# over plain http. Passing the token via an explicit `-H "Cookie: ..."` header instead
# bypasses that jar logic entirely, matching what v17's own manual verification did.
login() {
  local email="$1" password="$2" headers_file
  headers_file="$(mktemp -p "$WORKDIR")"
  curl -sS -D "$headers_file" -o /dev/null \
    -X POST "$BASE_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$email\",\"password\":\"$password\"}"
  local token
  # `|| true`: under `set -eo pipefail`, a plain assignment whose right-hand side is a
  # failing pipeline (grep finding no Set-Cookie line, e.g. on a genuine 401) aborts the
  # whole script right here -- silently, before the deliberate diagnostic below ever gets
  # a chance to run. Confirmed by reproducing it directly; the `|| true` makes the
  # assignment itself always "succeed" so the empty-token check next is what actually
  # decides pass/fail, not a bare script abort.
  token="$(grep -i '^set-cookie: SPOTDL_SESSION=' "$headers_file" | head -n1 \
    | sed -E 's/^[Ss]et-[Cc]ookie: SPOTDL_SESSION=([^;]+).*/\1/' | tr -d '\r\n')" || true
  if [ -z "$token" ]; then
    echo "login failed for $email -- no Set-Cookie in response (check credentials/ALLOWED_EMAILS)" >&2
    exit 1
  fi
  echo "$token"
}

echo "Logging in as A ($SPOTDL_WEB_USER_A_EMAIL)..."
TOKEN_A="$(login "$SPOTDL_WEB_USER_A_EMAIL" "$SPOTDL_WEB_USER_A_PASSWORD")"
if [ -n "${SPOTDL_WEB_USER_B_TOKEN:-}" ]; then
  echo "Using pre-minted token for B..."
  TOKEN_B="$SPOTDL_WEB_USER_B_TOKEN"
else
  echo "Logging in as B ($SPOTDL_WEB_USER_B_EMAIL)..."
  TOKEN_B="$(login "$SPOTDL_WEB_USER_B_EMAIL" "$SPOTDL_WEB_USER_B_PASSWORD")"
fi
# B's all_users=true check below only means anything if B genuinely isn't admin -- catch
# the easy-to-make mistake (reusing an admin identity for both B and ADMIN) with a clear
# message instead of a confusing "FAIL" that's actually a test-setup error, not a real leak.
ME_B="$(curl -sS "$BASE_URL/api/auth/me" -H "Cookie: SPOTDL_SESSION=$TOKEN_B")"
case "$ME_B" in
  *'"is_admin":true'*)
    echo "SPOTDL_WEB_USER_B_EMAIL ($SPOTDL_WEB_USER_B_EMAIL) is admin -- the all_users=true check below would trivially pass for the wrong reason. Use a genuine non-admin identity for B." >&2
    exit 1
    ;;
esac

TOKEN_ADMIN=""
if [ -n "${SPOTDL_WEB_ADMIN_EMAIL:-}" ]; then
  echo "Logging in as admin ($SPOTDL_WEB_ADMIN_EMAIL)..."
  TOKEN_ADMIN="$(login "$SPOTDL_WEB_ADMIN_EMAIL" "${SPOTDL_WEB_ADMIN_PASSWORD:?set SPOTDL_WEB_ADMIN_PASSWORD alongside SPOTDL_WEB_ADMIN_EMAIL}")"
  ME="$(curl -sS "$BASE_URL/api/auth/me" -H "Cookie: SPOTDL_SESSION=$TOKEN_ADMIN")"
  case "$ME" in
    *'"is_admin":true'*) ;;
    *)
      echo "SPOTDL_WEB_ADMIN_EMAIL is not actually an admin (got: $ME) -- skipping the reverse-direction check" >&2
      TOKEN_ADMIN=""
      ;;
  esac
fi

CAPTURE_A="$WORKDIR/capture_a.log"
CAPTURE_B="$WORKDIR/capture_b.log"
CAPTURE_B_ALLUSERS="$WORKDIR/capture_b_allusers.log"
CAPTURE_ADMIN="$WORKDIR/capture_admin.log"

echo "Opening SSE captures (${CAPTURE_SECONDS}s window)..."
timeout "$CAPTURE_SECONDS" curl -sS -N "$BASE_URL/api/stream" -H "Cookie: SPOTDL_SESSION=$TOKEN_A" >"$CAPTURE_A" 2>/dev/null &
PID_A=$!
timeout "$CAPTURE_SECONDS" curl -sS -N "$BASE_URL/api/stream" -H "Cookie: SPOTDL_SESSION=$TOKEN_B" >"$CAPTURE_B" 2>/dev/null &
PID_B=$!
# The sweep table's other SSE row: B (non-admin) attempting the admin pattern-subscribe
# query param must be silently ignored server-side (`use_pattern = all_users and
# user.is_admin`, stream.py), not just inert client-side -- proven from the wire the same
# way as B's plain channel, not inferred from the mocked unit test alone.
timeout "$CAPTURE_SECONDS" curl -sS -N "$BASE_URL/api/stream?all_users=true" -H "Cookie: SPOTDL_SESSION=$TOKEN_B" >"$CAPTURE_B_ALLUSERS" 2>/dev/null &
PID_B_ALLUSERS=$!
PID_ADMIN=""
if [ -n "$TOKEN_ADMIN" ]; then
  timeout "$CAPTURE_SECONDS" curl -sS -N "$BASE_URL/api/stream?all_users=true" -H "Cookie: SPOTDL_SESSION=$TOKEN_ADMIN" >"$CAPTURE_ADMIN" 2>/dev/null &
  PID_ADMIN=$!
fi

# Let both (p)subscribes actually land server-side before generating events -- a create
# immediately after connecting could race the subscribe call inside _event_stream().
sleep 2

echo "Creating a real job as A..."
CREATE_RESPONSE="$(curl -sS -X POST "$BASE_URL/api/jobs" \
  -H "Content-Type: application/json" -H "Cookie: SPOTDL_SESSION=$TOKEN_A" \
  -d "{\"url\":\"$TEST_TRACK_URL\"}")"
JOB_ID="$(echo "$CREATE_RESPONSE" | grep -oE '"id"[[:space:]]*:[[:space:]]*"[0-9a-f-]{36}"' | head -n1 | grep -oE '[0-9a-f-]{36}')"
if [ -z "$JOB_ID" ]; then
  echo "Job creation did not return an id (response: $CREATE_RESPONSE)" >&2
  exit 1
fi
echo "Job id: $JOB_ID"

echo "Waiting for expansion to finish..."
for _ in $(seq 1 15); do
  STATE_RESPONSE="$(curl -sS "$BASE_URL/api/jobs/$JOB_ID" -H "Cookie: SPOTDL_SESSION=$TOKEN_A")"
  case "$STATE_RESPONSE" in
    *'"state":"expanding"'*) sleep 1 ;;
    *) break ;;
  esac
done

echo "Cancelling the job as A (generates job.state + track.state events)..."
curl -sS -X DELETE "$BASE_URL/api/jobs/$JOB_ID" -H "Cookie: SPOTDL_SESSION=$TOKEN_A" >/dev/null

# Give the cancel's events a moment to land on the wire before the captures close.
sleep 3

wait "$PID_A" 2>/dev/null || true
wait "$PID_B" 2>/dev/null || true
wait "$PID_B_ALLUSERS" 2>/dev/null || true
[ -n "$PID_ADMIN" ] && { wait "$PID_ADMIN" 2>/dev/null || true; }

PASS=true

if grep -q "$JOB_ID" "$CAPTURE_A"; then
  echo "PASS: A's own stream saw its own job ($JOB_ID) -- events are flowing."
else
  echo "FAIL: A's own stream never saw its own job -- SSE itself may be broken; the B check below proves nothing." >&2
  PASS=false
fi

if grep -q "$JOB_ID" "$CAPTURE_B"; then
  echo "FAIL: B's stream received A's job id ($JOB_ID) -- CROSS-USER LEAK. Captured bytes:" >&2
  cat "$CAPTURE_B" >&2
  PASS=false
else
  echo "PASS: B's stream contains zero mention of A's job id."
fi

if grep -q "$JOB_ID" "$CAPTURE_B_ALLUSERS"; then
  echo "FAIL: B's all_users=true stream received A's job id ($JOB_ID) -- a non-admin's pattern-subscribe attempt was honored. Captured bytes:" >&2
  cat "$CAPTURE_B_ALLUSERS" >&2
  PASS=false
else
  echo "PASS: B's all_users=true attempt was silently ignored -- zero mention of A's job id."
fi

if [ -n "$TOKEN_ADMIN" ]; then
  if grep -q "$JOB_ID" "$CAPTURE_ADMIN"; then
    echo "PASS: admin's all_users=true pattern-subscribe saw A's job id (reverse direction confirmed)."
  else
    echo "FAIL: admin's all_users=true stream never saw A's job -- pattern-subscribe may be broken." >&2
    PASS=false
  fi
fi

if [ "$PASS" != "true" ]; then
  echo "verify_separation_sse: FAILED" >&2
  exit 1
fi
echo "verify_separation_sse: all checks passed."
