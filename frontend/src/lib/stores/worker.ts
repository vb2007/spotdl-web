import { writable } from 'svelte/store';
import * as api from '$lib/api';
import type { WorkerStatus } from '$lib/api';

function createWorkerStore() {
	const status = writable<WorkerStatus | null>(null);

	async function refresh(): Promise<void> {
		status.set(await api.workerStatus());
	}

	async function pause(): Promise<void> {
		status.set(await api.pauseWorker());
	}

	async function resume(): Promise<void> {
		status.set(await api.resumeWorker());
	}

	async function release(): Promise<void> {
		status.set(await api.releaseBreaker());
	}

	return { status, refresh, pause, resume, release };
}

export const worker = createWorkerStore();
