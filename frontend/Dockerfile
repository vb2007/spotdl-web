# v52: the dev `web` image (docker-compose.override.yml, `target: dev`), never built for
# production (the last stage below is the default target). Only the dependencies: the source
# is bind-mounted. Everything runs as `node` (uid 1000, the usual first user on a Linux host),
# so whatever Vite writes into the bind mount is the developer's, not root's (D3).
# node_modules, src/lib/paraglide and .svelte-kit are owned by `node` here, so the volumes the
# override mounts over them start out owned by `node` too. The stamp records which lockfile
# node_modules was installed from: the dev command reinstalls when the bind-mounted
# package-lock.json no longer matches it (D4).
FROM node:22-alpine AS dev
WORKDIR /app
# As the build stage below: `$env/static/public` (src/lib/api.ts) needs it declared, and empty
# means same-origin. In the environment it also wins over a `frontend/.env` that names another
# origin, so the dev container never depends on that file.
ARG PUBLIC_API_BASE_URL=""
ENV PUBLIC_API_BASE_URL=$PUBLIC_API_BASE_URL
RUN chown node:node /app
USER node
COPY --chown=node:node package.json package-lock.json ./
COPY --chown=node:node scripts/lockfile-stamp.mjs scripts/
RUN npm ci \
	&& mkdir -p src/lib/paraglide .svelte-kit \
	&& node scripts/lockfile-stamp.mjs > node_modules/.package-lock.sha256

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

# Baked in at build time — SvelteKit's `$env/static/public` (src/lib/api.ts) is a literal
# string substitution done by the build, not something a running container can override.
# Defaults to "" (same-origin: the browser calls the API through this same container's
# nginx /api/ proxy, see nginx.conf) so a fresh clone can build this image with zero
# configuration — previously this depended on an untracked frontend/.env existing first.
ARG PUBLIC_API_BASE_URL=""
ENV PUBLIC_API_BASE_URL=$PUBLIC_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/build /usr/share/nginx/html
# Replaces the stock default.conf entirely (see nginx.conf's own header comment for why:
# same-origin /api/ proxy + the SPA-fallback fix for prerendered non-root routes).
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
