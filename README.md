# spotdl-web
SpotDL web download tool that handles massive user queries, retries &amp; schedules on error, switches proxies automatically, and so on..

## Plan

This project is built one feature slice ("version") at a time. The roadmap and rationale live in
[`plan/00-master-plan.md`](plan/00-master-plan.md); implementation detail for each version is in
`plan/vNN-*.md`. Durable decisions, gotchas, and current state live in [`CLAUDE.md`](CLAUDE.md).

This project runs in two distinct environments — don't mix up their setup steps:

- **Local development** (day-to-day iteration, your own PC): [`docs/LOCAL_DEV.md`](docs/LOCAL_DEV.md)
  + `.env.dev.example`. Fast hot-reload loop; points at its own disposable database over the LAN.
- **Production deployment** (the Debian host, final target): [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
  + `.env.example`.

Postgres itself is never dockerized and never duplicated (see `CLAUDE.md`) — both environments
reach the same physical Postgres server, but each uses its own separate database so local work
can't affect what's deployed.

Cloudflare Tunnel is behind the `tunnel` compose profile in both — it stays off until a real
`CLOUDFLARE_TUNNEL_TOKEN` is configured (v12):

```bash
docker compose --profile tunnel up
```
