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

## Rollback / recovery (v21)

The automated pipeline (`.github/workflows/publish-deploy.yml`) already rolls back on its own
when a fresh deploy fails its health gate — see `docs/RELEASE_PIPELINE.md` for exactly what that
covers (code/image rollback only, never an Alembic downgrade). This section is for recovering
**by hand**, when the workflow itself can't run or its own rollback didn't fully resolve things.

**Roll back to a known-good version manually:**
```bash
cd /mnt/raid1/spotdl-web
git fetch origin --tags
git checkout --detach v<previous-good-version>
sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=<previous-good-version>/" .env   # no leading "v"
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel up -d --no-build
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

**A migration itself needs undoing** (rare — Alembic downgrades are never run automatically, by
design): restore the pre-deploy `pg_dump` instead of attempting `alembic downgrade`, following
the [Backups](#backups) restore procedure below, but against the real database this time (stop
the stack first: `docker compose -f docker-compose.yml -f docker-compose.prod.yml down`, restore,
then bring it back up on the rolled-back code from the step above).

**The very first automated deploy fails** (no `PREV_TAG` to roll back to — the workflow will say
so explicitly and exit non-zero rather than guessing): fix the underlying cause and re-run the
workflow, or fall back to [Upgrading an existing deployment](#upgrading-an-existing-deployment-manual-fallback)
to bring the stack up manually while you investigate.

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
crash-loops at boot), `FRONTEND_ORIGINS`, `DOWNLOADS_DIR`, and `CLOUDFLARE_TUNNEL_TOKEN` — see
the "Upgrading" section above for what each should be for this app's real values, and
`.env.example`'s own comments for anything not covered there.

> **Proxy list (v07+):** `worker-meta` bind-mounts `./proxies.txt` read-only. Create it
> (`cp proxies.txt.example proxies.txt`) before bringing the stack up, or Docker creates
> an empty *directory* there instead, breaking `sync_from_file()` on boot.

### 7. Bring up the stack

Same command as the "Upgrading" section's step 4 — see there.

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
[Rollback / recovery](#rollback--recovery-v21) above; migrations are never auto-downgraded.

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
| `worker-dl`/`worker-meta` show permanently `unhealthy` right after a deploy | Healthcheck's `start_period` (90s) hasn't elapsed yet — a fresh `celery inspect ping` pays a real cold-import cost | Wait it out; only worth investigating past ~2 minutes |
| A healthcheck referencing `$HOSTNAME` never passes | Compose interpolates `$VAR` in the compose file itself before the container sees it — needs `$$HOSTNAME` (escaped) so the container's shell expands it instead | Check `docker-compose.yml`'s worker healthchecks use `$$HOSTNAME`, not `$HOSTNAME` |
| `GET /login` (or any non-`/` route) returns 404 through the tunnel | Stock nginx has no route for an extensionless path to a prerendered `.html` file | Confirm `frontend/nginx.conf`'s explicit `location = /login { try_files /login.html =404; }` block is actually in the built image (`docker compose exec web cat /etc/nginx/conf.d/default.conf`) |
| `docker compose` command not found | compose plugin missing | re-run the one-time setup's step 4 |
| Containers restart-looping | check `docker compose logs <service>` first — don't guess | |
