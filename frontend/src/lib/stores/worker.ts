import { writable } from 'svelte/store';
import * as api from '$lib/api';
import type { WorkerStatus } from '$lib/api';

function createWorkerStore() {
	const status = writable<WorkerStatus | null>(null);
	// v43: bumped by every read and action. A read applies only if nothing started after it,
	// so a 5s poll that read the row just before a confirmed pause/release (and answered after
	// it) can't put the old state back on screen.
	let seq = 0;

	async function refresh(): Promise<void> {
		const mine = ++seq;
		const next = await api.workerStatus();
		if (mine === seq) status.set(next);
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
