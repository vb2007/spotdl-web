# Local development environment

This is the primary environment for day-to-day work: your own PC, Docker already installed,
fast iteration with hot reload. **The Debian production host (`docs/DEPLOYMENT.md`) is a
separate, final deployment target** — not where you debug a broken feature. Bouncing every
fix through a `git pull` + rebuild + SSH-log-check cycle on that box doesn't scale as a
develop loop; do that locally instead, and only touch the Debian host to verify a version is
genuinely ready to merge.

Postgres itself is never dockerized, never duplicated (locked decision) — both environments
reach the same physical instance on the Debian host over the network. **For now, both also
point at the same database.** There's no real user data yet to protect, so the extra ceremony
of a separate dev database isn't worth it while that's true. Revisit this (a dedicated,
disposable `spotdl_web_dev` database) once the app holds anything a developer testing locally
shouldn't be able to wipe out — realistically once v09 (frontend) or later makes it easy to
generate real-looking state. Redis and every other container still run entirely locally and
are never shared with the deployed instance, regardless.

---

## 1. Configure `.env`

```bash
cp .env.dev.example .env
```

Fill in the real Postgres password (same role/database the Debian host uses — see
`docs/DEPLOYMENT.md` for how that was created). Everything else in `.env.dev.example` is
already dev-appropriate out of the box — notably `LADDER_SECONDS` is pre-shortened to seconds
instead of hours, since testing the real retry ladder shouldn't take literal days.

## 2. Bring up the stack

Unlike the production host, you *want* `docker-compose.override.yml` here — it's what gives
you `uvicorn --reload` and `vite dev` with bind-mounted source, so edits show up without a
rebuild:

```bash
docker compose up
```

(No `-f docker-compose.yml` exclusion — that flag is specifically to *avoid* the override on
the production host. Here, the override is the point.)

## 3. Verify

```bash
curl -s http://localhost:8000/api/health
```

Ports bound to `127.0.0.1` is fine and expected here too — this is your own machine, nothing
about the Cloudflare-Tunnel-only ingress rule changes; it just happens to not matter locally
since nothing here is reachable from anywhere else regardless.

## 4. When a version is ready

Push the branch and open/update the PR as usual. Before merging, do one final check on the
real target per `docs/DEPLOYMENT.md` — that's the only remaining reason to touch the Debian
host mid-development, and it should be a confirmation, not a debugging session.

## Once there's real data worth protecting

Switch `DATABASE_URL` in the local `.env` to a dedicated `spotdl_web_dev` database (create it
with the same `CREATE ROLE`/`CREATE DATABASE` pattern as `docs/DEPLOYMENT.md` §2, on the Debian
host) so local runs stop touching the deployed instance's data. Everything else about this
workflow stays the same.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Every container fails at startup with `failed to add the host <=> sandbox pair interfaces: operation not supported` (or any other veth/bridge networking error) | A kernel update landed via the package manager but the machine hasn't rebooted into it yet — the running kernel's module directory (including `veth`) has already been deleted from disk in favor of the new one | Compare `uname -r` against the installed kernel package version (`pacman -Q linux` on Arch) and check `/lib/modules/$(uname -r)/` exists; if it doesn't, reboot |
| `web` fails with `Bind for 127.0.0.1:5173 failed: port is already allocated`, even though nothing else is using that port | `docker-compose.override.yml`'s `ports:` list *merges* with `docker-compose.yml`'s instead of replacing it (list-type keys merge by default across compose files — `command`/`build` don't, so this is easy to miss), so `web` ends up with two host bindings to the same address | Confirmed fixed for `web` via the `!override` merge tag on its `ports:` key — if you add a *new* port mapping to any service in the override, check `docker compose config` for duplicates rather than assuming a plain list will replace the base file's |
| Stack was working, comes back broken after `docker compose down && up` with no config changes | Check `docker compose config` for the resolved service definitions before assuming it's a code regression — compose-file merge behavior is a common source of surprises that look like app bugs | |
