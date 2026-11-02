import {
	baseLocale,
	isLocale,
	locales,
	overwriteGetLocale,
	type Locale
} from '$lib/paraglide/runtime';
import { hasLocaleMessages, loadLocaleMessages } from 'virtual:locale-messages';

/** v46: which language the interface speaks (owner's rule, PR #68):
 *
 * - signed out, always the browser's: the first of `navigator.languages` whose primary subtag
 *   is one we ship, else English;
 * - signed in, the user's saved preference (`/api/auth/me`'s `language`) when they've picked
 *   one on /account, else the browser's as above.
 *
 * So a user who prefers English on a Hungarian browser sees Hungarian on /login and English
 * once signed in. Nothing is stored in the browser.
 *
 * Paraglide's `getLocale()` is overwritten to read a `$state`, so every message a template
 * (or a `$derived`) renders re-renders on a switch, with no reload. The flip side: a string
 * computed once, outside a reactive context, stays in the language it was computed in. Keep
 * labels as functions or `$derived`, never as module-level constants. */

export function detectLocale(languages: readonly string[] = browserLanguages()): Locale {
	for (const tag of languages) {
		const primary = tag.toLowerCase().split('-')[0];
		if (isLocale(primary)) return primary;
	}
	return baseLocale;
}

export function browserLanguages(): readonly string[] {
	if (typeof navigator === 'undefined') return [];
	return navigator.languages?.length ? navigator.languages : [navigator.language];
}

/** A session's saved preference (`null`: none saved, or signed out), else the browser's. */
export function resolveLocale(saved: string | null | undefined): Locale {
	if (saved && isLocale(saved)) return saved;
	return detectLocale();
}

let current = $state<Locale>(resolveLocale(null));
overwriteGetLocale(() => current);
syncDocumentLang();

/* v67 (U8): each language's messages are a chunk of their own, downloaded only when the page
 * speaks it (vite.config.ts's `paraglideLocaleSplit`). A language is switched to only once its
 * messages are here, so nothing renders in a language that hasn't arrived. Nothing loads until
 * `+layout.ts` applies the session's language (signed out: the browser's) and awaits
 * `localeReady()`, before any route renders: a user whose saved language isn't the browser's
 * downloads only the saved one. */
let ready: Promise<void> = Promise.resolve();
// The newest switch asked for: a slower, older load never lands over it.
let latest = 0;

/** Reactive: reading `locale.current` in a template or `$derived` tracks it. */
export const locale = {
	get current(): Locale {
		return current;
	}
};

// A language download that hangs (a stalled mobile connection) counts as failed, so no
// navigation waits on it for ever.
const LOAD_TIMEOUT_MS = 15_000;

/** Whether `locale` loaded in time; `late` runs if it arrives after the timeout after all. */
function load(locale: Locale, late?: () => void): Promise<boolean> {
	const attempt = loadLocaleMessages(locale);
	return Promise.race([
		attempt.then(() => true),
		new Promise<boolean>((resolve) => setTimeout(() => resolve(false), LOAD_TIMEOUT_MS))
	])
		.catch(() => false)
		.then((loaded) => {
			if (!loaded && late) attempt.then(late, () => {});
			return loaded;
		});
}

/** Switches to `next` once its messages are here: at once when they already are. The returned
 * promise (`localeReady()` waits on the same switch) settles once it has happened, `true`, or
 * once it couldn't, `false`: the language couldn't be downloaded (offline, a deploy replacing
 * the build), and the page stays in the one on screen, whose messages are here. With none on
 * screen yet (a first load offline whose language the service worker doesn't hold), the first
 * language that does load is shown instead: a page always has a language to speak. */
export function applyLocale(next: Locale): Promise<boolean> {
	const request = ++latest;
	if (hasLocaleMessages(next)) {
		current = next;
		syncDocumentLang();
		ready = Promise.resolve();
		return Promise.resolve(true);
	}
	const show = (locale: Locale) => {
		if (request !== latest) return;
		current = locale;
		syncDocumentLang();
	};
	// A download that times out but arrives later still switches, if nothing newer was asked.
	const switched = load(next, () => show(next)).then(async (loaded) => {
		if (loaded) {
			show(next);
			return true;
		}
		if (!locales.some((locale) => hasLocaleMessages(locale))) {
			for (const other of locales) {
				if (other !== next && (await load(other))) {
					show(other);
					break;
				}
			}
		}
		return false;
	});
	ready = switched.then(() => undefined);
	return switched;
}

/** Settles once the language last asked for is on screen (or couldn't be loaded). */
export function localeReady(): Promise<void> {
	return ready;
}

// The signed-in user's saved language, `null` for automatic (and whenever signed out): what
// /account shows as chosen. The language spoken is `current`, resolved from it.
let savedLanguage = $state<Locale | null>(null);

export const languagePreference = {
	get current(): Locale | null {
		return savedLanguage;
	}
};

/** A session's saved language (or `null`: automatic, or signed out), applied: remembered for
 * /account and resolved into the language the page speaks. */
export function applyLanguagePreference(saved: string | null | undefined): Promise<boolean> {
	savedLanguage = saved && isLocale(saved) ? saved : null;
	return applyLocale(resolveLocale(savedLanguage));
}

function syncDocumentLang() {
	if (typeof document !== 'undefined') document.documentElement.lang = current;
	// v67 (U8): the installed app's worker keeps the language on screen for the next build;
	// only one that is (its messages here), never the module's first guess at the browser's.
	if (typeof navigator !== 'undefined' && hasLocaleMessages(current))
		navigator.serviceWorker?.controller?.postMessage({ type: 'locale', locale: current });
}

/** Each language in its own name, so it's findable by someone who can't read the current
 * one. Not messages: these never change with the interface language. Hungarian first,
 * since most of this app's users read it. */
export const LANGUAGES: readonly { code: Locale; name: string }[] = [
	{ code: 'hu', name: 'Magyar' },
	{ code: 'en', name: 'English' }
];

/** v46 (owner's rule, PR #68): the time format, by the same rules as the language. `null` is
 * automatic: the browser's region decides 12- or 24-hour (`format.ts`). Signed in, a format
 * pinned on /account overrides it; signed out, it's always automatic. */
export type Clock = '12h' | '24h';

let clock = $state<Clock | null>(null);

export const clockPreference = {
	get current(): Clock | null {
		return clock;
	}
};

export function applyClock(next: string | null | undefined): void {
	clock = next === '12h' || next === '24h' ? next : null;
}
