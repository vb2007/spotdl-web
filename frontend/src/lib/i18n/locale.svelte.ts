import { baseLocale, isLocale, overwriteGetLocale, type Locale } from '$lib/paraglide/runtime';
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

/** Switches to `next` once its messages are here: at once when they already are. The returned
 * promise (also `localeReady()`) settles when the switch has happened. */
export function applyLocale(next: Locale): Promise<void> {
	const request = ++latest;
	if (hasLocaleMessages(next)) {
		current = next;
		syncDocumentLang();
		ready = Promise.resolve();
		return ready;
	}
	ready = loadLocaleMessages(next).then(
		() => {
			if (request !== latest) return;
			current = next;
			syncDocumentLang();
		},
		// Couldn't download it (offline, a deploy replacing the build): stay in the language
		// already on screen, whose messages are here.
		() => {}
	);
	return ready;
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
export function applyLanguagePreference(saved: string | null | undefined): Promise<void> {
	savedLanguage = saved && isLocale(saved) ? saved : null;
	return applyLocale(resolveLocale(savedLanguage));
}

function syncDocumentLang() {
	if (typeof document !== 'undefined') document.documentElement.lang = current;
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
