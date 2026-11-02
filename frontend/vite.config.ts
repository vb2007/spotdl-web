import { createHash } from 'node:crypto';
import { createReadStream, readFileSync } from 'node:fs';
import { stat } from 'node:fs/promises';
import path from 'node:path';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { paraglideVitePlugin } from '@inlang/paraglide-js';
import { defineConfig, type Plugin } from 'vite';

const DOWNLOADS_ROOT = '/downloads';
// v28: the sorted library root -- matches AppSettings's library_target_dir default and
// nginx.conf's own /internal-library/ alias target (docker-compose.override.yml mounts
// the real ./test-library here for local dev).
const LIBRARY_ROOT = '/mnt/raid1/media/music';

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

					// accelUri looks like "/internal-downloads/<percent-encoded relative path>" or
					// (v28, a track already moved into the sorted library) "/internal-library/...".
					// Same two prefixes nginx's own `internal` locations (frontend/nginx.conf) alias
					// to DOWNLOADS_ROOT/LIBRARY_ROOT respectively.
					const root = accelUri.startsWith('/internal-library/') ? LIBRARY_ROOT : DOWNLOADS_ROOT;
					const prefix = accelUri.startsWith('/internal-library/')
						? '/internal-library/'
						: '/internal-downloads/';
					const relative = decodeURIComponent(accelUri.slice(prefix.length));
					const resolved = path.resolve(root, relative);
					if (resolved !== root && !resolved.startsWith(root + path.sep)) {
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
					// v35 (e): the frontend's HEAD probe gets the same status and headers
					// (the stat above already proved the file exists) without reading it.
					if (req.method === 'HEAD') {
						res.end();
						return;
					}
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

/** v46: the dev container keeps Paraglide's compiled messages in a volume of their own (v52: named)
 * (docker-compose.override.yml), and Vite's recursive watcher on the project doesn't cross into
 * a nested mount: a recompile landed on disk while the dev server kept serving the old module.
 * Watching the directory explicitly brings its changes back. Dev-only, like the plugin above. */
function watchCompiledMessages(): Plugin {
	return {
		name: 'watch-compiled-messages',
		configureServer(server) {
			server.watcher.add(path.resolve('src/lib/paraglide'));
		}
	};
}

/** v67 (U8): each language's messages in a chunk of its own, and only the page's language
 * downloaded. Paraglide's index (`messages/_index.js`) imports every language statically, so
 * both shipped in one chunk on every route. This plugin rewrites the index into thin dispatchers
 * over modules loaded on demand (`virtual:locale-messages`, which `lib/i18n/locale.svelte.ts`
 * awaits before a language is shown), and names each language's chunk
 * `messages-<locale>.<hash>.js` so the service worker can leave them out of its precache (it
 * keeps the one the page loads). Paraglide is pinned (package.json): the rewrite reads its index's
 * `export const <key> =` lines and fails the build if it finds none. vitest keeps Paraglide's
 * own index, every language loaded. */
const MESSAGE_LOCALES = ['en', 'hu'] as const;
const LOCALE_MESSAGES = 'virtual:locale-messages';

function paraglideLocaleSplit(): Plugin {
	const dir = path.resolve('src/lib/paraglide/messages');
	const index = path.join(dir, '_index.js');
	const testing = Boolean(process.env.VITEST);
	let clientBuild = false;
	return {
		name: 'paraglide-locale-split',
		configResolved(config) {
			clientBuild = config.command === 'build' && !config.build.ssr;
		},
		buildStart() {
			if (!clientBuild) return;
			// SvelteKit names chunks by hash alone; an emitted chunk keeps the name given here, so
			// the name must change whenever the chunk can: nginx serves `_app/immutable` for a
			// year. Its content depends on more than the message file (the toolchain, and the
			// content-hashed shared chunk it imports, which other code can change), so the hash
			// covers the message file and this build: a deploy is a new file (~20 KB once), never
			// a stale one importing a chunk the deploy removed.
			const build = String(Date.now());
			for (const locale of MESSAGE_LOCALES) {
				const hash = createHash('sha256')
					.update(readFileSync(path.resolve(`messages/${locale}.json`)))
					.update(build)
					.digest('base64url')
					.slice(0, 10);
				this.emitFile({
					type: 'chunk',
					id: path.join(dir, `${locale}.js`),
					fileName: `_app/immutable/chunks/messages-${locale}.${hash}.js`
				});
			}
		},
		resolveId(id) {
			return id === LOCALE_MESSAGES ? `\0${LOCALE_MESSAGES}` : undefined;
		},
		load(id) {
			if (id !== `\0${LOCALE_MESSAGES}`) return;
			if (testing)
				return 'export async function loadLocaleMessages() {}\nexport const hasLocaleMessages = () => true;';
			return `export { __loadLocaleMessages as loadLocaleMessages, __hasLocaleMessages as hasLocaleMessages } from ${JSON.stringify(index)};`;
		},
		transform(code, id) {
			if (testing || id !== index) return;
			const keys = [...code.matchAll(/^export const (\w+) = /gm)].map((match) => match[1]);
			const exports = code.match(/^export /gm)?.length ?? 0;
			// Every export must be a message this rewrite keeps: another form (an aliased key, a
			// re-export) would silently vanish from `m`.
			if (keys.length === 0 || exports !== keys.length)
				this.error(
					`paraglide-locale-split: ${keys.length} messages but ${exports} exports in ${id}`
				);
			const [base, ...others] = MESSAGE_LOCALES;
			return [
				'import { getLocale, experimentalStaticLocale } from "../runtime.js";',
				`const __loaded = {};`,
				// The asked-for language, else the base one, else whichever is loaded: a message
				// read before its language arrived shows in another rather than throwing; with
				// nothing loaded at all (every language failed to download), its key.
				'const __msg = (key) => (inputs, options = {}) => {',
				'	const locale = experimentalStaticLocale ?? options.locale ?? getLocale();',
				`	const messages = __loaded[locale] ?? __loaded.${base} ?? ${others.map((l) => `__loaded.${l}`).join(' ?? ')};`,
				'	return messages ? messages[key](inputs) : key;',
				'};',
				...keys.map(
					(key) => `export const ${key} = /* @__PURE__ */ __msg(${JSON.stringify(key)});`
				),
				'const __loaders = {',
				...MESSAGE_LOCALES.map((l) => `	${l}: () => import("./${l}.js"),`),
				'};',
				'export async function __loadLocaleMessages(locale) {',
				'	__loaded[locale] ??= await __loaders[locale]();',
				'}',
				'export function __hasLocaleMessages(locale) {',
				'	return locale in __loaded;',
				'}'
			].join('\n');
		}
	};
}

export default defineConfig(({ command }) => ({
	plugins: [
		// v46: compiles messages/{en,hu}.json into typed message functions under
		// src/lib/paraglide (generated, gitignored). The locale is resolved by
		// src/lib/i18n/locale.svelte.ts, which overwrites the runtime's getLocale; the strategy
		// here is only what code outside the browser app (vitest, the e2e suite) falls back to.
		// `locale-modules`: one module per language. The default (one per message) made the
		// dev server answer ~650 module requests per page load, slow enough that a page loaded
		// in the e2e suite was still blank when the keyboard specs started on it.
		paraglideVitePlugin({
			project: './project.inlang',
			outdir: './src/lib/paraglide',
			strategy: ['globalVariable', 'baseLocale'],
			outputStructure: 'locale-modules',
			// Rewrite the files in place rather than emptying the directory first: a recreated
			// directory drops out of the dev server's watch (below), and it kept serving the old
			// messages (v52: removing it on the host also detaches the dev container's volume;
			// scripts/check-messages.mjs compiles in place too). With one module per language
			// every file is rewritten on each compile.
			cleanOutdir: false
		}),
		paraglideLocaleSplit(),
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			// v62 (F5): a SPA shell for paths no route prerenders, which nginx serves on a 404
			// (nginx.conf's error_page) so the app's own +error.svelte answers an unknown address.
			adapter: adapter({ fallback: '404.html' }),
			// v37: the Playwright suite isn't under src/, so the generated tsconfig (and with it
			// `npm run check`'s svelte-check) wouldn't see it otherwise.
			typescript: {
				config: (config) => {
					config.include.push('../e2e/**/*.ts', '../playwright.config.ts');
				}
			}
		}),
		...(command === 'serve' ? [devFileDownloadFallback(), watchCompiledMessages()] : [])
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
				changeOrigin: true,
				// v34.2: when `api` dies mid-response (a restart, a crash), the proxy never
				// ended the browser's side of a still-streaming response. For the SSE
				// stream that meant an EventSource that never errors, never reconnects and
				// never re-hydrates in the dev loop (production nginx does close it, which
				// is what api.createEventSource's reconnect logic relies on). Tear the
				// client response down whenever the upstream one closes without completing.
				configure: (proxy) => {
					proxy.on('proxyRes', (proxyRes, _req, res) => {
						proxyRes.on('close', () => {
							if (!proxyRes.complete && !res.destroyed) res.destroy();
						});
					});
				}
			}
		}
	}
}));
