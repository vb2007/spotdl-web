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
// v67 (U8): each language's messages (`messages-<locale>.<hash>.js`, vite.config.ts) are left out
// too, so a visit downloads only its own language; the one a page loads is kept when it's fetched
// (below), so the installed app still opens offline in a language it holds.
const MESSAGES = /\/messages-[a-z]+\.[\w-]+\.js$/;
const IMMUTABLE = build.filter((path) => !path.endsWith('.woff') && !MESSAGES.test(path));
const LAZY = new Set(build.filter((path) => MESSAGES.test(path)));
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
			// v67 (U8): the languages the previous build's cache held, in this build's chunks: an
			// update while the app is open never fetches them (the page runs the old build), and
			// the installed app would then open offline with no messages at all.
			const held = new Set<string>();
			for (const key of await caches.keys()) {
				if (key === CACHE || !key.startsWith('shell-')) continue;
				for (const request of await (await caches.open(key)).keys()) {
					const locale = /\/messages-([a-z]+)\./.exec(new URL(request.url).pathname)?.[1];
					if (locale) held.add(locale);
				}
			}
			// Nothing held yet (the first update from a build before v67, whose cache had one
			// chunk for every language): the browser's language, as the page resolves it signed out.
			if (held.size === 0) {
				const languages = sw.navigator.languages ?? [sw.navigator.language];
				const locales = new Set(
					[...LAZY].map((path) => /\/messages-([a-z]+)\./.exec(path)?.[1] ?? '')
				);
				const browser = languages
					.map((tag) => tag.toLowerCase().split('-')[0])
					.find((primary) => locales.has(primary));
				held.add(browser ?? 'en');
			}
			await cache.addAll(
				[...LAZY].filter((path) => held.has(/\/messages-([a-z]+)\./.exec(path)?.[1] ?? ''))
			);
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
			// v67 (U8): on a first visit the page fetched its language before this worker took
			// over; keep whichever language the browser already holds (`only-if-cached` never goes
			// to the network), so the installed app opens offline in it.
			const cache = await caches.open(CACHE);
			for (const path of LAZY) {
				if (await cache.match(path)) continue;
				try {
					const held = await fetch(path, { cache: 'only-if-cached', mode: 'same-origin' });
					if (held.ok) await cache.put(path, held);
				} catch {
					// Not in the HTTP cache: a language this browser hasn't used.
				}
			}
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
	} else if (LAZY.has(url.pathname)) {
		// v67 (U8): a language's messages, kept once fetched (immutable: the name carries the hash).
		event.respondWith(
			(async () => {
				const cache = await caches.open(CACHE);
				const cached = await cache.match(url.pathname);
				if (cached) return cached;
				const answer = await fetch(request);
				// Keeping it is a bonus: a failed write (storage full) never fails the download.
				if (answer.ok) event.waitUntil(cache.put(url.pathname, answer.clone()).catch(() => {}));
				return answer;
			})()
		);
	}
});

// `/account` shows which build the worker serves (`version`), asked over a MessageChannel.
sw.addEventListener('message', (event) => {
	if (event.data?.type === 'version') event.ports[0]?.postMessage(version);
});

// v66: a job notification shown through this worker (Chrome on Android, where the page's own
// `new Notification` throws). A tap focuses an open app tab, the dashboard first, and asks it to
// focus the job's row (the page's own click does the same); with no tab open it opens the
// dashboard. Only notifications carrying a job id are handled.
sw.addEventListener('notificationclick', (event) => {
	const jobId: unknown = event.notification.data?.jobId;
	if (typeof jobId !== 'string') return;
	event.notification.close();
	event.waitUntil(
		(async () => {
			const tabs = await sw.clients.matchAll({ type: 'window', includeUncontrolled: true });
			const tab = tabs.find((client) => new URL(client.url).pathname === '/') ?? tabs[0];
			if (!tab) {
				await sw.clients.openWindow('/');
				return;
			}
			// The job first: the row is focused even where the tab's focus is refused.
			tab.postMessage({ type: 'job-notification-click', jobId });
			await tab.focus();
		})()
	);
});
