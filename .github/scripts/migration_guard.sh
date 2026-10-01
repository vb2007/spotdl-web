#!/usr/bin/env bash
# Refuses a rollback whose image can't run against the database's current schema (v33).
#
# Alembic migrations are never downgraded automatically (docs/RELEASE_PIPELINE.md). So if the
# failed deploy's `migrate` already upgraded the database past what the rollback image knows,
# starting the old stack is doomed: its own `migrate` would refuse the unknown revision and every
# backend service (which depends on migrate) would never start. That's exactly the state v29's
# hand recovery ended in (plan/master-v4/00-master-plan.md, "The pipeline incident").
#
# Run it with DEPLOY_DIR already restored to the rollback commit and its .env IMAGE_TAG to the
# rollback tag, so `migrate` resolves to the rollback image with production's own env_file and
# extra_hosts. It reads the database's alembic_version and the image's own revision graph, both
# from inside that image (a read-only SELECT, no schema change), and compares them:
#
#   exit 0  every database revision is known to the image (equal or behind: its migrate will
#           no-op or upgrade, both fine)
#   exit 3  the database is ahead of (or diverged from) the image: don't start it
#   exit 1  the comparison itself failed: fail closed, since "unknown" isn't "safe"
#
# Usage: migration_guard.sh <deploy_dir> [backup_path]
# GUARD_COMPOSE_ARGS replaces the compose arguments (default: the prod pair). The local-stack
# verification uses it to add `-p <name>`, so the probe's one-off container doesn't share a
# network with the running dev stack.
set -euo pipefail

DEPLOY_DIR="${1:?usage: migration_guard.sh <deploy_dir> [backup_path]}"
BACKUP_PATH="${2:-}"

cd "$DEPLOY_DIR"
read -ra ARGS <<< "${GUARD_COMPOSE_ARGS:--f docker-compose.yml -f docker-compose.prod.yml}"
COMPOSE=(docker compose "${ARGS[@]}")

# One python process in the rollback image: its own ScriptDirectory is the authority on which
# revisions it can run, and the database URL comes from the same env_file the stack uses. Only
# revision ids are printed, never the URL.
read -r -d '' PROBE <<'PY' || true
import os
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

script = ScriptDirectory.from_config(Config("alembic.ini"))
known = {rev.revision for rev in script.walk_revisions()}
heads = sorted(script.get_heads())

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as conn:
    if inspect(conn).has_table("alembic_version"):
        current = sorted(r[0] for r in conn.execute(text("SELECT version_num FROM alembic_version")))
    else:
        current = []

unknown = [rev for rev in current if rev not in known]
print(f"database revision(s): {', '.join(current) or '(none)'}")
print(f"rollback image head(s): {', '.join(heads) or '(none)'}")
if unknown:
    print(f"unknown to the rollback image: {', '.join(unknown)}")
    sys.exit(3)
PY

echo "migration_guard: comparing the database's Alembic revision with the rollback image's"
set +e
"${COMPOSE[@]}" run --rm --no-deps -T migrate python -c "$PROBE"
rc=$?
set -e

restore_hint() {
  if [ -n "$BACKUP_PATH" ]; then
    echo "  pre-deploy pg_backup: $BACKUP_PATH" >&2
  else
    echo "  pre-deploy pg_backup: (path not recorded -- newest dump in $DEPLOY_DIR/backups/)" >&2
  fi
  echo "  Either restore that backup and roll back by hand, or roll forward with a fix." >&2
  echo "  See docs/DEPLOYMENT.md, 'Rollback / recovery'." >&2
}

case "$rc" in
  0)
    echo "migration_guard: the rollback image knows the database's revision -- safe to start"
    ;;
  3)
    echo "::error::migration_guard: the database is AHEAD of the rollback image. Not starting the old stack." >&2
    restore_hint
    ;;
  *)
    echo "::error::migration_guard: could not compare revisions (exit $rc). Failing closed: not starting the old stack." >&2
    restore_hint
    rc=1
    ;;
esac
exit "$rc"
