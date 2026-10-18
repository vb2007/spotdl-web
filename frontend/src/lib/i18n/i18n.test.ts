import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { ApiError } from '$lib/api';
import { baseLocale, overwriteGetLocale, type Locale } from '$lib/paraglide/runtime';
import { apiErrorText, errorText } from '$lib/i18n/errors';
import { detectLocale, resolveLocale } from '$lib/i18n/locale.svelte';

// The unit tests run in Node, which has no `localStorage`: a Map-backed stand-in.
beforeAll(() => {
	const store = new Map<string, string>();
	globalThis.localStorage = {
		getItem: (key: string) => store.get(key) ?? null,
		setItem: (key: string, value: string) => void store.set(key, String(value)),
		removeItem: (key: string) => void store.delete(key),
		clear: () => store.clear(),
		key: (index: number) => [...store.keys()][index] ?? null,
		get length() {
			return store.size;
		}
	} as Storage;
});

function speak(locale: Locale) {
	overwriteGetLocale(() => locale);
}

afterEach(() => {
	speak(baseLocale);
	localStorage.clear();
});

describe('detectLocale', () => {
	it('takes the first browser language we ship, by its primary subtag', () => {
		expect(detectLocale(['hu-HU'])).toBe('hu');
		expect(detectLocale(['en-US'])).toBe('en');
		expect(detectLocale(['HU'])).toBe('hu');
		expect(detectLocale(['de-DE', 'hu-HU', 'en-US'])).toBe('hu');
		expect(detectLocale(['de-DE', 'en-GB', 'hu'])).toBe('en');
	});

	it('falls back to English for a language we do not ship, or none', () => {
		expect(detectLocale(['de-DE'])).toBe('en');
		expect(detectLocale(['de-DE', 'fr-FR'])).toBe('en');
		expect(detectLocale([])).toBe('en');
	});
});

describe('resolveLocale', () => {
	it('puts a saved preference first, then the /login choice, then the browser', () => {
		localStorage.setItem('spotdl.locale', 'en');
		expect(resolveLocale('hu')).toBe('hu');
		expect(resolveLocale(null)).toBe('en');
		localStorage.setItem('spotdl.locale', 'hu');
		expect(resolveLocale(null)).toBe('hu');
		expect(resolveLocale('en')).toBe('en');
	});

	it('ignores a stored value that is not a language we ship', () => {
		localStorage.setItem('spotdl.locale', 'de');
		expect(resolveLocale('xx')).toBe(detectLocale());
	});
});

describe('apiErrorText', () => {
	it('translates a known code, in the active language', () => {
		const err = new ApiError(404, 'Job not found', 'job_not_found');
		expect(apiErrorText(err)).toBe('Job not found');
		speak('hu');
		expect(apiErrorText(err)).toBe('Nincs ilyen feladat');
	});

	it('interpolates the params a code carries', () => {
		const err = new ApiError(409, 'Track is downloading, not retryable', 'track_not_retryable', {
			state: 'downloading'
		});
		expect(apiErrorText(err)).toBe('Track is downloading, not retryable');
		speak('hu');
		expect(apiErrorText(err)).toBe('A szám állapota „letöltés”, így nem próbálható újra');
	});

	it('falls back to the server’s detail for an unknown code, or none', () => {
		speak('hu');
		expect(apiErrorText(new ApiError(418, 'I am a teapot', 'teapot_brewing'))).toBe(
			'I am a teapot'
		);
		expect(apiErrorText(new ApiError(404, 'Not Found'))).toBe('Not Found');
	});

	it('uses the caller’s fallback for anything that is not an API error', () => {
		speak('hu');
		expect(errorText(new TypeError('Failed to fetch'))).toBe('Nem sikerült elérni a szervert.');
		expect(errorText(new TypeError('x'), () => 'saját')).toBe('saját');
		expect(errorText(new ApiError(404, 'File not found', 'file_not_found'))).toBe(
			'A fájl nem található'
		);
	});
});
