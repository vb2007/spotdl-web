# Deploying spotdl-web to the Debian 12 host

Target host: **192.168.100.200** (Debian 12 "bookworm"), reachable on the local network.
The real deploy checkout lives at **`/mnt/raid1/spotdl-web`** — this diverges from earlier
versions of this doc, which described `/opt/spotdl-web`; corrected here rather than moved,
since moving a live deploy directory isn't worth the churn. Likewise `DOWNLOADS_DIR` on this
host is `/home/vb2007/spotdl`, not the `/srv/spotdl-web/downloads` this doc originally
suggested — the two paths below don't have to match yours if you're setting up a *new* host,
they're documented here as ground truth for *this* one.

**As of v21, deployment is automated** — see [Automated deployment](#automated-deployment-v21)
below, the primary path now. The manual steps further down (originally "Upgrading an existing
deployment to v12") remain as the fallback for when the pipeline itself needs debugging, or
for a genuinely fresh host.

Ports are intentionally **not** exposed beyond the host's loopback interface (see
[Firewall / network notes](#firewall--network-notes)) — the locked decision is Cloudflare
Tunnel as the only ingress, ever. Verification happens over SSH or through the tunnel
itself, not by curling the LAN IP directly.

Run every command below on the target host (`ssh <you>@192.168.100.200`) unless marked
otherwise.

---

## Automated deployment (v21+)

Every merge into `main` (that bumped the version — see `CLAUDE.md`'s versioning rule) flows
through three chained GitHub Actions workflows, running on the self-hosted runner on this same
host: **CI → Release → Publish & Deploy**. The last of those pulls the freshly-published
`ghcr.io/vb2007/spotdl-web-backend`/`-frontend` images onto `/mnt/raid1/spotdl-web` and
restarts the stack, with a pre-migration `pg_backup.sh` run and automatic rollback if the new
stack doesn't come up healthy. Full pipeline detail, GHCR package layout, idempotency, and
every manual-recovery lever live in **`docs/RELEASE_PIPELINE.md`** — this doc doesn't duplicate
that, only what's specific to this host.

**Deploying a branch before merging its PR:** the "Publish & Deploy" workflow also accepts
`workflow_dispatch`, so you don't have to merge first to try something on the real host:

```bash
gh workflow run "Publish & Deploy" --repo vb2007/spotdl-web -f ref=<branch-or-tag-or-sha>
```

This builds a throwaway `manual-<short-sha>` image (never `:latest`, so a plain
`docker compose pull` never picks it up by accident) and deploys it immediately — always, with
no skip/idempotency checks, since it's an explicit on-demand request. The *next* real
release-driven deploy always supersedes it.

**Manual fallback**, if the pipeline itself is broken and you need to get a specific known-good
version running directly:

```bash
cd /mnt/raid1/spotdl-web
git fetch origin --tags
git checkout --detach v2.21.0   # or whatever tag/commit you need
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=2.21.0/' .env   # match the tag, no leading "v"
./scripts/pg_backup.sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel up -d --no-build
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

If GHCR itself is unreachable, build from source instead of pulling — see the manual
local-build steps in
[Upgrading an existing deployment](#upgrading-an-existing-deployment-manual-fallback) below.

---

## Upgrading an existing deployment (manual fallback)

### 1. Pull the merged code

```bash
cd /mnt/raid1/spotdl-web
git pull origin main
```

### 2. Update `.env`

Diff your existing `.env` against `.env.example` and add whatever's new for v12:

| Key | What to set it to |
|---|---|
| `FRONTEND_ORIGINS` | `https://spotdl.vb2007.hu` (see §4 below — same-origin in prod, but still worth setting correctly as the fallback allowlist) |
| `DOWNLOADS_DIR` | A real host path, e.g. `/home/vb2007/spotdl` (this host's actual value) — read only by `docker-compose.prod.yml`, see §3 |
| `LIBRARY_DIR` (v28) | A real host path for the actual music library `worker-meta`'s sort & move sweep writes into and `web` serves file downloads from read-only — e.g. `/mnt/raid1/media/music` (this host's actual value). `docker-compose.prod.yml`'s `${LIBRARY_DIR:?...}` crash-loops the stack at `up` time if this is unset, by design. See the new "Set up the library directory" step below §3 |
| `STALE_TRACK_AFTER_SECONDS` | Leave at the `.env.example` default (`1800`) for real production use — see §7's restart-survival test for why you might *temporarily* lower it during verification |

**No longer needed:** a `frontend/.env` file, and a manual `alembic upgrade head` step —
both are now automatic (see §4 and §5 below). If you have a leftover `frontend/.env` from
an earlier version, it's harmless but no longer read by anything; safe to delete.

### 3. Migrate the downloads directory (one-time, before first boot with the new bind mount)

`docker-compose.prod.yml` switches `worker-dl`/`worker-meta`'s `/downloads` mount from the
base file's Docker-managed named volume to a real host directory — so downloaded files
are directly browsable/backup-able and survive `docker compose down -v`. This must happen
**before** the first `up` against the new compose files, or `reconcile_disk()` will find
the (correctly) empty new directory, refuse to prune (a v12 safety guard added
specifically for this), and log an error rather than silently deleting your dedup ledger —
but you still need to actually move the files over for downloads to keep working without
re-fetching everything.

```bash
# Confirm the exact volume name first -- it's <project-name>_downloads, and the project
# name is derived from the compose project (normally the directory name, "spotdl-web").
docker volume ls | grep downloads

sudo mkdir -p /home/vb2007/spotdl   # or wherever you're pointing DOWNLOADS_DIR
docker run --rm \
  -v spotdl-web_downloads:/from \
  -v /home/vb2007/spotdl:/to \
  alpine sh -c 'cp -a /from/. /to/ && echo "copied $(ls /to | wc -l) entries"'

# Non-root containers (v12) run as uid/gid 1000 by default (backend/Dockerfile's
# APP_UID/APP_GID build args) -- chown to match, or worker-dl/worker-meta will get
# permission-denied writing new downloads.
sudo chown -R 1000:1000 /home/vb2007/spotdl
```

If your deploy user ended up with a different uid than 1000 and you'd rather match that
than chown the directory, rebuild with `--build-arg APP_UID=<uid> --build-arg
APP_GID=<gid>` instead — see step 4's build command.

**`LIBRARY_DIR` (v28)** is a separate, second bind mount — the real music library
(`docker-compose.prod.yml` maps it to `/mnt/raid1/media/music` in `worker-meta` read-write and
`web` read-only) that the admin-only sort & move sweep moves completed downloads into. Unlike
`DOWNLOADS_DIR`, there's no one-time volume migration here — it's your existing library directory,
set once in `.env`. It still needs the same uid 1000 write access, or the sweep's `copy_verify`
fails every row with a permission error:

```bash
sudo chown -R 1000:1000 <LIBRARY_DIR>   # only if it isn't already owned by that uid/gid
```

The folder template (`{artist} - {album} - ({year})` by default), the quarantine toggle, and the
quarantine directory are **admin settings**, not env vars — configured post-deploy from `/settings`
(`app_settings.get_library_settings`'s get-or-create defaults apply until an admin changes them),
the same pattern as v13's output-config settings. `LIBRARY_DIR`/`.env` only decides *where the bind
mount points*, never the folder layout inside it.

Confirm both mounts landed correctly after `up`: `docker compose exec worker-meta ls -la /downloads
/mnt/raid1/media/music` should show the real library's existing folders, writable by the container.

### 4. Bring up the stack with the production overlay

```bash
cd /mnt/raid1/spotdl-web
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel up -d --build
```

This is a different invocation from pre-v12 versions in three ways:
- **`-f docker-compose.prod.yml`** is new — carries resource limits, the downloads bind
  mount from step 3, and the `web` build arg (see below).
- **`--profile tunnel`** now actually starts `cloudflared` for real, using the
  `CLOUDFLARE_TUNNEL_TOKEN` already sitting in `.env` from earlier testing.
- You no longer need a separate `frontend/.env` before this — `web`'s `PUBLIC_API_BASE_URL`
  build arg defaults to `""` (same-origin, see §5), baked in by `docker-compose.yml`
  itself. A fresh checkout can run this command with zero additional frontend config.

**Do not** add `-f docker-compose.override.yml` — that file is dev-only (bind-mounted
source, hot reload) and was never meant to run here; omitting `-f` for it (as above) is
correct, not an oversight.

A new **`migrate`** service now runs `alembic upgrade head` automatically and every other
service waits for it to exit `0` before starting — the old manual "confirm Alembic wiring"
step from earlier versions of this doc is gone; it happens on every `up` now, on its own.

### 5. Configure the Cloudflare Tunnel (Zero Trust dashboard)

Ingress is same-origin: the `web` container's nginx serves the built frontend *and*
reverse-proxies `/api/*` to the `api` service internally (see `frontend/nginx.conf`) — so
the tunnel only needs to know about **one** service, `web`, not two. There is no path
rule to get right in the dashboard.

1. Go to [the Zero Trust dashboard](https://one.dash.cloudflare.com/) → **Networks →
   Tunnels**.
2. Open the tunnel whose token is already in this host's `CLOUDFLARE_TUNNEL_TOKEN`.
3. **Public Hostname** tab → **Add a public hostname**.
4. Subdomain: `spotdl`, Domain: `vb2007.hu` (→ `spotdl.vb2007.hu`).
5. Service **Type: HTTP**, **URL: `web:80`** — the compose service name and nginx's
   internal port; `cloudflared` reaches it over the compose network the same way it
   already reaches `api` today, never `localhost`.
6. Save. DNS + the edge certificate can take a minute to become reachable.

Optional but recommended, since this makes the app genuinely internet-reachable with no
other gate in front of it:
- A **Cache Rule** bypassing cache for `spotdl.vb2007.hu/api/*` (extensionless paths are
  already unlikely to be cached by Cloudflare's default rules, but this makes it explicit
  rather than relying on that default).
- A **Rate Limiting** rule on `spotdl.vb2007.hu/api/auth/login` (e.g. 5 requests/minute per
  IP) — there's no rate limiting anywhere in the app itself, and this endpoint proxies
  credentials to the upstream auth API.

### 6. Verify

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Expect every service `healthy` except `beat` (deliberately has no healthcheck — see its
comment in `docker-compose.yml`) and `migrate`/`cloudflared` (one-shot / no healthcheck
defined). If anything is `unhealthy`, `docker compose logs <service>` — output is now
structured JSON (v12), so `docker compose logs api | jq .` is worth doing over raw
scrollback.

From the host:
```bash
curl -s http://localhost:8000/api/health
```
Expect `{"status":"ok"}`.

Through the real tunnel, from your own machine (not the host):
```bash
curl -I https://spotdl.vb2007.hu/login   # expect 200, not 404 -- see the SPA-fallback note below
curl -N https://spotdl.vb2007.hu/api/stream --max-time 20   # expect a ": heartbeat" line within ~15s (requires a valid session cookie to get past auth -- a 401 with no heartbeat is still a meaningful check that the proxy itself is reachable)
```

`GET /login` returning `200` instead of `404` is a real, previously-shipped bug this
version fixes (stock nginx has no route for the extensionless `/login` path to the
prerendered `login.html` file) — worth confirming explicitly, not assuming.

Both bind mounts, present and writable by the container user (v28):
```bash
docker compose exec worker-meta ls -la /downloads /mnt/raid1/media/music
```
Should show the real library's existing artist/album folders, not an empty directory —
an empty result here with real ledger rows already in the database means `LIBRARY_DIR`
or `DOWNLOADS_DIR` is misconfigured in `.env`, not that the library is actually empty.

---

## Ongoing maintenance

- **Backups**: install the cron job below once; see [Backups](#backups) for the restore
  drill you should also do at least once to actually trust it.
  ```bash
  crontab -e
  # add:
  0 3 * * * /mnt/raid1/spotdl-web/scripts/pg_backup.sh >> /home/vb2007/spotdl-web-pg-backup.log 2>&1
  ```
- **`cloudflared` image**: deliberately left on a floating tag (see its comment in
  `docker-compose.yml`) since Cloudflare periodically deprecates old client versions.
  Re-pull it every so often rather than letting it silently age:
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel pull cloudflared
  docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel up -d cloudflared
  ```
- **Disk/image pruning**: `.github/workflows/publish-deploy.yml`'s `deploy` job already runs
  `docker image prune -f` / `docker builder prune -f --keep-storage 5GB` after every successful
  automated deploy (v21) — the periodic manual check below is now a belt-and-suspenders
  fallback, not the only thing keeping this in check:
  ```bash
  docker system df
  docker image prune -f
  docker builder prune -f --keep-storage 5GB
  ```

---

## Rollback / recovery (v21, v33)

The automated pipeline (`.github/workflows/publish-deploy.yml`) rolls back on its own when a
fresh deploy fails its health gate. Since v33 that rollback restores the previous release's
**commit and `IMAGE_TAG` together** (from `/mnt/raid1/spotdl-web/.last-good`), and it refuses to
start the old stack at all when the failed deploy already migrated the database past what the old
image knows. `docs/RELEASE_PIPELINE.md`, "Rollback", has the exact semantics. Every failure, and
every real deploy, posts to the Matrix room ([Matrix alert bot](#matrix-alert-bot-v33) below), so
you hear about it. This section is for recovering **by hand**: when the workflow itself can't run,
or when it stopped and told you to come here.

**Where things stand after a failed run.** The run's **Summary** step prints the deploy
checkout's `HEAD`, the `.env` `IMAGE_TAG` line, `.last-good` and `compose ps`, so you can read
the host's state from the Actions page without SSHing in. The Matrix message says which of these
happened:

| Rollback says | What it means | What to do |
|---|---|---|
| not needed | The preflight (or the backup) failed before anything on the host moved. | Fix the cause, typically a missing `.env` variable named in the log (see "A deploy needs a new `.env` variable" below), then re-run. |
| succeeded | The old commit + tag are back up and healthy. The run is still red, because the deploy failed. | Investigate at leisure, fix, re-run. |
| succeeded, back on … the pre-deploy version | v33.1 fallback: the database was ahead of `.last-good`, so the rollback returned to what was running before the deploy (typically a `manual-*` dispatch) instead. `.last-good` is unchanged. | As above. The host is on a dispatch build until the next real release. |
| refused | The database is **ahead** of the rollback image. The failed deploy's checkout and containers were left exactly as they were. | "The database is ahead of the rollback image" below. |
| not started | The rollback stopped before moving anything (no rollback target recorded, the previous commit unreadable). The failed deploy is still in place. | Read the log, then roll back manually if needed. |
| not started (guard error) | The migration guard couldn't compare revisions (Postgres unreachable, the old image unpullable, a compose error such as a changed network definition, or the new `migrate` still running after 5 minutes), so it started nothing. The checkout and containers were left as they were. | Read the guard's error in the log, fix it, then re-check the guard by hand (below) before rolling back manually. |
| failed | The rollback itself broke part-way. The stack may be down. | "Roll back to a known-good version manually" below. |
| not needed, the new version passed its health gate | A step after the health gate failed (writing `.last-good`, say). The new version is up. | Check the Summary; `.last-good` may still name the previous release. |
| UNKNOWN, the deploy job reported nothing | The deploy job produced no step outcomes (the runner died, the host rebooted, a cancel before it started). | Check the host's state (HEAD, `IMAGE_TAG`, `compose ps`) before doing anything. |
| not attempted, the host may be mid-deploy | The deploy step started but no rollback ran: the run was cut off before the rollback step could start. | Check the Summary's state, then roll back manually if needed. |

**A deploy needs a new `.env` variable** (the preflight failed, naming it): add it to
`/mnt/raid1/spotdl-web/.env`, with the value the version's PR lists under "Deploy notes", then
re-run the failed run from the Actions page. Nothing else on the host needs undoing: the
preflight runs before the backup, the checkout and `IMAGE_TAG` ever move.

**Roll back to a known-good version manually.** `.last-good` holds the last release that came up
healthy:
```bash
cd /mnt/raid1/spotdl-web
cat .last-good                     # IMAGE_TAG=<tag> and COMMIT=<sha>
# No .last-good yet (before the first release-mode run after v33)? Pick the release instead:
#   COMMIT=$(git rev-list -n1 v<version>)   IMAGE_TAG=<version>   (no leading "v")
git fetch origin --tags
git checkout --detach --force <COMMIT from .last-good>
git reset --hard <COMMIT from .last-good>
sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=<IMAGE_TAG from .last-good>/" .env
# Before starting anything: is the database ahead of this image? (the guard is new in v33, so
# take it from main). Exit 3 = stop here and follow "The database is ahead" below.
git show origin/main:.github/scripts/migration_guard.sh > /tmp/migration_guard.sh
bash /tmp/migration_guard.sh "$PWD"
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel up -d --no-build --remove-orphans
bash .github/scripts/wait_for_stack_health.sh "$PWD" 420
```
Always move the commit and the tag **together**. Afterwards, if you recovered by hand onto a
*newer* healthy release than `.last-good` names, update it (`IMAGE_TAG=<tag>` and
`COMMIT=<sha>`), since only a release-mode run writes it. An old image under new compose files (or the
reverse) is exactly what broke the 2026-09-27 recovery.

**The database is ahead of the rollback image** (the migration guard refused, v33). The failed
deploy's `migrate` already upgraded the schema, so the old image's own `migrate` would refuse the
unknown revision and nothing would start. Alembic downgrades are never run automatically, by
design. You have two ways out:

1. **Roll forward (usually better):** fix the failure on a branch and deploy that. The schema
   stays where it is, so no data is lost. Use this whenever the migration itself was fine and
   something else broke.
2. **Restore the pre-deploy backup, then roll back.** The run log prints its path as
   `Pre-deploy pg_backup: /mnt/raid1/spotdl-web/backups/spotdl_web_<timestamp>.dump`. Anything
   written to the database after that dump is lost (downloads recorded since the deploy started),
   so prefer this only when the migration itself is the problem.
   Restore into an **emptied** schema, not with `pg_restore --clean` over the live one:
   `--clean` only drops what is *in* the dump, so the tables, enum types and indexes the failed
   migration created would survive, and the next roll-forward's `migrate` would fail on
   "already exists".
   ```bash
   cd /mnt/raid1/spotdl-web
   DUMP=/mnt/raid1/spotdl-web/backups/spotdl_web_<timestamp>.dump   # from the run log
   docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel down
   # DATABASE_URL is written for the containers: drop the +psycopg suffix, and the host reaches
   # the host-native Postgres as localhost, not host.docker.internal (same as pg_backup.sh).
   DB_URL="$(grep -E '^DATABASE_URL=' .env | tail -n1 | cut -d= -f2- \
     | sed -e 's/postgresql+psycopg:/postgresql:/' -e 's/host\.docker\.internal/localhost/')"
   pg_restore --list "$DUMP" | head    # sanity: the dump is readable, before anything is dropped
   psql "$DB_URL" -v ON_ERROR_STOP=1 -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public AUTHORIZATION CURRENT_USER;'
   pg_restore --no-owner --exit-on-error --dbname="$DB_URL" "$DUMP"
   ```
   The dump recreates the `pg_trgm` extension too. This runs as the role in `DATABASE_URL`,
   which owns the database. If `DROP SCHEMA` is refused anyway, run it as `postgres` but name
   the app role as the new schema's owner
   (`sudo -u postgres psql -d spotdlweb -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public AUTHORIZATION spotdlweb;'`),
   or the restore that follows fails with "permission denied for schema public".
   Then run "Roll back to a known-good version manually" above, using `.last-good`. Its
   `migrate` finds the schema at its own revision and no-ops.

   **If a `manual-*` dispatch ran a migration since `.last-good` was written**, the database was
   already ahead of `.last-good` *before* this deploy, so the pre-deploy backup is ahead too and
   restoring it doesn't help. Since v33.1 the pipeline handles this itself: it falls back to the
   version that was running before the deploy (the dispatch) when that knows the schema, and the
   message reads "back on `manual-<sha>`: the pre-deploy version". You only land here when that
   pre-deploy version is *also* behind the database, or couldn't be checked; the error says
   which. Then roll forward rather than restoring anything.

You can re-check the guard by hand before starting anything, with the checkout and `.env`
already on the rollback commit and tag. The guard is new in v33, so take it from `main` rather
than the checkout, which may predate it:
```bash
cd /mnt/raid1/spotdl-web
git show origin/main:.github/scripts/migration_guard.sh > /tmp/migration_guard.sh
bash /tmp/migration_guard.sh "$PWD"   # exit 0: safe to start; 3: the database is still ahead
```

**The very first automated deploy fails** (nothing recorded to roll back to; the workflow says so
explicitly and exits non-zero rather than guessing): fix the underlying cause and re-run the
workflow, or fall back to [Upgrading an existing deployment](#upgrading-an-existing-deployment-manual-fallback)
to bring the stack up manually while you investigate.

---

## Matrix alert bot (v33)

The pipeline posts to one Matrix room on this host's Synapse: a message for any failed or
cancelled Publish & Deploy or Release run, and one for every real (release-mode) deploy that
succeeded. v36's app alerts will reuse the same bot and room. This is a one-time setup, done by
the owner, since it touches the production Synapse. Until the three repository secrets exist,
the `notify` jobs print a warning and pass, so nothing breaks in the meantime.

The steps assume Synapse's client API is reachable at `https://<homeserver>` (the public URL your
Matrix clients use) and that you can run commands in the Synapse container. Adjust the container
name to match yours (`docker ps | grep -i synapse`).

1. **Create the bot user.** A plain non-admin account is enough. `register_new_matrix_user`
   ships with Synapse, and uses the `registration_shared_secret` from `homeserver.yaml`:
   ```bash
   docker exec -it <synapse-container> register_new_matrix_user \
     -c /data/homeserver.yaml --no-admin -u spotdl-bot http://localhost:8008
   # prompts for a password; store it in Vaultwarden
   ```
2. **Get the bot's access token** by logging in once. The token in the response is what the
   pipeline uses, so treat it like a password:
   ```bash
   read -rs BOT_PASSWORD   # the password from step 1, so it stays out of shell history
   # The body goes in on stdin (-d @-), so the password never appears in curl's argv, which
   # other users on this shared host could read via ps.
   # json.dumps escapes a password containing " or \ correctly.
   BOT_PASSWORD="$BOT_PASSWORD" python3 -c 'import json,os; print(json.dumps({"type":"m.login.password","identifier":{"type":"m.id.user","user":"spotdl-bot"},"password":os.environ["BOT_PASSWORD"],"initial_device_display_name":"spotdl-web pipeline"}))' \
     | curl -sS -X POST "https://<homeserver>/_matrix/client/v3/login" -H 'Content-Type: application/json' -d @-
   # -> {"user_id":"@spotdl-bot:<server>","access_token":"syt_...","device_id":"..."}
   ```
   Don't log the bot out afterwards: logging out revokes this token.
3. **Create the room** from your own account in Element: a new private room, for example
   "spotdl-web alerts", with **end-to-end encryption off**. The pipeline sends plain HTTP API
   messages and does no encryption, so it can't post legibly to an encrypted room. Then invite
   `@spotdl-bot:<server>`.
4. **Get the room id**: Element → room settings → **Advanced** → "Internal room ID", shaped like
   `!AbCdEf123:<server>`. Not the `#alias`.
5. **Join the room as the bot**, which accepts the invite:
   ```bash
   read -rs BOT_TOKEN   # the access_token from step 2
   # -H @file reads the header from a file, here a process substitution (printf is a builtin, so
   # the token never appears in any argv).
   curl -sS -X POST -H @<(printf 'Authorization: Bearer %s' "$BOT_TOKEN") \
     "https://<homeserver>/_matrix/client/v3/join/$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' '!AbCdEf123:<server>')"
   ```
6. **Add the three repository secrets**. `gh secret set` reads the value from stdin when you
   don't pass `--body`, so the token never lands in shell history:
   ```bash
   gh secret set MATRIX_HOMESERVER_URL --repo vb2007/spotdl-web   # https://<homeserver>, no trailing path
   gh secret set MATRIX_ACCESS_TOKEN   --repo vb2007/spotdl-web   # the access_token from step 2
   gh secret set MATRIX_ROOM_ID        --repo vb2007/spotdl-web   # the !room id from step 4
   ```
7. **Send a test message** with the same sender the workflows use:
   ```bash
   export MATRIX_HOMESERVER_URL=https://<homeserver> MATRIX_ROOM_ID='!AbCdEf123:<server>' MATRIX_TXN_ID="manual-$(date +%s)"
   read -rs MATRIX_ACCESS_TOKEN; export MATRIX_ACCESS_TOKEN
   echo "spotdl-web: Matrix alert test" | python3 .github/scripts/matrix_notify.py
   # -> matrix_notify: sent (HTTP 200), and the message appears in the room
   ```

To rotate the token, log in again (step 2), update `MATRIX_ACCESS_TOKEN` (step 6), then log the
old session out from Element's **Sessions** list. To turn alerts off, delete any one of the three
secrets.

---

## One-time host setup (already done on this host — kept for reference)

### 1. Install PostgreSQL (host-native — not a container)

Postgres is deliberately **not** dockerized; it runs directly on the Debian host and
containers reach it via `host.docker.internal` (wired in `docker-compose.yml`'s
`extra_hosts`).

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql
```

Debian 12's own repo ships PostgreSQL 15, but this host actually runs a newer major
version via the PGDG apt repo — **don't assume a version or hardcode a config path**:

```bash
psql --version
sudo -u postgres psql -c "SHOW config_file;"
sudo -u postgres psql -c "SHOW hba_file;"
```

### 2. Create the role and database

```bash
sudo -u postgres psql -c "CREATE ROLE spotdl_web WITH LOGIN PASSWORD 'changeme';"
sudo -u postgres psql -c "CREATE DATABASE spotdl_web OWNER spotdl_web;"
```

If you need to change the password later, use `\password <role>` inside an interactive
`psql` session rather than passing it on the command line — special characters (`!`,
etc., which this project's own real password contains) can't be mangled by shell quoting
or history expansion that way.

### 3. Let Docker containers reach Postgres

**Do not hardcode `172.17.0.1`** (the default bridge's gateway) — `docker compose up`
creates its own project-scoped bridge with a different subnet, and `host.docker.internal`
(via `extra_hosts: host-gateway`) is the address that actually resolves correctly
per-container regardless of which subnet Compose picked.

```bash
PGCONF=/etc/postgresql/18/main/postgresql.conf   # whatever `SHOW config_file` printed
sudo sed -i "s/^#\?listen_addresses\s*=.*/listen_addresses = '*'/" "$PGCONF"

PGHBA=/etc/postgresql/18/main/pg_hba.conf   # whatever `SHOW hba_file` printed
echo "host    spotdl_web    spotdl_web    172.16.0.0/12    scram-sha-256" | sudo tee -a "$PGHBA"
sudo systemctl restart postgresql
```

Postgres reads `pg_hba.conf` top-to-bottom, first match wins — if a broader rule already
exists above this one (this host also runs Matrix/Synapse, Vaultwarden, etc.), the
appended line is dead weight, harmless but worth checking with `sudo cat "$PGHBA"` if
something doesn't behave as expected.

### 4. Install Docker + the Compose plugin

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"   # newgrp docker, or log out/in
```

### 5. Clone the repo

```bash
# This host actually ended up at /mnt/raid1/spotdl-web (a RAID array, not /opt) --
# pick whatever real path makes sense for your host; /opt is only this doc's example.
sudo mkdir -p /mnt/raid1/spotdl-web
sudo chown "$USER" /mnt/raid1/spotdl-web
git clone https://github.com/vb2007/spotdl-web.git /mnt/raid1/spotdl-web
cd /mnt/raid1/spotdl-web
```

### 6. Configure `.env`

```bash
cp .env.example .env
```

Fill in `DATABASE_URL`, `REDIS_PASSWORD`/`REDIS_URL`, `SESSION_SECRET`, `ALLOWED_EMAILS`,
`ADMIN_EMAIL` (v17+ — must also appear in `ALLOWED_EMAILS`, or every backend container
crash-loops at boot), `FRONTEND_ORIGINS`, `DOWNLOADS_DIR`, `LIBRARY_DIR` (v28 — see the
"Upgrading" section's §3 for the chown step it needs too), and `CLOUDFLARE_TUNNEL_TOKEN` — see
the "Upgrading" section above for what each should be for this app's real values, and
`.env.example`'s own comments for anything not covered there.

> **Proxy list (v07+):** `worker-meta` bind-mounts `./proxies.txt` read-only. Create it
> (`cp proxies.txt.example proxies.txt`) before bringing the stack up, or Docker creates
> an empty *directory* there instead, breaking `sync_from_file()` on boot.

### 7. Bring up the stack

Same command as the "Upgrading" section's step 4 — see there.

---

## Adding a second (or third) user (v17+)

Every allowlisted person gets their own private queue and job history (`jobs.user_id`, enforced
end to end — see `CLAUDE.md`'s "Master v2 invariants"); adding one is a config change, not a
migration:

```bash
# On the host, edit .env's ALLOWED_EMAILS to add the new address (comma-separated), then:
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps api
```

Only `api` needs recreating — it's the sole service that reads `ALLOWED_EMAILS` at request time
(the login check); `worker-dl`/`worker-meta`/`beat` don't, so leaving them running avoids
interrupting an in-flight download. The new person's `users` row is created automatically on their
first successful login (`services.users.get_or_create_user`) — nothing to seed by hand. They are
never admin unless their address also matches `ADMIN_EMAIL`. Confirm with:

```bash
curl -sS -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"<new-address>","password":"<their-real-password>"}' -D - -o /dev/null
# expect: HTTP 200 and a Set-Cookie: SPOTDL_SESSION=... line
```

---

## Firewall / network notes

- `api` (`8000`) and `web` (`5173`→`80`) are published as `127.0.0.1:<port>:<port>` in
  `docker-compose.yml` — reachable only from processes on the host itself, never the LAN
  or the internet directly. This is deliberate: Cloudflare Tunnel is the only ingress,
  ever, including for ad hoc testing.
- To check the deployment from your own machine without SSHing in, use an SSH tunnel
  rather than opening the port:
  ```bash
  ssh -N -L 8000:localhost:8000 <you>@192.168.100.200
  # then, on your machine: curl http://localhost:8000/api/health
  ```
- Postgres (`5432`) should never be reachable from the LAN either — `pg_hba.conf`'s
  scoping to `172.16.0.0/12` is what actually rejects a LAN client. Defense in depth:
  ```bash
  sudo ufw allow OpenSSH
  sudo ufw default deny incoming
  sudo ufw enable
  ```
  Docker manipulates iptables directly for container traffic, so this doesn't need a
  separate allow rule for Docker→Postgres.

### IPv6 escalation rung (v29) — production rollout

v29 adds a direct-IPv6 rung to the download retry ladder (attempt 2, between direct-IPv4 and proxy —
see `CLAUDE.md`'s "Retry engine numbers"). The app-level code works on any host; it needs no daemon
change to *ship*. But it can't do anything useful on this host until the container network actually
has a routable IPv6 path.

**Status as of 2026-09-27: fully applied on this host.** Both halves are done — the owner enabled
daemon-level IPv6 (`/etc/docker/daemon.json`) and confirmed every other service on the shared daemon
stayed healthy afterward, and `docker-compose.prod.yml` now carries its own `enable_ipv6` block.
`worker-dl` was confirmed to actually receive a real `AF_INET6` address after both halves landed.
Left in place below as the record of what was actually done and verified, and as the rollback/
reference for anyone rebuilding this host from scratch.

**Prerequisite check, run during v29's session (2026-09-27) — record here, don't re-derive:**

- This host's public IPv6 is real and working: `curl -6 -m 5 https://www.youtube.com` returned `200`
  directly from the host (outside any container).
- `/etc/docker/daemon.json` does not exist on this host — Docker's containers are IPv4-only by
  default, exactly as `docker-compose.override.yml`'s own v29 comment describes for local dev.
- This Docker daemon (29.7.2) is shared with several other real services on this host: the Matrix
  homeserver stack (Synapse + several `mautrix-*` bridges + LiveKit + coturn + a router), Vaultwarden,
  and a few smaller apps (Arcane, SearXNG, tubearchivist, zuti-clicker). Enabling daemon-level IPv6
  requires a full `dockerd` restart, which recreates every container's NAT rules — this is real blast
  radius, not a local-only concern the way the compose-level `docker-compose.override.yml` change is.

**Deliberately deferred during v29's own session**: per the owner's own call, that session did
**not** touch `/etc/docker/daemon.json` or restart the daemon, and left `docker-compose.prod.yml`'s
own network block unwritten — both were explicitly left to the owner to apply on their own schedule.
The owner applied the daemon-level half directly afterward (below); the compose-level half was added
in a small follow-up PR once the owner asked for it, verified via `docker compose config` to have no
effect on any other compose project's network on this shared daemon before being applied.

**Rollout** (do this on the production host, not local dev — local dev's own IPv6 is
`docker-compose.override.yml`'s job, already in place):

```bash
# 1. Back up the current daemon config (it may not exist -- that's fine, `cp` just no-ops)
sudo cp /etc/docker/daemon.json /etc/docker/daemon.json.bak 2>/dev/null || true

# 2. Add (don't replace, if the file already has other keys) ip6tables support
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "ip6tables": true
}
EOF

# 3. Restart the daemon -- this recreates every container's network attachment.
#    Expect a brief (seconds) network blip for every running container, not downtime of
#    the containers themselves (they keep running, just re-attach).
sudo systemctl restart docker

# 4. Confirm every OTHER service on this host is still healthy before touching this app's
#    own stack -- Matrix (Element/any client), Vaultwarden (web vault), the others.
docker ps --format 'table {{.Names}}\t{{.Status}}'

# 5. Only then, bring this app's own stack up -- docker-compose.prod.yml already carries its
#    own enable_ipv6 + ipam.config block (same shape as docker-compose.override.yml's
#    dev-only version, never applies to each other), scoped to this project's own network
#    alone -- confirmed via `docker compose config` to have no effect on any other compose
#    project's network on this shared daemon (Matrix, Vaultwarden, etc. each get their own).
#    A full down/up (not just `up -d` again) is needed the first time this applies, since
#    changing a network's own config recreates it -- see this file's own IPv6 gotcha in
#    docs/GOTCHAS.md's v29 entry (a container `up -d` doesn't also recreate is left with
#    broken embedded-DNS service-name resolution).
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel down
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel up -d
```

**Rollback** (if any other service on this daemon misbehaves after the restart):

```bash
sudo mv /etc/docker/daemon.json.bak /etc/docker/daemon.json  # or: sudo rm /etc/docker/daemon.json
sudo systemctl restart docker
```

Removing the `networks:` block from `docker-compose.prod.yml` (once added) and re-running
`docker compose up -d` reverts this app's own containers to IPv4-only without needing the daemon
change reverted too, if the daemon-level change itself turns out safe but this app's own IPv6 usage
needs to be paused independently.

**Verify it worked**: `docker compose exec worker-dl python -c "import socket;
print(socket.getaddrinfo(socket.gethostname(), None))"` should list an `AF_INET6` address alongside
the existing `AF_INET` one (confirmed with this exact command against local dev after its own
compose-level change — see `docs/GOTCHAS.md`'s v29 entry).

---

## Backups

`scripts/pg_backup.sh` is a plain host script (Postgres isn't dockerized, so this isn't a
compose service). What it actually does, step by step:

1. Reads `DATABASE_URL` straight out of this repo's own `.env` via `grep`/`cut` (deliberately
   not `source`-ing the file — the real password contains shell-hostile characters like `!`),
   so backup credentials never drift out of sync with the real ones.
2. Strips SQLAlchemy's `+psycopg` driver suffix, since `pg_dump` doesn't understand it.
3. Runs `pg_dump -Fc --no-owner` — **custom format**, compressed and restorable with
   `pg_restore` (including `--clean` for a from-scratch overwrite), not a plain-SQL dump you'd
   have to pipe into `psql` by hand.
4. Writes to `$SPOTDL_WEB_BACKUP_DIR/spotdl_web_<UTC-timestamp>.dump` — default
   `<repo root>/backups` (derived from the script's own location, so it always lands next to
   whatever checkout is running it — on this host, `/mnt/raid1/spotdl-web/backups`). **v21
   correction:** this used to default to a hardcoded `/srv/spotdl-web/backups`, which never
   matched this host's real layout and, when that default was first exercised for real, silently
   created a fresh `/srv/spotdl-web` directory on the OS's root disk instead of the RAID array —
   found and fixed after the fact; see `docs/GOTCHAS.md`'s v21 section. Gitignored (`/backups/`)
   since it now lives inside the git-managed deploy checkout — critical, since the automated
   deploy's `git clean -fd` would otherwise delete it on every deploy.
5. Prunes any `.dump` file older than `SPOTDL_WEB_BACKUP_RETENTION_DAYS` (default 14) — a daily
   cron therefore keeps roughly the last 14 dumps.

v21's `publish-deploy.yml` also runs this script automatically before every real deploy, right
before `alembic upgrade head` can touch the schema — on top of the daily cron below, not instead
of it. Install the cron once via the line in [Ongoing maintenance](#ongoing-maintenance) above.

**Restore verification — do this at least once, don't just trust that the script "should"
work:**

```bash
# 1. Take a real dump (safe -- pg_dump is read-only against the real DB).
./scripts/pg_backup.sh

# 2. Spin up a throwaway scratch Postgres -- never restore over the real database to "test"
#    a restore.
docker run -d --name pg-restore-check -e POSTGRES_PASSWORD=test -e POSTGRES_DB=restorecheck postgres:18-alpine
until docker exec pg-restore-check pg_isready -U postgres | grep -q "accepting connections"; do sleep 2; done

# 3. Restore the most recent dump into it.
LATEST=$(ls -t /mnt/raid1/spotdl-web/backups/*.dump | head -1)
docker cp "$LATEST" pg-restore-check:/tmp/restore.dump
docker exec pg-restore-check pg_restore -U postgres -d restorecheck --no-owner --clean --if-exists /tmp/restore.dump

# 4. Confirm the schema and real row counts came back.
docker exec pg-restore-check psql -U postgres -d restorecheck -c "\dt"
docker exec pg-restore-check psql -U postgres -d restorecheck -c "
SELECT 'jobs' t, count(*) FROM jobs
UNION ALL SELECT 'tracks', count(*) FROM tracks
UNION ALL SELECT 'downloaded_tracks', count(*) FROM downloaded_tracks;"

# 5. Clean up the scratch container -- it was never meant to persist.
docker rm -f pg-restore-check
```
This exact sequence (against the real dev/shared database, not a fixture) was run once
during v12 development: all 7 tables reconstructed, row counts matched the real data
(73 jobs / 138 tracks / 87 downloaded_tracks at the time) exactly.

**Restoring for real** (not into a scratch container — this replaces the live database, so stop
the stack first):

```bash
cd /mnt/raid1/spotdl-web
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
LATEST=$(ls -t /mnt/raid1/spotdl-web/backups/*.dump | head -1)   # or a specific older dump
pg_restore --no-owner --clean --if-exists \
  --dbname="$(grep -E '^DATABASE_URL=' .env | cut -d= -f2- | sed 's/postgresql+psycopg:/postgresql:/')" \
  "$LATEST"
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel up -d --no-build
```

This is also the recovery path if a deploy's Alembic migration needs undoing — see
[Rollback / recovery](#rollback--recovery-v21-v33) above; migrations are never auto-downgraded.

---

## Restart-survival test

`docker compose down && up -d` must leave every in-flight track's `scheduled_at` and
`attempt_count` untouched for anything in `waiting` — but that property was never actually
at risk (a `waiting` track is a pure Postgres row; the v06 retry engine already tested
this at the unit level). The property that genuinely needed hardening in v12 is a track
**actively downloading** when the stack goes down, since that's a live process, not just a
DB row. Test that specifically:

```bash
# 1. Submit a real track and watch for it to enter `downloading` (via the UI, or:
docker compose exec api python -c "
from app.db import SessionLocal
from app.models import Track, TrackState
db = SessionLocal()
print([t.id for t in db.query(Track).filter(Track.state == TrackState.DOWNLOADING).all()])
"

# 2. While it's genuinely downloading, hard-kill worker-dl (SIGKILL, not the graceful
#    stop_grace_period path -- this is the actual failure mode being tested):
docker compose kill worker-dl
docker compose up -d worker-dl

# 3. Confirm the track does NOT stay stranded in `downloading` forever. It resolves one of
#    two ways: Celery's task_acks_late redelivers the same task once the broker's
#    visibility_timeout (3600s) elapses, OR beat's stale-track reclaim sweep resets it to
#    `waiting` once STALE_TRACK_AFTER_SECONDS elapses (1800s in production; temporarily
#    export a lower value in .env + `docker compose up -d beat` before this test if you
#    don't want to wait 30 minutes to observe it -- restore the real value afterward).
watch -n 5 'docker compose exec api python -c "
from app.db import SessionLocal
from app.models import Track
db = SessionLocal()
t = db.get(Track, \"<track-id-from-step-1>\")
print(t.state, t.attempt_count, t.scheduled_at)
"'
```

**Never run `docker compose down -v`** for this or any other check — `-v` destroys the
`redis-data` volume (the broker, including any unacked messages) and, pre-v12, the
`downloads` named volume. v12's production overlay already moved downloads to a host bind
mount specifically so this can't destroy real files, but the flag is still a one-keystroke
way to lose the Redis broker state.

To actually observe `docker compose ps` reporting a service `unhealthy` (rather than just
`restarting`, which is what killing a container's main process produces), you need a
*hung* process, not a killed one:
```bash
docker compose exec worker-dl kill -STOP 1   # freezes the main process without killing it
# wait ~2 healthcheck intervals (worker-dl's is 120s) -> `docker compose ps` shows unhealthy
docker compose exec worker-dl kill -CONT 1   # unfreeze
```

The literal full-host-reboot test from the original plan is **explicitly skipped** —
this is a shared production host running other live services (Matrix/Synapse,
Vaultwarden) that can't be rebooted just to verify this app's restart survival.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/api/health` reports `postgres` failing | `pg_hba.conf`/`listen_addresses` not picked up | `sudo systemctl restart postgresql`; `docker compose logs api` now emits structured JSON (v12) — `\| jq .` it before guessing further |
| Postgres reachable via `psql` from the host, but not from the container | Tested against a hardcoded IP (e.g. `172.17.0.1`) instead of this container's actual gateway | Use `host.docker.internal`; confirm with `docker compose exec api getent hosts host.docker.internal` |
| `/api/health` reports `redis` failing | `REDIS_URL` password doesn't match `REDIS_PASSWORD` | update both together in `.env` |
| `api`/`worker-dl`/`worker-meta` crash-loop with `PermissionError: [Errno 13] Permission denied: '/home/spotdl'` | Rebuilt the backend image without `--create-home` (v12's non-root user needs a real home directory — `import spotdl` creates a `~/.spotdl` cache dir at *import time*) | Confirm `backend/Dockerfile`'s `useradd` line has `--create-home`, not `--no-create-home`; rebuild |
| `worker-dl`/`worker-meta` permission-denied writing to `/downloads` | `DOWNLOADS_DIR` on the host isn't owned by uid/gid 1000 (or whatever `APP_UID`/`APP_GID` the image was built with) | `sudo chown -R 1000:1000 <DOWNLOADS_DIR>` |
| A library sort & move sweep (v28) fails every row with a permission error | `LIBRARY_DIR` isn't owned by uid/gid 1000 the same way `DOWNLOADS_DIR` needs to be | `sudo chown -R 1000:1000 <LIBRARY_DIR>` |
| `worker-dl`/`worker-meta` show permanently `unhealthy` right after a deploy | Healthcheck's `start_period` (90s) hasn't elapsed yet — a fresh `celery inspect ping` pays a real cold-import cost | Wait it out; only worth investigating past ~2 minutes |
| A healthcheck referencing `$HOSTNAME` never passes | Compose interpolates `$VAR` in the compose file itself before the container sees it — needs `$$HOSTNAME` (escaped) so the container's shell expands it instead | Check `docker-compose.yml`'s worker healthchecks use `$$HOSTNAME`, not `$HOSTNAME` |
| `GET /login` (or any non-`/` route) returns 404 through the tunnel | Stock nginx has no route for an extensionless path to a prerendered `.html` file | Confirm `frontend/nginx.conf`'s explicit `location = /login { try_files /login.html =404; }` block is actually in the built image (`docker compose exec web cat /etc/nginx/conf.d/default.conf`) |
| `docker compose` command not found | compose plugin missing | re-run the one-time setup's step 4 |
| Containers restart-looping | check `docker compose logs <service>` first — don't guess | |
| A host-level script (e.g. `scripts/pg_backup.sh`) misbehaves in a way its current source on GitHub doesn't explain, or `git status`/`git log` on the deploy checkout shows an unexpected commit relative to the running `IMAGE_TAG` | The on-disk checkout at `/mnt/raid1/spotdl-web` only moves when a deploy (automated or manual) explicitly checks out a ref — a `workflow_dispatch` test deploy or interrupted release can leave it detached on an old commit, or (found in v22) a **stale local tag** left over from pre-release testing that no longer matches the real GitHub tag of the same name, silently shadowing it | `git fetch origin --tags`; if it's rejected with "would clobber existing tag", the local tag is stale — `git tag -d v<X.Y.Z> && git fetch origin --tags` to get the real one back, then `git checkout --detach v<X.Y.Z>` matching the `IMAGE_TAG` currently in `.env`. This only touches the working tree (compose files, scripts) — it does not affect the already-running containers |
