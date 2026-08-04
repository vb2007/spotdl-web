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
