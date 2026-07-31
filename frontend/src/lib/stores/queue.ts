import { derived, writable } from 'svelte/store';
import * as api from '$lib/api';
import type { Job, StreamEvent, Track } from '$lib/api';

export type LiveTrack = Track & { progress?: number };

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

	async function refreshJobs(): Promise<Job[]> {
		const list = await api.listJobs();
		jobs.update((current) => {
			const next = { ...current };
			for (const job of list) next[job.id] = job;
			return next;
		});
		return list;
	}

	async function refreshJobTracks(jobId: string): Promise<void> {
		const list = await api.listJobTracks(jobId);
		tracks.update((current) => {
			const next = { ...current };
			for (const track of list) next[track.id] = { ...current[track.id], ...track };
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

	function applyTrackEvent(event: Extract<StreamEvent, { type: 'track.state' }>): void {
		tracks.update((current) => {
			const existing = current[event.track_id];
			const next: LiveTrack = {
				...existing,
				id: event.track_id,
				job_id: event.job_id,
				state: event.state
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

	const trackList = derived(tracks, ($tracks) =>
		Object.values($tracks).sort((a, b) => TRACK_STATE_ORDER[a.state] - TRACK_STATE_ORDER[b.state])
	);
	const activeTracks = derived(trackList, ($t) => $t.filter((t) => t.state === 'downloading'));
	const waitingTracks = derived(trackList, ($t) => $t.filter((t) => t.state === 'waiting'));
	const lookupFailedTracks = derived(trackList, ($t) =>
		$t.filter((t) => t.state === 'lookup_failed')
	);

	return {
		jobs,
		tracks,
		trackList,
		activeTracks,
		waitingTracks,
		lookupFailedTracks,
		loadAll,
		addJob,
		applyEvent
	};
}

export const queue = createQueueStore();
