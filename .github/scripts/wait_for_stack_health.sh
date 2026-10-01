#!/usr/bin/env bash
# Polls the spotdl-web prod compose stack until every service that can report health/running
# actually does, or TIMEOUT_SECONDS elapses. Shared by publish-deploy.yml for two different
# uses: a single instant check (timeout 0) to decide whether a redundant deploy can be
# skipped, and the real post-deploy health gate (timeout ~420s).
#
# 420s is not arbitrary: worker-dl/worker-meta's healthchecks (docker-compose.yml) have a 90s
# start_period and a 120s interval, so a genuinely healthy worker can take ~3.5 minutes to
# even report it — a shorter timeout would false-negative a perfectly good deploy.
#
# v33: a compose *error* (an interpolation failure such as a missing `${VAR:?}`, a bad file, an
# unreachable daemon) fails fast with exit 2, instead of reading as "not healthy yet" and waiting
# out the whole timeout. `compose ps` exits 0 with empty output for a service that simply has no
# container yet, so its exit status alone separates the two.
set -euo pipefail

DEPLOY_DIR="${1:?usage: wait_for_stack_health.sh <deploy_dir> <timeout_seconds>}"
TIMEOUT_SECONDS="${2:?usage: wait_for_stack_health.sh <deploy_dir> <timeout_seconds>}"

cd "$DEPLOY_DIR"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel)

# Services with a real healthcheck (docker-compose.yml) must report "healthy".
HEALTHY_SERVICES=(redis api worker-dl worker-meta web)
# beat/cloudflared deliberately have no healthcheck — "running" is the most that can be asked.
RUNNING_SERVICES=(beat cloudflared)

deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))

# Prints one `compose ps` field for a service; exits the whole script on a compose error. Called
# as `x="$(compose_ps ...)" || exit 2`, since an `exit` inside $(...) only leaves the subshell.
# stderr is kept apart from the value: a harmless warning on a successful call (an unset
# variable defaulting to blank, an obsolete attribute) must not end up compared to "healthy".
compose_ps() {
  local out err rc=0
  err="$(mktemp)"
  out="$("${COMPOSE[@]}" ps "$@" 2>"$err")" || rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "wait_for_stack_health: docker compose failed, not a health wait:" >&2
    cat "$err" >&2
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

  if $ok && curl -fsS -o /dev/null http://localhost:8000/api/health; then
    echo "wait_for_stack_health: stack is healthy"
    exit 0
  fi

  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "wait_for_stack_health: not healthy after ${TIMEOUT_SECONDS}s" >&2
    "${COMPOSE[@]}" ps || true
    exit 1
  fi

  sleep 10
done
