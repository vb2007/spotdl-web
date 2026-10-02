import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Job, JobsPage, StreamEvent, TracksPage, TrackWithJob } from '$lib/api';

vi.mock('$lib/api', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api')>();
	return {
		...actual,
		listJobsPage: vi.fn(),
		listTracksPage: vi.fn(),
		getJob: vi.fn()
	};
});

const api = await import('$lib/api');
const { queue } = await import('$lib/stores/queue');

const listJobsPage = vi.mocked(api.listJobsPage);
const listTracksPage = vi.mocked(api.listTracksPage);
const getJob = vi.mocked(api.getJob);

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((r) => (resolve = r));
	return { promise, resolve };
}

function job(id: string, state: Job['state'], lifecycle: Job['status']['lifecycle']): Job {
	return {
		id,
		source_url: `https://open.spotify.com/track/${id}`,
		source_type: 'track',
		state,
		priority: 0,
		error: null,
		created_at: '2026-10-01T18:00:00+00:00',
		archived_at: null,
		track_counts: {},
		owner_email: 'a@example.com',
		owner_username: null,
		title: id,
		status: { lifecycle, outcome: null }
	};
}

function downloadingTrack(id: string, jobId = 'job-1'): TrackWithJob {
	return {
		id,
		job_id: jobId,
		state: 'downloading',
		title: 'Africa',
		artists: ['TOTO'],
		album: 'Toto IV',
		spotify_track_id: 'sp',
		attempt_count: 0,
		attempts_made: 0,
		failure_count: 0,
		scheduled_at: null,
		last_error: null,
		last_error_type: null,
		job: {
			id: jobId,
			source_url: 'u',
			source_type: 'track',
			owner_email: 'a@example.com',
			owner_username: null,
			title: 'Africa'
		}
	};
}

function jobsPage(items: Job[], next_cursor: string | null = null): JobsPage {
	return { items, next_cursor, total_estimate: items.length, counts_by_status: {} };
}

function tracksPage(items: TrackWithJob[], next_cursor: string | null = null): TracksPage {
	return { items, next_cursor, counts_by_state: {} };
}

function trackEvent(trackId: string, state: TrackWithJob['state'], progress?: number) {
	return {
		type: 'track.state',
		track_id: trackId,
		job_id: 'job-1',
		state,
		progress,
		title: 'Africa',
		artists: ['TOTO'],
		album: 'Toto IV',
		ts: '2026-10-01T18:00:01+00:00'
	} satisfies StreamEvent;
}

/** Routes each listing call to the right fake: the page's own reload (no status filter)
 * always gets an empty page; the incoming/active hydrations get the given responses. */
function routeLists(opts: {
	incoming?: () => Promise<JobsPage>;
	active?: () => Promise<TracksPage>;
}) {
	listJobsPage.mockImplementation((params = {}) =>
		params.status?.includes('expanding')
			? (opts.incoming?.() ?? Promise.resolve(jobsPage([])))
			: Promise.resolve(jobsPage([]))
	);
	listTracksPage.mockImplementation(() => opts.active?.() ?? Promise.resolve(tracksPage([])));
}

const hydrationCalls = () => ({
	incoming: listJobsPage.mock.calls.filter(([p]) => p?.status?.includes('expanding')),
	active: listTracksPage.mock.calls.filter(([p]) => p?.state?.includes('downloading'))
});

beforeEach(() => {
	vi.useFakeTimers();
	queue.reset();
	vi.resetAllMocks();
});

afterEach(() => {
	queue.reset();
	vi.useRealTimers();
});

describe('v34 live hydration', () => {
	it('hydrates a hard reload: downloading track with its metadata, expanding + failed jobs', async () => {
		routeLists({
			incoming: async () =>
				jobsPage([job('exp', 'expanding', 'expanding'), job('bad', 'failed', 'failed')]),
			active: async () => tracksPage([downloadingTrack('t1')])
		});
		await queue.reload();

		const lanes = get(queue.activeTracks);
		expect(lanes).toHaveLength(1);
		expect(lanes[0]).toMatchObject({ id: 't1', title: 'Africa', artists: ['TOTO'] });
		expect(lanes[0]).not.toHaveProperty('job');
		expect(
			get(queue.incomingJobs)
				.map((j) => j.id)
				.sort()
		).toEqual(['bad', 'exp']);
	});

	it('issues exactly one bulk request per overlay per reload, with the right filters', async () => {
		routeLists({});
		await queue.reload();
		const calls = hydrationCalls();
		expect(calls.incoming).toHaveLength(1);
		expect(calls.incoming[0][0]).toMatchObject({
			status: ['expanding', 'failed'],
			allUsers: false
		});
		expect(calls.active).toHaveLength(1);
		expect(calls.active[0][0]).toMatchObject({
			state: ['downloading'],
			includeArchived: true,
			allUsers: false,
			limit: 1000
		});
		expect(getJob).not.toHaveBeenCalled();
	});

	it('race: downloading -> completed over SSE while hydration is in flight never resurrects the track', async () => {
		const active = deferred<TracksPage>();
		routeLists({ active: () => active.promise });
		const reloading = queue.reload();

		await queue.applyEvent(trackEvent('t1', 'downloading', 70));
		await queue.applyEvent(trackEvent('t1', 'completed'));
		expect(get(queue.activeTracks)).toHaveLength(0);

		// The snapshot was read before the completion landed -- it still says downloading.
		active.resolve(tracksPage([downloadingTrack('t1')]));
		await reloading;
		expect(get(queue.activeTracks)).toHaveLength(0);
	});

	it('race: a job event during an in-flight incoming hydration wins over the snapshot, even before its own fetch resolves', async () => {
		const incoming = deferred<JobsPage>();
		routeLists({ incoming: () => incoming.promise });
		const fetched = deferred<Job>();
		getJob.mockReturnValue(fetched.promise);
		const reloading = queue.reload();

		// The event lands; its getJob is still pending when the (older) snapshot arrives.
		const handling = queue.applyEvent({
			type: 'job.state',
			job_id: 'exp',
			state: 'expanded',
			ts: '2026-10-01T18:00:02+00:00'
		});
		incoming.resolve(jobsPage([job('exp', 'expanding', 'expanding')]));
		await reloading;
		expect(get(queue.incomingJobs)).toHaveLength(0);

		fetched.resolve({ ...job('exp', 'expanded', 'active'), track_counts: { queued: 1 } });
		await handling;
		expect(get(queue.incomingJobs)).toHaveLength(0);
	});

	it('a reconnect re-hydrates to one lane per track and keeps the in-memory progress', async () => {
		routeLists({
			incoming: async () => jobsPage([job('exp', 'expanding', 'expanding')]),
			active: async () => tracksPage([downloadingTrack('t1')])
		});
		await queue.reload();
		await queue.applyEvent(trackEvent('t1', 'downloading', 40));
		await queue.reload();

		const lanes = get(queue.activeTracks);
		expect(lanes).toHaveLength(1);
		// The in-memory progress survives a re-hydration; REST has none to offer.
		expect(lanes[0].progress).toBe(40);
		expect(get(queue.incomingJobs)).toHaveLength(1);
	});

	it('a complete snapshot drops a lane whose ending event was missed, but leaves a grace-window lane to its timer', async () => {
		routeLists({});
		await queue.applyEvent(trackEvent('missed', 'downloading', 25));
		await queue.applyEvent(trackEvent('grace', 'downloading', 25));
		await queue.applyEvent(trackEvent('grace', 'waiting'));
		await queue.reload();

		expect(get(queue.activeTracks).map((t) => t.id)).toEqual(['grace']);
		vi.advanceTimersByTime(60_000);
		expect(get(queue.activeTracks)).toHaveLength(0);
	});

	it('a truncated snapshot (next_cursor set) proves nothing about absent entries', async () => {
		queue.addJob(job('mine', 'expanding', 'expanding'));
		routeLists({
			incoming: async () => jobsPage([job('other', 'failed', 'failed')], 'cursor'),
			active: async () => tracksPage([], 'cursor')
		});
		await queue.applyEvent(trackEvent('t1', 'downloading', 10));
		await queue.reload();
		expect(
			get(queue.incomingJobs)
				.map((j) => j.id)
				.sort()
		).toEqual(['mine', 'other']);
		expect(get(queue.activeTracks)).toHaveLength(1);
	});

	it('reset() while a hydration is in flight: nothing repopulates (v22 store-reset invariant)', async () => {
		const incoming = deferred<JobsPage>();
		const active = deferred<TracksPage>();
		routeLists({ incoming: () => incoming.promise, active: () => active.promise });
		const reloading = queue.reload();

		queue.reset();
		incoming.resolve(jobsPage([job('a-job', 'expanding', 'expanding')]));
		active.resolve(tracksPage([downloadingTrack('a-track')]));
		await reloading;

		expect(get(queue.incomingJobs)).toHaveLength(0);
		expect(get(queue.activeTracks)).toHaveLength(0);
	});

	it('a scope switch drops the old scope’s in-flight snapshot; the reconnect’s resync hydrates the new scope', async () => {
		const mineActive = deferred<TracksPage>();
		routeLists({ active: () => mineActive.promise });
		const firstReload = queue.reload();

		queue.setAllUsers(true);
		expect(get(queue.page)).toMatchObject({ items: [], loading: true, totalEstimate: 0 });

		// The superseded mine-scope response lands late -- it must not leak in.
		mineActive.resolve(tracksPage([downloadingTrack('mine-scope-stale')]));
		await firstReload;
		expect(get(queue.activeTracks)).toHaveLength(0);

		// What the page's stream onopen does after reconnecting under the new scope.
		routeLists({
			incoming: async () => jobsPage([job('someone-elses', 'expanding', 'expanding')]),
			active: async () => tracksPage([downloadingTrack('global')])
		});
		await queue.reload();
		expect(get(queue.activeTracks).map((t) => t.id)).toEqual(['global']);
		expect(hydrationCalls().active.at(-1)?.[0]).toMatchObject({ allUsers: true });
		expect(hydrationCalls().incoming.at(-1)?.[0]).toMatchObject({ allUsers: true });

		routeLists({});
		queue.setAllUsers(false);
		expect(get(queue.activeTracks)).toHaveLength(0);
		expect(get(queue.incomingJobs)).toHaveLength(0);
		await queue.reload();
		expect(hydrationCalls().active.at(-1)?.[0]).toMatchObject({ allUsers: false });
	});

	it('setAllUsers itself fetches nothing (the reconnect resyncs); a late old-scope page response never lands', async () => {
		const oldPage = deferred<JobsPage>();
		listJobsPage.mockImplementation((params = {}) =>
			params.status?.includes('expanding') ? Promise.resolve(jobsPage([])) : oldPage.promise
		);
		listTracksPage.mockResolvedValue(tracksPage([]));
		const reloading = queue.reload();
		const callsBefore = listJobsPage.mock.calls.length + listTracksPage.mock.calls.length;

		queue.setAllUsers(true);
		expect(listJobsPage.mock.calls.length + listTracksPage.mock.calls.length).toBe(callsBefore);

		oldPage.resolve(jobsPage([job('old-scope-row', 'expanded', 'active')]));
		await reloading;
		expect(get(queue.page)).toMatchObject({ items: [], loading: true });
	});

	it('a filter change reloads only the page, never the live overlays', async () => {
		routeLists({});
		queue.setFilters({ sort: 'title' });
		await vi.waitFor(() => expect(listJobsPage).toHaveBeenCalled());
		expect(hydrationCalls().incoming).toHaveLength(0);
		expect(hydrationCalls().active).toHaveLength(0);
	});

	it('a lane in its grace window does not lend its old progress to a new attempt', async () => {
		routeLists({ active: async () => tracksPage([downloadingTrack('t1')]) });
		await queue.applyEvent(trackEvent('t1', 'downloading', 100));
		await queue.applyEvent(trackEvent('t1', 'waiting'));
		await queue.reload();
		expect(get(queue.activeTracks)[0]).toMatchObject({ state: 'downloading', progress: undefined });
	});

	it('a job event whose fetch resolves after reset() never lands in the next identity', async () => {
		routeLists({});
		const fetched = deferred<Job>();
		getJob.mockReturnValue(fetched.promise);
		const handling = queue.applyEvent({
			type: 'job.state',
			job_id: 'a-job',
			state: 'failed',
			ts: '2026-10-01T18:00:03+00:00'
		});
		queue.reset();
		fetched.resolve(job('a-job', 'failed', 'failed'));
		await handling;
		expect(get(queue.incomingJobs)).toHaveLength(0);
	});

	it('a job event whose fetch resolves after a scope switch never lands in the new scope', async () => {
		routeLists({});
		const fetched = deferred<Job>();
		getJob.mockReturnValue(fetched.promise);
		queue.setAllUsers(true);
		const handling = queue.applyEvent({
			type: 'job.state',
			job_id: 'someone-elses',
			state: 'expanding',
			ts: '2026-10-01T18:00:03+00:00'
		});
		queue.setAllUsers(false);
		// Let the new scope's hydration fully merge first, so it can't mask the late fetch
		// by pruning it afterwards -- the order that actually leaks.
		for (let i = 0; i < 20; i++) await Promise.resolve();
		fetched.resolve(job('someone-elses', 'expanding', 'expanding'));
		await handling;
		expect(get(queue.incomingJobs)).toHaveLength(0);
	});

	it('an archived failed job leaves the overlay live, matching the hydration rule', async () => {
		queue.addJob(job('bad', 'failed', 'failed'));
		getJob.mockResolvedValue({
			...job('bad', 'failed', 'failed'),
			archived_at: '2026-10-01T18:05:00+00:00'
		});
		await queue.applyEvent({
			type: 'job.state',
			job_id: 'bad',
			state: 'failed',
			archived: true,
			ts: '2026-10-01T18:05:00+00:00'
		});
		expect(get(queue.incomingJobs)).toHaveLength(0);
	});

	describe('progress across a hard reload (v34.2, localStorage)', () => {
		function fakeStorage() {
			const data = new Map<string, string>();
			return {
				data,
				getItem: (k: string) => data.get(k) ?? null,
				setItem: (k: string, v: string) => void data.set(k, v),
				removeItem: (k: string) => void data.delete(k)
			};
		}

		afterEach(() => vi.unstubAllGlobals());

		/** A hard reload: a brand-new store module (and api mock) in the same browser,
		 * i.e. the same localStorage -- never `reset()`, which is logout and clears it. */
		async function hardReload(active: TracksPage) {
			vi.resetModules();
			const freshApi = await import('$lib/api');
			const fresh = (await import('$lib/stores/queue')).queue;
			vi.mocked(freshApi.listJobsPage).mockResolvedValue(jobsPage([]));
			vi.mocked(freshApi.listTracksPage).mockResolvedValue(active);
			await fresh.reload();
			return get(fresh.activeTracks);
		}

		it('a hard reload shows this browser’s last tick for the same attempt', async () => {
			vi.stubGlobal('localStorage', fakeStorage());
			await queue.applyEvent(trackEvent('t1', 'downloading', 70));
			const lanes = await hardReload(tracksPage([downloadingTrack('t1')]));
			expect(lanes[0].progress).toBe(70);
		});

		it('a retry’s lane created purely from SSE keys its cache on the event’s attempt_count', async () => {
			vi.stubGlobal('localStorage', fakeStorage());
			await queue.applyEvent({ ...trackEvent('t1', 'downloading', 60), attempt_count: 3 });
			const lanes = await hardReload(tracksPage([{ ...downloadingTrack('t1'), attempt_count: 3 }]));
			expect(lanes[0].progress).toBe(60);
		});

		it('ticks are remembered as they land, and forgotten when the track leaves downloading', async () => {
			const store = fakeStorage();
			vi.stubGlobal('localStorage', store);
			await queue.applyEvent(trackEvent('t1', 'downloading', 40));
			expect(JSON.parse(store.data.get('spotdl:live-progress:v1')!).t1.progress).toBe(40);
			await queue.applyEvent(trackEvent('t1', 'completed'));
			expect(store.data.has('spotdl:live-progress:v1')).toBe(false);
		});

		it('a different attempt never inherits the stored progress', async () => {
			vi.stubGlobal('localStorage', fakeStorage());
			const { rememberProgress } = await import('$lib/stores/progressCache');
			rememberProgress('t1', 90, 0);
			routeLists({
				active: async () => tracksPage([{ ...downloadingTrack('t1'), attempt_count: 1 }])
			});
			await queue.reload();
			expect(get(queue.activeTracks)[0].progress).toBeUndefined();
		});

		it('reset() (logout) clears it, like every other piece of queue state', async () => {
			const store = fakeStorage();
			vi.stubGlobal('localStorage', store);
			await queue.applyEvent(trackEvent('t1', 'downloading', 40));
			queue.reset();
			expect(store.data.size).toBe(0);
		});

		it('storage that throws is ignored, not fatal', async () => {
			vi.stubGlobal('localStorage', {
				getItem: () => {
					throw new Error('denied');
				},
				setItem: () => {
					throw new Error('denied');
				},
				removeItem: () => {
					throw new Error('denied');
				}
			});
			await queue.applyEvent(trackEvent('t1', 'downloading', 40));
			routeLists({ active: async () => tracksPage([downloadingTrack('t1')]) });
			queue.reset();
			await queue.reload();
			expect(get(queue.activeTracks)).toHaveLength(1);
		});
	});
});

describe('v35 (g) tracks-scope state counts', () => {
	function countsCalls() {
		return listTracksPage.mock.calls.filter(([p]) => p?.limit === 1);
	}

	it('loads counts with the page and re-reads them once after a state change, not per tick', async () => {
		listTracksPage.mockResolvedValue({
			...tracksPage([downloadingTrack('t1')]),
			counts_by_state: { downloading: 1, waiting: 2 }
		});
		getJob.mockResolvedValue(job('job-1', 'expanded', 'active'));
		queue.setFilters({ scope: 'tracks' });
		await vi.runAllTimersAsync();
		expect(get(queue.page).countsByState).toEqual({ downloading: 1, waiting: 2 });

		// Progress ticks of an unchanged state never re-read the counts.
		await queue.applyEvent(trackEvent('t1', 'downloading', 10));
		await queue.applyEvent(trackEvent('t1', 'downloading', 20));
		listTracksPage.mockClear();
		await queue.applyEvent(trackEvent('t1', 'downloading', 30));
		await vi.advanceTimersByTimeAsync(2000);
		expect(countsCalls()).toHaveLength(0);

		listTracksPage.mockResolvedValue({
			...tracksPage([]),
			counts_by_state: { completed: 1, waiting: 2 }
		});
		await queue.applyEvent(trackEvent('t1', 'completed'));
		await vi.advanceTimersByTimeAsync(2000);
		expect(countsCalls()).toHaveLength(1);
		expect(get(queue.page).countsByState).toEqual({ completed: 1, waiting: 2 });
	});

	it('never re-reads counts in the jobs scope', async () => {
		routeLists({});
		getJob.mockResolvedValue(job('job-1', 'expanded', 'active'));
		await queue.reload();
		await queue.applyEvent(trackEvent('t1', 'completed'));
		await vi.advanceTimersByTimeAsync(2000);
		expect(countsCalls()).toHaveLength(0);
	});

	it('drops a counts read that resolves after a reset', async () => {
		listTracksPage.mockResolvedValue(tracksPage([]));
		getJob.mockResolvedValue(job('job-1', 'expanded', 'active'));
		queue.setFilters({ scope: 'tracks' });
		await vi.runAllTimersAsync();
		const late = deferred<TracksPage>();
		listTracksPage.mockReturnValue(late.promise);
		await queue.applyEvent(trackEvent('t1', 'waiting'));
		await vi.advanceTimersByTimeAsync(1500);
		queue.reset();
		late.resolve({ ...tracksPage([]), counts_by_state: { waiting: 99 } });
		await vi.runAllTimersAsync();
		expect(get(queue.page).countsByState).toEqual({});
	});

	it('re-reads counts on a job.state event (an archive from another session)', async () => {
		listTracksPage.mockResolvedValue(tracksPage([]));
		getJob.mockResolvedValue(job('job-1', 'expanded', 'settled'));
		queue.setFilters({ scope: 'tracks' });
		await vi.runAllTimersAsync();
		listTracksPage.mockResolvedValue({ ...tracksPage([]), counts_by_state: { completed: 3 } });
		await queue.applyEvent({
			type: 'job.state',
			job_id: 'job-1',
			state: 'expanded',
			archived: true,
			ts: '2026-10-01T18:00:02+00:00'
		} as StreamEvent);
		await vi.advanceTimersByTimeAsync(2000);
		expect(countsCalls()).toHaveLength(1);
		expect(get(queue.page).countsByState).toEqual({ completed: 3 });
	});

	it('a counts refresh that raced an in-flight reload is re-read after it', async () => {
		listTracksPage.mockResolvedValue(tracksPage([]));
		getJob.mockResolvedValue(job('job-1', 'expanded', 'active'));
		queue.setFilters({ scope: 'tracks' });
		await vi.runAllTimersAsync();

		const slowReload = deferred<TracksPage>();
		listTracksPage.mockReturnValueOnce(slowReload.promise);
		queue.setFilters({ q: 'x' });
		listTracksPage.mockResolvedValue({ ...tracksPage([]), counts_by_state: { completed: 2 } });
		await queue.applyEvent(trackEvent('t1', 'completed'));
		await vi.advanceTimersByTimeAsync(1500);
		expect(get(queue.page).countsByState).toEqual({ completed: 2 });

		slowReload.resolve({ ...tracksPage([]), counts_by_state: { downloading: 1 } });
		await vi.advanceTimersByTimeAsync(0);
		// The reload's own (older) counts land first, then one more re-read converges.
		expect(get(queue.page).countsByState).toEqual({ downloading: 1 });
		await vi.runAllTimersAsync();
		expect(get(queue.page).countsByState).toEqual({ completed: 2 });
	});
});
