import type { TrackAttempt } from '$lib/api';
import { formatNumber } from '$lib/i18n/format';
import * as m from '$lib/paraglide/messages';

/** One timeline entry: a single attempt, or a run of consecutive attempts that read the
 * same (outcome, error class, error text, note), newest first. */
export interface AttemptGroup {
	key: string;
	attempts: TrackAttempt[];
}

function sameReading(a: TrackAttempt, b: TrackAttempt): boolean {
	return (
		a.outcome === b.outcome &&
		a.error_type === b.error_type &&
		a.error_message === b.error_message &&
		a.warning_message === b.warning_message
	);
}

/** v41: the API answers oldest first; the timeline reads newest first, and a run of
 * identical consecutive readings collapses into one entry ("×5 · NO_OUTPUT"). Only
 * *consecutive* repeats merge, so the order of events is never rewritten. A group is keyed
 * by its *oldest* attempt, which stays put while a run grows at its newest end, so an open
 * run stays open (and keeps focus) when the next identical failure lands. */
export function groupAttempts(oldestFirst: TrackAttempt[]): AttemptGroup[] {
	const groups: AttemptGroup[] = [];
	for (const attempt of [...oldestFirst].reverse()) {
		const last = groups.at(-1);
		if (last && sameReading(last.attempts[0], attempt)) {
			last.attempts.push(attempt);
			last.key = attempt.id;
		} else groups.push({ key: attempt.id, attempts: [attempt] });
	}
	return groups;
}

/** v35 (b): the path an attempt actually took, from the API's network_path. A row without
 * one either never reached the network or predates v29 recording it; only a completed/failed
 * pre-v29 row falls back to the old proxy-or-direct reading. v46: a kind, so callers group
 * and compare paths without matching (translated) words. */
export type AttemptPath = 'direct-ipv4' | 'direct-ipv6' | 'proxy' | 'direct' | 'none';

export function attemptPath(attempt: TrackAttempt): AttemptPath {
	if (attempt.network_path === 'direct-ipv4' || attempt.network_path === 'direct-ipv6')
		return attempt.network_path;
	// v56: `proxy_label` too: a deleted proxy leaves `proxy_id` null but keeps its label (A4).
	if (attempt.network_path === 'proxy' || attempt.proxy_id || attempt.proxy_label) return 'proxy';
	if (attempt.outcome === 'completed' || attempt.outcome === 'failed') return 'direct';
	return 'none';
}

/** A path in words; a proxied one names its proxy when the API gave a label (`proxyLabel`
 * is shown as-is, never translated). */
export function pathLabel(path: AttemptPath, proxyLabel: string | null = null): string {
	switch (path) {
		case 'direct-ipv4':
			return m.attempt_via_direct_ipv4();
		case 'direct-ipv6':
			return m.attempt_via_direct_ipv6();
		case 'proxy':
			return proxyLabel ? m.attempt_via_proxy_named({ proxy: proxyLabel }) : m.attempt_via_proxy();
		case 'direct':
			return m.attempt_via_direct();
		case 'none':
			return m.attempt_via_none();
	}
}

export function attemptVia(attempt: TrackAttempt): string {
	// Only a row that recorded the proxy path carries its label (a pre-v29 proxied row doesn't).
	const label = attempt.network_path === 'proxy' ? attempt.proxy_label : null;
	return pathLabel(attemptPath(attempt), label);
}

/** A collapsed run's paths, by family rather than by proxy address, so five proxied
 * attempts through five pool proxies read "via proxy ×5", not five addresses. */
export function summarizeVia(attempts: TrackAttempt[]): string {
	const counts = new Map<AttemptPath, number>();
	for (const attempt of attempts) {
		const path = attemptPath(attempt);
		counts.set(path, (counts.get(path) ?? 0) + 1);
	}
	return [...counts]
		.map(([path, n]) =>
			n > 1
				? m.attempt_via_repeated({ via: pathLabel(path), times: formatNumber(n) })
				: pathLabel(path)
		)
		.join(', ');
}

/** "just now", "12m ago", "3h 05m ago", "2d 4h ago". */
export function relativeTime(iso: string, now: number): string {
	const seconds = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000));
	if (seconds < 60) return m.time_just_now();
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return m.time_minutes_ago({ minutes: formatNumber(minutes) });
	const hours = Math.floor(minutes / 60);
	// A whole hour or day has its own message: Hungarian says "2 órája", never "2 óra 0 perce"
	// (English keeps "2h 00m ago").
	if (hours < 24 && minutes % 60 === 0) return m.time_hours_ago({ hours: formatNumber(hours) });
	if (hours < 24)
		return m.time_hours_minutes_ago({
			hours: formatNumber(hours),
			minutes: formatNumber(minutes % 60),
			minutesPadded: String(minutes % 60).padStart(2, '0')
		});
	if (hours % 24 === 0) return m.time_days_ago({ days: formatNumber(Math.floor(hours / 24)) });
	return m.time_days_hours_ago({
		days: formatNumber(Math.floor(hours / 24)),
		hours: formatNumber(hours % 24)
	});
}

/** "0.4s", "24s", "3m 05s". */
export function formatDuration(seconds: number): string {
	// Rounded before the unit is picked, so 9.96s never reads "10.0s" nor 59.6s "60s".
	const tenths = Number(seconds.toFixed(1));
	if (tenths < 10)
		return m.time_seconds({
			seconds: formatNumber(tenths, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
		});
	const whole = Math.round(seconds);
	if (whole < 60) return m.time_seconds({ seconds: formatNumber(whole) });
	return m.time_minutes_seconds({
		minutes: formatNumber(Math.floor(whole / 60)),
		seconds: String(whole % 60).padStart(2, '0')
	});
}

/** v41 (F23): a countdown past 24h gets a days unit -- "1d 23:12:03", never "47:12:03". */
export function formatCountdown(ms: number): string {
	if (ms <= 0) return m.time_due_now();
	const totalSeconds = Math.floor(ms / 1000);
	const d = Math.floor(totalSeconds / 86400);
	const h = Math.floor((totalSeconds % 86400) / 3600);
	const min = Math.floor((totalSeconds % 3600) / 60);
	const s = totalSeconds % 60;
	const pad = (n: number) => String(n).padStart(2, '0');
	if (d > 0)
		return m.time_countdown_days({
			days: formatNumber(d),
			clock: `${pad(h)}:${pad(min)}:${pad(s)}`
		});
	return h > 0 ? `${h}:${pad(min)}:${pad(s)}` : `${min}:${pad(s)}`;
}
