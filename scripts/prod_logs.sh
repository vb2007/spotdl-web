#!/usr/bin/env bash
# Reads the production stack's container logs for the last N hours from the host's journald
# (v60, O3), across every deploy and reboot in that window. Run it on the production host.
#
# `docker compose logs` reads only the containers that exist right now, and every deploy
# recreates all of them, so it never reaches back past the last deploy. docker-compose.prod.yml
# sends every service's output to journald instead, tagged with the container name and the
# compose project/service labels; this filters on those fields, so old containers' lines come
# back too. Lines written before the switch to journald (json-file era) are gone for good.
#
# Usage: scripts/prod_logs.sh [HOURS] [SERVICE...]
#   HOURS    how far back, a whole number of hours (default 6)
#   SERVICE  only these compose services (api, worker-dl, beat, ...); default every one
#   Extra journalctl options go in PROD_LOGS_OPTS, e.g. PROD_LOGS_OPTS="-p err" (errors and
#   worse: a container's stderr is priority 3, stdout 6) or "-o cat" (messages only).
#
# Env overrides (all optional):
#   SPOTDL_WEB_PROJECT  compose project name (default spotdl-web, the deploy checkout's dir)
#
# Reading another service's journal entries takes the `systemd-journal` (or `adm`) group, or
# root. Without it this runs journalctl through `sudo -n` if that works, and otherwise says how
# to get access (docs/DEPLOYMENT.md, "Logs").
set -euo pipefail

HOURS="${1:-6}"
[ "$#" -gt 0 ] && shift
if ! [[ "$HOURS" =~ ^[0-9]+$ ]] || [ "$HOURS" -eq 0 ]; then
  echo "prod_logs: HOURS must be a whole number of hours above 0 (got '$HOURS')" >&2
  exit 2
fi
PROJECT="${SPOTDL_WEB_PROJECT:-spotdl-web}"

# Same field twice = OR, different fields = AND (journalctl's own matching).
MATCHES=("COM_DOCKER_COMPOSE_PROJECT=$PROJECT")
for svc in "$@"; do
  MATCHES+=("COM_DOCKER_COMPOSE_SERVICE=$svc")
done

JOURNALCTL=(journalctl)
if [ "$(id -u)" -ne 0 ] && ! id -nG | tr ' ' '\n' | grep -qxE 'systemd-journal|adm'; then
  if sudo -n true 2>/dev/null; then
    JOURNALCTL=(sudo -n journalctl)
  else
    echo "prod_logs: $(id -un) can't read the system journal. Either run it as root, or once:" >&2
    echo "  sudo usermod -aG systemd-journal $(id -un)   # then log in again" >&2
    exit 1
  fi
fi

# shellcheck disable=SC2086 # PROD_LOGS_OPTS is a word list on purpose
"${JOURNALCTL[@]}" --no-pager -o short-iso --since "$HOURS hours ago" ${PROD_LOGS_OPTS:-} "${MATCHES[@]}"
