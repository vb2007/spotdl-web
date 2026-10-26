// Settings shared by the background script, the options page and the popup.

export const DEFAULT_ORIGIN = 'https://spotdl.vb2007.hu';

// storage.local only: an API key is a secret, and nothing here is ever synced.
// A key is stored with the origin it was saved for, and goes nowhere else.
export const KEYS = { origin: 'appOrigin', apiKey: 'apiKey', apiKeyOrigin: 'apiKeyOrigin', submissions: 'submissions' };

export const HISTORY_LIMIT = 10;

const LOOPBACK = new Set(['localhost', '127.0.0.1']);

/**
 * The app origin typed into the options page, normalized (`https://host[:port]`), or `null`
 * when it can't be one. Plain HTTP is accepted only on loopback (a dev or agent stack): the
 * session cookie is `Secure`, and an API key must never cross a network in clear text.
 */
export function normalizeOrigin(input) {
	if (typeof input !== 'string') return null;
	let text = input.trim();
	if (text === '') return null;
	if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) text = `https://${text}`;
	let url;
	try {
		url = new URL(text);
	} catch {
		return null;
	}
	if (url.username || url.password) return null;
	if (url.protocol === 'https:') return url.origin;
	if (url.protocol === 'http:' && LOOPBACK.has(url.hostname)) return url.origin;
	return null;
}

/**
 * The host permission an origin needs. A Firefox match pattern has no port (docs/GOTCHAS.md
 * v53: `http://127.0.0.1:5176/*` is invalid, not merely ungranted), so a port-bearing origin
 * asks for its host on every port.
 */
export function originPattern(origin) {
	const url = new URL(origin);
	return `${url.protocol}//${url.hostname}/*`;
}

/** An API key's shape (v53: `sdw_<prefix>_<secret>`); the app is the judge of the rest. */
export function looksLikeApiKey(value) {
	return typeof value === 'string' && /^sdw_[A-Za-z0-9_-]{8,}$/.test(value.trim());
}

/**
 * The saved settings. `origin` overrides the saved address (the options page checking one
 * before saving it). The key comes back only for the origin it was saved for, so it's never
 * sent to an address typed later.
 */
export async function readSettings(storage, origin = null) {
	const stored = await storage.local.get([KEYS.origin, KEYS.apiKey, KEYS.apiKeyOrigin]);
	const target = origin ?? normalizeOrigin(stored[KEYS.origin] ?? '') ?? DEFAULT_ORIGIN;
	const key = typeof stored[KEYS.apiKey] === 'string' && stored[KEYS.apiKey] !== '' ? stored[KEYS.apiKey] : null;
	const keyOrigin = normalizeOrigin(stored[KEYS.apiKeyOrigin] ?? '') ?? DEFAULT_ORIGIN;
	return { origin: target, apiKey: key && keyOrigin === target ? key : null, storedKey: key, keyOrigin };
}
