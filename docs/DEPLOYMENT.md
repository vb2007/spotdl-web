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

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql
```

Debian 12's repo ships PostgreSQL 15 — config lives at `/etc/postgresql/15/main/`.

## 2. Create the role and database

Pick a real password and substitute it everywhere below (`changeme`). One-liners, run as the
`postgres` OS user:

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

Sanity check the role can authenticate and see its database:

```bash
psql "postgresql://spotdl_web:changeme@localhost:5432/spotdl_web" -c "SELECT current_user, current_database();"
```

## 3. Let Docker containers reach Postgres

By default Postgres only listens on `localhost` and only trusts local Unix-socket connections.
Containers connect over the Docker bridge, so both need widening — but only to that bridge, not
to the LAN.

Edit `/etc/postgresql/15/main/postgresql.conf`:

```bash
sudo sed -i "s/^#listen_addresses = .*/listen_addresses = 'localhost,172.17.0.1'/" /etc/postgresql/15/main/postgresql.conf
```

`172.17.0.1` is the default `docker0` bridge gateway. If you're unsure it matches your setup,
confirm with `ip -4 addr show docker0`.

Add a `pg_hba.conf` entry scoped to Docker's private address space (covers the default bridge and
any compose-created bridge network, all of which fall inside `172.16.0.0/12`):

```bash
echo "host    spotdl_web    spotdl_web    172.16.0.0/12    scram-sha-256" | sudo tee -a /etc/postgresql/15/main/pg_hba.conf
sudo systemctl restart postgresql
```

This scopes trust to exactly one role connecting to exactly one database — not `all`/`all` — so a
compromised container can't pivot to unrelated data.

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
- Postgres (`5432`) should never be reachable from the LAN either — `listen_addresses` above only
  binds `localhost` and the Docker bridge gateway, not the host's LAN interface, so this is
  already closed off at the Postgres level. If you run `ufw` or another host firewall, an explicit
  default-deny on `5432` is good defense in depth:
  ```bash
  sudo ufw allow OpenSSH
  sudo ufw default deny incoming
  sudo ufw enable
  ```
  (No separate allow rule is needed for Docker→Postgres traffic — that hits `postgresql.conf`'s
  bridge-gateway address, not a LAN-facing one.)

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/api/health` reports `postgres` failing | `pg_hba.conf`/`listen_addresses` not picked up | `sudo systemctl restart postgresql`, re-check step 3 |
| `/api/health` reports `redis` failing | `REDIS_URL` password doesn't match `REDIS_PASSWORD` | make sure both were updated together in `.env` |
| `docker compose` command not found | compose plugin missing | re-run step 4 |
| `api` container can't resolve `host.docker.internal` | old Docker Engine (< 20.10) | `docker --version`; upgrade via step 4 |
| Containers restart-looping | check `docker compose -f docker-compose.yml logs <service>` first — don't guess | |
