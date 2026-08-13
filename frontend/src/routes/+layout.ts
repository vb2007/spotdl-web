import { redirect } from '@sveltejs/kit';
import * as api from '$lib/api';
import { queue } from '$lib/stores/queue';
import type { LayoutLoad } from './$types';

// Adapter-static has no server to run a `+layout.server.ts` load against at request
// time — each of this project's routes (/, /login, /settings, /account) still gets its
// own prerendered shell (`prerender = true`), but the actual session check only makes
// sense in the browser against the live cookie, hence `ssr = false`.
export const ssr = false;
export const prerender = true;

export const load: LayoutLoad = async ({ url }) => {
	const onLoginPage = url.pathname === '/login';

	let session: api.SessionInfo | null;
	try {
		session = await api.me();
	} catch {
		session = null;
	}

	if (session === null && !onLoginPage) {
		// `queue` is a module-level singleton that survives this client-side redirect (no
		// hard reload) -- explicit onLogout isn't the only path here. A session can go
		// invalid for other reasons (expiry, revocation) and surface through this exact
		// `load()` re-running on the next in-app navigation, so this is the one chokepoint
		// that must clear it regardless of *why* the session is gone.
		queue.reset();
		redirect(302, '/login');
	}
	if (session !== null && onLoginPage) {
		redirect(302, '/');
	}

	return { session };
};
