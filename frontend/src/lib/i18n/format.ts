import { getLocale } from '$lib/paraglide/runtime';
import { browserLanguages, clockPreference } from './locale.svelte';

/** v46: every number, date and time the UI prints goes through `Intl`, never a hand-built
 * string or `toLocaleString()`. The words (month names, AM/PM) follow the interface language;
 * the conventions (date order, digit grouping, decimal mark, 12/24-hour) follow the browser's
 * region (owner's rule, PR #68): English on a Hungarian browser reads "17 Oct 2026, 13:05"
 * and "12 345". Where Intl has no data for the pair (`hu-US`), numbers and the clock still
 * follow the region; only the date order stays the language's. A time format the user pinned
 * on /account overrides the region's clock.
 * Called from a template or `$derived`, each re-renders on a language or clock switch. */

/** The browser's region, from its first language tag (`hu-HU` → HU; a bare `hu` → HU by
 * likely-subtags), or `undefined` when it names none. */
export function browserRegion(
	languages: readonly string[] = browserLanguages()
): string | undefined {
	const tag = languages[0];
	if (!tag) return undefined;
	try {
		return new Intl.Locale(tag).maximize().region;
	} catch {
		return undefined;
	}
}

/** The interface language with the browser's region (`en-HU`). */
export function formatLocale(): string {
	const language = getLocale();
	const region = browserRegion();
	if (!region) return language;
	try {
		return new Intl.Locale(language, { region }).toString();
	} catch {
		return language;
	}
}

/** Whether Intl has data for the language-region pair. Where it hasn't (`hu-US`), it falls
 * back to the bare language and the region would silently stop counting. */
function pairSupported(locale: string): boolean {
	return new Intl.DateTimeFormat(locale).resolvedOptions().locale === locale;
}

/** The region's own conventions, for what has no words: its likeliest locale (DE → de-DE).
 * Maximized explicitly: Intl never maximizes `und-DE` itself, it falls back to the runtime's
 * default locale, and the region would stop counting again. */
function regionLocale(): string | undefined {
	const region = browserRegion();
	if (!region) return undefined;
	try {
		const likely = new Intl.Locale('und', { region }).maximize();
		return `${likely.language}-${region}`;
	} catch {
		return undefined;
	}
}

function clockOptions(): Intl.DateTimeFormatOptions {
	const pinned = clockPreference.current;
	if (pinned !== null) return { hourCycle: pinned === '24h' ? 'h23' : 'h12' };
	return regionClockOptions();
}

/** Automatic: the region's clock, even where the pair has no data of its own (a Hungarian
 * interface on a US browser still reads 12-hour). */
function regionClockOptions(): Intl.DateTimeFormatOptions {
	const locale = formatLocale();
	const region = regionLocale();
	if (pairSupported(locale) || !region) return {};
	const hourCycle = new Intl.DateTimeFormat(region, { hour: 'numeric' }).resolvedOptions()
		.hourCycle;
	return hourCycle ? { hourCycle } : {};
}

export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
	// Digits carry no words, so where the pair has no data the region's own conventions apply,
	// in Latin digits like every other number on the page (an Egyptian or Iranian region would
	// otherwise bring its own beside Latin clocks and countdowns).
	const locale = formatLocale();
	const region = regionLocale();
	if (pairSupported(locale) || !region) return new Intl.NumberFormat(locale, options).format(value);
	return new Intl.NumberFormat(region, { ...options, numberingSystem: 'latn' }).format(value);
}

/** A plural message's inputs: the raw `count` picks the form, `n` is how it's written. */
export function counted(count: number): { count: number; n: string } {
	return { count, n: formatNumber(count) };
}

function toDate(value: Date | string | number): Date {
	return value instanceof Date ? value : new Date(value);
}

/** "14:03" (or "2:03 PM" where the region or the user's clock says so). */
export function formatClock(value: Date | string | number): string {
	return new Intl.DateTimeFormat(formatLocale(), {
		hour: '2-digit',
		minute: '2-digit',
		...clockOptions()
	}).format(toDate(value));
}

/** "14:03:27": a clock with seconds. */
export function formatTime(value: Date | string | number): string {
	return new Intl.DateTimeFormat(formatLocale(), { timeStyle: 'medium', ...clockOptions() }).format(
		toDate(value)
	);
}

export function formatDateTime(
	value: Date | string | number,
	options: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short' }
): string {
	// The clock only matters to a format that shows the hour.
	const showsHour = options.hour !== undefined || options.timeStyle !== undefined;
	return new Intl.DateTimeFormat(formatLocale(), {
		...options,
		...(showsHour ? clockOptions() : {})
	}).format(toDate(value));
}

/** For the /account choice: what a clock reads as with `clock` pinned, or with the browser
 * region's own (`null`), whatever the user has pinned right now. */
export function clockExample(value: Date | string | number, clock: '12h' | '24h' | null): string {
	const pinned = clock === null ? {} : { hourCycle: clock === '24h' ? 'h23' : 'h12' };
	// The same shape as `formatClock`, so the example reads as the app's times will.
	return new Intl.DateTimeFormat(formatLocale(), {
		hour: '2-digit',
		minute: '2-digit',
		...(clock === null ? regionClockOptions() : pinned)
	} as Intl.DateTimeFormatOptions).format(toDate(value));
}

/** v41/v47: a " · "-joined reading ("120 done · 3 waiting") wraps only between its parts,
 * never inside one, and a wrapped line starts with its separator instead of the line above
 * ending on one (Hungarian's longer words stranded a "·" at the line's end). */
export function keepReadings(text: string): string {
	return text
		.split(' · ')
		.map((part) => part.replace(/ /g, ' '))
		.join(' · ');
}
