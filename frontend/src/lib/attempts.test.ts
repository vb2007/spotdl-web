import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TrackAttempt } from '$lib/api';
import {
	attemptCount,
	attemptPath,
	attemptVia,
	formatCountdown,
	formatDuration,
	groupAttempts,
	relativeTime,
	summarizeVia
} from '$lib/attempts';
import { baseLocale, overwriteGetLocale, type Locale } from '$lib/paraglide/runtime';

function useLocale(locale: Locale) {
	overwriteGetLocale(() => locale);
}

function attempt(n: number, over: Partial<TrackAttempt> = {}): TrackAttempt {
	return {
		id: `a${n}`,
		attempt_number: n,
		started_at: '2026-10-14T15:00:00Z',
		finished_at: '2026-10-14T15:00:05Z',
		duration_seconds: 5,
		outcome: 'failed',
		error_type: 'no_output',
		error_message: 'spotdl returned no output file',
		warning_message: null,
		proxy_id: null,
		proxy_label: null,
		network_path: 'direct-ipv4',
		...over
	};
}

describe('groupAttempts', () => {
	it('reads newest first and collapses only consecutive identical readings', () => {
		const groups = groupAttempts([
			attempt(1, { error_type: 'other', error_message: 'proxy unreachable' }),
			attempt(2),
			attempt(3, { network_path: 'proxy', proxy_label: 'http://1.2.3.4:8080' }),
			attempt(4, { error_type: 'lookup', error_message: 'No results found' }),
			attempt(5)
		]);
		expect(groups.map((g) => g.attempts.map((a) => a.attempt_number))).toEqual([
			[5],
			[4],
			[3, 2],
			[1]
		]);
	});

	it('keys a run by its oldest attempt, so the key survives the run growing', () => {
		const three = groupAttempts([attempt(1, { error_type: 'other' }), attempt(2), attempt(3)]);
		const four = groupAttempts([
			attempt(1, { error_type: 'other' }),
			attempt(2),
			attempt(3),
			attempt(4)
		]);
		expect(three[0].key).toBe('a2');
		expect(four[0].key).toBe('a2');
		expect(four[0].attempts).toHaveLength(3);
	});

	it('never merges a different outcome or note', () => {
		const groups = groupAttempts([
			attempt(1, { outcome: 'completed', error_type: null, error_message: null }),
			attempt(2, {
				outcome: 'completed',
				error_type: null,
				error_message: null,
				warning_message: 'tag warning: cover art missing'
			})
		]);
		expect(groups).toHaveLength(2);
	});

	it('summarizes a run by path family', () => {
		const [run] = groupAttempts([
			attempt(1),
			attempt(2, { network_path: 'direct-ipv6' }),
			attempt(3, { network_path: 'proxy', proxy_label: 'http://1.2.3.4:1' }),
			attempt(4, { network_path: 'proxy', proxy_label: 'http://5.6.7.8:2' })
		]);
		expect(summarizeVia(run.attempts)).toBe('via proxy ×2, direct · IPv6, direct · IPv4');
	});
});

describe('formatting', () => {
	it('gives a countdown past 24h a days unit', () => {
		expect(formatCountdown(47 * 3600_000 + 12 * 60_000 + 3_000)).toBe('1d 23:12:03');
		expect(formatCountdown(3 * 3600_000 + 5_000)).toBe('3:00:05');
		expect(formatCountdown(65_000)).toBe('1:05');
		expect(formatCountdown(0)).toBe('due now');
	});

	it('formats relative times and durations', () => {
		const now = Date.parse('2026-10-14T18:00:00Z');
		expect(relativeTime('2026-10-14T17:59:30Z', now)).toBe('just now');
		expect(relativeTime('2026-10-14T17:48:00Z', now)).toBe('12m ago');
		expect(relativeTime('2026-10-14T14:55:00Z', now)).toBe('3h 05m ago');
		expect(relativeTime('2026-10-12T14:00:00Z', now)).toBe('2d 4h ago');
		expect(relativeTime('2026-10-14T16:00:00Z', now)).toBe('2h 00m ago');
		expect(relativeTime('2026-10-12T18:00:00Z', now)).toBe('2d 0h ago');
		expect(formatDuration(0.42)).toBe('0.4s');
		expect(formatDuration(24.1)).toBe('24s');
		expect(formatDuration(183.2)).toBe('3m 03s');
		expect(formatDuration(9.96)).toBe('10s');
		expect(formatDuration(59.6)).toBe('1m 00s');
	});
});

// v46: the same readings in Hungarian, through Intl and the message files.
describe('formatting in Hungarian', () => {
	// A Hungarian browser (Node's own says en-US): conventions follow the browser's region.
	beforeEach(() => vi.stubGlobal('navigator', { languages: ['hu-HU'], language: 'hu-HU' }));
	afterEach(() => vi.unstubAllGlobals());

	afterEach(() => useLocale(baseLocale));

	it('formats countdowns, relative times and durations', () => {
		useLocale('hu');
		expect(formatCountdown(47 * 3600_000 + 12 * 60_000 + 3_000)).toBe('1 nap 23:12:03');
		expect(formatCountdown(65_000)).toBe('1:05');
		expect(formatCountdown(0)).toBe('most esedékes');
		const now = Date.parse('2026-10-14T18:00:00Z');
		expect(relativeTime('2026-10-14T17:59:30Z', now)).toBe('épp most');
		expect(relativeTime('2026-10-14T17:48:00Z', now)).toBe('12 perce');
		expect(relativeTime('2026-10-14T14:55:00Z', now)).toBe('3 óra 5 perce');
		expect(relativeTime('2026-10-12T14:00:00Z', now)).toBe('2 nap 4 órája');
		// A whole hour or day drops the zero remainder.
		expect(relativeTime('2026-10-14T16:00:00Z', now)).toBe('2 órája');
		expect(relativeTime('2026-10-12T18:00:00Z', now)).toBe('2 napja');
		// A decimal comma, not a point.
		expect(formatDuration(0.42)).toBe('0,4 mp');
		expect(formatDuration(24.1)).toBe('24 mp');
		expect(formatDuration(183.2)).toBe('3 p 03 mp');
	});

	it('names the paths, and leaves a proxy label as it is', () => {
		useLocale('hu');
		expect(attemptVia(attempt(1, { network_path: 'direct-ipv6' }))).toBe('közvetlen · IPv6');
		expect(
			attemptVia(attempt(1, { network_path: 'proxy', proxy_label: 'http://1.2.3.4:8080' }))
		).toBe('proxyn át: http://1.2.3.4:8080');
		const [run] = groupAttempts([
			attempt(1),
			attempt(2, { network_path: 'proxy', proxy_label: 'http://1.2.3.4:1' }),
			attempt(3, { network_path: 'proxy', proxy_label: 'http://5.6.7.8:2' })
		]);
		expect(summarizeVia(run.attempts)).toBe('proxyn át ×2, közvetlen · IPv4');
	});
});

describe('attemptPath', () => {
	it('keeps a pre-v29 proxied attempt proxied after its proxy is deleted (v56, A4)', () => {
		const legacy = { network_path: null, outcome: 'failed' as const };
		expect(
			attemptPath(attempt(1, { ...legacy, proxy_id: 'p1', proxy_label: 'http://1.2.3.4:8080' }))
		).toBe('proxy');
		expect(
			attemptPath(attempt(2, { ...legacy, proxy_id: null, proxy_label: 'http://1.2.3.4:8080' }))
		).toBe('proxy');
		expect(attemptPath(attempt(3, { ...legacy, proxy_id: null, proxy_label: null }))).toBe(
			'direct'
		);
	});
});

describe('v62 (F11) a collapsed hold counts as its holds', () => {
	const held = (n: number, hold_count: number) =>
		attempt(n, {
			outcome: 'held',
			error_type: null,
			error_message: null,
			warning_message: 'circuit breaker active; rescheduled without attempting',
			network_path: null,
			hold_count
		});

	it('one held row standing for 460 holds reads ×460', () => {
		const [group] = groupAttempts([held(1, 460)]);
		expect(group.attempts).toHaveLength(1);
		expect(group.count).toBe(460);
	});

	it('a run of held rows sums their holds; any other row counts once', () => {
		const groups = groupAttempts([attempt(1), attempt(2), held(3, 3), held(4, 2)]);
		expect(groups.map((g) => [g.attempts.length, g.count])).toEqual([
			[2, 5],
			[2, 2]
		]);
	});

	it('a row from before v55 (no hold_count) is one hold, and a failure never multiplies', () => {
		expect(attemptCount({ ...held(1, 1), hold_count: undefined })).toBe(1);
		expect(attemptCount(attempt(2, { hold_count: 9 }))).toBe(1);
	});
});
