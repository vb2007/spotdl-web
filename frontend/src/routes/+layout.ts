import { redirect } from '@sveltejs/kit';
import * as api from '$lib/api';
import type { LayoutLoad } from './$types';

// Adapter-static has no server to run a `+layout.server.ts` load against at request
// time — this project has exactly two routes, so each still gets its own prerendered
// shell (`prerender = true`), but the actual session check only makes sense in the
// browser against the live cookie, hence `ssr = false`.
export const ssr = false;
export const prerender = true;

export const load: LayoutLoad = async ({ url }) => {
	const onLoginPage = url.pathname === '/login';

	let email: string | null;
	try {
		email = (await api.me()).email;
	} catch {
		email = null;
	}

	if (email === null && !onLoginPage) {
		redirect(302, '/login');
	}
	if (email !== null && onLoginPage) {
		redirect(302, '/');
	}

	return { email };
};
