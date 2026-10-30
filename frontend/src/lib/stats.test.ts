import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AdminStats, BreakerEvent } from '$lib/api';
import { baseLocale, overwriteGetLocale, type Locale } from '$lib/paraglide/runtime';
import {
	axisPosition,
	bucketHeld,
	bucketLabel,
	errorTypeCondition,
	errorTypeLabel,
	failurePeak,
	formatBytes,
	formatRate,
	formatSpan,
	holdGeometry,
	holdSpans,
	instantLabel,
	pathLabel,
	slotted,
	windowHeading
} from '$lib/stats';
import * as m from '$lib/paraglide/messages';
import { counted } from '$lib/i18n/format';

const HOUR = 3600 * 1000;
const START = Date.parse('2026-10-16T00:00:00Z');

function stats(events: BreakerEvent[] = [], over: Partial<AdminStats> = {}): AdminStats {
	return {
		window: '24h',
		generated_at: new Date(START + 23.5 * HOUR).toISOString(),
		window_start: new Date(START).toISOString(),
		utc_offset_minutes: 0,
		bucket_seconds: 3600,
		network_paths: [],
		proxies: [],
		failures: {
			buckets: Array.from({ length: 24 }, (_, i) => new Date(START + i * HOUR).toISOString()),
			series: [
				{ error_type: 'audio_provider', counts: Array(24).fill(0).fill(3, 5, 6), total: 3 },
				{ error_type: 'lookup', counts: Array(24).fill(1), total: 24 }
			]
		},
		breaker: {
			current: { paused: false, holding_until: null, trip_count: 0 },
			events,
			trips: 0
		},
		queue: {
			counts: { pending: 0, queued: 0, downloading: 0, waiting: 0 },
			oldest_waiting_since: null,
			oldest_waiting_age_seconds: null
		},
		...over
	};
}

function at(hours: number): string {
	return new Date(START + hours * HOUR).toISOString();
}

function trip(
	hours: number,
	stepHours: number,
	kind: 'tripped' | 'escalated' = 'tripped'
): BreakerEvent {
	return {
		kind,
		occurred_at: at(hours),
		step_seconds: stepHours * 3600,
		trip_count: 1,
		paused_until: at(hours + stepHours),
		manual: false
	};
}

function release(hours: number, manual: boolean): BreakerEvent {
	return {
		kind: 'released',
		occurred_at: at(hours),
		step_seconds: null,
		trip_count: null,
		paused_until: null,
		manual
	};
}

describe('holdSpans', () => {
	it('runs a pause to its own end when it ran out', () => {
		const [span] = holdSpans(stats([trip(6, 2), release(8, false)]));
		expect(span.from).toBeCloseTo(6 / 24);
		expect(span.to).toBeCloseTo(8 / 24);
		expect(span.manual).toBe(false);
		expect(span.ongoing).toBe(false);
	});

	it('cuts a pause short at a manual release', () => {
		const [span] = holdSpans(stats([trip(6, 6), release(7, true)]));
		expect(span.to).toBeCloseTo(7 / 24);
		expect(span.manual).toBe(true);
	});

	it('draws a hold still running up to now, not into the future', () => {
		const [span] = holdSpans(stats([trip(23, 6, 'escalated')]));
		expect(span.ongoing).toBe(true);
		expect(span.escalated).toBe(true);
		expect(span.to).toBeCloseTo(23.5 / 24);
	});

	it('clips a pause that began before the window', () => {
		const [span] = holdSpans(stats([trip(-1, 2), release(1, false)]));
		expect(span.from).toBe(0);
		expect(span.to).toBeCloseTo(1 / 24);
	});

	it('ignores a release belonging to a later trip', () => {
		const spans = holdSpans(stats([trip(2, 1), trip(10, 2), release(11, true)]));
		expect(spans.map((s) => s.manual)).toEqual([false, true]);
		expect(spans[0].to).toBeCloseTo(3 / 24);
	});
});

describe('a hold over before the window', () => {
	it('is not drawn, even when its scheduled end reaches into the window', () => {
		// Tripped 1h before the window for 6h, released 30m before it.
		expect(holdSpans(stats([trip(-1, 6), release(-0.5, true)]))).toEqual([]);
	});
});

describe('bucketLabel', () => {
	it("labels on the response's own clock, whatever the browser's zone", () => {
		// Budapest in summer (+120): the day bucket for Oct 16 starts at 22:00Z on Oct 15.
		const s = stats([], {
			window: '7d',
			bucket_seconds: 86400,
			utc_offset_minutes: 120,
			failures: { buckets: ['2026-10-15T22:00:00Z'], series: [] }
		});
		expect(bucketLabel(s, '2026-10-15T22:00:00Z', true)).toMatch(/16/);
		const hourly = stats([], { utc_offset_minutes: 120 });
		expect(bucketLabel(hourly, '2026-10-16T10:00:00Z', true)).toMatch(/^12:00/);
	});
});

describe('holds ended early', () => {
	it('ends a hold at a later trip that takes over before its scheduled end', () => {
		const spans = holdSpans(stats([trip(2, 6), trip(4, 2, 'escalated'), release(6, false)]));
		expect(spans[0].to).toBeCloseTo(4 / 24);
		expect(spans[0].early).toBe(true);
		expect(spans[0].manual).toBe(false);
		expect(spans[1].early).toBe(false);
	});

	it('marks a non-manual release before the scheduled end as early, not "ran out"', () => {
		const [span] = holdSpans(stats([trip(6, 6), release(7, false)]));
		expect(span.early).toBe(true);
		expect(span.manual).toBe(false);
	});

	it('labels a hold instant with its time of day, on the response clock', () => {
		const s = stats([], { utc_offset_minutes: 120 });
		expect(instantLabel(s, '2026-10-16T10:05:00Z')).toMatch(/12:05/);
	});
});

describe('holdGeometry', () => {
	const at = (from: number, to: number) => ({ from, to }) as Parameters<typeof holdGeometry>[0];
	it('widens a short hold to the whole buckets it touches, matching bucketHeld', () => {
		// 24 buckets; a 12-minute hold across the 11:00/12:00 boundary.
		const g = holdGeometry(at(11.9 / 24, 12.1 / 24), 24);
		expect(g.left).toBeCloseTo(11 / 24);
		expect(g.left + g.width).toBeCloseTo(13 / 24);
		// Inside one bucket: exactly that bucket; in the last bucket: never past the end.
		const one = holdGeometry(at(5.2 / 24, 5.3 / 24), 24);
		expect([one.left, one.left + one.width].map((x) => x * 24)).toEqual([5, 6]);
		const last = holdGeometry(at(23.9 / 24, 1), 24);
		expect(last.left + last.width).toBeCloseTo(1);
	});

	it('draws a long hold as it happened', () => {
		expect(holdGeometry(at(0.25, 0.5), 24)).toEqual({ left: 0.25, width: 0.25 });
	});
});

describe('bucketHeld', () => {
	it('marks the buckets a hold overlaps', () => {
		const s = stats([trip(6.5, 2)]);
		const spans = holdSpans(s);
		expect([5, 6, 7, 8, 9].map((i) => bucketHeld(s, spans, i))).toEqual([
			false,
			true,
			true,
			true,
			false
		]);
	});
});

describe('formatting', () => {
	it('never rounds a partial rate to 0% or 100%', () => {
		expect(formatRate(null)).toBe('—');
		expect(formatRate(1)).toBe('100%');
		expect(formatRate(0.996)).toBe('>99%');
		expect(formatRate(0.004)).toBe('<1%');
		expect(formatRate(0)).toBe('0%');
		expect(formatRate(0.7491)).toBe('75%');
	});

	it('spans read in the largest sensible unit', () => {
		expect(formatSpan(30)).toBe('30s');
		expect(formatSpan(1800)).toBe('30m');
		expect(formatSpan(7200)).toBe('2h');
		expect(formatSpan(5400)).toBe('1h 30m');
		expect(formatSpan(5 * 86400)).toBe('5d');
	});

	it('names lookup "not found" and colours a verdict apart from a retry', () => {
		expect(errorTypeLabel('lookup')).toBe('not found');
		expect(errorTypeLabel('no_output')).toBe('no_output');
		expect(errorTypeCondition('lookup')).toBe('fail');
		expect(errorTypeCondition('audio_provider')).toBe('waiting');
		expect(errorTypeCondition('unknown')).toBe('idle');
	});

	it('shares one y-scale across rows and places instants on the axis', () => {
		const s = stats();
		expect(failurePeak(s)).toBe(3);
		expect(axisPosition(s, at(12))).toBeCloseTo(0.5);
		expect(axisPosition(s, at(30))).toBe(1);
	});
});

// v46: the same readings in Hungarian, the noun singular after a numeral and Intl's own
// number and date forms.
describe('in Hungarian', () => {
	// A Hungarian browser (Node's own says en-US): conventions follow the browser's region.
	beforeEach(() => vi.stubGlobal('navigator', { languages: ['hu-HU'], language: 'hu-HU' }));
	afterEach(() => vi.unstubAllGlobals());

	const speak = (locale: Locale) => overwriteGetLocale(() => locale);
	afterEach(() => speak(baseLocale));

	it('labels paths, windows and error types', () => {
		speak('hu');
		expect(pathLabel('direct-ipv4')).toBe('közvetlen · IPv4');
		expect(pathLabel('unknown')).toBe('nincs rögzítve');
		expect(windowHeading('7d')).toBe('Az elmúlt 7 nap');
		expect(errorTypeLabel('lookup')).toBe('nem található');
		// A machine name reads the same in every language.
		expect(errorTypeLabel('no_output')).toBe('no_output');
	});

	it('formats rates and spans', () => {
		speak('hu');
		expect(formatRate(0.7491)).toBe('75%');
		expect(formatRate(0.996)).toBe('>99%');
		expect(formatSpan(30)).toBe('30 mp');
		expect(formatSpan(5400)).toBe('1 ó 30 p');
		expect(formatSpan(5 * 86400)).toBe('5 nap');
	});

	it('reads bucket and instant labels on the response clock, in Hungarian forms', () => {
		speak('hu');
		const hourly = stats([], { utc_offset_minutes: 120 });
		expect(bucketLabel(hourly, '2026-10-16T10:00:00Z', true)).toBe('12:00–13:00');
		expect(instantLabel(hourly, '2026-10-16T10:05:00Z')).toMatch(/okt\. 16\..*12:05/);
	});

	it('keeps the noun singular after a numeral', () => {
		for (const [count, en, hu] of [
			[0, 'Columns share one scale: the tallest is 0 failures in one hour.', '0 hiba'],
			[1, 'Columns share one scale: the tallest is 1 failure in one hour.', '1 hiba'],
			[5, 'Columns share one scale: the tallest is 5 failures in one hour.', '5 hiba']
		] as const) {
			speak('en');
			expect(m.stats_scale_hour(counted(count))).toBe(en);
			speak('hu');
			expect(m.stats_scale_hour(counted(count))).toContain(`${hu} egy órában`);
		}
		speak('hu');
		expect(m.stats_attempts_unit(counted(5))).toBe('próbálkozás');
		speak('en');
		expect(m.stats_attempts_unit(counted(1))).toBe('attempt');
		expect(m.stats_attempts_unit(counted(5))).toBe('attempts');
	});
});

describe('slotted', () => {
	it('splits a message at its values, in the order the language puts them', () => {
		expect(slotted(m.stats_proxies_on_cooling, { on: '3', cooling: '1' })).toEqual([
			{ key: null, text: 'Proxies: ' },
			{ key: 'on', text: '3' },
			{ key: null, text: ' switched on, ' },
			{ key: 'cooling', text: '1' },
			{ key: null, text: ' cooling down.' }
		]);
		overwriteGetLocale(() => 'hu');
		const hu = slotted(m.stats_oldest_waiting, { age: '45 mp', when: '14:03' });
		overwriteGetLocale(() => baseLocale);
		expect(hu.map((slot) => slot.text).join('')).toBe(
			'A legrégebben várakozó szám 45 mp óta vár (14:03).'
		);
		expect(hu.filter((slot) => slot.key !== null).map((slot) => slot.key)).toEqual(['age', 'when']);
	});
});

describe('v66: a user’s own stats', () => {
	const speak = (locale: Locale) => overwriteGetLocale(() => locale);
	afterEach(() => speak(baseLocale));

	it('draws no breaker holds without a breaker', () => {
		const { breaker: _, ...mine } = stats([trip(2, 1)]);
		expect(holdSpans(mine)).toEqual([]);
	});

	it('formats sizes in decimal units, a whole number from 100 up', () => {
		speak('en');
		expect(formatBytes(0)).toBe('0 bytes');
		expect(formatBytes(999)).toBe('999 bytes');
		expect(formatBytes(1)).toBe('1 byte');
		expect(formatBytes(1500)).toBe('1.5 kB');
		expect(formatBytes(409_400_000)).toBe('409 MB');
		expect(formatBytes(3_140_000_000)).toBe('3.1 GB');
		vi.stubGlobal('navigator', { languages: ['hu-HU'], language: 'hu-HU' });
		speak('hu');
		expect(formatBytes(3_140_000_000)).toBe('3,1 GB');
		expect(formatBytes(0)).toBe('0 bájt');
		vi.unstubAllGlobals();
		// A Hungarian UI in an en-US browser: the word is still Hungarian (live review round 2).
		vi.stubGlobal('navigator', { languages: ['en-US'], language: 'en-US' });
		expect(formatBytes(0)).toBe('0 bájt');
		vi.unstubAllGlobals();
	});
});
