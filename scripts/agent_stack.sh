#!/usr/bin/env bash
# v50: the single entry point for a parallel agent stack (master v5, "Parallel execution model").
#
# Each implementation agent works in its own git worktree, with its own compose project, host
# ports and local Postgres container. The slot (1-4) picks all of them:
#
#   slot  project        api   web   database (container `postgres` in the project)
#   1     spotdlweb-s1   8001  5174  spotdlweb_s1
#   2     spotdlweb-s2   8002  5175  spotdlweb_s2
#   3     spotdlweb-s3   8003  5176  spotdlweb_s3
#   4     spotdlweb-s4   8004  5177  spotdlweb_s4
#
# Usage: scripts/agent_stack.sh <slot> <command> [args...]
#   env                 write .env.agent from the worktree's .env (test identities, slot ports,
#                       slot DB; never a production value). PG_PORT=<port> also publishes the
#                       slot's Postgres on 127.0.0.1:<port>; AGENT_EXTRA_EMAILS=a@x,b@y allowlists
#                       more test identities. Both are remembered on later runs.
#   up                  build and start the stack (worker-dl stays off), wait until it's healthy
#   down [--volumes]    stop and remove it; --volumes also drops its database and Redis
#   ps | logs [args]    docker compose ps/logs for the slot
#   psql [args]         psql on the slot's database
#   run <cmd...>        run <cmd> with the slot's compose project, files and ports exported
#                       (e.g. `run scripts/verify_separation_sse.sh`, `run docker compose exec api sh`)
#   pytest [args]       the backend suite, inside the slot's api container
#   seed                the e2e ledger fixture (idempotent; `e2e` runs it itself)
#   e2e [args]          the full Playwright suite against the slot (under the realdl lock: the
#                       suite needs worker-dl, though it never downloads)
#   realdl <cmd...>     start worker-dl under the host-wide lock /tmp/spotdl-web-realdl.lock,
#                       run <cmd>, then stop worker-dl and release the lock
#
# docs/LOCAL_DEV.md, "Parallel agent stacks", is the runbook.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="$ROOT/.env"
ENV_AGENT="$ROOT/.env.agent"
# Generated next to .env.agent when PG_PORT is set; gitignored.
PG_PORT_OVERLAY="$ROOT/.agent-stack/pg-port.yml"
REALDL_LOCK=/tmp/spotdl-web-realdl.lock
# app/config.py's PRODUCTION_DATABASE_NAMES: a .env naming one is a production checkout.
PRODUCTION_DATABASE_NAMES=(spotdlweb spotdl_web)
# Copied verbatim from the worktree's .env: download/engine tuning and the upstream login, none
# of it an identity, a secret of production's or a database. Everything else is generated.
COPIED_KEYS=(
	UPSTREAM_AUTH_BASE_URL SPOTIFY_CLIENT_ID SPOTIFY_CLIENT_SECRET DOWNLOAD_OUTPUT_DIR
	DEFAULT_FORMAT DEFAULT_BITRATE COOKIE_FILE LADDER_SECONDS STALE_TRACK_AFTER_SECONDS
	PACING_MIN_SEC PACING_MAX_SEC YOUTUBE_PLAYER_CLIENTS PROXY_FILE
)

die() {
	echo "agent_stack: $*" >&2
	exit 1
}

usage() {
	sed -n '/^# Usage:/,/^# docs/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
	exit 2
}

[ $# -ge 2 ] || usage
SLOT=$1
CMD=$2
shift 2
case "$SLOT" in
1 | 2 | 3 | 4) ;;
*) die "unknown slot '$SLOT': slots are 1-4" ;;
esac

PROJECT="spotdlweb-s$SLOT"
API_PORT=$((8000 + SLOT))
WEB_PORT=$((5173 + SLOT))
PG_DB="spotdlweb_s$SLOT"
PG_USER=spotdlweb

# A value from a dotenv file (the last assignment wins, as in Compose), quotes stripped.
env_value() {
	local file=$1 key=$2
	[ -f "$file" ] || return 0
	sed -n "s/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}${key}[[:space:]]*=\(.*\)$/\2/p" "$file" |
		tail -n 1 | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e "s/^\"\(.*\)\"$/\1/" -e "s/^'\(.*\)'$/\1/"
}

# --- Refusals, checked before any command ---------------------------------------------------

# A checkout whose .env names the production database is the production host's (or a copy of
# its .env): nothing here may run there.
refuse_production_env() {
	[ -f "$ENV_FILE" ] || return 0
	local url name prod
	url="$(env_value "$ENV_FILE" DATABASE_URL)"
	[ -n "$url" ] || return 0
	name="${url%%\?*}"
	name="${name##*/}"
	# A `?dbname=` query parameter overrides the path, as for libpq.
	if [[ "$url" =~ [?\&]dbname=([^\&]*) ]]; then name="${BASH_REMATCH[1]}"; fi
	name="${name,,}"
	for prod in "${PRODUCTION_DATABASE_NAMES[@]}"; do
		if [ "$name" = "$prod" ]; then
			die "$ENV_FILE names the production database ($name). Refusing: agent stacks never run from a production checkout (copy the owner's dev .env instead)."
		fi
	done
}

# A slot belongs to the worktree that started it until it's taken down there: its containers
# carry that worktree in Compose's working_dir label, and its database volume in our own label.
refuse_foreign_slot() {
	local dir volume_dir
	while IFS= read -r dir; do
		if [ -n "$dir" ] && [ "$dir" != "$ROOT" ]; then
			die "slot $SLOT ($PROJECT) is in use by another worktree: $dir. Take it down there (scripts/agent_stack.sh $SLOT down), or pick another slot."
		fi
	done < <(docker ps -a --filter "label=com.docker.compose.project=$PROJECT" \
		--format '{{.Label "com.docker.compose.project.working_dir"}}' | sort -u)
	volume_dir="$(docker volume inspect "${PROJECT}_pgdata" \
		--format '{{index .Labels "spotdlweb.worktree"}}' 2>/dev/null || true)"
	if [ -n "$volume_dir" ] && [ "$volume_dir" != "$ROOT" ]; then
		die "slot $SLOT's database volume ${PROJECT}_pgdata belongs to another worktree: $volume_dir. Drop it there (scripts/agent_stack.sh $SLOT down --volumes), or, if that worktree is gone, docker volume rm ${PROJECT}_pgdata."
	fi
}

refuse_production_env
refuse_foreign_slot

# --- .env.agent ---------------------------------------------------------------------------------

random_secret() {
	od -An -N24 -tx1 /dev/urandom | tr -d ' \n'
}

write_env_agent() {
	local previous
	previous="$(env_value "$ENV_AGENT" AGENT_SLOT)"
	if [ -n "$previous" ] && [ "$previous" != "$SLOT" ] &&
		docker ps -a --filter "label=com.docker.compose.project=spotdlweb-s$previous" \
			--format '{{.Label "com.docker.compose.project.working_dir"}}' | grep -qxF "$ROOT"; then
		die "this worktree's stack is slot $previous's and still exists: scripts/agent_stack.sh $previous down first"
	fi
	[ -f "$ENV_FILE" ] || die "no $ENV_FILE: copy the main checkout's dev .env into this worktree first (docs/LOCAL_DEV.md, 'Parallel agent stacks')."
	# Kept across runs: the database volume was initialised with this password, and a new
	# session secret would sign everyone out.
	local pg_password redis_password session_secret pg_port extra_emails emails key line tmp
	pg_password="$(env_value "$ENV_AGENT" AGENT_PG_PASSWORD)"
	redis_password="$(env_value "$ENV_AGENT" REDIS_PASSWORD)"
	session_secret="$(env_value "$ENV_AGENT" SESSION_SECRET)"
	# Set in the environment (even empty, to clear it) wins over the stored value.
	pg_port="${PG_PORT-$(env_value "$ENV_AGENT" PG_PORT)}"
	extra_emails="${AGENT_EXTRA_EMAILS-$(env_value "$ENV_AGENT" AGENT_EXTRA_EMAILS)}"
	if [ -z "$pg_password" ] && docker volume inspect "${PROJECT}_pgdata" >/dev/null 2>&1; then
		die "slot $SLOT's database volume exists but $ENV_AGENT (with its password) is gone: restore it, or drop the database with scripts/agent_stack.sh $SLOT down --volumes"
	fi
	[ -n "$pg_password" ] || pg_password="$(random_secret)"
	[ -n "$redis_password" ] || redis_password="$(random_secret)"
	[ -n "$session_secret" ] || session_secret="$(random_secret)"
	if [ -n "$pg_port" ] && ! [[ "$pg_port" =~ ^[0-9]+$ ]]; then
		die "PG_PORT must be a port number, got '$pg_port'"
	fi
	emails="v5s${SLOT}admin@example.com,v5s${SLOT}user@example.com${extra_emails:+,$extra_emails}"

	tmp="$(mktemp "$ROOT/.env.agent.XXXXXX")"
	{
		echo "# Generated by scripts/agent_stack.sh $SLOT env from $ENV_FILE ($(date -u +%Y-%m-%dT%H:%M:%SZ))."
		echo "# Regenerate rather than edit: a re-run keeps the secrets, PG_PORT and AGENT_EXTRA_EMAILS"
		echo "# (PG_PORT= or AGENT_EXTRA_EMAILS= in the environment clears one)."
		echo "AGENT_SLOT=$SLOT"
		echo "AGENT_WORKTREE=$ROOT"
		echo "COMPOSE_PROJECT_NAME=$PROJECT"
		echo "API_PORT=$API_PORT"
		echo "WEB_PORT=$WEB_PORT"
		[ -z "$pg_port" ] || echo "PG_PORT=$pg_port"
		echo "SPOTDL_ENV=dev"
		echo "AGENT_PG_DB=$PG_DB"
		echo "AGENT_PG_USER=$PG_USER"
		echo "AGENT_PG_PASSWORD=$pg_password"
		# No DATABASE_URL: docker-compose.agent.yml builds it from the three above.
		echo "REDIS_PASSWORD=$redis_password"
		echo "REDIS_URL=redis://:$redis_password@redis:6379/0"
		echo "SESSION_SECRET=$session_secret"
		echo "# Test identities only (register them on the upstream, docs/LOCAL_DEV.md)."
		echo "ALLOWED_EMAILS=$emails"
		[ -z "$extra_emails" ] || echo "AGENT_EXTRA_EMAILS=$extra_emails"
		echo "ADMIN_EMAIL=v5s${SLOT}admin@example.com"
		echo "FRONTEND_ORIGINS=http://localhost:$WEB_PORT,http://127.0.0.1:$WEB_PORT"
		# cloudflared never starts here (its profile), but the base file interpolates its token.
		echo "CLOUDFLARE_TUNNEL_TOKEN="
		echo "# Copied from $ENV_FILE."
		for key in "${COPIED_KEYS[@]}"; do
			line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=" "$ENV_FILE" | tail -n 1 || true)"
			[ -z "$line" ] || echo "$line"
		done
		# The login must reach the real vb2007.hu-api: without the key in .env, the live one.
		grep -qE "^[[:space:]]*(export[[:space:]]+)?UPSTREAM_AUTH_BASE_URL[[:space:]]*=" "$ENV_FILE" ||
			echo "UPSTREAM_AUTH_BASE_URL=https://api.vb2007.hu"
	} >"$tmp"
	chmod 600 "$tmp"
	mv "$tmp" "$ENV_AGENT"
	echo "agent_stack: wrote $ENV_AGENT (slot $SLOT: $PROJECT, api $API_PORT, web $WEB_PORT, db $PG_DB)"
}

require_env_agent() {
	[ -f "$ENV_AGENT" ] || die "no $ENV_AGENT yet: run scripts/agent_stack.sh $SLOT env (or up)"
	local slot
	slot="$(env_value "$ENV_AGENT" AGENT_SLOT)"
	[ "$slot" = "$SLOT" ] || die "$ENV_AGENT is slot ${slot:-?}'s, not slot $SLOT's: run scripts/agent_stack.sh $SLOT env to switch this worktree"
	[ "$(env_value "$ENV_AGENT" AGENT_WORKTREE)" = "$ROOT" ] || die "$ENV_AGENT was written for another worktree: run scripts/agent_stack.sh $SLOT env here"
}

# --- Compose ------------------------------------------------------------------------------------

# Exported rather than passed as flags, so anything run under this script (the e2e suite's own
# `docker compose` calls, frontend/e2e/support/stack.ts) targets the slot too.
export_compose_env() {
	local files="$ROOT/docker-compose.yml:$ROOT/docker-compose.override.yml:$ROOT/docker-compose.agent.yml"
	local pg_port
	pg_port="$(env_value "$ENV_AGENT" PG_PORT)"
	if [ -n "$pg_port" ]; then
		mkdir -p "$(dirname "$PG_PORT_OVERLAY")"
		printf 'services:\n  postgres:\n    ports:\n      - "127.0.0.1:%s:5432"\n' "$pg_port" >"$PG_PORT_OVERLAY"
		files="$files:$PG_PORT_OVERLAY"
	else
		rm -f "$PG_PORT_OVERLAY"
	fi
	export COMPOSE_PROJECT_NAME="$PROJECT"
	export COMPOSE_FILE="$files"
	export COMPOSE_ENV_FILES="$ENV_AGENT"
	export COMPOSE_PROFILES=""
	export API_PORT WEB_PORT
}

dc() {
	docker compose --project-directory "$ROOT" "$@"
}

stack_running() {
	[ -n "$(dc ps --status running -q api 2>/dev/null)" ]
}

# Every started service healthy (beat has no healthcheck: running), migrate exited 0. worker-dl
# isn't part of `up`: it runs only under a realdl lock, which watches it itself.
wait_healthy() {
	local deadline=$((SECONDS + 420)) pending line service state health exit_code
	while :; do
		pending=""
		while read -r service state health exit_code; do
			[ -n "$service" ] && [ "$service" != worker-dl ] || continue
			if [ "$service" = migrate ]; then
				[ "$state" = exited ] && [ "$exit_code" = 0 ] && continue
				[ "$state" = exited ] && die "migrate exited $exit_code: scripts/agent_stack.sh $SLOT logs migrate"
			elif [ "$state" = running ] && { [ "$health" = healthy ] || [ "$health" = "-" ]; }; then
				continue
			elif [ "$state" = exited ] || [ "$health" = unhealthy ]; then
				die "$service is $state${health:+ ($health)}: scripts/agent_stack.sh $SLOT logs $service"
			fi
			pending="$pending $service"
		done < <(dc ps -a --format '{{.Service}} {{.State}} {{if .Health}}{{.Health}}{{else}}-{{end}} {{.ExitCode}}')
		[ -n "$pending" ] || return 0
		[ "$SECONDS" -lt "$deadline" ] || die "not healthy in time, still waiting on:$pending"
		sleep 5
	done
}

# Bind-mount sources and the dev `web` container's anonymous-volume mountpoints must exist
# before `up`, or Docker creates them root-owned (and a directory, for proxies.txt): the uid-1000
# workers couldn't write ./downloads, and a host `npm ci` couldn't fill frontend/node_modules.
prepare_mounts() {
	mkdir -p "$ROOT/downloads" "$ROOT/test-library" "$ROOT/frontend/node_modules" \
		"$ROOT/frontend/src/lib/paraglide"
	[ -e "$ROOT/proxies.txt" ] || : >"$ROOT/proxies.txt"
	# $env/static/public needs PUBLIC_API_BASE_URL declared (empty: same-origin), for Vite in the
	# container and `npm run check` on the host alike. The template's value is the dev one.
	[ -e "$ROOT/frontend/.env" ] || cp "$ROOT/frontend/.env.example" "$ROOT/frontend/.env"
}

# The dev `web` container runs Vite as root, which writes .svelte-kit/ and project.inlang's cache
# into the worktree root-owned, and then host-side `npm run check`/`lint` fail with EACCES
# (docs/GOTCHAS.md, v44). A fresh worktree hits that on its first `up`, so hand them back.
# (Vite keeps writing as root afterwards; v52 owns the lasting fix.)
return_frontend_files() {
	# Not into the container's own node_modules and compiled messages (anonymous volumes).
	dc exec -T web sh -c "find /app \\( -path /app/node_modules -o -path /app/src/lib/paraglide \\) -prune -o -user 0 -exec chown $(id -u):$(id -g) {} +" || true
}

# --- realdl lock --------------------------------------------------------------------------------

REALDL_HELD=""

release_realdl() {
	if [ -n "$REALDL_HELD" ]; then
		# A second Ctrl-C (or a SIGTERM) mustn't cut the cleanup short: worker-dl can take up to
		# its stop_grace_period to finish a download.
		trap '' INT TERM
		echo "agent_stack: stopping worker-dl and releasing the realdl lock" >&2
		# Removed, not just stopped: an exited worker-dl container would sit in `ps -a` as if
		# it had crashed.
		if COMPOSE_PROFILES=realdl dc rm --stop --force worker-dl >&2; then
			: >"$REALDL_LOCK"
		else
			# The lock frees anyway when this process exits; the next acquire_realdl refuses
			# while this worker-dl still runs.
			echo "agent_stack: worker-dl didn't stop: scripts/agent_stack.sh $SLOT down" >&2
		fi
		flock -u 9
		REALDL_HELD=""
	fi
}

# Any slot's worker-dl running outside the lock (an interrupted cleanup, a hand-started one).
stray_worker_dl() {
	docker ps --filter label=com.docker.compose.service=worker-dl \
		--format '{{.Label "com.docker.compose.project"}} {{.Names}}' |
		grep -E '^spotdlweb-s[1-4] ' | grep -v "^$PROJECT " || true
}

# Takes the host-wide lock (or fails naming its holder), then starts worker-dl and waits until
# it answers. The lock stays held until this script exits, however it exits.
acquire_realdl() {
	local purpose=$1 holder deadline
	stack_running || die "slot $SLOT isn't up: scripts/agent_stack.sh $SLOT up"
	exec 9>>"$REALDL_LOCK"
	if ! flock -n 9; then
		holder="$(cat "$REALDL_LOCK" 2>/dev/null || true)"
		die "the realdl lock ($REALDL_LOCK) is held by ${holder:-another process (holder not recorded yet)}. Only one stack talks to YouTube at a time: wait and retry."
	fi
	# Before the cleanup trap: refusing here leaves this slot's (stopped) worker-dl alone, and the
	# lock frees as the script exits.
	holder="$(stray_worker_dl)"
	[ -z "$holder" ] || die "another slot's worker-dl runs without the lock ($holder): take it down there first"
	REALDL_HELD=1
	trap release_realdl EXIT
	trap 'exit 130' INT TERM
	printf 'slot %s (%s, %s), pid %s, since %s: %s\n' "$SLOT" "$PROJECT" "$ROOT" "$$" \
		"$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$purpose" >"$REALDL_LOCK"
	echo "agent_stack: realdl lock taken; starting worker-dl" >&2
	# --build: `up` skips a profiled service, so this is where worker-dl's image follows the
	# others (a dependency or yt-dlp change).
	COMPOSE_PROFILES=realdl dc up -d --build --no-deps worker-dl >&2
	deadline=$((SECONDS + 240))
	# shellcheck disable=SC2016 # $HOSTNAME is the container's, expanded by its shell
	until COMPOSE_PROFILES=realdl dc exec -T worker-dl sh -c \
		'celery -A app.tasks.celery_app inspect ping -d "worker-dl@$HOSTNAME" -t 5' >/dev/null 2>&1; do
		[ "$SECONDS" -lt "$deadline" ] || die "worker-dl didn't answer a ping in time: scripts/agent_stack.sh $SLOT logs worker-dl"
		sleep 5
	done
	echo "agent_stack: worker-dl is up" >&2
	export COMPOSE_PROFILES=realdl
}

# --- e2e fixture ---------------------------------------------------------------------------------

# A fresh slot database has none of what the e2e suite leans on from the owner's long-lived dev
# database: ledger rows for every track a default run submits, and the e2e admin's history.
# scripts/agent_seed.py recreates both, idempotently.
seed_fixture() {
	stack_running || die "slot $SLOT isn't up: scripts/agent_stack.sh $SLOT up"
	dc exec -T worker-meta python - <"$ROOT/scripts/agent_seed.py"
}

# The slot's e2e identities: frontend/e2e/.env.e2e.s<slot> (gitignored), exported so it wins
# over a frontend/e2e/.env.e2e copied in from elsewhere (loadE2eEnv never overrides).
load_e2e_credentials() {
	local file="$ROOT/frontend/e2e/.env.e2e.s$SLOT" key value
	[ -f "$file" ] || die "no $file: copy frontend/e2e/.env.e2e.example there and fill in slot $SLOT's two test identities (docs/LOCAL_DEV.md, 'Parallel agent stacks')"
	while IFS= read -r line || [ -n "$line" ]; do
		[[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=(.*)$ ]] || continue
		key="${BASH_REMATCH[1]}"
		value="$(env_value "$file" "$key")"
		export "$key=$value"
	done <"$file"
	export E2E_BASE_URL="http://localhost:$WEB_PORT"
}

# --- Commands -----------------------------------------------------------------------------------

# A function, called on the last line: bash reads a script as it runs it, so a long `realdl` or
# `e2e` would otherwise execute whatever a concurrent edit or `git rebase` put at its offset.
main() {
case "$CMD" in
env)
	write_env_agent
	;;
up)
	[ -f "$ENV_AGENT" ] || write_env_agent
	require_env_agent
	export_compose_env
	prepare_mounts
	dc up -d --build "$@"
	echo "agent_stack: waiting for slot $SLOT to be healthy"
	wait_healthy
	return_frontend_files
	echo "agent_stack: slot $SLOT is up: web http://localhost:$WEB_PORT, api http://localhost:$API_PORT"
	;;
down)
	require_env_agent
	export_compose_env
	COMPOSE_PROFILES=realdl dc down --remove-orphans "$@"
	;;
ps)
	require_env_agent
	export_compose_env
	COMPOSE_PROFILES=realdl dc ps "$@"
	;;
logs)
	require_env_agent
	export_compose_env
	COMPOSE_PROFILES=realdl dc logs "$@"
	;;
psql)
	require_env_agent
	export_compose_env
	if [ -t 0 ]; then tty_flag=(); else tty_flag=(-T); fi
	dc exec "${tty_flag[@]}" postgres psql -U "$PG_USER" -d "$(env_value "$ENV_AGENT" AGENT_PG_DB)" "$@"
	;;
pytest)
	require_env_agent
	export_compose_env
	stack_running || die "slot $SLOT isn't up: scripts/agent_stack.sh $SLOT up"
	# pytest isn't in the runtime image: a venv on top of its packages, at uv.lock's versions,
	# made once per api container. The suite gets a clean environment, as on CI and the host:
	# the container's own (the slot identities, its DATABASE_URL) would override conftest.py's
	# test defaults. v51 points it at a throwaway database on the slot's Postgres.
	lock_version() {
		awk -v name="$1" '$0 == "name = \"" name "\"" { getline; gsub(/version = |"/, ""); print; exit }' "$ROOT/backend/uv.lock"
	}
	pytest_pin="pytest==$(lock_version pytest)"
	asyncio_pin="pytest-asyncio==$(lock_version pytest-asyncio)"
	dc exec -T api sh -c "[ -x /tmp/pytest-venv/bin/pytest ] || { python -m venv --system-site-packages /tmp/pytest-venv && uv pip install --quiet --python /tmp/pytest-venv/bin/python '$pytest_pin' '$asyncio_pin'; }"
	if [ -t 1 ]; then tty_flag=(); else tty_flag=(-T); fi
	dc exec "${tty_flag[@]}" -w /app api env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp PYTHONDONTWRITEBYTECODE=1 \
		/tmp/pytest-venv/bin/python -m pytest -p no:cacheprovider "$@"
	;;
run)
	[ $# -ge 1 ] || die "usage: scripts/agent_stack.sh $SLOT run <command...>"
	require_env_agent
	export_compose_env
	"$@"
	;;
seed)
	require_env_agent
	export_compose_env
	seed_fixture
	;;
e2e)
	require_env_agent
	export_compose_env
	load_e2e_credentials
	# The specs import the compiled messages from the host side; the web container's copy is
	# its own (an anonymous volume).
	[ -f "$ROOT/frontend/src/lib/paraglide/messages.js" ] ||
		die "frontend/src/lib/paraglide isn't compiled on the host: run npm ci && npm run check in frontend/ first"
	acquire_realdl "e2e"
	seed_fixture
	(cd "$ROOT/frontend" && npm run test:e2e -- "$@")
	;;
realdl)
	[ $# -ge 1 ] || die "usage: scripts/agent_stack.sh $SLOT realdl <command...>"
	require_env_agent
	export_compose_env
	acquire_realdl "$*"
	"$@"
	;;
*)
	usage
	;;
esac
}

# One line, so bash has read all of it before main runs.
main "$@"; exit
