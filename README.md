# spotdl-web
SpotDL web download tool that handles massive user queries, retries &amp; schedules on error, switches proxies automatically, and so on..

## Plan

This project is built one feature slice ("version") at a time. Master v1 (v00–v13) is complete and
deployed; master v2 is in progress. The roadmap and rationale live in
[`plan/master-v2/00-master-plan.md`](plan/master-v2/00-master-plan.md); implementation detail for
each version is in `plan/master-v1/vNN-*.md` (historical) and `plan/master-v2/vNN-*.md` (current).
Durable decisions and current state live in [`CLAUDE.md`](CLAUDE.md); accumulated gotchas and war
stories live in [`docs/GOTCHAS.md`](docs/GOTCHAS.md).

This project runs in two distinct environments — don't mix up their setup steps:

- **Local development** (day-to-day iteration, your own PC): [`docs/LOCAL_DEV.md`](docs/LOCAL_DEV.md)
  + `.env.dev.example`. Fast hot-reload loop.
- **Production deployment** (the Debian host, final target): [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
  + `.env.example`.

Postgres itself is never dockerized and never duplicated (see `CLAUDE.md`) — both environments
reach the same physical Postgres server, and **currently the same database on it** too (revisit
once there's data worth protecting). Everything else about the local/production split stays the
same regardless.

Cloudflare Tunnel is behind the `tunnel` compose profile in both — it stays off until a real
`CLOUDFLARE_TUNNEL_TOKEN` is configured (v12):

```bash
docker compose --profile tunnel up
```
