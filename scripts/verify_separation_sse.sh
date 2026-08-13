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
# What it does: logs in as two distinct real identities (A, B), opens three concurrent
# raw SSE captures (A's own channel, B's own channel, and -- if admin credentials are
# supplied -- the admin all-users pattern-subscribe), has A create and cancel a real job
# on the real stack, and inspects the captured bytes:
#   - A's own capture MUST contain the job id (positive control -- proves events flow at
#     all, so a clean B capture below isn't just a broken stream).
#   - B's capture MUST NOT contain the job id anywhere (the actual property under test).
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
#   SPOTDL_WEB_USER_B_EMAIL / _PASSWORD   required -- a DIFFERENT user than A
#   SPOTDL_WEB_ADMIN_EMAIL / _PASSWORD    optional -- if set, must be a real admin
#                                          identity, distinct from A and B; enables the
#                                          reverse-direction pattern-subscribe check
#   SPOTDL_WEB_TEST_TRACK_URL     default: a single well-known Spotify track (small,
#                                  fast to expand) -- override if the default ever stops
#                                  resolving
#   SPOTDL_WEB_CAPTURE_SECONDS    how long each curl -N stays open (default: 20 -- must
#                                  comfortably exceed the expand+cancel round trip)
set -euo pipefail

BASE_URL="${SPOTDL_WEB_BASE_URL:-http://localhost:8000}"
TEST_TRACK_URL="${SPOTDL_WEB_TEST_TRACK_URL:-https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT}"
CAPTURE_SECONDS="${SPOTDL_WEB_CAPTURE_SECONDS:-20}"

: "${SPOTDL_WEB_USER_A_EMAIL:?set SPOTDL_WEB_USER_A_EMAIL}"
: "${SPOTDL_WEB_USER_A_PASSWORD:?set SPOTDL_WEB_USER_A_PASSWORD}"
: "${SPOTDL_WEB_USER_B_EMAIL:?set SPOTDL_WEB_USER_B_EMAIL}"
: "${SPOTDL_WEB_USER_B_PASSWORD:?set SPOTDL_WEB_USER_B_PASSWORD}"

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
  token="$(grep -i '^set-cookie: SPOTDL_SESSION=' "$headers_file" | head -n1 \
    | sed -E 's/^[Ss]et-[Cc]ookie: SPOTDL_SESSION=([^;]+).*/\1/' | tr -d '\r\n')"
  if [ -z "$token" ]; then
    echo "login failed for $email -- no Set-Cookie in response (check credentials/ALLOWED_EMAILS)" >&2
    exit 1
  fi
  echo "$token"
}

echo "Logging in as A ($SPOTDL_WEB_USER_A_EMAIL)..."
TOKEN_A="$(login "$SPOTDL_WEB_USER_A_EMAIL" "$SPOTDL_WEB_USER_A_PASSWORD")"
echo "Logging in as B ($SPOTDL_WEB_USER_B_EMAIL)..."
TOKEN_B="$(login "$SPOTDL_WEB_USER_B_EMAIL" "$SPOTDL_WEB_USER_B_PASSWORD")"

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
CAPTURE_ADMIN="$WORKDIR/capture_admin.log"

echo "Opening SSE captures (${CAPTURE_SECONDS}s window)..."
timeout "$CAPTURE_SECONDS" curl -sS -N "$BASE_URL/api/stream" -H "Cookie: SPOTDL_SESSION=$TOKEN_A" >"$CAPTURE_A" 2>/dev/null &
PID_A=$!
timeout "$CAPTURE_SECONDS" curl -sS -N "$BASE_URL/api/stream" -H "Cookie: SPOTDL_SESSION=$TOKEN_B" >"$CAPTURE_B" 2>/dev/null &
PID_B=$!
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
