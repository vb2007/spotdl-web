import type { TrackState } from '$lib/api';
import * as m from '$lib/paraglide/messages';

/** v46: the state words more than one surface prints, as functions (a constant would freeze
 * the language it was built in). */

/** A job's rollup status, keyed by `api.statusKey()`'s token (the state filter's values). */
export function jobStatusLabel(token: string): string {
	switch (token) {
		case 'expanding':
			return m.status_expanding();
		case 'active':
			return m.status_active();
		case 'waiting':
			return m.status_waiting();
		case 'settled:partial':
			return m.status_settled_partial();
		case 'settled:complete':
			return m.status_settled_complete();
		case 'cancelled':
			return m.status_cancelled();
		case 'failed':
			return m.status_failed();
		default:
			return token;
	}
}

export function trackStateLabel(state: TrackState | string): string {
	switch (state) {
		case 'pending':
			return m.state_pending();
		case 'queued':
			return m.state_queued();
		case 'downloading':
			return m.state_downloading();
		case 'completed':
			return m.state_completed();
		case 'waiting':
			return m.state_waiting();
		case 'lookup_failed':
			return m.state_lookup_failed();
		case 'skipped_duplicate':
			return m.state_skipped_duplicate();
		case 'cancelled':
			return m.state_cancelled();
		default:
			return state;
	}
}
