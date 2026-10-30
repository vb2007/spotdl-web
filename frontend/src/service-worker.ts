/// <reference types="@sveltejs/kit" />
/// <reference no-default-lib="true"/>
/// <reference lib="esnext" />
/// <reference lib="webworker" />

// v65: the installed app's service worker, kept minimal on purpose. It caches the static app
// shell (the build's files, `static/` and the prerendered pages) so the app installs and opens
// offline to its own "can't reach the server" screen, and nothing else:
// - `/api/` is never answered here, so live data, the stream and the session always go to the
//   network (and offline, the layout's `/me` fails and the page says so: never stale data);
// - a page is fetched from the network first, the cached shell only when that fails;
// - the cache is named after the build's `version`, so a new build is a new worker (nginx
//   serves this file `no-cache`): it takes over at once and drops the old build's cache.
import { build, files, prerendered, version } from '$service-worker';

const sw = self as unknown as ServiceWorkerGlobalScope;

const CACHE = `shell-${version}`;
// Content-hashed build files can come from the HTTP cache (they're immutable); the rest is
// asked for afresh. The legacy `.woff` fonts are left out: every browser this serves uses woff2.
const IMMUTABLE = build.filter((path) => !path.endsWith('.woff'));
const FRESH = [...files, ...prerendered];
// Under `vite dev` there is no build (`build` is empty) and `version` is fixed for the dev
// server's life: static files are left to the network there, so an edited one shows at once.
const ASSETS = new Set(build.length > 0 ? [...IMMUTABLE, ...files] : []);

sw.addEventListener('install', (event) => {
	event.waitUntil(
		(async () => {
			const cache = await caches.open(CACHE);
			// Pages and static files past the HTTP cache: one cached under the previous build must
			// not be stored as this one's.
			await cache.addAll([
				...IMMUTABLE,
				...FRESH.map((path) => new Request(path, { cache: 'reload' }))
			]);
			await sw.skipWaiting();
		})()
	);
});

sw.addEventListener('activate', (event) => {
	event.waitUntil(
		(async () => {
			for (const key of await caches.keys()) {
				if (key !== CACHE && key.startsWith('shell-')) await caches.delete(key);
			}
			await sw.clients.claim();
		})()
	);
});

sw.addEventListener('fetch', (event) => {
	const { request } = event;
	if (request.method !== 'GET') return;
	const url = new URL(request.url);
	if (url.origin !== sw.location.origin || url.pathname.startsWith('/api/')) return;

	if (request.mode === 'navigate') {
		const shell = async (answer?: Response) => {
			const cache = await caches.open(CACHE);
			// Every prerendered page is the same client-rendered shell; the root one stands in
			// for a path that has none (the client router finds no route for it).
			const page =
				(await cache.match(url.pathname, { ignoreSearch: true })) ?? (await cache.match('/'));
			return page ?? answer ?? Response.error();
		};
		event.respondWith(
			// A 5xx for a page is the front door saying the app is down (Cloudflare's 502 during
			// a deploy): the shell then shows the app's own "can't reach the server" screen.
			fetch(request).then(
				(answer) => (answer.status >= 500 ? shell(answer) : answer),
				() => shell()
			)
		);
		return;
	}

	if (ASSETS.has(url.pathname)) {
		event.respondWith(
			(async () => (await (await caches.open(CACHE)).match(url.pathname)) ?? fetch(request))()
		);
	}
});

// `/account` shows which build the worker serves (`version`), asked over a MessageChannel.
sw.addEventListener('message', (event) => {
	if (event.data?.type === 'version') event.ports[0]?.postMessage(version);
});
