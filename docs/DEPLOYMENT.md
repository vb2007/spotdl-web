# Deploying spotdl-web (v01 — scaffold) to the Debian 12 host

Target host: **192.168.100.200** (Debian 12 "bookworm"), reachable on the local network.
This covers the v01 scaffold only: the stack comes up and `/api/health` reports Postgres +
Redis reachable. There is no real feature (auth, downloading, etc.) yet — that starts at v03.

Ports are intentionally **not** exposed beyond the host's loopback interface (see
[Firewall / network notes](#firewall--network-notes)) — this matches the locked decision that
Cloudflare Tunnel is the only ingress, ever, even during early testing. Verification therefore
happens over SSH, not by curling the LAN IP directly.

Run every command below on the target host (`ssh <you>@192.168.100.200`), as a user with `sudo`.

---

## 1. Install PostgreSQL (host-native — not a container)

Postgres is deliberately **not** dockerized; it runs directly on the Debian host and containers
reach it via `host.docker.internal` (wired in `docker-compose.yml`'s `extra_hosts`).

If this host already runs Postgres for other services (a shared instance is common — e.g.
alongside Matrix/Synapse, Vaultwarden, etc.), skip straight to step 2 and reuse it; spotdl-web just
needs its own role and database on it, not a dedicated instance.

Otherwise, install it:

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql
```

Debian 12's own repo ships PostgreSQL 15, but a host may well be running a newer major version via
the PGDG apt repo instead. **Don't assume a version or hardcode a config path** — confirm both
first:

```bash
psql --version
sudo -u postgres psql -c "SHOW config_file;"
sudo -u postgres psql -c "SHOW hba_file;"
```

Use whatever paths those report for `postgresql.conf`/`pg_hba.conf` in step 3 below, not
`/etc/postgresql/15/main/` — that's only correct if you're actually on 15.

## 2. Create the role and database

The names below (`spotdl_web`) are just this doc's placeholder — pick whatever role/database name
and password you like, but **use the exact same values everywhere**: the role name, database name,
and password you set here must match `DATABASE_URL` in `.env` (step 6) character-for-character,
including case and any special characters. One-liners, run as the `postgres` OS user:

```bash
sudo -u postgres psql -c "CREATE ROLE spotdl_web WITH LOGIN PASSWORD 'changeme';"
sudo -u postgres psql -c "CREATE DATABASE spotdl_web OWNER spotdl_web;"
```

Equivalent interactively, if you'd rather see it happen inside a `psql` session:

```bash
sudo -u postgres psql
```
```sql
CREATE ROLE spotdl_web WITH LOGIN PASSWORD 'changeme';
CREATE DATABASE spotdl_web OWNER spotdl_web;
\q
```

If you need to change the password later, use `\password <role>` inside an interactive `psql`
session rather than passing it on the command line — it prompts for the value directly, so special
characters (`!`, `,`, etc.) can't be mangled by shell quoting or history expansion.

Sanity check the role can authenticate and see its database:

```bash
psql "postgresql://spotdl_web:changeme@localhost:5432/spotdl_web" -c "SELECT current_user, current_database();"
```

## 3. Let Docker containers reach Postgres

By default Postgres only listens on `localhost` and only trusts local Unix-socket connections.
Containers connect over the Docker bridge, so both need widening — but only to that bridge, not
to the LAN. (If Postgres is shared with other services that already widened this, just add the
`pg_hba.conf` line below for spotdl-web's own role/database — don't touch `listen_addresses` again.)

**Do not hardcode `172.17.0.1`.** That's the gateway of Docker's *default* bridge network — but
`docker compose up` creates its own project-scoped bridge network (e.g. `spotdl-web_default`) with
a different subnet (Compose picks the next free one, often `172.18.0.0/16` or higher), and Docker
isolates bridge networks from each other by default. A connection to `172.17.0.1` from the host
itself will succeed (the host has a direct interface there), which is a misleading test — the same
address is very likely *unreachable from inside the containers* on Compose's own network. This is
exactly why `docker-compose.yml` uses `extra_hosts: host.docker.internal:host-gateway`: that magic
value always resolves, per-container, to *that container's own network's* gateway, whatever subnet
Compose actually picked.

So bind Postgres broadly and let `pg_hba.conf` (next step) do the real access control, rather than
chasing the exact subnet Compose happened to choose. Using the config path from step 1
(`$PGCONF` below — substitute what `SHOW config_file` actually printed):

```bash
PGCONF=/etc/postgresql/18/main/postgresql.conf   # whatever `SHOW config_file` printed
sudo sed -i "s/^#\?listen_addresses\s*=.*/listen_addresses = '*'/" "$PGCONF"
grep listen_addresses "$PGCONF"   # confirm it actually took — see note below if not
```

If that `grep` doesn't show `listen_addresses = '*'`, the file already had an uncommented,
non-default value the pattern didn't match (common on a host already tuned for other services) —
open the file and edit that line by hand instead.

This is safe here specifically because `pg_hba.conf` below scopes trust to one role talking to one
database from Docker's private address range only — an unauthenticated LAN client still gets
rejected at the `pg_hba` stage, `listen_addresses` only controls which interface the socket accepts
connections on before that check runs.

Add a `pg_hba.conf` entry scoped to Docker's private address space (covers the default bridge and
any compose-created bridge network, all of which fall inside `172.16.0.0/12`). Use the `hba_file`
path from step 1's `SHOW hba_file`:

```bash
PGHBA=/etc/postgresql/18/main/pg_hba.conf   # whatever `SHOW hba_file` printed
echo "host    spotdl_web    spotdl_web    172.16.0.0/12    scram-sha-256" | sudo tee -a "$PGHBA"
sudo systemctl restart postgresql
```

This scopes trust to exactly one role connecting to exactly one database — not `all`/`all` — so a
compromised container can't pivot to unrelated data. Postgres reads `pg_hba.conf` top-to-bottom and
uses the *first* matching line, so if this instance already has a broader rule above (e.g. an
existing `all`/`all` line for the same address range from another service), that earlier line wins
and this appended one is dead weight — harmless, but worth checking with
`sudo cat "$PGHBA"` if something still doesn't behave as expected.

## 4. Install Docker + the Compose plugin

Debian's own `docker.io` package is often stale and lacks the `compose` plugin. Use Docker's apt
repo instead:

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
```

Let your deploy user run `docker` without `sudo`:

```bash
sudo usermod -aG docker "$USER"
newgrp docker   # or log out/in
```

Verify:

```bash
docker compose version
```

## 5. Clone the repo

```bash
sudo mkdir -p /opt/spotdl-web
sudo chown "$USER" /opt/spotdl-web
git clone https://github.com/vb2007/spotdl-web.git /opt/spotdl-web
cd /opt/spotdl-web
git checkout dev-scaffold   # switch to `main` once PR #2 is merged
```

## 6. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

| Key | Value |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://spotdl_web:changeme@host.docker.internal:5432/spotdl_web` |
| `REDIS_PASSWORD` | a fresh random value (`openssl rand -hex 24`) |
| `REDIS_URL` | `redis://:<same REDIS_PASSWORD>@redis:6379/0` |
| `SESSION_SECRET` | `openssl rand -hex 32` |
| `ALLOWED_EMAILS` | left as a placeholder for now — real values land in v03 |
| `DOWNLOAD_OUTPUT_DIR` | leave as `/downloads` (in-container path — see note below) |

Everything else can stay at its `.env.example` default for v01.

> **Downloads storage:** `docker-compose.yml` mounts `/downloads` inside `worker-dl` from a
> Docker-managed named volume, not a host path. That's fine for v01 (nothing downloads yet). Once
> v05 lands and you want the files directly browsable on the host filesystem, add a
> machine-local, **untracked** override (e.g. `docker-compose.local.yml`, not committed) that
> bind-mounts a real directory over the `downloads` volume, and run compose with
> `-f docker-compose.yml -f docker-compose.local.yml`.

> **Proxy list (v07+):** `worker-meta` bind-mounts `./proxies.txt` read-only. Create it
> (`cp proxies.txt.example proxies.txt`, then edit) before bringing the stack up — if the
> host file doesn't exist yet, Docker creates an empty *directory* there instead, which
> breaks `sync_from_file()` on boot. An empty/comment-only file is fine; rotation just has
> nothing to draw from and every attempt falls back to direct.

## 7. Bring up the stack

`docker-compose.override.yml` is dev-only (bind-mounted source, `uvicorn --reload`, `vite dev`) —
**do not** let it apply on this host. Always pass `-f docker-compose.yml` explicitly to exclude it:

```bash
docker compose -f docker-compose.yml up -d --build
```

This starts `redis`, `api`, `worker-dl`, `worker-meta`, `beat`, and `web`. `cloudflared` stays off
— it's behind the `tunnel` compose profile until v12 wires a real `CLOUDFLARE_TUNNEL_TOKEN`.

## 8. Verify

From the host itself (ports are bound to `127.0.0.1`, by design — see below):

```bash
docker compose -f docker-compose.yml ps
curl -s http://localhost:8000/api/health
```

Expect `{"status":"ok"}`. If it instead reports a failing dependency, check:

```bash
docker compose -f docker-compose.yml logs api
```

Confirm Alembic wiring works with zero revisions (matches the v01 "done when" criterion):

```bash
docker compose -f docker-compose.yml exec api alembic upgrade head
```

---

## Firewall / network notes

- `api` (`8000`) and `web` (`5173`→`80`) are published as `127.0.0.1:<port>:<port>` in
  `docker-compose.yml` — reachable only from processes on the host itself, **not** from
  `192.168.100.0/24` or the internet. This is deliberate: the locked ingress decision is
  Cloudflare Tunnel only, no port forwarding, ever — that applies just as much to ad hoc LAN
  testing as to production.
- To check the deployment from your own machine instead of SSHing in and running `curl` locally,
  use an SSH tunnel rather than opening the port:
  ```bash
  ssh -N -L 8000:localhost:8000 <you>@192.168.100.200
  # then, on your machine: curl http://localhost:8000/api/health
  ```
- Postgres (`5432`) should never be reachable from the LAN either. Because `listen_addresses` is
  `*` (step 3), the socket itself accepts connections on every interface, including the LAN one —
  `pg_hba.conf`'s scoping to `172.16.0.0/12` is what actually rejects a LAN client (the TCP
  handshake completes, then Postgres refuses the connection at the authentication stage). Still
  worth a firewall as defense in depth, since it's cheap and means unauthorized clients get
  dropped before they can even attempt to authenticate:
  ```bash
  sudo ufw allow OpenSSH
  sudo ufw default deny incoming
  sudo ufw enable
  ```
  Docker manipulates iptables directly for container traffic, so this doesn't need a separate
  allow rule for Docker→Postgres — `ufw`'s chain sits alongside, not in front of, Docker's own
  rules for that path.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/api/health` reports `postgres` failing | `pg_hba.conf`/`listen_addresses` not picked up | `sudo systemctl restart postgresql`, re-check step 3. `docker compose -f docker-compose.yml logs api` now logs the real exception (fixed in v01) — read it before guessing further. |
| Postgres reachable via `psql` from the host, but not from the container | Tested against a hardcoded IP (e.g. `172.17.0.1`) that isn't this container's actual gateway — Docker isolates bridge networks from each other, so a host-side test against the wrong bridge's gateway can "succeed" while the container still can't reach it | Use `host.docker.internal` in `DATABASE_URL`, not a hardcoded IP; confirm what it resolves to with `docker compose -f docker-compose.yml exec api getent hosts host.docker.internal` |
| `/api/health` reports `redis` failing | `REDIS_URL` password doesn't match `REDIS_PASSWORD` | make sure both were updated together in `.env` |
| `docker compose` command not found | compose plugin missing | re-run step 4 |
| `api` container can't resolve `host.docker.internal` | old Docker Engine (< 20.10) | `docker --version`; upgrade via step 4 |
| Containers restart-looping | check `docker compose -f docker-compose.yml logs <service>` first — don't guess | |
