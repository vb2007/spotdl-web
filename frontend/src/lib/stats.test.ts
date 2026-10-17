import { describe, expect, it } from 'vitest';
import type { AdminStats, BreakerEvent } from '$lib/api';
import {
	axisPosition,
	bucketHeld,
	bucketLabel,
	errorTypeCondition,
	errorTypeLabel,
	failurePeak,
	formatRate,
	formatSpan,
	holdSpans
} from '$lib/stats';

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
