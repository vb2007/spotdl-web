import { redirect } from '@sveltejs/kit';
import * as api from '$lib/api';
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
		redirect(302, '/login');
	}
	if (session !== null && onLoginPage) {
		redirect(302, '/');
	}

	return { session };
};
