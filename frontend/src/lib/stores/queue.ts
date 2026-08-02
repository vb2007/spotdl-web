import { derived, writable } from 'svelte/store';
import * as api from '$lib/api';
import type { Job, StreamEvent, Track, TrackState } from '$lib/api';

/** States nothing in this app ever transitions a track *out of* -- `waiting`/
 * `lookup_failed`/`failed` don't qualify since retry-now can revive them back to
 * `waiting`. A track's own real (uninterruptible) download can keep publishing stray
 * `downloading` progress events for several seconds after a cancel has already landed
 * (spotdl's progress callback has no idea a cancel happened -- see CLAUDE.md's v10
 * gotchas); once a track is known to be in one of these states, any further event for
 * it is necessarily stale and must be ignored, not applied. */
const TRULY_TERMINAL_STATES = new Set<TrackState>(['completed', 'skipped_duplicate', 'cancelled']);

export type LiveTrack = Track & { progress?: number; updatedAt: number };

/** State priority governs both color mapping and default table order — most-needs-
 * attention first, matching the "what's downloading right now" priority the direction
 * is built around. */
export const TRACK_STATE_ORDER: Record<Track['state'], number> = {
	downloading: 0,
	waiting: 1,
	queued: 2,
	pending: 3,
	lookup_failed: 4,
	failed: 5,
	completed: 6,
	skipped_duplicate: 7,
	cancelled: 8
};

function createQueueStore() {
	const jobs = writable<Record<string, Job>>({});
	const tracks = writable<Record<string, LiveTrack>>({});

	// Guards against an out-of-order REST response clobbering fresher state: the SSE
	// `expanded`/reconnect paths can both trigger overlapping `refreshJobTracks` calls for
	// the same job, and network timing gives no guarantee the one that started first is
	// also the one that resolves first. Each call captures the sequence number current at
	// call time and only applies its result if nothing newer has started since.
	let jobsFetchSeq = 0;
	const trackFetchSeq: Record<string, number> = {};

	async function refreshJobs(): Promise<Job[]> {
		const seq = ++jobsFetchSeq;
		const list = await api.listJobs();
		if (seq !== jobsFetchSeq) return list;
		jobs.update((current) => {
			const next = { ...current };
			for (const job of list) next[job.id] = job;
			return next;
		});
		return list;
	}

	async function refreshJobTracks(jobId: string): Promise<void> {
		const seq = (trackFetchSeq[jobId] ?? 0) + 1;
		trackFetchSeq[jobId] = seq;
		const list = await api.listJobTracks(jobId);
		if (trackFetchSeq[jobId] !== seq) return;
		tracks.update((current) => {
			const next = { ...current };
			for (const track of list) {
				next[track.id] = { ...current[track.id], ...track, updatedAt: Date.now() };
			}
			return next;
		});
	}

	/** Full REST resync — used on first load and on every SSE reconnect, per the v08
	 * documented contract (the stream never replays missed events). */
	async function loadAll(): Promise<void> {
		const jobList = await refreshJobs();
		await Promise.all(jobList.map((job) => refreshJobTracks(job.id)));
	}

	/** Optimistic insert right after a successful `POST /api/jobs`, so the new job is
	 * visible immediately rather than waiting for its own `expanding` SSE echo. */
	function addJob(job: Job): void {
		jobs.update((current) => ({ ...current, [job.id]: job }));
	}

	function mergeTrack(track: Track): void {
		tracks.update((current) => ({
			...current,
			[track.id]: { ...current[track.id], ...track, updatedAt: Date.now() }
		}));
	}

	/** Same optimistic-then-resync pattern as `addJob`: apply the mutation's own response
	 * immediately rather than waiting on the SSE echo, then pull the affected tracks via
	 * REST since a job-level cancel can touch many tracks the response body doesn't list
	 * individually (each still gets its own `track.state` SSE event, this just doesn't
	 * wait on it). */
	async function cancelJob(jobId: string): Promise<void> {
		const job = await api.cancelJob(jobId);
		jobs.update((current) => ({ ...current, [job.id]: job }));
		await refreshJobTracks(jobId);
	}

	function mergeJob(job: Job): void {
		jobs.update((current) => ({ ...current, [job.id]: job }));
	}

	async function bumpJob(jobId: string): Promise<void> {
		mergeJob(await api.bumpJob(jobId));
	}

	async function setJobPriority(jobId: string, priority: number): Promise<void> {
		mergeJob(await api.setJobPriority(jobId, priority));
	}

	async function cancelTrack(trackId: string): Promise<void> {
		mergeTrack(await api.cancelTrack(trackId));
	}

	/** Returns whether the retry is held behind the global breaker, so the caller can
	 * surface that precedence to the user rather than leaving a silent no-op. */
	async function retryTrack(trackId: string): Promise<{ breakerHeld: boolean }> {
		const { breaker_held, ...track } = await api.retryTrack(trackId);
		mergeTrack(track);
		return { breakerHeld: breaker_held };
	}

	function applyTrackEvent(event: Extract<StreamEvent, { type: 'track.state' }>): void {
		tracks.update((current) => {
			const existing = current[event.track_id];
			// A stray event arriving after a track already reached a truly terminal
			// state is necessarily stale -- applying it would flip the track back to
			// non-terminal for a moment (e.g. a cancelled track visibly "resuming" its
			// download) before the eventual correcting event catches up. Ignoring it
			// outright is simpler and more robust than trying to compare timestamps.
			if (existing && TRULY_TERMINAL_STATES.has(existing.state)) {
				return current;
			}
			const next: LiveTrack = {
				...existing,
				id: event.track_id,
				job_id: event.job_id,
				state: event.state,
				updatedAt: Date.now()
			} as LiveTrack;
			if (event.progress !== undefined) next.progress = event.progress;
			if (event.scheduled_at !== undefined) next.scheduled_at = event.scheduled_at;
			if (event.error !== undefined) next.last_error = event.error;
			if (event.attempt_count !== undefined) next.attempt_count = event.attempt_count;
			return { ...current, [event.track_id]: next };
		});
	}

	async function applyJobEvent(event: Extract<StreamEvent, { type: 'job.state' }>): Promise<void> {
		await refreshJobs();
		// Track creation itself is never published — expand_job only emits job.state
		// events, so `expanded` is the signal that this job's tracks now exist to fetch.
		if (event.state === 'expanded') {
			await refreshJobTracks(event.job_id);
		}
	}

	async function applyEvent(event: StreamEvent): Promise<void> {
		if (event.type === 'track.state') {
			applyTrackEvent(event);
		} else {
			await applyJobEvent(event);
		}
	}

	/** State priority alone isn't enough of a sort key -- a track's row was sitting at the
	 * very top while `downloading` (priority 0), and the instant it completed (priority 6)
	 * it fell all the way to wherever it happened to land among every other same-priority
	 * track, which for a track that only just joined the `tracks` record is dead last per
	 * plain object insertion order. Confirmed via real-stack testing: a live completion
	 * jumped from index 0 to index 25 of 38 rows, well below the fold -- reading as "the
	 * track vanished" even though it was still in the DOM the whole time. Sorting newest
	 * update first within a priority tier keeps a just-changed row visible near the top of
	 * its own tier instead of wherever insertion order happened to leave it. */
	const trackList = derived(tracks, ($tracks) =>
		Object.values($tracks).sort(
			(a, b) => TRACK_STATE_ORDER[a.state] - TRACK_STATE_ORDER[b.state] || b.updatedAt - a.updatedAt
		)
	);
	const activeTracks = derived(trackList, ($t) => $t.filter((t) => t.state === 'downloading'));
	const waitingTracks = derived(trackList, ($t) => $t.filter((t) => t.state === 'waiting'));
	const lookupFailedTracks = derived(trackList, ($t) =>
		$t.filter((t) => t.state === 'lookup_failed')
	);

	/** A job between "submitted" and "its tracks exist" has nothing else in the UI to
	 * represent it -- expanding a URL takes several real seconds (a genuine Spotify
	 * metadata round trip, not something to fake away), and with no visible trace of the
	 * submission during that window a user has every reason to think the click didn't
	 * register and try again. Also carries `failed` jobs (expansion errored out with zero
	 * tracks ever created) since those otherwise vanish with no explanation anywhere. */
	const incomingJobs = derived(jobs, ($jobs) =>
		Object.values($jobs)
			.filter((j) => j.state === 'expanding' || j.state === 'failed')
			.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
	);

	return {
		jobs,
		tracks,
		trackList,
		activeTracks,
		waitingTracks,
		lookupFailedTracks,
		incomingJobs,
		loadAll,
		addJob,
		applyEvent,
		cancelJob,
		cancelTrack,
		retryTrack,
		bumpJob,
		setJobPriority
	};
}

export const queue = createQueueStore();
