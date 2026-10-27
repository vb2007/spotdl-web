#!/usr/bin/env bash
# Polls the spotdl-web prod compose stack until every service that can report health/running
# actually does, or TIMEOUT_SECONDS elapses. Used by publish-deploy.yml three ways: a single
# instant check (timeout 0) to decide whether a redundant deploy can be skipped, the pre-deploy
# probe of what's running (180s, v60, verdict only), and the real post-deploy health gate
# (timeout ~420s).
#
# 420s is not arbitrary: worker-dl/worker-meta/worker-expand's healthchecks (docker-compose.yml) have a 90s
# start_period and a 120s interval, so a genuinely healthy worker can take ~3.5 minutes to
# even report it — a shorter timeout would false-negative a perfectly good deploy.
#
# v33: a compose *error* (an interpolation failure such as a missing `${VAR:?}`, a bad file, an
# unreachable daemon) fails fast with exit 2, instead of reading as "not healthy yet" and waiting
# out the whole timeout. `compose ps` exits 0 with empty output for a service that simply has no
# container yet, so its exit status alone separates the two.
#
# v60: a compose error is retried 3 times (5s, 10s, 20s) before it counts, so a transient dockerd
# hiccup (a restart, a slow socket) doesn't fail a deploy's health gate at once (P5). A real
# render error still fails within about 35s, not the whole timeout. Compose's stderr is printed
# only through redact_env.py, since compose echoes .env values (or parts of them) in render
# errors (P6).
set -euo pipefail

DEPLOY_DIR="${1:?usage: wait_for_stack_health.sh <deploy_dir> <timeout_seconds>}"
TIMEOUT_SECONDS="${2:?usage: wait_for_stack_health.sh <deploy_dir> <timeout_seconds>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DEPLOY_DIR"
ENV_FILE="$PWD/.env"

# Compose stderr (stdin) to stderr, every .env value and URL credential masked. If the redactor
# can't run, nothing of the original is printed.
redacted() {
  local text
  text="$(cat)"
  if [ -n "$text" ]; then
    printf '%s\n' "$text" | python3 "$SCRIPT_DIR/redact_env.py" "$ENV_FILE" >&2 \
      || echo "wait_for_stack_health: (compose's message withheld: it couldn't be redacted)" >&2
  fi
}
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel)

# Services with a real healthcheck (docker-compose.yml) must report "healthy".
HEALTHY_SERVICES=(redis api worker-dl worker-meta worker-expand web)
# beat/cloudflared deliberately have no healthcheck — "running" is the most that can be asked.
RUNNING_SERVICES=(beat cloudflared)

deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))

# Prints one `compose ps` field for a service; exits the whole script on a compose error. Called
# as `x="$(compose_ps ...)" || exit 2`, since an `exit` inside $(...) only leaves the subshell.
# stderr is kept apart from the value: a harmless warning on a successful call (an unset
# variable defaulting to blank, an obsolete attribute) must not end up compared to "healthy".
compose_ps() {
  local out err rc attempt
  err="$(mktemp)"
  for attempt in 1 2 3 4; do
    rc=0
    out="$("${COMPOSE[@]}" ps "$@" 2>"$err")" || rc=$?
    [ "$rc" -eq 0 ] && break
    if [ "$attempt" -lt 4 ]; then
      echo "wait_for_stack_health: docker compose failed (attempt $attempt of 4), retrying in $(( 5 << (attempt - 1) ))s" >&2
      sleep $(( 5 << (attempt - 1) ))
    fi
  done
  if [ "$rc" -ne 0 ]; then
    echo "wait_for_stack_health: docker compose failed 4 times, not a health wait:" >&2
    redacted < "$err"
    rm -f "$err"
    return 1
  fi
  rm -f "$err"
  printf '%s' "$out"
}

while true; do
  ok=true

  for svc in "${HEALTHY_SERVICES[@]}"; do
    status="$(compose_ps --format '{{.Health}}' "$svc")" || exit 2
    [ "$status" = "healthy" ] || ok=false
  done

  for svc in "${RUNNING_SERVICES[@]}"; do
    state="$(compose_ps --format '{{.State}}' "$svc")" || exit 2
    [ "$state" = "running" ] || ok=false
  done

  # migrate is one-shot: must have exited 0, not still running.
  migrate_line="$(compose_ps -a --format '{{.State}} {{.ExitCode}}' migrate)" || exit 2
  [ "$migrate_line" = "exited 0" ] || ok=false

  if $ok && curl -fsS --max-time 10 -o /dev/null http://localhost:8000/api/health; then
    echo "wait_for_stack_health: stack is healthy"
    exit 0
  fi

  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "wait_for_stack_health: not healthy after ${TIMEOUT_SECONDS}s" >&2
    # stdout (the container list) as is; stderr, if ps itself fails, redacted.
    err="$(mktemp)"
    "${COMPOSE[@]}" ps 2>"$err" || true
    redacted < "$err"
    rm -f "$err"
    exit 1
  fi

  sleep 10
done
