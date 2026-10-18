import { baseLocale, isLocale, overwriteGetLocale, type Locale } from '$lib/paraglide/runtime';

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

/** Reactive: reading `locale.current` in a template or `$derived` tracks it. */
export const locale = {
	get current(): Locale {
		return current;
	}
};

export function applyLocale(next: Locale): void {
	current = next;
	syncDocumentLang();
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
