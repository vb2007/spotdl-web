# Local development environment

This is the primary environment for day-to-day work: your own PC, Docker already installed,
fast iteration with hot reload. **The Debian production host (`docs/DEPLOYMENT.md`) is a
separate, final deployment target** — not where you debug a broken feature. Bouncing every
fix through a `git pull` + rebuild + SSH-log-check cycle on that box doesn't scale as a
develop loop; do that locally instead, and only touch the Debian host to verify a version is
genuinely ready to merge.

The one thing the two environments share is the physical Postgres server (locked decision:
Postgres is never dockerized, never duplicated). They do **not** share a database — local dev
points at its own, disposable database on that same server, so nothing you do locally can
corrupt or interfere with whatever's deployed. Redis and every other container run entirely
locally and aren't shared with the deployed instance at all.

---

## 1. One-time: create the dev database on the Debian host

You've already got LAN connectivity from this PC to Postgres on the Debian host sorted out.
What's still needed is a database dedicated to local dev, separate from whatever's deployed —
so treat this one as fully disposable: drop and recreate it whenever it's easier than trying
to reconcile it with a schema change.

On the Debian host:

```bash
sudo -u postgres psql -c "CREATE ROLE spotdl_web_dev WITH LOGIN PASSWORD 'changeme';"
sudo -u postgres psql -c "CREATE DATABASE spotdl_web_dev OWNER spotdl_web_dev;"
```

If `pg_hba.conf` doesn't already have a line covering this PC's address for this specific
database (existing entries are matched per-database, so a new database name needs its own
line even if the network path is already open), add one scoped to *this machine* specifically
— tighter than opening the whole LAN, since this database will end up with debug data,
shortened retry timers, and whatever else a dev loop produces:

```bash
# find this PC's LAN IP first (run ON THIS PC, not the Debian host): hostname -I
echo "host    spotdl_web_dev    spotdl_web_dev    <this-pc-ip>/32    scram-sha-256" | sudo tee -a "$PGHBA"
sudo systemctl restart postgresql
```

(`$PGHBA` — see `docs/DEPLOYMENT.md` step 1 for how to find the real path; don't assume a
version or hardcode one.)

## 2. Configure `.env`

On your PC, in the repo:

```bash
cp .env.dev.example .env
```

Fill in the real password from step 1. Everything else in `.env.dev.example` is already
dev-appropriate out of the box — notably `LADDER_SECONDS` is pre-shortened to seconds instead
of hours, since testing the real retry ladder shouldn't take literal days.

## 3. Bring up the stack

Unlike the production host, you *want* `docker-compose.override.yml` here — it's what gives
you `uvicorn --reload` and `vite dev` with bind-mounted source, so edits show up without a
rebuild:

```bash
docker compose up
```

(No `-f docker-compose.yml` exclusion — that flag is specifically to *avoid* the override on
the production host. Here, the override is the point.)

## 4. Verify

```bash
curl -s http://localhost:8000/api/health
```

Ports bound to `127.0.0.1` is fine and expected here too — this is your own machine, nothing
about the Cloudflare-Tunnel-only ingress rule changes; it just happens to not matter locally
since nothing here is reachable from anywhere else regardless.

## 5. When a version is ready

Push the branch and open/update the PR as usual. Before merging, do one final check on the
real target per `docs/DEPLOYMENT.md` — that's the only remaining reason to touch the Debian
host mid-development, and it should be a confirmation, not a debugging session.

## Resetting the dev database

Since it's disposable by design, don't be precious about it:

```bash
# on the Debian host
sudo -u postgres psql -c "DROP DATABASE spotdl_web_dev;"
sudo -u postgres psql -c "CREATE DATABASE spotdl_web_dev OWNER spotdl_web_dev;"
```

Then re-run migrations locally: `docker compose exec api alembic upgrade head`.
