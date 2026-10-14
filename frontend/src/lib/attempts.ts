import type { TrackAttempt } from '$lib/api';

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

/** v35 (b): the path the attempt actually took, from the API's network_path. A row
 * without one either never reached the network or predates v29 recording it; only a
 * completed/failed pre-v29 row falls back to the old proxy-or-direct label. */
export function attemptVia(attempt: TrackAttempt): string {
	if (attempt.network_path === 'direct-ipv4') return 'direct · IPv4';
	if (attempt.network_path === 'direct-ipv6') return 'direct · IPv6';
	if (attempt.network_path === 'proxy') return `via proxy ${attempt.proxy_label ?? ''}`.trim();
	if (attempt.proxy_id) return 'via proxy';
	if (attempt.outcome === 'completed' || attempt.outcome === 'failed') return 'direct';
	return 'no network';
}

/** A collapsed run's paths, by family rather than by proxy address, so five proxied
 * attempts through five pool proxies read "via proxy ×5", not five addresses. */
export function summarizeVia(attempts: TrackAttempt[]): string {
	const counts = new Map<string, number>();
	for (const attempt of attempts) {
		const via = attemptVia(attempt).startsWith('via proxy') ? 'via proxy' : attemptVia(attempt);
		counts.set(via, (counts.get(via) ?? 0) + 1);
	}
	return [...counts].map(([via, n]) => (n > 1 ? `${via} ×${n}` : via)).join(', ');
}

/** "just now", "12m ago", "3h 05m ago", "2d 4h ago". */
export function relativeTime(iso: string, now: number): string {
	const seconds = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000));
	if (seconds < 60) return 'just now';
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ${String(minutes % 60).padStart(2, '0')}m ago`;
	return `${Math.floor(hours / 24)}d ${hours % 24}h ago`;
}

/** "0.4s", "24s", "3m 05s". */
export function formatDuration(seconds: number): string {
	if (seconds < 10) return `${seconds.toFixed(1)}s`;
	if (seconds < 60) return `${Math.round(seconds)}s`;
	const whole = Math.round(seconds);
	return `${Math.floor(whole / 60)}m ${String(whole % 60).padStart(2, '0')}s`;
}

/** v41 (F23): a countdown past 24h gets a days unit -- "1d 23:12:03", never "47:12:03". */
export function formatCountdown(ms: number): string {
	if (ms <= 0) return 'due now';
	const totalSeconds = Math.floor(ms / 1000);
	const d = Math.floor(totalSeconds / 86400);
	const h = Math.floor((totalSeconds % 86400) / 3600);
	const m = Math.floor((totalSeconds % 3600) / 60);
	const s = totalSeconds % 60;
	const pad = (n: number) => String(n).padStart(2, '0');
	if (d > 0) return `${d}d ${pad(h)}:${pad(m)}:${pad(s)}`;
	return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}
