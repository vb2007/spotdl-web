import { baseLocale, isLocale, overwriteGetLocale, type Locale } from '$lib/paraglide/runtime';

/** v46: which language the interface speaks, in the plan's order of precedence:
 *
 * 1. the signed-in user's saved preference (`/api/auth/me`'s `language`),
 * 2. a choice made on /login before signing in (this browser's `localStorage`),
 * 3. the first of `navigator.languages` whose primary subtag is one we ship,
 * 4. English.
 *
 * Paraglide's `getLocale()` is overwritten to read a `$state`, so every message a template
 * (or a `$derived`) renders re-renders on a switch, with no reload. The flip side: a string
 * computed once, outside a reactive context, stays in the language it was computed in. Keep
 * labels as functions or `$derived`, never as module-level constants. */

/** The `/login` choice. Wrapped in try/catch: storage can be blocked or absent. */
const STORAGE_KEY = 'spotdl.locale';

export function detectLocale(languages: readonly string[] = browserLanguages()): Locale {
	for (const tag of languages) {
		const primary = tag.toLowerCase().split('-')[0];
		if (isLocale(primary)) return primary;
	}
	return baseLocale;
}

function browserLanguages(): readonly string[] {
	if (typeof navigator === 'undefined') return [];
	return navigator.languages?.length ? navigator.languages : [navigator.language];
}

// The /login choice as this tab last made it: what reads it back when storage is blocked.
let chosenHere: Locale | null = null;

export function loginChoice(): Locale | null {
	if (chosenHere) return chosenHere;
	try {
		const stored = localStorage.getItem(STORAGE_KEY);
		return stored && isLocale(stored) ? stored : null;
	} catch {
		return null;
	}
}

export function saveLoginChoice(locale: Locale): void {
	chosenHere = locale;
	try {
		localStorage.setItem(STORAGE_KEY, locale);
	} catch {
		// Storage blocked: the choice still applies to this tab, and sign-in carries it.
	}
}

/** The precedence above, for a session's saved preference (`null`: none, or signed out). */
export function resolveLocale(saved: string | null | undefined): Locale {
	if (saved && isLocale(saved)) return saved;
	return loginChoice() ?? detectLocale();
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
