import { writable } from 'svelte/store';
import * as api from '$lib/api';
import type { WorkerStatus } from '$lib/api';

function createWorkerStore() {
	const status = writable<WorkerStatus | null>(null);
	// v43: bumped by every read and action. A read applies only if nothing started after it,
	// so a 5s poll that read the row just before a confirmed pause/release (and answered after
	// it) can't put the old state back on screen.
	let seq = 0;

	/** Reads the status, and returns what it read even when a later read overtook it on
	 * screen: a caller deciding on a fresh value decides on this one, never on the store. */
	async function refresh(): Promise<WorkerStatus> {
		const mine = ++seq;
		const next = await api.workerStatus();
		if (mine === seq) status.set(next);
		return next;
	}

	async function act(call: () => Promise<WorkerStatus>): Promise<void> {
		++seq;
		status.set(await call());
	}

	const pause = () => act(api.pauseWorker);
	const resume = () => act(api.resumeWorker);
	const release = () => act(api.releaseBreaker);

	return { status, refresh, pause, resume, release };
}

export const worker = createWorkerStore();
