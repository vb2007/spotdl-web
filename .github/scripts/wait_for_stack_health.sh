#!/usr/bin/env bash
# Polls the spotdl-web prod compose stack until every service that can report health/running
# actually does, or TIMEOUT_SECONDS elapses. Shared by publish-deploy.yml for two different
# uses: a single instant check (timeout 0) to decide whether a redundant deploy can be
# skipped, and the real post-deploy health gate (timeout ~420s).
#
# 420s is not arbitrary: worker-dl/worker-meta's healthchecks (docker-compose.yml) have a 90s
# start_period and a 120s interval, so a genuinely healthy worker can take ~3.5 minutes to
# even report it — a shorter timeout would false-negative a perfectly good deploy.
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

while true; do
  ok=true

  for svc in "${HEALTHY_SERVICES[@]}"; do
    status="$("${COMPOSE[@]}" ps --format '{{.Health}}' "$svc" 2>/dev/null || true)"
    [ "$status" = "healthy" ] || ok=false
  done

  for svc in "${RUNNING_SERVICES[@]}"; do
    state="$("${COMPOSE[@]}" ps --format '{{.State}}' "$svc" 2>/dev/null || true)"
    [ "$state" = "running" ] || ok=false
  done

  # migrate is one-shot: must have exited 0, not still running.
  migrate_line="$("${COMPOSE[@]}" ps -a --format '{{.State}} {{.ExitCode}}' migrate 2>/dev/null || true)"
  [ "$migrate_line" = "exited 0" ] || ok=false

  if $ok && curl -fsS -o /dev/null http://localhost:8000/api/health; then
    echo "wait_for_stack_health: stack is healthy"
    exit 0
  fi

  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "wait_for_stack_health: not healthy after ${TIMEOUT_SECONDS}s" >&2
    "${COMPOSE[@]}" ps
    exit 1
  fi

  sleep 10
done
