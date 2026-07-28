# spotdl-web
SpotDL web download tool that handles massive user queries, retries &amp; schedules on error, switches proxies automatically, and so on..

## Plan

This project is built one feature slice ("version") at a time. The roadmap and rationale live in
[`plan/00-master-plan.md`](plan/00-master-plan.md); implementation detail for each version is in
`plan/vNN-*.md`. Durable decisions, gotchas, and current state live in [`CLAUDE.md`](CLAUDE.md).

## Running locally

Prerequisites:
- Docker + Docker Compose
- A PostgreSQL instance reachable from Docker containers (this stack does **not** run Postgres in
  a container — see `CLAUDE.md` for why). On the same host, `host.docker.internal` resolves to it
  automatically via `extra_hosts`.

```bash
cp .env.example .env   # fill in DATABASE_URL, SESSION_SECRET, ALLOWED_EMAILS, etc.
docker compose up
```

`docker-compose.override.yml` is applied automatically and adds hot-reload (bind-mounted source,
`uvicorn --reload`, `vite dev`). For a prod-like run without it:

```bash
docker compose -f docker-compose.yml up
```

Cloudflare Tunnel is behind the `tunnel` profile — it stays off until a real
`CLOUDFLARE_TUNNEL_TOKEN` is configured (v12):

```bash
docker compose --profile tunnel up
```

Check the stack is healthy:

```bash
curl http://localhost:8000/api/health
```
