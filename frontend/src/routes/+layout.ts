import { redirect } from '@sveltejs/kit';
import * as api from '$lib/api';
import { queue } from '$lib/stores/queue';
import * as notifications from '$lib/notifications';
import { consumeSessionEnded, markSessionEnded } from '$lib/stores/sessionEnded';
import { shortcutsEnabled } from '$lib/keyboard/registry';
import {
	applyClock,
	applyLanguagePreference,
	applyLocale,
	languagePreference,
	locale,
	localeReady,
	resolveLocale
} from '$lib/i18n/locale.svelte';
import { hasLocaleMessages } from 'virtual:locale-messages';
import { locales } from '$lib/paraglide/runtime';
import { loginFor, safeNext } from '$lib/nextPath';
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

// v46: whose language and clock the page last applied (`null`: signed out; `undefined`:
// nothing yet). Signed out, both follow the browser; signed in, the user's saved ones win.
// Applied here, before the route renders, so a page never paints in the wrong language first.
// Only when the identity changes, as v45 does for the shortcut switch: within one session the
// tab's own value is the truth (`/account` applies it on save), and a later load may carry a
// `/me` preloaded on hover before that save. Another device's change arrives on reload.
let localeAppliedFor: string | null | undefined;

export const load: LayoutLoad = async ({ url }) => {
	const onLoginPage = url.pathname === '/login';

	let session: api.SessionInfo | null;
	// v42: only a 401 says the session is gone. A network error or a 5xx (api restarting)
	// says nothing about it, and this load also runs on a hover preload while `/` stays
	// mounted, so it must not wipe the store (which `/` now answers with a reload) over a
	// blip. A real navigation still goes to /login as before; if someone else then signs
	// in on this tab, the identity-change reset below clears the store.
	let sessionGone = false;
	// 0: the request never got an answer (the network, the api down).
	let failedStatus: number | null = null;
	// v69: `access_removed` -- the session was ended by a removal from the allowlist.
	let accessRemoved = false;
	try {
		session = await api.me();
	} catch (err) {
		session = null;
		failedStatus = err instanceof api.ApiError ? err.status : 0;
		sessionGone = failedStatus === 401;
		accessRemoved = sessionGone && err instanceof api.ApiError && err.code === 'access_removed';
	}

	// v47: nor does a failed first answer sign anyone out. A 5xx, a 429 or a network failure
	// (an api restart, a deploy) used to send a signed-in user to /login, where they stayed after
	// the api came back. The layout shows "can't reach the server" and retries instead. Any
	// other answer (a 4xx from something in front of the app) won't pass by waiting, so it
	// goes to /login as before rather than retrying forever.
	const transient = failedStatus === 0 || failedStatus === 429 || (failedStatus ?? 0) >= 500;
	const unreachable = session === null && transient && !onLoginPage;

	if (session === null && !onLoginPage && !unreachable) {
		// `queue` is a module-level singleton that survives this client-side redirect (no
		// hard reload) -- explicit onLogout isn't the only path here. A session can go
		// invalid for other reasons (expiry, revocation) and surface through this exact
		// `load()` re-running on the next in-app navigation, so this is the one chokepoint
		// that must clear it regardless of *why* the session is gone.
		if (sessionGone) {
			queue.reset();
			notifications.reset();
			// v47: only a tab that had a session here says it ended (not a first visit). v69: a
			// removed session says so even on a fresh load (a reload right after the removal):
			// its cookie proves there was one.
			if (accessRemoved && !api.isSigningOut()) markSessionEnded('access_removed');
			else if (lastSessionEmail !== null && !api.isSigningOut()) markSessionEnded();
		}
		// v65: a share opened signed out comes back to itself, its parameters included.
		redirect(302, url.pathname === '/share' ? loginFor(url.pathname + url.search) : '/login');
	}
	if (session !== null) {
		// v47: a live session answers any earlier "it ended" (a hover preload's, say).
		consumeSessionEnded();
		if (lastSessionEmail !== null && lastSessionEmail !== session.email) {
			queue.reset();
			notifications.reset();
			// v45: the new identity's own switch, at once. A hover preload's `data` is never
			// applied, so the layout's effect wouldn't set it until the next real navigation.
			shortcutsEnabled.set(session.keyboard_shortcuts ?? true);
		}
		lastSessionEmail = session.email;
	}
	const identity = session?.email ?? null;
	// Unreachable says nothing about who is signed in: keep the language already on screen.
	if (identity !== localeAppliedFor && !(unreachable && localeAppliedFor !== undefined)) {
		localeAppliedFor = identity;
		applyLanguagePreference(session?.language);
		applyClock(session?.clock);
		// v67 (U8): the language's messages are downloaded on demand; no route renders before
		// they're here.
		await localeReady();
	} else {
		// v67 (U8): the session's language, if it never arrived (every download failed or timed
		// out, the page showing keys or a fallback), is tried again on a later load, in the
		// background: it switches when it lands, and the navigation never waits on it. Only
		// when this load applied none: a fresh apply is the newest request. With a language on
		// screen there is nothing to wait for (an unreachable reload keeps it).
		const wanted = resolveLocale(languagePreference.current);
		if (wanted !== locale.current || !hasLocaleMessages(wanted))
			// With no language at all (the page showing keys) there is nothing better to show:
			// this navigation waits for it, so the route renders in it.
			applyLocale(wanted, { background: locales.some((one) => hasLocaleMessages(one)) });
		await localeReady();
	}
	if (session !== null && onLoginPage) {
		// v65: signed in already (another tab), so straight on to where the login was for.
		redirect(302, safeNext(url.searchParams.get('next')) ?? '/');
	}

	return { session, unreachable };
};
