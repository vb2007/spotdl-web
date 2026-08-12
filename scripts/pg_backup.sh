#!/usr/bin/env bash
# Host-level Postgres backup for spotdl-web (v12). Not containerized — Postgres itself
# lives directly on the Debian host (never dockerized, per the locked decision in
# CLAUDE.md), so this is a plain host script/cron job, not something `docker compose`
# runs. See docs/DEPLOYMENT.md for the exact crontab line and the restore-verification
# procedure.
#
# Reads DATABASE_URL from this repo's own .env (the same one docker-compose.yml uses),
# so backup credentials never have to be duplicated or kept in sync separately.
#
# Env overrides (all optional):
#   SPOTDL_WEB_ENV_FILE              path to .env (default: repo root .env)
#   SPOTDL_WEB_BACKUP_DIR            where dumps are written (default: /srv/spotdl-web/backups)
#   SPOTDL_WEB_BACKUP_RETENTION_DAYS how long to keep dumps (default: 14)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${SPOTDL_WEB_ENV_FILE:-$REPO_ROOT/.env}"
BACKUP_DIR="${SPOTDL_WEB_BACKUP_DIR:-/srv/spotdl-web/backups}"
RETENTION_DAYS="${SPOTDL_WEB_BACKUP_RETENTION_DAYS:-14}"

if [ ! -f "$ENV_FILE" ]; then
  echo "pg_backup: $ENV_FILE not found" >&2
  exit 1
fi

# Extract DATABASE_URL with grep/cut rather than `source`-ing the whole .env — this
# project's own real values can contain shell-hostile characters (e.g. a password with
# "!", the same class of issue docs/DEPLOYMENT.md's `\password` note already warns about
# for interactive psql), which `source` would mangle or expand unexpectedly.
DATABASE_URL="$(grep -E '^DATABASE_URL=' "$ENV_FILE" | tail -n1 | cut -d= -f2-)"
if [ -z "$DATABASE_URL" ]; then
  echo "pg_backup: DATABASE_URL not set in $ENV_FILE" >&2
  exit 1
fi

# pg_dump doesn't understand SQLAlchemy's "+psycopg" driver suffix — strip it back to a
# plain postgresql:// URI it can actually parse.
PG_URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"

# v21: this script runs directly ON the host (never inside a container — see the header
# comment), but DATABASE_URL is written for the *containers* (docker-compose.yml's
# extra_hosts: host.docker.internal:host-gateway resolves it for them). That hostname is
# NOT resolvable from the host's own DNS on Linux — Docker only wires it up inside
# containers, unlike Docker Desktop on macOS/Windows, which also maps it on the host.
# Confirmed the hard way: pg_dump failed with "could not translate host name
# host.docker.internal" running this script for real on the production host before this
# fix. Since Postgres is host-native (locked decision), the host reaches it as `localhost`.
PG_URL="${PG_URL/host.docker.internal/localhost}"

mkdir -p "$BACKUP_DIR"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_FILE="$BACKUP_DIR/spotdl_web_${TIMESTAMP}.dump"

echo "pg_backup: dumping to $DUMP_FILE"
# -Fc (custom format): compressed, and restorable with pg_restore (including --clean for
# a from-scratch overwrite) rather than a plain-SQL dump that would need manual `psql <`.
pg_dump -Fc --no-owner --dbname="$PG_URL" --file="$DUMP_FILE"

# Retention: prune dumps older than RETENTION_DAYS. A daily cron with the 14-day default
# keeps roughly the last 14 dumps, per the plan's "keep last 14 daily" bullet.
find "$BACKUP_DIR" -maxdepth 1 -name 'spotdl_web_*.dump' -mtime "+$RETENTION_DAYS" -print -delete

REMAINING="$(find "$BACKUP_DIR" -maxdepth 1 -name 'spotdl_web_*.dump' | wc -l)"
echo "pg_backup: done. $REMAINING dump(s) retained in $BACKUP_DIR."
