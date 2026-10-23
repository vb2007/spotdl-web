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

# A value from a dotenv file (the last assignment wins, as in Compose): a quoted value up to its
# closing quote, an unquoted one without its inline ` # comment`.
env_value() {
	local file=$1 key=$2
	[ -f "$file" ] || return 0
	sed -n "s/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}${key}[[:space:]]*=\(.*\)$/\2/p" "$file" |
		tail -n 1 | sed -e 's/^[[:space:]]*//' -e 'ta' -e ':a' \
		-e "s/^\"\([^\"]*\)\".*$/\1/;t" -e "s/^'\([^']*\)'.*$/\1/;t" \
		-e 's/[[:space:]]#.*$//' -e 's/[[:space:]]*$//'
}

# --- Refusals, checked before any command ---------------------------------------------------

# A checkout whose .env names the production database is the production host's (or a copy of
# its .env): nothing here may run there.
refuse_production_env() {
	[ -f "$ENV_FILE" ] || return 0
	local url path query name dbname prod
	url="$(env_value "$ENV_FILE" DATABASE_URL)"
	[ -n "$url" ] || return 0
	# SQLAlchemy's own URL pattern (sqlalchemy.engine.url._parse_url, which app/config.py's guard
	# relies on): scheme, optional user:password@, host, port, /database, ?query.
	local re='^[A-Za-z0-9_+]+://(([^:/]*)(:([^@]*))?@)?((\[[^/?]+\])|([^/:?]+))?(:([^/?]*))?(/([^?]*))?(\?(.*))?'
	[[ "$url" =~ $re ]] ||
		die "$ENV_FILE's DATABASE_URL can't be parsed: refusing (app/config.py would too)"
	path="${BASH_REMATCH[11]}"
	query="${BASH_REMATCH[13]}"
	if [[ "&$query" =~ \&dbname=([^\&]*) ]]; then dbname="${BASH_REMATCH[1]}"; else dbname=""; fi
	# Either name, percent-decoded, trimmed and case-folded, refuses (a superset of the guard's).
	for name in "$path" "$dbname"; do
		name="$(printf '%b' "${name//%/\\x}")"
		name="${name%/}"
		name="${name#"${name%%[![:space:]]*}"}"
		name="${name%"${name##*[![:space:]]}"}"
		name="${name,,}"
		for prod in "${PRODUCTION_DATABASE_NAMES[@]}"; do
			if [ "$name" = "$prod" ]; then
				die "$ENV_FILE names the production database ($name). Refusing: agent stacks never run from a production checkout (copy the owner's dev .env instead)."
			fi
		done
	done
}

# A slot belongs to the worktree that started it until it's taken down there: its containers
# carry that worktree in Compose's working_dir label, and its database volume in our own label.
refuse_foreign_slot() {
	local dir volume_dir dirs
	dirs="$(docker ps -a --filter "label=com.docker.compose.project=$PROJECT" \
		--format '{{.Label "com.docker.compose.project.working_dir"}}')" ||
		die "docker ps failed: can't check who owns slot $SLOT"
	while IFS= read -r dir; do
		if [ -n "$dir" ] && [ "$dir" != "$ROOT" ]; then
			die "slot $SLOT ($PROJECT) is in use by another worktree: $dir. Take it down there (scripts/agent_stack.sh $SLOT down), or pick another slot."
		fi
	done <<<"$dirs"
	volume_dir="$(docker volume inspect "${PROJECT}_pgdata" \
		--format '{{index .Labels "spotdlweb.worktree"}}' 2>/dev/null || true)"
	if [ -n "$volume_dir" ] && [ "$volume_dir" != "$ROOT" ]; then
		die "slot $SLOT's database volume ${PROJECT}_pgdata belongs to another worktree: $volume_dir. Drop it there (scripts/agent_stack.sh $SLOT down --volumes), or, if that worktree is gone, docker volume rm ${PROJECT}_pgdata ${PROJECT}_redis-data (Redis's queue goes with it)."
	fi
}

# The shared main checkout belongs to the owner and other sessions (and its ./downloads and
# ./test-library to the owner's stack): a slot runs only from a linked worktree of its own.
refuse_main_checkout() {
	local git_dir common_dir
	# Fails closed: a slot runs only from a worktree git can vouch for.
	git_dir="$(git -C "$ROOT" rev-parse --path-format=absolute --git-dir 2>/dev/null)" &&
		common_dir="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" ||
		die "can't tell whether $ROOT is a linked git worktree (git rev-parse failed): refusing"
	[ "$git_dir" != "$common_dir" ] ||
		die "$ROOT is the main checkout: run slots from a worktree of your own (git worktree add, docs/LOCAL_DEV.md 'Parallel agent stacks')"
}

# Commands that create or remove the slot's containers hold a per-slot lock, so two worktrees
# claiming the same free slot at once can't both pass the ownership check below.
lock_slot() {
	case "$CMD" in
	env | up | down)
		exec 8>"/tmp/spotdl-web-slot$SLOT.lock"
		flock -w 900 8 || die "slot $SLOT stayed locked by another env/up/down for 15 minutes"
		;;
	esac
}


# --- .env.agent ---------------------------------------------------------------------------------

random_secret() {
	od -An -N24 -tx1 /dev/urandom | tr -d ' \n'
}

# The worktree's .env is the owner's dev one, LAN database included: a habitual plain
# `docker compose up` (or `run migrate`) here would run this branch's migrations on the owner's
# spotdlwebtest. Without a DATABASE_URL every backend service refuses to start instead.
disable_env_database() {
	[ -f "$ENV_FILE" ] || return 0
	if grep -qE "^[[:space:]]*(export[[:space:]]+)?DATABASE_URL[[:space:]]*=" "$ENV_FILE"; then
		sed -i -E 's/^([[:space:]]*(export[[:space:]]+)?DATABASE_URL[[:space:]]*=)/# agent_stack.sh: disabled, a slot worktree never uses the LAN database: \1/' "$ENV_FILE"
		echo "agent_stack: disabled DATABASE_URL in $ENV_FILE (plain docker compose here can't reach the owner's database)"
	fi
}

write_env_agent() {
	local previous
	previous="$(env_value "$ENV_AGENT" AGENT_SLOT)"
	local previous_dirs
	if [ -n "$previous" ] && [ "$previous" != "$SLOT" ]; then
		previous_dirs="$(docker ps -a --filter "label=com.docker.compose.project=spotdlweb-s$previous" \
			--format '{{.Label "com.docker.compose.project.working_dir"}}')"
		# A here-string, not a pipe: under pipefail, grep -q exiting early can fail the pipeline.
		if grep -qxF -- "$ROOT" <<<"$previous_dirs"; then
			die "this worktree's stack is slot $previous's and still exists: scripts/agent_stack.sh $previous down first"
		fi
		local previous_volume_dir
		previous_volume_dir="$(docker volume inspect "spotdlweb-s${previous}_pgdata" \
			--format '{{index .Labels "spotdlweb.worktree"}}' 2>/dev/null || true)"
		if [ "$previous_volume_dir" = "$ROOT" ]; then
			die "this worktree still owns slot $previous's database volume, and no other worktree could take that slot: scripts/agent_stack.sh $previous down --volumes first"
		fi
		# The stored password is slot $previous's; a volume this slot kept was made with its own.
		if docker volume inspect "${PROJECT}_pgdata" >/dev/null 2>&1; then
			die "slot $SLOT still has a database volume from before, with a password .env.agent no longer holds: drop it with scripts/agent_stack.sh $SLOT down --volumes (after env for slot $SLOT fails, use docker volume rm ${PROJECT}_pgdata ${PROJECT}_redis-data)"
		fi
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
	if [ -n "$pg_port" ] && { ! [[ "$pg_port" =~ ^[1-9][0-9]{0,4}$ ]] || [ "$pg_port" -gt 65535 ]; }; then
		die "PG_PORT must be a port number (1-65535), got '$pg_port'"
	fi
	# A plain character set: anything else could break the dotenv line or be interpolated ($).
	if [ -n "$extra_emails" ] && ! [[ "$extra_emails" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+(,[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+)*$ ]]; then
		die "AGENT_EXTRA_EMAILS must be comma-separated addresses, got '$extra_emails'"
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
	disable_env_database
	echo "agent_stack: wrote $ENV_AGENT (slot $SLOT: $PROJECT, api $API_PORT, web $WEB_PORT, db $PG_DB)"
}

require_env_agent() {
	[ -f "$ENV_AGENT" ] || die "no $ENV_AGENT yet: run scripts/agent_stack.sh $SLOT env (or up)"
	local slot
	slot="$(env_value "$ENV_AGENT" AGENT_SLOT)"
	[ "$slot" = "$SLOT" ] || die "this worktree is slot ${slot:-?}'s, not slot $SLOT's: to switch, scripts/agent_stack.sh ${slot:-<old slot>} down, then scripts/agent_stack.sh $SLOT env"
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
	fi
	# Never deleted here: a realdl or e2e still running in this worktree may list it.
	# Compose prefers the shell's variables over COMPOSE_ENV_FILES: one left exported by a caller
	# (an AGENT_SLOT of another slot, a REDIS_PASSWORD) would override .env.agent's.
	unset AGENT_SLOT AGENT_WORKTREE AGENT_PG_DB AGENT_PG_USER AGENT_PG_PASSWORD REDIS_PASSWORD \
		CLOUDFLARE_TUNNEL_TOKEN IMAGE_TAG DOWNLOADS_DIR LIBRARY_DIR
	export COMPOSE_PROJECT_NAME="$PROJECT"
	export COMPOSE_FILE="$files"
	export COMPOSE_ENV_FILES="$ENV_AGENT"
	export COMPOSE_PROFILES=""
	export API_PORT WEB_PORT
}

# fd 9 is the realdl lock: no compose process (or anything it leaves behind) may keep it.
dc() {
	docker compose --project-directory "$ROOT" "$@" 9>&-
}

stack_running() {
	[ -n "$(dc ps --status running -q api 2>/dev/null)" ]
}

# Every started service healthy (beat has no healthcheck: running), migrate exited 0. worker-dl
# isn't part of `up`: it runs only under a realdl lock, which watches it itself.
wait_healthy() {
	local deadline=$((SECONDS + 420)) pending line name service state health exit_code rows
	while :; do
		pending=""
		# Captured first, so a failing `ps` stops here instead of reading as "nothing pending".
		rows="$(dc ps -a --format '{{.Name}} {{.Service}} {{.State}} {{if .Health}}{{.Health}}{{else}}-{{end}} {{.ExitCode}}')" ||
			die "docker compose ps failed for slot $SLOT"
		[ -n "$rows" ] || pending=" (no containers yet)"
		while read -r name service state health exit_code; do
			[ -n "$service" ] && [ "$service" != worker-dl ] || continue
			# A one-off `docker compose run` container isn't part of the stack.
			[[ "$name" != *-run-* ]] || continue
			if [ "$service" = migrate ]; then
				[ "$state" = exited ] && [ "$exit_code" = 0 ] && continue
				[ "$state" = exited ] && die "migrate exited $exit_code: scripts/agent_stack.sh $SLOT logs migrate"
			elif [ "$state" = running ] && { [ "$health" = healthy ] || [ "$health" = "-" ]; }; then
				continue
			elif [ "$state" = exited ] || [ "$state" = restarting ] || [ "$health" = unhealthy ]; then
				die "$service is $state${health:+ ($health)}: scripts/agent_stack.sh $SLOT logs $service"
			fi
			pending="$pending $service"
		done <<<"$rows"
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
	trap '' INT TERM HUP PIPE
	if [ -n "$REALDL_HELD" ]; then
		# Nothing may cut the cleanup short. errexit off, and SIGPIPE ignored: with the terminal
		# closed or a `| tee` reader gone, the first message would otherwise end the shell before
		# worker-dl is removed. A second Ctrl-C (or a SIGTERM) waits too: worker-dl can take up to
		# its stop_grace_period to finish a download. Ignoring them protects bash only (the Go
		# docker CLI re-enables SIGINT), so the removal runs in a session of its own, which the
		# terminal's Ctrl-C doesn't reach.
		set +e
		trap '' INT TERM HUP PIPE
		echo "agent_stack: stopping worker-dl and releasing the realdl lock" >&2
		# Removed, not just stopped: an exited worker-dl container would sit in `ps -a` as if
		# it had crashed. Its output goes to a file first: written straight to a dead stderr, the
		# docker CLI itself dies of SIGPIPE before removing anything.
		local log="$ROOT/.agent-stack/realdl-cleanup.log"
		mkdir -p "${log%/*}"
		if COMPOSE_PROFILES=realdl setsid --wait docker compose --project-directory "$ROOT" \
			rm --stop --force worker-dl </dev/null >"$log" 2>&1 9>&-; then
			cat "$log" >&2
			: >"$REALDL_LOCK"
		else
			cat "$log" >&2
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
	# 600: the holder line records the command, which may carry a credential.
	(umask 077 && : >>"$REALDL_LOCK")
	chmod 600 "$REALDL_LOCK" 2>/dev/null || true
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
	trap 'exit 130' INT
	trap 'exit 143' TERM
	trap 'exit 129' HUP
	# A message to a stderr whose reader is gone (`| tee` killed by the same Ctrl-C) would kill
	# bash with SIGPIPE, and a signal death skips the EXIT trap, so worker-dl would stay up. With
	# SIGPIPE ignored the write just fails, errexit exits, and the cleanup runs.
	trap '' PIPE
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
	# Again, now that this one runs: another slot's may have started meanwhile (a /tmp that isn't
	# shared, a hand-started one), and the two would talk to YouTube at once.
	holder="$(stray_worker_dl)"
	[ -z "$holder" ] || die "another slot's worker-dl started meanwhile ($holder): stopping this one"
	echo "agent_stack: worker-dl is up" >&2
	export COMPOSE_PROFILES=realdl
}

# Runs the command the lock is held for. In the background, so a signal to this script reaches
# its trap at once (bash defers a trapped signal until a foreground child exits) and is passed
# on as SIGTERM (a background child starts with SIGINT ignored). Without fd 9: if this script is
# killed outright, the lock frees, and stray_worker_dl keeps the other slots out while this
# slot's worker-dl still runs. Stdin stays the caller's.
LOCKED_CHILD=""
LOCKED_SIGNAL=""

# A process and all its descendants (they started with SIGINT ignored, and a wrapper like
# `sh -c` doesn't pass a TERM on), deepest first.
process_tree() {
	local child
	for child in $(ps -o pid= --ppid "$1" 2>/dev/null); do
		process_tree "$child"
	done
	echo "$1"
}

stop_locked_child() {
	LOCKED_SIGNAL=$1
	[ -n "$LOCKED_CHILD" ] || return 0
	# shellcheck disable=SC2046 # one pid per word
	kill -TERM $(process_tree "$LOCKED_CHILD") 2>/dev/null || true
}

run_locked() {
	local status=0
	# Traps first: a signal between the launch and the trap would otherwise exit without ever
	# signalling the command just started.
	trap 'stop_locked_child 130' INT
	trap 'stop_locked_child 143' TERM
	trap 'stop_locked_child 129' HUP
	# The command gets SIGPIPE back (a pipeline in it behaves as usual).
	(
		trap - PIPE
		exec "$@"
	) <&0 9>&- &
	LOCKED_CHILD=$!
	[ -z "$LOCKED_SIGNAL" ] || stop_locked_child "$LOCKED_SIGNAL"
	# A trapped signal ends `wait` early: wait again until the child has really exited.
	while :; do
		status=0
		wait "$LOCKED_CHILD" || status=$?
		kill -0 "$LOCKED_CHILD" 2>/dev/null || break
	done
	LOCKED_CHILD=""
	trap 'exit 130' INT
	trap 'exit 143' TERM
	trap 'exit 129' HUP
	[ -z "$LOCKED_SIGNAL" ] || exit "$LOCKED_SIGNAL"
	return "$status"
}

# Tracks that would really download once worker-dl runs: not finished, and not in the ledger.
# Beat keeps re-dispatching them while worker-dl is off (its stale-track reclaim), so their
# messages wait in the slot's Redis.
# A job still expanding counts too: its tracks don't exist yet, and could be anything.
pending_downloads() {
	dc exec -T postgres psql -U "$PG_USER" -d "$(env_value "$ENV_AGENT" AGENT_PG_DB)" -Atc \
		"select (select count(*) from tracks t where t.state in ('pending', 'queued', 'downloading', 'waiting')
		         and not exists (select 1 from downloaded_tracks d where d.spotify_track_id = t.spotify_track_id))
		      + (select count(*) from jobs where state = 'expanding')"
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
		[[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=(.*)$ ]] || continue
		key="${BASH_REMATCH[2]}"
		value="$(env_value "$file" "$key")"
		export "$key=$value"
	done <"$file"
	export E2E_BASE_URL="http://localhost:$WEB_PORT"
}

# --- Commands -----------------------------------------------------------------------------------

# A function, called on the last line: bash reads a script as it runs it, so a long `realdl` or
# `e2e` would otherwise execute whatever a concurrent edit or `git rebase` put at its offset.
main() {
# Inside main, like everything that can wait (lock_slot's flock): see the comment above.
refuse_production_env
refuse_main_checkout
lock_slot
refuse_foreign_slot
case "$CMD" in
env)
	write_env_agent
	;;
up)
	# Rewritten on every up (secrets, PG_PORT and extra emails kept), so a changed .env or a
	# PG_PORT=… given to up takes effect.
	write_env_agent
	require_env_agent
	export_compose_env
	for arg in "$@"; do
		[ "$arg" != worker-dl ] || die "worker-dl runs only under the realdl lock: scripts/agent_stack.sh $SLOT realdl <command>"
	done
	prepare_mounts
	dc up -d --build "$@"
	echo "agent_stack: waiting for slot $SLOT to be healthy"
	wait_healthy
	return_frontend_files
	echo "agent_stack: slot $SLOT is up: web http://localhost:$WEB_PORT, api http://localhost:$API_PORT"
	;;
down)
	if [ ! -f "$ENV_AGENT" ]; then
		# .env.agent is gone (git clean, say): Compose can't render the slot without it, so
		# remove by label. refuse_foreign_slot has already checked the slot is this worktree's.
		echo "agent_stack: no $ENV_AGENT: removing slot $SLOT's containers by label" >&2
		docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" | xargs -r docker rm -fv >/dev/null
		docker network rm "${PROJECT}_default" >/dev/null 2>&1 || true
		if [ "${1:-}" = --volumes ] || [ "${1:-}" = -v ]; then
			docker volume rm "${PROJECT}_pgdata" "${PROJECT}_redis-data" >/dev/null 2>&1 || true
			echo "agent_stack: removed ${PROJECT}_pgdata and ${PROJECT}_redis-data" >&2
		fi
		return 0
	fi
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
	if [ -t 0 ] && [ -t 1 ]; then tty_flag=(); else tty_flag=(-T); fi
	dc exec "${tty_flag[@]}" -w /src api env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp PYTHONDONTWRITEBYTECODE=1 \
		/tmp/pytest-venv/bin/python -m pytest -p no:cacheprovider "$@"
	;;
run)
	[ $# -ge 1 ] || die "usage: scripts/agent_stack.sh $SLOT run <command...>"
	# Naming a profiled service enables its profile: `run docker compose up worker-dl` would start
	# it without the lock.
	# A best-effort guard (a script that starts it unseen gets through); the stray checks are the
	# backstop.
	if [[ "$*" == *realdl* || "$*" == *COMPOSE_PROFILES* ]] ||
		{ [[ " $* " == *" worker-dl "* ]] && [[ " $* " =~ \ (up|start|restart|create|run)\  ]]; }; then
		die "worker-dl runs only under the realdl lock: scripts/agent_stack.sh $SLOT realdl <command>"
	fi
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
	stack_running || die "slot $SLOT isn't up: scripts/agent_stack.sh $SLOT up"
	backlog="$(pending_downloads)"
	[ "$backlog" = 0 ] || die "slot $SLOT has $backlog unfinished track(s) outside the ledger or job(s) still expanding, which worker-dl could really download during the suite: cancel those jobs first (or run them with realdl)"
	# Before worker-dl starts: a queued fixture track whose stand-in is gone must be back on disk
	# before anything can dispatch it.
	seed_fixture
	acquire_realdl "e2e"
	run_locked npm --prefix "$ROOT/frontend" run test:e2e -- "$@"
	;;
realdl)
	[ $# -ge 1 ] || die "usage: scripts/agent_stack.sh $SLOT realdl <command...>"
	require_env_agent
	export_compose_env
	stack_running || die "slot $SLOT isn't up: scripts/agent_stack.sh $SLOT up"
	backlog="$(pending_downloads)"
	[ "$backlog" = 0 ] || echo "agent_stack: note: $backlog unfinished track(s) outside the ledger or expanding job(s) may download once worker-dl starts" >&2
	acquire_realdl "$*"
	run_locked "$@"
	;;
*)
	usage
	;;
esac
}

# One line, so bash has read all of it before main runs.
main "$@"; exit
