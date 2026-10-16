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

// v42: whose session the module-level `queue` store last served. A tab's identity can
// change without a logout in *this* tab (A logs out and C logs in in another tab, then
// this tab navigates), and the store would otherwise carry A's rows and filters into C's
// dashboard. `null` until the first session is seen.
let lastSessionEmail: string | null = null;

export const load: LayoutLoad = async ({ url }) => {
	const onLoginPage = url.pathname === '/login';

	let session: api.SessionInfo | null;
	// v42: only a 401 says the session is gone. A network error or a 5xx (api restarting)
	// says nothing about it, and this load also runs on a hover preload while `/` stays
	// mounted, so it must not wipe the store (which `/` now answers with a reload) over a
	// blip. A real navigation still goes to /login as before; if someone else then signs
	// in on this tab, the identity-change reset below clears the store.
	let sessionGone = false;
	try {
		session = await api.me();
	} catch (err) {
		session = null;
		sessionGone = err instanceof api.ApiError && err.status === 401;
	}

	if (session === null && !onLoginPage) {
		// `queue` is a module-level singleton that survives this client-side redirect (no
		// hard reload) -- explicit onLogout isn't the only path here. A session can go
		// invalid for other reasons (expiry, revocation) and surface through this exact
		// `load()` re-running on the next in-app navigation, so this is the one chokepoint
		// that must clear it regardless of *why* the session is gone.
		if (sessionGone) queue.reset();
		redirect(302, '/login');
	}
	if (session !== null) {
		if (lastSessionEmail !== null && lastSessionEmail !== session.email) queue.reset();
		lastSessionEmail = session.email;
	}
	if (session !== null && onLoginPage) {
		redirect(302, '/');
	}

	return { session };
};
