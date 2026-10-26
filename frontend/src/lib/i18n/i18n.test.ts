import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '$lib/api';
import { baseLocale, overwriteGetLocale, type Locale } from '$lib/paraglide/runtime';
import { apiErrorText, errorText, knowsCode } from '$lib/i18n/errors';
import {
	applyClock,
	applyLanguagePreference,
	detectLocale,
	languagePreference,
	locale,
	resolveLocale
} from '$lib/i18n/locale.svelte';
import {
	browserRegion,
	clockExample,
	counted,
	formatClock,
	formatDateTime,
	formatLocale,
	formatNumber
} from '$lib/i18n/format';
import * as m from '$lib/paraglide/messages';

function speak(locale: Locale) {
	overwriteGetLocale(() => locale);
}

// The browser the formatting tests pretend to be (Node's own `navigator` says en-US).
function browser(...languages: string[]) {
	vi.stubGlobal('navigator', { languages, language: languages[0] });
}

afterEach(() => {
	speak(baseLocale);
	applyClock(null);
	vi.unstubAllGlobals();
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
	it('puts a signed-in user’s saved preference first, else the browser decides', () => {
		browser('hu-HU', 'en-US');
		expect(resolveLocale(null)).toBe('hu');
		expect(resolveLocale('en')).toBe('en');
		browser('de-DE');
		expect(resolveLocale(null)).toBe('en');
		expect(resolveLocale('hu')).toBe('hu');
	});

	it('remembers whether a language is saved, and automatic speaks the browser’s', () => {
		browser('hu-HU');
		applyLanguagePreference('en');
		expect(languagePreference.current).toBe('en');
		expect(locale.current).toBe('en');
		applyLanguagePreference(null);
		expect(languagePreference.current).toBeNull();
		expect(locale.current).toBe('hu');
	});

	it('ignores a saved value that is not a language we ship', () => {
		browser('hu-HU');
		expect(resolveLocale('xx')).toBe('hu');
	});
});

describe('formatting: the interface language with the browser’s region', () => {
	const at = new Date('2026-10-17T13:05:00');

	it('reads the region from the browser’s first language tag', () => {
		expect(browserRegion(['hu-HU'])).toBe('HU');
		expect(browserRegion(['en-GB', 'hu'])).toBe('GB');
		expect(browserRegion(['hu'])).toBe('HU');
		expect(browserRegion([])).toBeUndefined();
	});

	it('writes English words with a Hungarian browser’s conventions', () => {
		browser('hu-HU');
		expect(formatLocale()).toBe('en-HU');
		expect(formatNumber(12345.5)).toBe('12 345,5');
		expect(formatClock(at)).toBe('13:05');
		expect(formatDateTime(at)).toBe('17 Oct 2026, 13:05');
		expect(m.dashboard_count_tracks(counted(12345))).toBe('12 345 tracks');
	});

	it('keeps a US browser’s conventions', () => {
		browser('en-US');
		expect(formatNumber(12345.5)).toBe('12,345.5');
		expect(formatClock(at)).toBe('01:05 PM');
	});

	it('keeps the region’s numbers and clock where the pair has no data (hu-US)', () => {
		browser('en-US');
		speak('hu');
		expect(formatLocale()).toBe('hu-US');
		expect(formatNumber(12345.5)).toBe('12,345.5');
		expect(formatClock(at)).toMatch(/^du\. 01:05$/);
		expect(m.dashboard_count_tracks(counted(12345))).toBe('12,345 szám');
		// A pinned clock still wins.
		applyClock('24h');
		expect(formatClock(at)).toBe('13:05');
	});

	it('takes the region’s own conventions, not the runtime default, for a pair without data', () => {
		// Node's default locale is en-US; a German region must still read German conventions.
		speak('hu');
		browser('de-DE');
		expect(formatNumber(12345.5)).toBe('12.345,5');
		expect(formatClock(at)).toBe('13:05');
		browser('en-GB');
		expect(formatNumber(12345.5)).toBe('12,345.5');
		expect(formatClock(at)).toBe('13:05');
		// A region with its own digits keeps its separators but writes Latin digits.
		speak('en');
		browser('ar-EG', 'en');
		expect(formatNumber(12345.5)).toMatch(/^12.345.5$/);
	});

	it('lets a pinned clock override the region’s, and only the clock', () => {
		browser('en-US');
		applyClock('24h');
		expect(formatClock(at)).toBe('13:05');
		expect(formatDateTime(at)).toBe('Oct 17, 2026, 13:05');
		expect(formatNumber(1000)).toBe('1,000');
		browser('hu-HU');
		applyClock('12h');
		// The region's own spelling of the period: en-HU writes it lowercase.
		expect(formatClock(at)).toBe('01:05 pm');
		// A date without the hour is untouched by the clock.
		expect(formatDateTime(at, { dateStyle: 'medium' })).toBe('17 Oct 2026');
		applyClock(null);
		expect(formatClock(at)).toBe('13:05');
	});

	it('shows each /account choice as it would read', () => {
		browser('en-US');
		applyClock('24h');
		// The same padded shape as every time the app prints.
		expect(clockExample(at, null)).toBe('01:05 PM');
		expect(clockExample(at, '12h')).toBe('01:05 PM');
		expect(clockExample(at, '24h')).toBe('13:05');
		browser('hu-HU');
		expect(clockExample(at, null)).toBe('13:05');
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
		expect(apiErrorText(err)).toBe('A szám állapota „letöltés alatt”, így nem próbálható újra');
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

describe('plurals and numbers', () => {
	it('picks the English plural for 0, 1 and 5', () => {
		expect(m.dashboard_count_tracks(counted(0))).toBe('0 tracks');
		expect(m.dashboard_count_tracks(counted(1))).toBe('1 track');
		expect(m.dashboard_count_tracks(counted(5))).toBe('5 tracks');
		expect(m.stats_attempts_unit(counted(1))).toBe('attempt');
		expect(m.stats_attempts_unit(counted(5))).toBe('attempts');
		expect(m.library_progress_valuetext({ count: 1, processed: '0', total: '1' })).toBe(
			'0 of 1 file'
		);
		expect(m.library_progress_valuetext({ count: 5, processed: '2', total: '5' })).toBe(
			'2 of 5 files'
		);
	});

	it('keeps the Hungarian noun singular after a numeral: 0, 1 and 5', () => {
		speak('hu');
		expect(m.dashboard_count_tracks(counted(0))).toBe('0 szám');
		expect(m.dashboard_count_tracks(counted(1))).toBe('1 szám');
		expect(m.dashboard_count_tracks(counted(5))).toBe('5 szám');
		expect(m.incoming_older(counted(5))).toBe('5 korábbi linket nem sikerült beolvasni');
		expect(m.library_progress_valuetext({ count: 1, processed: '0', total: '1' })).toBe(
			'1 fájlból 0 kész'
		);
	});

	it('groups digits the way the browser’s region writes them', () => {
		browser('en-US');
		expect(m.dashboard_count_tracks(counted(12345))).toBe('12,345 tracks');
		expect(formatNumber(0.5, { minimumFractionDigits: 1 })).toBe('0.5');
		browser('hu-HU');
		speak('hu');
		// Hungary groups with a (no-break) space from five digits, and writes a decimal comma.
		expect(m.dashboard_count_tracks(counted(12345))).toBe('12\u00a0345 szám');
		expect(formatNumber(0.5, { minimumFractionDigits: 1 })).toBe('0,5');
	});
});

// Every code the web UI can meet from backend/app/errors.py's ApiErrors
// (tests/test_api_error_codes.py reaches each one), plus the ones api.ts assigns itself. v53's
// extension-only codes (api_key_invalid, url_not_spotify, cascade_*) never reach the web UI:
// it sends no key, no X-Spotdl-Client header and no cascade.
const BACKEND_CODES = [
	'invalid_credentials',
	'not_authenticated',
	'admin_required',
	'job_not_found',
	'archive_nothing_selected',
	'invalid_list_params',
	'library_sort_running',
	'track_not_found',
	'job_archived',
	'track_not_retryable',
	'file_not_found',
	'proxy_target_exists',
	'proxy_not_found',
	'proxy_url_required',
	'proxy_url_invalid',
	'proxy_url_exists',
	'unsupported_format',
	'unsupported_bitrate',
	'setting_blank',
	'setting_out_of_range',
	'alerts_not_configured',
	'alert_send_failed',
	'retention_days_invalid',
	// v53
	'rate_limited',
	'api_key_label_invalid',
	'api_key_limit_reached',
	'api_key_not_found',
	'queue_unavailable',
	'submit_too_long',
	// v56
	'job_not_cancellable',
	'track_not_cancellable'
];
const CLIENT_CODES = [
	'request_invalid',
	'download_failed',
	'file_empty',
	'server_error',
	'request_failed'
];
const PARAMS: Record<string, string | number> = {
	state: 'downloading',
	target: '203.0.113.5:8080',
	source: 'file',
	value: 'wma',
	field: 'alert_spike_threshold',
	min: 2,
	max: 1000,
	reason: 'HTTP 403',
	status: 'Bad Gateway',
	retry_after: 42
};

describe('every error code', () => {
	it.each([...BACKEND_CODES, ...CLIENT_CODES])('%s renders translated in Hungarian', (code) => {
		expect(knowsCode(code)).toBe(true);
		const err = new ApiError(400, 'the English detail', code, PARAMS);
		const english = apiErrorText(err);
		speak('hu');
		const hungarian = apiErrorText(err);
		expect(hungarian).not.toBe('the English detail');
		expect(hungarian).not.toBe(english);
		expect(hungarian).not.toMatch(/\{\w+\}/);
	});
});
