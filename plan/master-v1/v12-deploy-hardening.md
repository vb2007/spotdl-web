# v12 — Deployment Hardening

Branch: `dev-deploy-hardening` → PR into `main`

## Scope

Turn the working stack into something that survives a real Debian 12 server reboot unattended for
weeks, exposed only via Cloudflare Tunnel.

## Tasks

1. **cloudflared config** — `cloudflared` container/config (`config.yml` + tunnel credentials
   mounted, not baked into the image) routing the public hostname to the `web` service and a
   sub-path or separate hostname to the `api` service (whichever split matches how the frontend
   calls the API — same-origin via a reverse path is simplest to keep cookies same-site). Document
   the `cloudflared tunnel create` / DNS route steps in `docs/deploy.md` since those are one-time
   manual steps on your account, not something Compose can automate.
2. **Production compose file** (`docker-compose.prod.yml` or profile) —
   `restart: unless-stopped` on every service, resource limits sane for a personal server, no bind
   mounts of source code (baked images only), explicit image tags (no floating `latest` in prod).
3. **Logging** — structured JSON logs from the API and both Celery workers (so `docker compose logs
   -f worker-dl` is greppable for track IDs and error types); log rotation via Docker's own
   `json-file` driver limits (`max-size`, `max-file`) so logs don't fill the disk over a multi-week
   run.
4. **Healthchecks** — Compose `healthcheck:` blocks for `api` (hits `/api/health`), `redis`
   (`redis-cli ping`), and both Celery workers (`celery inspect ping`), so `docker compose ps`
   surfaces a dead worker immediately instead of silently.
5. **Postgres backups** — since Postgres lives on the host, not in Compose: a simple `pg_dump` cron
   job on the host (documented, not containerized) writing timestamped dumps with a retention
   policy (e.g. keep last 14 daily). This is host-level, so it's a doc + a script the user installs
   themselves, not something `docker compose up` runs.
6. **Restart-survives-everything test**: with tracks genuinely mid-ladder-wait, `docker compose
   down && docker compose up -d` (and ideally an actual host reboot) must leave the queue exactly
   as it was — this is the durability property the whole app exists for, and it gets a dedicated,
   explicit test here rather than being assumed from v06's unit-level restart test.
7. `graphify update .`

## Files touched (new)

`docker-compose.prod.yml`, `cloudflared/config.yml` (template), `docs/deploy.md`,
`scripts/pg_backup.sh`, healthcheck additions to `docker-compose.yml`.

## Done when

- A full `docker compose down && up -d` cycle, and separately a host reboot, both leave every
  in-flight `waiting` track's `scheduled_at` and `attempt_count` untouched, and dispatch resumes
  correctly afterward.
- `docker compose ps` shows healthy/unhealthy accurately when a worker process is killed inside its
  container.
- The public Cloudflare Tunnel hostname serves the app correctly with no ports manually forwarded
  on the router/host firewall.
- A restored `pg_dump` backup on a scratch database reconstructs the full schema and data
  correctly.
