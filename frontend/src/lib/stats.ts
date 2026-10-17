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
		const release = events
			.slice(index + 1)
			.find(
				(later) =>
					later.kind === 'released' || later.kind === 'escalated' || later.kind === 'tripped'
			);
		let endedAt = event.paused_until;
		let manual = false;
		if (
			release !== undefined &&
			release.kind === 'released' &&
			Date.parse(release.occurred_at) < pauseEnd
		) {
			endedAt = release.occurred_at;
			manual = release.manual;
		}
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
			ongoing
		});
	});
	return spans;
}

/** Whether the breaker held at any moment of bucket `index`. */
export function bucketHeld(stats: AdminStats, spans: HoldSpan[], index: number): boolean {
	const n = stats.failures.buckets.length;
	const from = index / n;
	const to = (index + 1) / n;
	return spans.some((span) => span.from < to && span.to > from);
}

/** Axis tick labels: every bucket gets a full label (tooltip, table); the axis shows only
 * every `step`th, so a 30-day or 24-hour row never crowds. */
export function bucketLabel(stats: AdminStats, iso: string, long = false): string {
	const date = new Date(iso);
	if (stats.bucket_seconds < 86400) {
		// The axis says "6 AM" / "06"; the tooltip and table give the full range.
		if (!long) return date.toLocaleTimeString([], { hour: 'numeric' });
		const hour = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
		const next = new Date(date.getTime() + stats.bucket_seconds * 1000);
		return `${hour}–${next.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
	}
	return date.toLocaleDateString(
		[],
		long
			? { weekday: 'short', month: 'short', day: 'numeric' }
			: stats.failures.buckets.length <= 7
				? { weekday: 'short', day: 'numeric' }
				: { month: 'short', day: 'numeric' }
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
