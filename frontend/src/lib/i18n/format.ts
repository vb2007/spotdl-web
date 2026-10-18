import { getLocale } from '$lib/paraglide/runtime';
import { browserLanguages, clockPreference } from './locale.svelte';

/** v46: every number, date and time the UI prints goes through `Intl`, never a hand-built
 * string or `toLocaleString()`. The words (month names, AM/PM) follow the interface language;
 * the conventions (date order, digit grouping, decimal mark, 12/24-hour) follow the browser's
 * region (owner's rule, PR #68): English on a Hungarian browser reads "17 Oct 2026, 13:05"
 * and "12 345". A time format the user pinned on /account overrides the region's clock.
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

/** The interface language with the browser's region (`en-HU`). Intl falls back to the bare
 * language where it has no data for the pair. */
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

function clockOptions(): Intl.DateTimeFormatOptions {
	const pinned = clockPreference.current;
	return pinned === null ? {} : { hourCycle: pinned === '24h' ? 'h23' : 'h12' };
}

export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
	return new Intl.NumberFormat(formatLocale(), options).format(value);
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
	return new Intl.DateTimeFormat(formatLocale(), {
		hour: 'numeric',
		minute: '2-digit',
		...(clock === null ? {} : { hourCycle: clock === '24h' ? 'h23' : 'h12' })
	}).format(toDate(value));
}
