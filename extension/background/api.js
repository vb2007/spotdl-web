// Every request the extension makes, and what each answer means. The only host it ever
// contacts is the configured app origin (docs/EXTENSION.md, "Privacy"), and the only thing it
// sends there is an item's canonical link and the cascade choice.
//
// Auth (master v5's locked decision, and v53's spike verdict that a background fetch carries
// the app's session cookie): the cookie first; on a 401, the API key if one is saved.
//
// Plain functions over injected `deps` ({fetch, storage, permissions, version}), so the
// tests run them against a fake fetch.
import { HISTORY_LIMIT, KEYS, originPattern, readSettings } from '../shared/config.js';

const ITEM_URL = /^https:\/\/open\.spotify\.com\/(track|album|artist|playlist)\/[A-Za-z0-9]{22}$/;
const CASCADES = { track: ['album', 'artist'], album: ['artist'], artist: [], playlist: [] };
const TIMEOUT_MS = 30000;

/** The answer for an error the extension decides on its own, before or instead of the app. */
const fail = (code, extra = {}) => ({ outcome: 'error', code, ...extra });

async function request(deps, settings, path, init, auth) {
	const headers = { ...init.headers, 'X-Spotdl-Client': `extension/${deps.version}` };
	if (auth === 'key') headers.Authorization = `Bearer ${settings.apiKey}`;
	let response;
	try {
		response = await deps.fetch(`${settings.origin}${path}`, {
			...init,
			headers,
			// The key attempt sends no cookie: the answer must be the key's own.
			credentials: auth === 'cookie' ? 'include' : 'omit',
			cache: 'no-store',
			redirect: 'error',
			signal: AbortSignal.timeout(TIMEOUT_MS),
		});
	} catch {
		return { network: true };
	}
	let body = null;
	try {
		body = await response.json();
	} catch {
		body = null;
	}
	return { status: response.status, headers: response.headers, body: body && typeof body === 'object' ? body : null };
}

/**
 * Sends one request the way the extension authenticates: the cookie, then (on a 401) the key.
 * Answers `{answer, via}`, or `{error}` with an extension-side code.
 */
async function authed(deps, path, init) {
	const settings = await readSettings(deps.storage);
	let granted = false;
	try {
		granted = await deps.permissions.contains({ origins: [originPattern(settings.origin)] });
	} catch {
		granted = false;
	}
	if (!granted) return { error: fail('permission_missing', { origin: settings.origin }) };

	let via = 'cookie';
	let answer = await request(deps, settings, path, init, 'cookie');
	if (!answer.network && answer.status === 401 && settings.apiKey) {
		via = 'key';
		answer = await request(deps, settings, path, init, 'key');
		if (!answer.network && answer.status === 401) return { error: fail('key_invalid', { origin: settings.origin }) };
	}
	if (answer.network) return { error: fail('unreachable', { origin: settings.origin }) };
	if (answer.status === 401) return { error: fail('login_required', { origin: settings.origin }) };
	if (answer.body === null) return { error: fail('not_an_app', { origin: settings.origin, status: answer.status }) };
	return { answer, via, origin: settings.origin };
}

/**
 * Queues one item. `url` must already be a canonical open.spotify.com item link (the content
 * script's selectors produce nothing else); anything else is refused here, never sent.
 */
export async function submit(deps, { url, cascade = null }) {
	const match = typeof url === 'string' ? ITEM_URL.exec(url) : null;
	if (!match) return fail('url_not_spotify');
	if (cascade !== null && !CASCADES[match[1]].includes(cascade)) return fail('cascade_invalid');

	const body = cascade ? { url, cascade } : { url };
	const sent = await authed(deps, '/api/jobs', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body),
	});
	if (sent.error) return sent.error;
	const { answer, via, origin } = sent;
	const data = answer.body;

	if ((answer.status === 200 || answer.status === 201) && typeof data.id === 'string') {
		const outcome =
			data.hint === 'already_queued' ? 'already_queued' : data.hint === 'in_library' ? 'in_library' : 'queued';
		return {
			outcome,
			via,
			origin,
			job: { id: data.id, sourceUrl: data.source_url, sourceType: data.source_type },
		};
	}
	if (answer.status === 409 && data.code === 'cascade_ambiguous') {
		const candidates = Array.isArray(data.params?.candidates) ? data.params.candidates : [];
		return {
			outcome: 'ambiguous',
			via,
			candidates: candidates
				.filter((c) => c && typeof c.name === 'string' && typeof c.url === 'string')
				.map((c) => ({ name: c.name, url: c.url })),
		};
	}
	if (answer.status === 429) {
		const retryAfter = Number.parseInt(answer.headers.get('Retry-After') ?? '', 10);
		return fail('rate_limited', { via, retryAfter: Number.isFinite(retryAfter) ? retryAfter : null });
	}
	return fail(typeof data.code === 'string' ? data.code : `http_${answer.status}`, { via, status: answer.status, origin });
}

/** Who the extension is signed in as (`GET /api/auth/me`), and through what. */
export async function me(deps) {
	const sent = await authed(deps, '/api/auth/me', { method: 'GET' });
	if (sent.error) return sent.error;
	const { answer, via, origin } = sent;
	if (answer.status === 200 && typeof answer.body.email === 'string') {
		return {
			outcome: 'signed_in',
			via,
			origin,
			user: { email: answer.body.email, username: answer.body.username ?? null },
		};
	}
	return fail(typeof answer.body.code === 'string' ? answer.body.code : `http_${answer.status}`, {
		origin,
		status: answer.status,
	});
}

/** The popup's list: the newest submissions first, at most HISTORY_LIMIT. */
export async function remember(storage, entry) {
	const stored = await storage.local.get(KEYS.submissions);
	const list = Array.isArray(stored[KEYS.submissions]) ? stored[KEYS.submissions] : [];
	const next = [entry, ...list].slice(0, HISTORY_LIMIT);
	await storage.local.set({ [KEYS.submissions]: next });
	return next;
}

export async function history(storage) {
	const stored = await storage.local.get(KEYS.submissions);
	return Array.isArray(stored[KEYS.submissions]) ? stored[KEYS.submissions] : [];
}
