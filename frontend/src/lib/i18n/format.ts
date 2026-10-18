import { getLocale } from '$lib/paraglide/runtime';

/** v46: every number, date and time the UI prints goes through `Intl` with the active
 * locale (`getLocale()`), never the browser's default (`toLocaleString([])`) or a hand-built
 * string. Called from a template or `$derived`, each re-renders on a language switch. */

export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
	return new Intl.NumberFormat(getLocale(), options).format(value);
}

function toDate(value: Date | string | number): Date {
	return value instanceof Date ? value : new Date(value);
}

/** "14:03" (or "2:03 PM" where the locale says so). */
export function formatClock(value: Date | string | number): string {
	return new Intl.DateTimeFormat(getLocale(), { hour: '2-digit', minute: '2-digit' }).format(
		toDate(value)
	);
}

/** "14:03:27": a clock with seconds. */
export function formatTime(value: Date | string | number): string {
	return new Intl.DateTimeFormat(getLocale(), { timeStyle: 'medium' }).format(toDate(value));
}

export function formatDateTime(
	value: Date | string | number,
	options: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short' }
): string {
	return new Intl.DateTimeFormat(getLocale(), options).format(toDate(value));
}
