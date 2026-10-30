// v65: where `/login?next=…` goes once signed in. A share opened signed out comes back to its
// own `/share?…` after the login, and nothing else: `next` is any same-origin path, never a
// link off the site (`//host`, `/\host`, `https://…`, `javascript:`), never `/login` itself.

// Any fixed origin: a path that resolves onto another one isn't a path of this site.
const BASE = 'https://app.invalid';

/** `raw` as a same-origin path (path, query, fragment), or null if it's anything else. */
export function safeNext(raw: string | null | undefined): string | null {
	if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) return null;
	// eslint-disable-next-line no-control-regex -- control characters are exactly what's refused
	if (/[\u0000-\u001f\u007f]/.test(raw)) return null;
	let parsed: URL;
	try {
		parsed = new URL(raw, BASE);
	} catch {
		return null;
	}
	if (parsed.origin !== BASE || parsed.pathname === '/login') return null;
	return parsed.pathname + parsed.search + parsed.hash;
}

/** The `/login` address that comes back to `path` (with its query) after signing in. */
export function loginFor(path: string): string {
	return `/login?next=${encodeURIComponent(path)}`;
}
