import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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

// The one-tab-announces protocol, with two tabs: two copies of the module on a shared in-memory
// BroadcastChannel, a recording Notification and a stubbed job read.
describe('v66: one tab announces', () => {
	type Listener = (event: { data: unknown }) => void;
	let bus: Set<{ listeners: Listener[]; name: string }>;
	let shown: string[];
	// A message that arrives only after both tabs' windows ended: the race the lowest-id rule is for.
	let slow = false;

	beforeEach(() => {
		vi.useFakeTimers();
		vi.resetModules();
		bus = new Set();
		shown = [];
		slow = false;
		class Channel {
			listeners: Listener[] = [];
			constructor(public name: string) {
				bus.add(this);
			}
			addEventListener(_type: string, listener: Listener) {
				this.listeners.push(listener);
			}
			postMessage(data: unknown) {
				// Never to itself, as a real channel; delivered asynchronously.
				for (const other of bus)
					if (other !== this && other.name === this.name) {
						const deliver = () => other.listeners.forEach((l) => l({ data }));
						if (slow) setTimeout(deliver, 0);
						else queueMicrotask(deliver);
					}
			}
		}
		class Recorded {
			static permission = 'granted';
			onclick: (() => void) | null = null;
			constructor(title: string) {
				shown.push(title);
			}
			close() {}
		}
		vi.stubGlobal('BroadcastChannel', Channel);
		vi.stubGlobal('window', { Notification: Recorded, focus() {} });
		vi.stubGlobal('Notification', Recorded);
		vi.stubGlobal('document', { documentElement: { lang: 'en' } });
		vi.doMock('$lib/api', () => ({
			getJob: async (id: string) => ({ id, title: `Album ${id}`, track_counts: { completed: 2 } })
		}));
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
		vi.doUnmock('$lib/api');
	});

	async function tab() {
		const module = await import('$lib/notifications');
		module.adopt('a@example.com', true);
		return module;
	}

	const settle: JobStatusEvent = {
		type: 'job.status',
		job_id: 'j1',
		status: 'settled:complete',
		prev_status: 'active',
		archived: false,
		ts: '2026-10-30T18:00:00Z'
	};

	it('shows one notification for an event both tabs receive', async () => {
		const one = await tab();
		vi.resetModules();
		const two = await tab();
		one.observe(settle);
		two.observe(settle);
		await vi.advanceTimersByTimeAsync(1000);
		expect(shown).toEqual(['Album j1']);
	});

	it('shows one when both tabs decide before either hears the other', async () => {
		const one = await tab();
		vi.resetModules();
		const two = await tab();
		slow = true;
		one.observe(settle);
		two.observe(settle);
		await vi.advanceTimersByTimeAsync(1000);
		expect(shown).toEqual(['Album j1']);
	});

	it('ignores a late offer for an event already decided', async () => {
		const one = await tab();
		vi.resetModules();
		const two = await tab();
		one.observe(settle);
		await vi.advanceTimersByTimeAsync(1000);
		two.observe(settle);
		await vi.advanceTimersByTimeAsync(1000);
		expect(shown).toEqual(['Album j1']);
	});

	it('follows another tab turning it off', async () => {
		const one = await tab();
		vi.resetModules();
		const two = await tab();
		two.setEnabled(false);
		await vi.advanceTimersByTimeAsync(10);
		one.observe(settle);
		await vi.advanceTimersByTimeAsync(1000);
		expect(shown).toEqual([]);
		// A `/me` read from before that save doesn't turn it back on.
		one.adopt('a@example.com', true);
		one.observe({ ...settle, ts: 'later' });
		await vi.advanceTimersByTimeAsync(1000);
		expect(shown).toEqual([]);
	});
});

// The admin's own `mine` stream (review rounds 2 and 3): one at a time, checked against the
// session at every open, restarted when silent or after a failed check.
describe('v66: the own stream', () => {
	let streams: FakeSource[];
	let meAnswers: (() => Promise<{ email: string }>)[];

	class FakeSource {
		static CLOSED = 2;
		readyState = 0;
		closed = false;
		onopen: (() => void) | null = null;
		onmessage: ((e: { data: string }) => void) | null = null;
		onerror: (() => void) | null = null;
		listeners: Record<string, () => void> = {};
		constructor() {
			streams.push(this);
		}
		addEventListener(type: string, listener: () => void) {
			this.listeners[type] = listener;
		}
		close() {
			this.closed = true;
			this.readyState = 2;
		}
	}

	beforeEach(() => {
		vi.useFakeTimers();
		vi.resetModules();
		streams = [];
		meAnswers = [];
		vi.stubGlobal('EventSource', FakeSource);
		vi.stubGlobal('window', { Notification: { permission: 'granted' } });
		vi.stubGlobal('Notification', { permission: 'granted' });
		vi.doMock('$lib/api', () => ({
			createEventSource: () => new FakeSource(),
			me: () => (meAnswers.shift() ?? (async () => ({ email: 'admin@example.com' })))()
		}));
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
		vi.doUnmock('$lib/api');
	});

	async function open() {
		const module = await import('$lib/notifications');
		module.adopt('admin@example.com', true);
		module.setOwnStream(true);
		return module;
	}

	it('is opened once, however often it is wanted', async () => {
		const n = await open();
		n.setOwnStream(true);
		n.checkOwnStream();
		expect(streams).toHaveLength(1);
	});

	it('starts over when silent past the heartbeat, and not while it hears one', async () => {
		const n = await open();
		await vi.advanceTimersByTimeAsync(10_000);
		streams[0].listeners.heartbeat();
		await vi.advanceTimersByTimeAsync(10_000);
		n.checkOwnStream();
		expect(streams).toHaveLength(1);
		await vi.advanceTimersByTimeAsync(20_000);
		n.checkOwnStream();
		expect(streams).toHaveLength(2);
		expect(streams[0].closed).toBe(true);
	});

	it('retries after a failed identity check instead of staying deaf', async () => {
		await open();
		meAnswers.push(async () => {
			throw new Error('502');
		});
		await streams[0].onopen?.();
		expect(streams[0].closed).toBe(true);
		await vi.advanceTimersByTimeAsync(1500);
		expect(streams).toHaveLength(2);
	});

	it('stops for good on someone else’s session', async () => {
		const n = await open();
		meAnswers.push(async () => ({ email: 'someone@example.com' }));
		await streams[0].onopen?.();
		expect(streams[0].closed).toBe(true);
		await vi.advanceTimersByTimeAsync(60_000);
		n.checkOwnStream();
		expect(streams).toHaveLength(1);
	});
});
