import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Job, JobsPage, StreamEvent, TracksPage, TrackWithJob } from '$lib/api';

vi.mock('$lib/api', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api')>();
	return {
		...actual,
		listJobsPage: vi.fn(),
		listTracksPage: vi.fn(),
		getJob: vi.fn(),
		cancelJob: vi.fn()
	};
});

const api = await import('$lib/api');
const { queue } = await import('$lib/stores/queue');

const listJobsPage = vi.mocked(api.listJobsPage);
const listTracksPage = vi.mocked(api.listTracksPage);
const getJob = vi.mocked(api.getJob);
const cancelJob = vi.mocked(api.cancelJob);

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
			view: 'mine'
		});
		expect(calls.active).toHaveLength(1);
		expect(calls.active[0][0]).toMatchObject({
			state: ['downloading'],
			includeArchived: true,
			view: 'mine',
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

		queue.setView('all');
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
		// v54: in `all` the active overlay is still the view's one listing.
		expect(hydrationCalls().active.at(-1)?.[0]).toMatchObject({ view: 'all' });
		expect(hydrationCalls().incoming.at(-1)?.[0]).toMatchObject({ view: 'all' });

		routeLists({});
		queue.setView('mine');
		expect(get(queue.activeTracks)).toHaveLength(0);
		expect(get(queue.incomingJobs)).toHaveLength(0);
		await queue.reload();
		expect(hydrationCalls().active.at(-1)?.[0]).toMatchObject({ view: 'mine' });
	});

	it('setView itself fetches nothing (the reconnect resyncs); a late old-scope page response never lands', async () => {
		const oldPage = deferred<JobsPage>();
		listJobsPage.mockImplementation((params = {}) =>
			params.status?.includes('expanding') ? Promise.resolve(jobsPage([])) : oldPage.promise
		);
		listTracksPage.mockResolvedValue(tracksPage([]));
		const reloading = queue.reload();
		const callsBefore = listJobsPage.mock.calls.length + listTracksPage.mock.calls.length;

		queue.setView('others');
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
		queue.setView('all');
		const handling = queue.applyEvent({
			type: 'job.state',
			job_id: 'someone-elses',
			state: 'expanding',
			ts: '2026-10-01T18:00:03+00:00'
		});
		queue.setView('mine');
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

		it('v47: ticks within a second are written once, then the newest on the trailing edge', async () => {
			vi.useFakeTimers();
			try {
				const store = fakeStorage();
				let writes = 0;
				const setItem = store.setItem;
				store.setItem = (k: string, v: string) => {
					writes += 1;
					setItem(k, v);
				};
				vi.stubGlobal('localStorage', store);
				for (const progress of [10, 20, 30, 40]) {
					await queue.applyEvent(trackEvent('t1', 'downloading', progress));
				}
				expect(writes).toBe(1);
				expect(JSON.parse(store.data.get('spotdl:live-progress:v1')!).t1.progress).toBe(10);
				vi.advanceTimersByTime(1000);
				expect(writes).toBe(2);
				expect(JSON.parse(store.data.get('spotdl:live-progress:v1')!).t1.progress).toBe(40);
			} finally {
				vi.useRealTimers();
			}
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

describe('v40.2 live view stays in sync with a settling job', () => {
	function settled(id: string): Job {
		return {
			...job(id, 'expanded', 'settled'),
			status: { lifecycle: 'settled', outcome: 'partial' }
		};
	}

	async function loadJobsPage(items: Job[], counts: Record<string, number>) {
		listJobsPage.mockImplementation((params = {}) =>
			Promise.resolve(
				params.status?.includes('expanding')
					? jobsPage([])
					: { ...jobsPage(items), counts_by_status: counts }
			)
		);
		listTracksPage.mockResolvedValue(tracksPage([]));
		await queue.reload();
	}

	it('a lookup_failed track leaves the Waterfall at once, not after the grace window', async () => {
		routeLists({});
		getJob.mockResolvedValue(job('job-1', 'expanded', 'active'));
		await queue.applyEvent(trackEvent('t1', 'downloading', 25));
		await queue.applyEvent(trackEvent('t1', 'lookup_failed'));
		expect(get(queue.activeTracks)).toHaveLength(0);
	});

	it('a hand retry of a lookup_failed track brings its lane back', async () => {
		routeLists({});
		getJob.mockResolvedValue(job('job-1', 'expanded', 'active'));
		await queue.applyEvent(trackEvent('t1', 'downloading', 25));
		await queue.applyEvent(trackEvent('t1', 'lookup_failed'));
		await queue.applyEvent(trackEvent('t1', 'queued'));
		await queue.applyEvent(trackEvent('t1', 'downloading', 5));
		expect(get(queue.activeTracks)).toMatchObject([{ id: 't1', progress: 5 }]);
	});

	it('a waiting track still keeps its lane for the grace window', async () => {
		routeLists({});
		getJob.mockResolvedValue(job('job-1', 'expanded', 'active'));
		await queue.applyEvent(trackEvent('t1', 'downloading', 25));
		await queue.applyEvent(trackEvent('t1', 'waiting'));
		expect(get(queue.activeTracks).map((t) => t.id)).toEqual(['t1']);
		vi.advanceTimersByTime(60_000);
		expect(get(queue.activeTracks)).toHaveLength(0);
	});

	it("a job settling through its track's event moves its state chip count, once", async () => {
		await loadJobsPage([job('job-1', 'expanded', 'active')], { active: 1 });
		getJob.mockResolvedValue(settled('job-1'));

		await queue.applyEvent(trackEvent('t1', 'lookup_failed'));
		await vi.advanceTimersByTimeAsync(1000);
		expect(get(queue.page).countsByStatus).toEqual({ active: 0, 'settled:partial': 1 });

		// The job's own event re-fetches the same, already-applied status: nothing moves twice.
		await queue.applyEvent({
			type: 'job.state',
			job_id: 'job-1',
			state: 'expanded',
			ts: '2026-10-01T18:00:05+00:00'
		});
		expect(get(queue.page).countsByStatus).toEqual({ active: 0, 'settled:partial': 1 });
	});

	it('a job that 404s on refresh leaves its state chip count and the total', async () => {
		await loadJobsPage([job('job-1', 'expanded', 'active'), job('job-2', 'expanded', 'active')], {
			active: 2
		});
		getJob.mockRejectedValue(new Error('404'));

		await queue.applyEvent(trackEvent('t1', 'completed'));
		await vi.advanceTimersByTimeAsync(1000);
		expect(get(queue.page).items.map((i) => i.id)).toEqual(['job-2']);
		expect(get(queue.page).countsByStatus).toEqual({ active: 1 });
		expect(get(queue.page).totalEstimate).toBe(1);
	});

	it('a job.state event on its own moves the count', async () => {
		await loadJobsPage([job('job-1', 'expanded', 'active')], { active: 1 });
		getJob.mockResolvedValue(settled('job-1'));
		await queue.applyEvent({
			type: 'job.state',
			job_id: 'job-1',
			state: 'expanded',
			ts: '2026-10-01T18:00:05+00:00'
		});
		expect(get(queue.page).countsByStatus).toEqual({ active: 0, 'settled:partial': 1 });
	});

	it("a cancel moves the row's count from active to cancelled", async () => {
		await loadJobsPage([job('job-1', 'expanded', 'active')], { active: 1 });
		cancelJob.mockResolvedValue(job('job-1', 'cancelled', 'cancelled'));
		await queue.cancelJob('job-1');
		expect(get(queue.page).countsByStatus).toEqual({ active: 0, cancelled: 1 });
	});

	it('a 404 reached by both the job event and the refresh is counted once', async () => {
		await loadJobsPage([job('job-1', 'expanded', 'active'), job('job-2', 'expanded', 'active')], {
			active: 2
		});
		getJob.mockRejectedValue(new Error('404'));
		await queue.applyEvent(trackEvent('t1', 'completed'));
		await queue.applyEvent({
			type: 'job.state',
			job_id: 'job-1',
			state: 'expanded',
			ts: '2026-10-01T18:00:05+00:00'
		});
		await vi.advanceTimersByTimeAsync(1000);
		expect(get(queue.page).countsByStatus).toEqual({ active: 1 });
		expect(get(queue.page).totalEstimate).toBe(1);
	});
});

describe('v54: the three-way view and whose lanes warm the page (U1)', () => {
	function owned(id: string, email: string, username: string | null = null): TrackWithJob {
		const t = downloadingTrack(id);
		return { ...t, job: { ...t.job, owner_email: email, owner_username: username } };
	}

	/** The active-overlay calls split by view: the view's own listing and, in `all`, the
	 * viewer's (`view: 'mine'`). */
	function routeActive(byView: Partial<Record<'mine' | 'all' | 'others', TrackWithJob[]>>) {
		listJobsPage.mockResolvedValue(jobsPage([]));
		listTracksPage.mockImplementation(async (params = {}) =>
			tracksPage(byView[params.view ?? 'mine'] ?? [])
		);
	}

	beforeEach(() => {
		vi.useFakeTimers();
		queue.reset();
		vi.resetAllMocks();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('mine: every lane is the viewer\u2019s, unnamed, with no extra request', async () => {
		routeActive({ mine: [owned('t1', 'me@example.com')] });
		await queue.reload();
		expect(get(queue.activeTracks)).toEqual([
			expect.objectContaining({ id: 't1', mine: true, owner: undefined })
		]);
		expect(get(queue.ownActiveTracks).map((t) => t.id)).toEqual(['t1']);
		expect(hydrationCalls().active).toHaveLength(1);
	});

	it('all: only the viewer\u2019s own lanes count as theirs; the rest are named', async () => {
		queue.setView('all');
		queue.setViewer('Me@example.com');
		routeActive({
			all: [owned('mine-1', 'me@example.com'), owned('theirs-1', 'anna@example.com', 'anna')],
			mine: [owned('mine-1', 'me@example.com')]
		});
		await queue.reload();
		const lanes = Object.fromEntries(get(queue.activeTracks).map((t) => [t.id, t]));
		expect(lanes['mine-1']).toMatchObject({ mine: true });
		expect(lanes['theirs-1']).toMatchObject({ mine: false, owner: 'anna' });
		expect(get(queue.ownActiveTracks).map((t) => t.id)).toEqual(['mine-1']);
	});

	it('others: no lane is the viewer\u2019s, so nothing warms the page', async () => {
		queue.setView('others');
		routeActive({ others: [owned('theirs-1', 'anna@example.com')] });
		await queue.reload();
		expect(get(queue.activeTracks)).toEqual([
			expect.objectContaining({ id: 'theirs-1', mine: false, owner: 'anna@example.com' })
		]);
		expect(get(queue.ownActiveTracks)).toHaveLength(0);
		expect(get(queue.viewerReceiving)).toBe(false);
		// The second request asks only whether the viewer has a download the view leaves out.
		expect(hydrationCalls().active.map(([p]) => p?.view)).toEqual(['others', 'mine']);
	});

	it('others: the viewer\u2019s own download, absent from the view, still warms the page', async () => {
		queue.setView('others');
		routeActive({
			others: [owned('theirs-1', 'anna@example.com')],
			mine: [owned('mine-1', 'me@example.com')]
		});
		await queue.reload();
		// No lane of theirs (the view leaves it out), but the page knows it's receiving.
		expect(get(queue.activeTracks).map((t) => t.id)).toEqual(['theirs-1']);
		expect(get(queue.viewerReceiving)).toBe(true);

		// It ends: the next poll says so.
		routeActive({ others: [owned('theirs-1', 'anna@example.com')], mine: [] });
		await queue.refreshOwnElsewhere();
		expect(get(queue.viewerReceiving)).toBe(false);

		// Only `others` asks; a switch away forgets it.
		routeActive({ mine: [owned('mine-1', 'me@example.com')] });
		await queue.refreshOwnElsewhere();
		expect(get(queue.viewerReceiving)).toBe(true);
		queue.setView('all');
		expect(get(queue.viewerReceiving)).toBe(false);
		const calls = listTracksPage.mock.calls.length;
		await queue.refreshOwnElsewhere();
		expect(listTracksPage.mock.calls.length).toBe(calls);
	});

	it('mine and all: the viewer receives exactly when a lane of theirs is live', async () => {
		routeActive({ mine: [owned('t1', 'me@example.com')] });
		await queue.reload();
		expect(get(queue.viewerReceiving)).toBe(true);
		queue.setView('all');
		queue.setViewer('me@example.com');
		routeActive({ all: [owned('theirs-1', 'anna@example.com')], mine: [] });
		await queue.reload();
		expect(get(queue.viewerReceiving)).toBe(false);
	});

	it('all: an SSE lane (no owner in the payload) is placed by one debounced lookup, once', async () => {
		queue.setView('all');
		queue.setViewer('me@example.com');
		routeActive({});
		await queue.reload();
		const before = hydrationCalls().active.length;
		routeActive({ all: [owned('t1', 'me@example.com')], mine: [owned('t1', 'me@example.com')] });

		await queue.applyEvent(trackEvent('t1', 'downloading', 10));
		await queue.applyEvent(trackEvent('t1', 'downloading', 20));
		// Unplaced, it reads as elsewhere until the lookup lands.
		expect(get(queue.ownActiveTracks)).toHaveLength(0);
		await vi.advanceTimersByTimeAsync(300);
		expect(hydrationCalls().active.length - before).toBe(1);
		expect(get(queue.ownActiveTracks).map((t) => t.id)).toEqual(['t1']);
		expect(get(queue.activeTracks)[0]).toMatchObject({ mine: true, owner: 'me@example.com' });

		// Further ticks of a placed lane ask nothing.
		await queue.applyEvent(trackEvent('t1', 'downloading', 30));
		await vi.advanceTimersByTimeAsync(300);
		expect(hydrationCalls().active.length - before).toBe(1);
	});

	it('others: an SSE lane is someone else\u2019s at once, and the lookup only names it', async () => {
		queue.setView('others');
		routeActive({});
		await queue.reload();
		routeActive({ others: [owned('t1', 'anna@example.com', 'anna')] });
		await queue.applyEvent(trackEvent('t1', 'downloading', 10));
		expect(get(queue.activeTracks)[0]).toMatchObject({ mine: false });
		expect(get(queue.activeTracks)[0].owner).toBeUndefined();
		await vi.advanceTimersByTimeAsync(300);
		expect(get(queue.activeTracks)[0]).toMatchObject({ mine: false, owner: 'anna' });
		expect(get(queue.ownActiveTracks)).toHaveLength(0);
	});

	it('a lookup that lands after a view switch or reset changes nothing', async () => {
		queue.setView('all');
		routeActive({});
		await queue.reload();
		const lookup = deferred<TracksPage>();
		listTracksPage.mockImplementation(() => lookup.promise);
		await queue.applyEvent(trackEvent('t1', 'downloading', 10));
		await vi.advanceTimersByTimeAsync(300);
		queue.reset();
		lookup.resolve(tracksPage([owned('t1', 'me@example.com')]));
		await vi.advanceTimersByTimeAsync(0);
		expect(get(queue.activeTracks)).toHaveLength(0);
		expect(queue.getView()).toBe('mine');
	});
});

describe('v54 review round 1', () => {
	function owned(id: string, email: string): TrackWithJob {
		const t = downloadingTrack(id);
		return { ...t, job: { ...t.job, owner_email: email } };
	}

	beforeEach(() => {
		vi.useFakeTimers();
		queue.reset();
		vi.resetAllMocks();
		listJobsPage.mockResolvedValue(jobsPage([]));
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('all: an own lane that ends and comes back on a retry is placed afresh', async () => {
		queue.setView('all');
		queue.setViewer('me@example.com');
		listTracksPage.mockResolvedValue(tracksPage([]));
		await queue.reload();
		listTracksPage.mockResolvedValue(tracksPage([owned('t1', 'me@example.com')]));
		await queue.applyEvent(trackEvent('t1', 'downloading', 10));
		await vi.advanceTimersByTimeAsync(300);
		expect(get(queue.ownActiveTracks).map((t) => t.id)).toEqual(['t1']);

		// The attempt fails; the lane leaves after its grace window.
		await queue.applyEvent(trackEvent('t1', 'waiting'));
		await vi.advanceTimersByTimeAsync(120_000);
		expect(get(queue.activeTracks)).toHaveLength(0);

		// Hours later the retry starts: the same id, a new lane, placed again.
		await queue.applyEvent(trackEvent('t1', 'downloading', 5));
		expect(get(queue.ownActiveTracks)).toHaveLength(0);
		await vi.advanceTimersByTimeAsync(300);
		expect(get(queue.ownActiveTracks).map((t) => t.id)).toEqual(['t1']);
	});

	it('others: a poll still in flight from before a resync never overwrites it', async () => {
		queue.setView('others');
		// The poll is sent (its worker-status answer still pending), then a resync starts.
		const status = deferred<boolean>();
		const polling = queue.refreshOwnElsewhere(status.promise);
		listTracksPage.mockImplementation(async (params = {}) =>
			tracksPage(params.view === 'mine' ? [owned('mine-1', 'me@example.com')] : [])
		);
		await queue.reload();
		expect(get(queue.viewerReceiving)).toBe(true);
		// The poll's older "worker idle" lands afterwards: dropped.
		status.resolve(false);
		await polling;
		expect(get(queue.viewerReceiving)).toBe(true);
	});
});

describe('v54 review round 2', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		queue.reset();
		vi.resetAllMocks();
		listJobsPage.mockResolvedValue(jobsPage([]));
		listTracksPage.mockResolvedValue(tracksPage([]));
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('others: a submit or retry that resolves there is never inserted', () => {
		queue.setView('others');
		queue.addJob(job('mine-1', 'expanding', 'expanding'));
		expect(get(queue.incomingJobs)).toHaveLength(0);
		queue.setView('all');
		queue.addJob(job('mine-2', 'expanding', 'expanding'));
		expect(get(queue.incomingJobs).map((j) => j.id)).toEqual(['mine-2']);
	});

	it('others: a poll that starts after a resync wins over the resync\u2019s older snapshot', async () => {
		queue.setView('others');
		const own = deferred<TracksPage>();
		listTracksPage.mockImplementation((params = {}) =>
			params.view === 'mine' ? own.promise : Promise.resolve(tracksPage([]))
		);
		const reloading = queue.reload();
		// The newer poll sees the viewer's download already over.
		listTracksPage.mockImplementation(async () => tracksPage([]));
		await queue.refreshOwnElsewhere();
		expect(get(queue.viewerReceiving)).toBe(false);
		// The resync's older snapshot (still downloading) lands afterwards: dropped.
		own.resolve(tracksPage([downloadingTrack('mine-1')]));
		await reloading;
		expect(get(queue.viewerReceiving)).toBe(false);
	});
});

describe('v54 review round 3', () => {
	function owned(id: string, email: string): TrackWithJob {
		const t = downloadingTrack(id);
		return { ...t, job: { ...t.job, owner_email: email } };
	}

	beforeEach(() => {
		vi.useFakeTimers();
		queue.reset();
		vi.resetAllMocks();
		listJobsPage.mockResolvedValue(jobsPage([]));
		listTracksPage.mockResolvedValue(tracksPage([]));
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('all: ticks closer than the wait never hold the lane lookup back', async () => {
		queue.setView('all');
		queue.setViewer('me@example.com');
		await queue.reload();
		listTracksPage.mockResolvedValue(tracksPage([owned('t1', 'me@example.com')]));
		for (let i = 0; i < 10; i++) {
			await queue.applyEvent(trackEvent('t1', 'downloading', i * 10));
			await vi.advanceTimersByTimeAsync(100);
		}
		expect(get(queue.ownActiveTracks).map((t) => t.id)).toEqual(['t1']);
	});

	it('all: a lane an event touched during a resync still takes the snapshot\u2019s owner', async () => {
		queue.setView('all');
		queue.setViewer('me@example.com');
		const active = deferred<TracksPage>();
		listTracksPage.mockImplementation(() => active.promise);
		const reloading = queue.reload();
		// The event lands while the snapshot is in flight, so its state wins over the snapshot's.
		await queue.applyEvent(trackEvent('t1', 'downloading', 40));
		active.resolve(tracksPage([owned('t1', 'me@example.com')]));
		await reloading;
		expect(get(queue.activeTracks)[0]).toMatchObject({ progress: 40, mine: true });
	});

	it('others: a cancel that resolves after a switch into it never inserts the viewer\u2019s job', async () => {
		queue.setViewer('a@example.com');
		const cancelled = deferred<Job>();
		cancelJob.mockReturnValue(cancelled.promise);
		queue.addJob(job('mine-1', 'failed', 'failed'));
		const cancelling = queue.cancelJob('mine-1');
		queue.setView('others');
		await queue.reload();
		cancelled.resolve(job('mine-1', 'cancelled', 'cancelled'));
		await cancelling;
		expect(get(queue.page).items).toHaveLength(0);
		// A cancel started and finished in others (a retry's dismiss) is refused the same way.
		cancelJob.mockResolvedValue(job('mine-2', 'cancelled', 'cancelled'));
		await queue.cancelJob('mine-2');
		expect(get(queue.page).items).toHaveLength(0);
	});
});

describe('v54 review round 4', () => {
	function owned(id: string, email: string): TrackWithJob {
		const t = downloadingTrack(id);
		return { ...t, job: { ...t.job, owner_email: email } };
	}

	beforeEach(() => {
		vi.useFakeTimers();
		queue.reset();
		vi.resetAllMocks();
		listJobsPage.mockResolvedValue(jobsPage([]));
		listTracksPage.mockResolvedValue(tracksPage([]));
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('all: a lane the lookup missed is asked again when it returns to downloading in its grace window', async () => {
		queue.setView('all');
		queue.setViewer('me@example.com');
		await queue.reload();
		// The first attempt dies before the lookup lands: it isn't listed.
		await queue.applyEvent(trackEvent('t1', 'downloading', 1));
		await vi.advanceTimersByTimeAsync(300);
		expect(get(queue.activeTracks)[0].mine).toBeUndefined();
		await queue.applyEvent(trackEvent('t1', 'waiting'));
		// Back within the grace window, and listed this time.
		listTracksPage.mockResolvedValue(tracksPage([owned('t1', 'me@example.com')]));
		await queue.applyEvent(trackEvent('t1', 'downloading', 2));
		await vi.advanceTimersByTimeAsync(300);
		expect(get(queue.ownActiveTracks).map((t) => t.id)).toEqual(['t1']);
	});

	it('others: with the worker idle the own-download check asks nothing', async () => {
		queue.setView('others');
		await queue.reload();
		const calls = listTracksPage.mock.calls.length;
		await queue.refreshOwnElsewhere(false);
		expect(listTracksPage.mock.calls.length).toBe(calls);
		expect(get(queue.viewerReceiving)).toBe(false);
		await queue.refreshOwnElsewhere(true);
		expect(listTracksPage.mock.calls.at(-1)?.[0]).toMatchObject({ view: 'mine', limit: 1 });
	});
});
