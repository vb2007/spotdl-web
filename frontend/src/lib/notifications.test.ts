import { describe, expect, it } from 'vitest';
import type { JobStatusEvent } from '$lib/api';
import { isSettle } from '$lib/notifications';

function event(status: string, prev?: string | null, archived = false): JobStatusEvent {
	const e: JobStatusEvent = { type: 'job.status', job_id: 'j', status, archived, ts: 't' };
	if (prev !== undefined) e.prev_status = prev;
	return e;
}

describe('v66: isSettle', () => {
	it('is a move into settled from a status that was not settled', () => {
		expect(isSettle(event('settled:complete', 'active'))).toBe(true);
		expect(isSettle(event('settled:partial', 'waiting'))).toBe(true);
		expect(isSettle(event('settled:complete', 'expanding'))).toBe(true);
		// A new job that is done at once (every track already in the library).
		expect(isSettle(event('settled:complete', null))).toBe(true);
	});

	it('is not any other move', () => {
		expect(isSettle(event('active', 'expanding'))).toBe(false);
		expect(isSettle(event('cancelled', 'active'))).toBe(false);
		expect(isSettle(event('failed', 'expanding'))).toBe(false);
		// Settled already: one outcome turning into the other is no new "done".
		expect(isSettle(event('settled:partial', 'settled:complete'))).toBe(false);
		// The server doesn't know what the job left.
		expect(isSettle(event('settled:complete'))).toBe(false);
		// Archived: old news.
		expect(isSettle(event('settled:complete', 'active', true))).toBe(false);
	});
});
