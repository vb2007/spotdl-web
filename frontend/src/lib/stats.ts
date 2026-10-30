// v44: the admin stats page's pure logic, kept out of the components so it can be tested
// without a DOM: display names, the hold spans the breaker strip draws, and where an
// instant sits on the window's time axis.
// v46: every label is a function and every number and date goes through `Intl` with the
// active locale, so the page re-renders in place on a language switch.
import type { BreakerEvent, PathStats, RecordedWindow, StatsWindow } from '$lib/api';
import { counted, formatDateTime, formatNumber } from '$lib/i18n/format';
import * as m from '$lib/paraglide/messages';

export function pathLabel(path: PathStats['path']): string {
	switch (path) {
		case 'direct-ipv4':
			return m.stats_path_direct_ipv4();
		case 'direct-ipv6':
			return m.stats_path_direct_ipv6();
		case 'proxy':
			return m.stats_path_proxy();
		// A real attempt with no recorded path: pre-v29 rows, or beat's stale-track reclaim.
		default:
			return m.stats_unrecorded();
	}
}

/** Error types read as in the logs and alerts (machine names, the same in every language),
 * except `lookup`, which the UI has called "not found" since v19. */
export function errorTypeLabel(errorType: string): string {
	if (errorType === 'lookup') return m.state_lookup_failed();
	if (errorType === 'unknown') return m.stats_unrecorded();
	return errorType;
}

/** The colour a failure class takes, from DESIGN.md's five conditions: a verdict the
 * retry engine won't revisit is `fail`; one it retries is `waiting` (v41's rule: a failed
 * attempt the ladder will retry reads in the waiting blue); an unrecorded cause is idle. */
export function errorTypeCondition(errorType: string): 'fail' | 'waiting' | 'idle' {
	if (errorType === 'lookup') return 'fail';
	if (errorType === 'unknown') return 'idle';
	return 'waiting';
}

const percent = (fraction: number) => formatNumber(fraction, { style: 'percent' });

const BYTE_UNITS = ['byte', 'kilobyte', 'megabyte', 'gigabyte', 'terabyte'] as const;

/** v66: a size in decimal units ("3.1 GB", "3,1 GB"), as file managers read them. */
export function formatBytes(bytes: number): string {
	let value = Math.max(0, bytes);
	let unit = 0;
	while (value >= 1000 && unit < BYTE_UNITS.length - 1) {
		value /= 1000;
		unit += 1;
	}
	// Plain bytes in words, from the message files: Intl's word follows the browser's region when
	// the UI language and the region make no locale it knows (a Hungarian UI in an en-US browser
	// read "0 bytes"; live review round 2). The multiples are symbols, the same everywhere.
	if (unit === 0) return m.stats_bytes(counted(Math.round(value)));
	return formatNumber(value, {
		style: 'unit',
		unit: BYTE_UNITS[unit],
		unitDisplay: 'short',
		maximumFractionDigits: unit === 0 || value >= 100 ? 0 : 1
	});
}

export function formatRate(rate: number | null): string {
	if (rate === null) return '—';
	const value = rate * 100;
	// Never round a partial result up to 100% or down to 0%: "100%" must mean every one.
	if (value > 99 && value < 100) return `>${percent(0.99)}`;
	if (value > 0 && value < 1) return `<${percent(0.01)}`;
	return percent(Math.round(value) / 100);
}

/** A step or an age: "45s", "30m", "1h 30m", "6h", "5d" ("45 mp", "1 ó 30 p" in Hungarian). */
export function formatSpan(seconds: number): string {
	const n = (value: number) => formatNumber(value);
	if (seconds < 60) return m.stats_span_seconds({ n: n(Math.max(0, Math.round(seconds))) });
	const minutes = Math.round(seconds / 60);
	if (minutes < 60) return m.stats_span_minutes({ n: n(minutes) });
	const hours = Math.floor(minutes / 60);
	if (hours < 48)
		return minutes % 60 === 0 || hours >= 10
			? m.stats_span_hours({ n: n(hours) })
			: m.stats_span_hours_minutes({ h: n(hours), m: n(minutes % 60) });
	return m.stats_span_days({ n: n(Math.floor(hours / 24)) });
}

export function windowEnd(stats: RecordedWindow): number {
	const buckets = stats.failures.buckets;
	return Date.parse(buckets[buckets.length - 1]) + stats.bucket_seconds * 1000;
}

/** An instant's position on the window's axis, 0..1 (clamped). */
export function axisPosition(stats: RecordedWindow, iso: string): number {
	const start = Date.parse(stats.window_start);
	const end = windowEnd(stats);
	return Math.min(1, Math.max(0, (Date.parse(iso) - start) / (end - start)));
}

export interface HoldSpan {
	/** 0..1 on the window's axis. */
	from: number;
	to: number;
	startedAt: string;
	endedAt: string;
	stepSeconds: number | null;
	escalated: boolean;
	/** Ended early by the admin's release. */
	manual: boolean;
	/** Ended before its own scheduled end (a release, or a later trip taking over). */
	early: boolean;
	/** Still holding when the stats were read. */
	ongoing: boolean;
}

/** Each trip's pause as a span: from the trip to whichever comes first, its own end or
 * the release that cut it short. Events arrive oldest first. */
export function holdSpans(stats: RecordedWindow): HoldSpan[] {
	// v66: a user's own stats carry no breaker (it's everyone's): no holds to draw.
	const events = stats.breaker?.events ?? [];
	const generated = Date.parse(stats.generated_at);
	const spans: HoldSpan[] = [];
	events.forEach((event: BreakerEvent, index: number) => {
		if (event.kind === 'released' || event.paused_until === null) return;
		const pauseEnd = Date.parse(event.paused_until);
		// Whatever comes next ends this hold if it comes before the scheduled end: a release
		// (the admin's, or a success's), or a later trip taking over.
		const next = events[index + 1];
		let endedAt = event.paused_until;
		let manual = false;
		let early = false;
		if (next !== undefined && Date.parse(next.occurred_at) < pauseEnd) {
			endedAt = next.occurred_at;
			manual = next.kind === 'released' && next.manual;
			early = true;
		}
		// Over before the window began (e.g. released early, before it): nothing to draw, and
		// the one-bucket minimum width would otherwise paint it into the first bucket.
		if (Date.parse(endedAt) <= Date.parse(stats.window_start)) return;
		const ongoing = !manual && Date.parse(endedAt) > generated;
		spans.push({
			from: axisPosition(stats, event.occurred_at),
			// An ongoing hold is drawn up to now: the rest of it hasn't happened yet.
			to: axisPosition(stats, ongoing ? stats.generated_at : endedAt),
			startedAt: event.occurred_at,
			endedAt,
			stepSeconds: event.step_seconds,
			escalated: event.kind === 'escalated',
			manual,
			early,
			ongoing
		});
	});
	return spans;
}

/** Where a hold is drawn, 0..1 on the axis. One shorter than a bucket is widened to the whole
 * buckets it touches, so it never reads as a hairline and covers exactly the buckets
 * `bucketHeld` (the crosshair, the table) calls held. A longer one is drawn as it happened. */
export function holdGeometry(span: HoldSpan, n: number): { left: number; width: number } {
	if (span.to - span.from >= 1 / n) return { left: span.from, width: span.to - span.from };
	const left = Math.min(Math.floor(span.from * n), n - 1) / n;
	const right = Math.min(1, Math.max(Math.ceil(span.to * n) / n, left + 1 / n));
	return { left, width: right - left };
}

/** Whether the breaker held at any moment of bucket `index`. */
export function bucketHeld(stats: RecordedWindow, spans: HoldSpan[], index: number): boolean {
	const n = stats.failures.buckets.length;
	const from = index / n;
	const to = (index + 1) / n;
	return spans.some((span) => span.from < to && span.to > from);
}

/** An instant (a hold's start or end) as date and time, on the same clock as the buckets. */
export function instantLabel(stats: RecordedWindow, iso: string): string {
	return formatDateTime(new Date(Date.parse(iso) + stats.utc_offset_minutes * 60_000), {
		timeZone: 'UTC',
		month: 'short',
		day: 'numeric',
		hour: '2-digit',
		minute: '2-digit'
	});
}

/** A bucket's label, read on the clock the buckets were cut on (the offset the page sent),
 * not the browser's own zone: across a DST change that zone's offset differs for the older
 * buckets, and a day bucket would be labelled with the day before (review round 1). The
 * axis shows only every `axisTickEvery`th label; the tooltip and the table show each one. */
export function bucketLabel(stats: RecordedWindow, iso: string, long = false): string {
	const shift = stats.utc_offset_minutes * 60_000;
	const date = new Date(Date.parse(iso) + shift);
	const utc = { timeZone: 'UTC' } as const;
	if (stats.bucket_seconds < 86400) {
		// The axis says "06:00" (v47: a bare "7 13 19" read as unitless numbers in Hungarian);
		// the tooltip and table give the full range.
		if (!long) return formatDateTime(date, { ...utc, hour: '2-digit', minute: '2-digit' });
		const hour = formatDateTime(date, { ...utc, hour: '2-digit', minute: '2-digit' });
		const next = new Date(date.getTime() + stats.bucket_seconds * 1000);
		return `${hour}–${formatDateTime(next, { ...utc, hour: '2-digit', minute: '2-digit' })}`;
	}
	return formatDateTime(
		date,
		long
			? { ...utc, weekday: 'short', month: 'short', day: 'numeric' }
			: stats.failures.buckets.length <= 7
				? { ...utc, weekday: 'short', day: 'numeric' }
				: { ...utc, month: 'short', day: 'numeric' }
	);
}

export function axisTickEvery(stats: RecordedWindow): number {
	const n = stats.failures.buckets.length;
	if (n <= 7) return 1;
	if (n <= 24) return 6;
	return 7;
}

/** The tallest column across every failure row: one shared y-scale, so rows compare. */
export function failurePeak(stats: RecordedWindow): number {
	let peak = 0;
	for (const series of stats.failures.series)
		for (const count of series.counts) peak = Math.max(peak, count);
	return peak;
}

export function windowHeading(window: StatsWindow): string {
	if (window === '7d') return m.stats_window_heading_7d();
	if (window === '30d') return m.stats_window_heading_30d();
	return m.stats_window_heading_24h();
}

/** The window switch's own button text ("24h", "7d", "30d"). */
export function windowName(window: StatsWindow): string {
	if (window === '7d') return m.stats_window_7d();
	if (window === '30d') return m.stats_window_30d();
	return m.stats_window_24h();
}

/** One piece of a message split at its values: plain text (`key` null), or the value named
 * `key`. A sentence whose numbers sit in their own markup ("Proxies: <mono>3</mono> switched
 * on") stays one message, in the order its language puts them. */
export interface Slot {
	key: string | null;
	text: string;
}

export function slotted<P extends Record<string, string>>(
	message: (values: P) => string,
	values: P
): Slot[] {
	const keys = Object.keys(values);
	const marked = Object.fromEntries(keys.map((key, i) => [key, `\uE000${i}\uE001`])) as P;
	return message(marked)
		.split(/\uE000(\d+)\uE001/)
		.map((text, i) =>
			i % 2 === 1
				? { key: keys[Number(text)], text: values[keys[Number(text)]] }
				: { key: null, text }
		)
		.filter((slot) => slot.text !== '');
}
