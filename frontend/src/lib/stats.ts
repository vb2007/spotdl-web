// v44: the admin stats page's pure logic, kept out of the components so it can be tested
// without a DOM: display names, the hold spans the breaker strip draws, and where an
// instant sits on the window's time axis.
import type { AdminStats, BreakerEvent, PathStats } from '$lib/api';

export const PATH_LABEL: Record<PathStats['path'], string> = {
	'direct-ipv4': 'direct · IPv4',
	'direct-ipv6': 'direct · IPv6',
	proxy: 'proxy',
	// A real attempt with no recorded path: pre-v29 rows, or beat's stale-track reclaim.
	unknown: 'unrecorded'
};

/** Error types read as in the logs and alerts (machine names), except `lookup`, which the
 * UI has called "not found" since v19. */
export function errorTypeLabel(errorType: string): string {
	if (errorType === 'lookup') return 'not found';
	if (errorType === 'unknown') return 'unrecorded';
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

export function formatRate(rate: number | null): string {
	if (rate === null) return '—';
	const percent = rate * 100;
	// Never round a partial result up to 100% or down to 0%: "100%" must mean every one.
	if (percent > 99 && percent < 100) return '>99%';
	if (percent > 0 && percent < 1) return '<1%';
	return `${Math.round(percent)}%`;
}

/** A step or an age: "45s", "30m", "1h 30m", "6h", "5d". */
export function formatSpan(seconds: number): string {
	if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
	const minutes = Math.round(seconds / 60);
	if (minutes < 60) return `${minutes}m`;
	const hours = Math.floor(minutes / 60);
	if (hours < 48)
		return minutes % 60 === 0 || hours >= 10 ? `${hours}h` : `${hours}h ${minutes % 60}m`;
	return `${Math.floor(hours / 24)}d`;
}

export function windowEnd(stats: AdminStats): number {
	const buckets = stats.failures.buckets;
	return Date.parse(buckets[buckets.length - 1]) + stats.bucket_seconds * 1000;
}

/** An instant's position on the window's axis, 0..1 (clamped). */
export function axisPosition(stats: AdminStats, iso: string): number {
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
export function holdSpans(stats: AdminStats): HoldSpan[] {
	const events = stats.breaker.events;
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
export function bucketHeld(stats: AdminStats, spans: HoldSpan[], index: number): boolean {
	const n = stats.failures.buckets.length;
	const from = index / n;
	const to = (index + 1) / n;
	return spans.some((span) => span.from < to && span.to > from);
}

/** An instant (a hold's start or end) as date and time, on the same clock as the buckets. */
export function instantLabel(stats: AdminStats, iso: string): string {
	return new Date(Date.parse(iso) + stats.utc_offset_minutes * 60_000).toLocaleString([], {
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
export function bucketLabel(stats: AdminStats, iso: string, long = false): string {
	const shift = stats.utc_offset_minutes * 60_000;
	const date = new Date(Date.parse(iso) + shift);
	const utc = { timeZone: 'UTC' } as const;
	if (stats.bucket_seconds < 86400) {
		// The axis says "6 AM" / "06"; the tooltip and table give the full range.
		if (!long) return date.toLocaleTimeString([], { ...utc, hour: 'numeric' });
		const hour = date.toLocaleTimeString([], { ...utc, hour: '2-digit', minute: '2-digit' });
		const next = new Date(date.getTime() + stats.bucket_seconds * 1000);
		return `${hour}–${next.toLocaleTimeString([], { ...utc, hour: '2-digit', minute: '2-digit' })}`;
	}
	return date.toLocaleDateString(
		[],
		long
			? { ...utc, weekday: 'short', month: 'short', day: 'numeric' }
			: stats.failures.buckets.length <= 7
				? { ...utc, weekday: 'short', day: 'numeric' }
				: { ...utc, month: 'short', day: 'numeric' }
	);
}

export function axisTickEvery(stats: AdminStats): number {
	const n = stats.failures.buckets.length;
	if (n <= 7) return 1;
	if (n <= 24) return 6;
	return 7;
}

/** The tallest column across every failure row: one shared y-scale, so rows compare. */
export function failurePeak(stats: AdminStats): number {
	let peak = 0;
	for (const series of stats.failures.series)
		for (const count of series.counts) peak = Math.max(peak, count);
	return peak;
}

export const WINDOW_HEADING: Record<AdminStats['window'], string> = {
	'24h': 'Last 24 hours',
	'7d': 'Last 7 days',
	'30d': 'Last 30 days'
};
