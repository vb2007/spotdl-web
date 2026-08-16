import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import path from 'node:path';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, type Plugin } from 'vite';

const DOWNLOADS_ROOT = '/downloads';

// spotdl's actually-supported output formats (app/services/tagging.py's SUPPORTED_FORMATS,
// plus wav) -- close enough to nginx's own mime.types-driven guess for what this app ever
// actually serves; unknown extensions fall back to a generic binary type.
const EXTENSION_CONTENT_TYPES: Record<string, string> = {
	'.mp3': 'audio/mpeg',
	'.flac': 'audio/flac',
	'.ogg': 'audio/ogg',
	'.opus': 'audio/opus',
	'.m4a': 'audio/mp4',
	'.wav': 'audio/wav'
};

/** Vite's dev proxy (below) forwards `GET /api/tracks/{id}/file` straight to the real `api`
 * container, but a plain http-proxy has no idea what `X-Accel-Redirect` means -- only real
 * nginx (production, or `docker compose -f docker-compose.yml up`) understands it. Without
 * this, a download in the normal `docker compose up` dev loop "succeeds" with a correctly
 * -named, 0-byte file (docs/GOTCHAS.md's v27 entry -- caught by the frontend's own
 * `blob.size === 0` guard, not silently). This intercepts exactly that one route, makes its
 * own request to `api`, and -- if the response carries `X-Accel-Redirect` -- serves the real
 * file itself from the same `./downloads` bind mount worker-dl/worker-meta write into
 * (docker-compose.override.yml's `web` volumes), instead of relying on nginx to do it.
 * Dev-only: only registered under `vite dev`, never `vite build` (see below), so this adds
 * nothing to the production bundle or its runtime behavior. */
function devFileDownloadFallback(): Plugin {
	return {
		name: 'dev-file-download-fallback',
		configureServer(server) {
			server.middlewares.use(async (req, res, next) => {
				if (!req.url || !/^\/api\/tracks\/[^/]+\/file(?:\?.*)?$/.test(req.url)) {
					next();
					return;
				}

				try {
					const upstream = await fetch(`http://api:8000${req.url}`, {
						method: req.method,
						headers: req.headers.cookie ? { cookie: req.headers.cookie } : undefined
					});
					const accelUri = upstream.headers.get('x-accel-redirect');

					if (!accelUri) {
						// Not the 200-plus-X-Accel-Redirect shape (a 401/404/etc error) -- forward
						// the real status/body as-is rather than trying to replicate every header.
						res.statusCode = upstream.status;
						res.setHeader(
							'Content-Type',
							upstream.headers.get('content-type') ?? 'application/json'
						);
						res.end(Buffer.from(await upstream.arrayBuffer()));
						return;
					}

					// accelUri looks like "/internal-downloads/<percent-encoded relative path>" --
					// same prefix nginx's own `internal` location (frontend/nginx.conf) aliases to
					// DOWNLOADS_ROOT.
					const relative = decodeURIComponent(accelUri.replace(/^\/internal-downloads\//, ''));
					const resolved = path.resolve(DOWNLOADS_ROOT, relative);
					if (resolved !== DOWNLOADS_ROOT && !resolved.startsWith(DOWNLOADS_ROOT + path.sep)) {
						// FastAPI already guards this server-side; this is a defensive second
						// check on a value that's otherwise trusted (it came from our own backend,
						// not directly from the request), not a real expected path.
						res.statusCode = 404;
						res.end();
						return;
					}

					const stats = await stat(resolved);
					const disposition = upstream.headers.get('content-disposition');
					res.statusCode = 200;
					if (disposition) res.setHeader('Content-Disposition', disposition);
					res.setHeader(
						'Content-Type',
						EXTENSION_CONTENT_TYPES[path.extname(resolved).toLowerCase()] ??
							'application/octet-stream'
					);
					res.setHeader('Content-Length', String(stats.size));
					createReadStream(resolved).pipe(res);
				} catch (err) {
					if (err && typeof err === 'object' && 'code' in err && err.code === 'ENOENT') {
						res.statusCode = 404;
						res.end();
						return;
					}
					next(err);
				}
			});
		}
	};
}

export default defineConfig(({ command }) => ({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			adapter: adapter()
		}),
		...(command === 'serve' ? [devFileDownloadFallback()] : [])
	],
	server: {
		proxy: {
			// v12: same-origin dev, mirroring production's nginx /api/ proxy
			// (frontend/nginx.conf) — see src/lib/api.ts's resolveApiBase for why. `api` is
			// the compose service name, resolvable because this dev server runs inside the
			// `web` container on the compose network (docker-compose.override.yml), not
			// directly on the host.
			'/api': {
				target: 'http://api:8000',
				changeOrigin: true
			}
		}
	}
}));
