// The background's network client against a fake fetch: the cookie → key fallback, what each
// answer of the app (v53's contract) maps to, and what is never sent at all.
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { checkKey, history, me, remember, submit } from '../background/api.js';
import { DEFAULT_ORIGIN, normalizeOrigin, originPattern } from '../shared/config.js';

const TRACK = 'https://open.spotify.com/track/0DiWol3AO6WpXZgp0goxAV';
const ALBUM = 'https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy';

function fakeStorage(initial = {}) {
	const data = { ...initial };
	return {
		data,
		local: {
			get: async (keys) => {
				const list = Array.isArray(keys) ? keys : [keys];
				return Object.fromEntries(list.filter((k) => k in data).map((k) => [k, data[k]]));
			},
			set: async (values) => Object.assign(data, values),
			remove: async (key) => delete data[key],
		},
	};
}

const json = (status, body, headers = {}) => new Response(JSON.stringify(body), { status, headers });

/** deps whose fetch answers from `answers` in turn, recording every call. */
function setup({ answers = [], stored = {}, granted = true } = {}) {
	const calls = [];
	const queue = [...answers];
	const deps = {
		version: '1.0.0',
		storage: fakeStorage(stored),
		permissions: {
			asked: [],
			contains: async (p) => {
				deps.permissions.asked.push(...p.origins);
				return granted;
			},
		},
		fetch: async (url, init) => {
			calls.push({ url, init });
			const next = queue.shift();
			if (next instanceof Error) throw next;
			return typeof next === 'function' ? next(url, init) : next;
		},
	};
	return { deps, calls };
}

const created = (hint = null) => json(201, { id: 'job-1', source_url: TRACK, source_type: 'track', hint });

describe('cookie first, then the key', () => {
	it('logged in: one request, with the cookie and the client header', async () => {
		const { deps, calls } = setup({ answers: [created()], stored: { appOrigin: 'http://127.0.0.1:5177' } });
		const result = await submit(deps, { url: TRACK });
		assert.equal(result.outcome, 'queued');
		assert.equal(result.via, 'cookie');
		assert.equal(calls.length, 1);
		assert.equal(calls[0].url, 'http://127.0.0.1:5177/api/jobs');
		assert.equal(calls[0].init.method, 'POST');
		assert.equal(calls[0].init.credentials, 'include');
		assert.equal(calls[0].init.headers['X-Spotdl-Client'], 'extension/1.0.0');
		assert.equal(calls[0].init.headers.Authorization, undefined);
		assert.deepEqual(JSON.parse(calls[0].init.body), { url: TRACK });
	});

	it('cookie refused, key saved: retried with Bearer and no cookie', async () => {
		const { deps, calls } = setup({
			answers: [json(401, { code: 'not_authenticated' }), created()],
			stored: { apiKey: 'sdw_abcdefgh_secret' },
		});
		const result = await submit(deps, { url: TRACK, cascade: 'album' });
		assert.equal(result.outcome, 'queued');
		assert.equal(result.via, 'key');
		assert.equal(calls.length, 2);
		assert.equal(calls[1].init.headers.Authorization, 'Bearer sdw_abcdefgh_secret');
		assert.equal(calls[1].init.credentials, 'omit');
		assert.equal(calls[1].init.headers['X-Spotdl-Client'], 'extension/1.0.0');
		assert.deepEqual(JSON.parse(calls[1].init.body), { url: TRACK, cascade: 'album' });
	});

	it('cookie refused, no key: login_required, no second request', async () => {
		const { deps, calls } = setup({ answers: [json(401, { code: 'not_authenticated' })] });
		const result = await submit(deps, { url: TRACK });
		assert.deepEqual(result, { outcome: 'error', code: 'login_required', origin: DEFAULT_ORIGIN });
		assert.equal(calls.length, 1);
	});

	it('the key refused too: key_invalid', async () => {
		const { deps } = setup({
			answers: [json(401, { code: 'not_authenticated' }), json(401, { code: 'api_key_invalid' })],
			stored: { apiKey: 'sdw_abcdefgh_revoked' },
		});
		assert.equal((await submit(deps, { url: TRACK })).code, 'key_invalid');
	});

	it('me answers who, and through what', async () => {
		const { deps, calls } = setup({
			answers: [json(401, { code: 'not_authenticated' }), json(200, { email: 'a@example.com', username: 'a', is_admin: true })],
			stored: { apiKey: 'sdw_abcdefgh_secret' },
		});
		const result = await me(deps);
		assert.deepEqual(result, {
			outcome: 'signed_in',
			via: 'key',
			origin: DEFAULT_ORIGIN,
			user: { email: 'a@example.com', username: 'a' },
		});
		assert.equal(calls[0].url, `${DEFAULT_ORIGIN}/api/auth/me`);
		assert.equal(calls[0].init.method, 'GET');
	});
});

describe('what the app answers', () => {
	const cases = [
		['201, no hint', created(), { outcome: 'queued' }],
		['201 in_library', created('in_library'), { outcome: 'in_library' }],
		['200 already_queued', json(200, { id: 'job-0', hint: 'already_queued' }), { outcome: 'already_queued' }],
		['422 url_not_spotify', json(422, { code: 'url_not_spotify', detail: '…' }), { outcome: 'error', code: 'url_not_spotify' }],
		['422 cascade_not_found', json(422, { code: 'cascade_not_found' }), { outcome: 'error', code: 'cascade_not_found' }],
		['503 cascade_unavailable', json(503, { code: 'cascade_unavailable' }), { outcome: 'error', code: 'cascade_unavailable' }],
		['503 queue_unavailable', json(503, { code: 'queue_unavailable' }), { outcome: 'error', code: 'queue_unavailable' }],
		['500 with no code', json(500, { detail: 'boom' }), { outcome: 'error', code: 'http_500' }],
		['an HTML page', new Response('<html>nginx</html>', { status: 404 }), { outcome: 'error', code: 'not_an_app' }],
		['another host’s HTML 401 (basic auth)', new Response('<h1>401 Authorization Required</h1>', { status: 401 }), { outcome: 'error', code: 'not_an_app' }],
		['a JSON 401 without the app’s codes', json(401, { error: 'unauthorized' }), { outcome: 'error', code: 'not_an_app' }],
		['the app’s own crash (Starlette’s plain-text 500)', new Response('Internal Server Error', { status: 500 }), { outcome: 'error', code: 'server_error' }],
		['nginx’s HTML 502 (the api down)', new Response('<html>502 Bad Gateway</html>', { status: 502 }), { outcome: 'error', code: 'unreachable' }],
		['Cloudflare’s 530 (the tunnel down)', new Response('<html>error 1033</html>', { status: 530 }), { outcome: 'error', code: 'unreachable' }],
	];
	for (const [name, answer, expected] of cases) {
		it(name, async () => {
			const { deps } = setup({ answers: [answer] });
			const result = await submit(deps, { url: TRACK });
			for (const [k, v] of Object.entries(expected)) assert.equal(result[k], v, k);
		});
	}

	it('429 rate_limited carries Retry-After', async () => {
		const { deps } = setup({ answers: [json(429, { code: 'rate_limited' }, { 'Retry-After': '17' })] });
		const result = await submit(deps, { url: TRACK });
		assert.equal(result.code, 'rate_limited');
		assert.equal(result.retryAfter, 17);
	});

	it('409 cascade_ambiguous hands back the candidates', async () => {
		const candidates = [
			{ name: 'A', url: 'https://open.spotify.com/artist/0TnOYISbd1XYRBk9myaseg' },
			{ name: 'B', url: 'https://open.spotify.com/artist/7iJrDbKM5fEkGdm5kpjFzS' },
		];
		const { deps } = setup({ answers: [json(409, { code: 'cascade_ambiguous', params: { candidates } })] });
		const result = await submit(deps, { url: TRACK, cascade: 'artist' });
		assert.equal(result.outcome, 'ambiguous');
		assert.deepEqual(result.candidates, candidates);
	});

	it('the app unreachable (network error): unreachable, with the origin', async () => {
		const { deps } = setup({ answers: [new TypeError('NetworkError when attempting to fetch resource.')] });
		assert.deepEqual(await submit(deps, { url: TRACK }), { outcome: 'error', code: 'unreachable', origin: DEFAULT_ORIGIN });
	});
});

describe('never sent', () => {
	for (const url of [
		'daft punk',
		'https://evil.example/track/0DiWol3AO6WpXZgp0goxAV',
		'spotify:track:0DiWol3AO6WpXZgp0goxAV',
		'https://open.spotify.com/show/4rOoJ6Egrf8K2IrywzwOMk',
		'https://open.spotify.com/track/0DiWol3AO6WpXZgp0goxAV?si=1',
		'https://open.spotify.com/intl-hu/track/0DiWol3AO6WpXZgp0goxAV',
		null,
	]) {
		it(`allowlist: ${url}`, async () => {
			const { deps, calls } = setup();
			assert.deepEqual(await submit(deps, { url }), { outcome: 'error', code: 'url_not_spotify' });
			assert.equal(calls.length, 0);
		});
	}

	it('a cascade the item has no way to take', async () => {
		for (const [url, cascade] of [
			[ALBUM, 'album'],
			['https://open.spotify.com/artist/0TnOYISbd1XYRBk9myaseg', 'artist'],
			[TRACK, 'label'],
		]) {
			const { deps, calls } = setup();
			assert.equal((await submit(deps, { url, cascade })).code, 'cascade_invalid');
			assert.equal(calls.length, 0);
		}
	});

	it('no host permission for the app: nothing sent, permission_missing', async () => {
		const { deps, calls } = setup({ granted: false, stored: { appOrigin: 'https://spotdl.example:8443' } });
		const result = await submit(deps, { url: TRACK });
		assert.equal(result.code, 'permission_missing');
		assert.equal(result.origin, 'https://spotdl.example:8443');
		assert.deepEqual(deps.permissions.asked, ['https://spotdl.example/*']);
		assert.equal(calls.length, 0);
	});
});

describe('settings', () => {
	it('normalizeOrigin: https anywhere, http only on loopback', () => {
		assert.equal(normalizeOrigin('spotdl.example.org'), 'https://spotdl.example.org');
		assert.equal(normalizeOrigin(' https://spotdl.example.org/some/path?q '), 'https://spotdl.example.org');
		assert.equal(normalizeOrigin('http://127.0.0.1:5177/'), 'http://127.0.0.1:5177');
		assert.equal(normalizeOrigin('http://localhost:5173'), 'http://localhost:5173');
		for (const bad of ['http://spotdl.example.org', 'ftp://x', 'https://user:pw@spotdl.example.org', '', '   ', 'http://[', null]) {
			assert.equal(normalizeOrigin(bad), null, String(bad));
		}
	});

	it('originPattern drops the port (a Firefox match pattern has none)', () => {
		assert.equal(originPattern('http://127.0.0.1:5177'), 'http://127.0.0.1/*');
		assert.equal(originPattern('https://spotdl.vb2007.hu'), 'https://spotdl.vb2007.hu/*');
	});

	it('a key saved for one app is never sent to another address', async () => {
		const { deps, calls } = setup({
			answers: [json(401, { code: 'not_authenticated' })],
			stored: { appOrigin: 'https://other.example', apiKey: 'sdw_abcdefgh_prodkey', apiKeyOrigin: DEFAULT_ORIGIN },
		});
		assert.equal((await submit(deps, { url: TRACK })).code, 'login_required');
		assert.equal(calls.length, 1);
		assert.equal(calls[0].init.headers.Authorization, undefined);
	});

	it('me can check an address before it is saved, without the saved key', async () => {
		const { deps, calls } = setup({
			answers: [json(401, { code: 'not_authenticated' })],
			stored: { apiKey: 'sdw_abcdefgh_prodkey', apiKeyOrigin: DEFAULT_ORIGIN },
		});
		const result = await me(deps, { origin: 'http://127.0.0.1:5177' });
		assert.equal(result.code, 'login_required');
		assert.equal(calls.length, 1);
		assert.equal(calls[0].url, 'http://127.0.0.1:5177/api/auth/me');
	});

	it('an IPv6 loopback address isn’t offered (no host permission covers it)', () => {
		assert.equal(normalizeOrigin('http://[::1]:5177'), null);
	});

	it('checkKey tries the key alone (no cookie) before it is saved', async () => {
		const ok = setup({ answers: [json(200, { email: 'a@example.com', username: 'a', is_admin: false })] });
		const result = await checkKey(ok.deps, 'sdw_abcdefgh_newkey');
		assert.equal(result.outcome, 'signed_in');
		assert.equal(result.via, 'key');
		assert.equal(ok.calls.length, 1);
		assert.equal(ok.calls[0].init.credentials, 'omit');
		assert.equal(ok.calls[0].init.headers.Authorization, 'Bearer sdw_abcdefgh_newkey');
		const refused = setup({ answers: [json(401, { code: 'api_key_invalid' })] });
		assert.equal((await checkKey(refused.deps, 'sdw_abcdefgh_revoked')).code, 'key_invalid');
		const down = setup({ answers: [new Response('<html>502 Bad Gateway</html>', { status: 502 })] });
		assert.equal((await checkKey(down.deps, 'sdw_abcdefgh_newkey')).code, 'unreachable');
		const malformed = setup();
		assert.equal((await checkKey(malformed.deps, 'not a key')).code, 'key_invalid');
		assert.equal(malformed.calls.length, 0);
	});

	it('a stored origin that isn’t valid falls back to the default', async () => {
		const { deps, calls } = setup({ answers: [created()], stored: { appOrigin: 'http://evil.example' } });
		await submit(deps, { url: TRACK });
		assert.equal(calls[0].url, `${DEFAULT_ORIGIN}/api/jobs`);
	});

	it('history keeps the newest 10', async () => {
		const storage = fakeStorage();
		for (let i = 0; i < 12; i++) await remember(storage, { url: `u${i}` });
		const list = await history(storage);
		assert.equal(list.length, 10);
		assert.equal(list[0].url, 'u11');
		assert.equal(list[9].url, 'u2');
	});
});
