<script lang="ts">
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import type { Job } from '$lib/api';

	let { jobs }: { jobs: Job[] } = $props();

	const SOURCE_LABEL: Record<Job['source_type'], string> = {
		track: 'track',
		album: 'album',
		playlist: 'playlist',
		artist: 'artist',
		search: 'search'
	};

	let cancelError = $state<Record<string, string>>({});

	async function handleCancel(jobId: string) {
		try {
			await queue.cancelJob(jobId);
		} catch (err) {
			cancelError = {
				...cancelError,
				[jobId]: err instanceof api.ApiError ? err.message : 'Could not cancel this job.'
			};
		}
	}
</script>

{#if jobs.length > 0}
	<ul class="incoming" aria-label="Incoming submissions">
		{#each jobs as job (job.id)}
			<li class="row" class:failed={job.state === 'failed'}>
				{#if job.state === 'expanding'}
					<span class="dot" aria-hidden="true"></span>
					<span class="mono label-text">tuning in {SOURCE_LABEL[job.source_type]}</span>
				{:else}
					<span class="dot fail" aria-hidden="true"></span>
					<span class="mono label-text"
						>no signal — could not read this {SOURCE_LABEL[job.source_type]}</span
					>
				{/if}
				<span class="url">{job.source_url}</span>
				<button type="button" class="cancel" onclick={() => handleCancel(job.id)}>
					{job.state === 'expanding' ? 'cancel' : 'dismiss'}
				</button>
				{#if cancelError[job.id]}
					<span class="error mono" role="alert">{cancelError[job.id]}</span>
				{/if}
			</li>
		{/each}
	</ul>
{/if}

<style>
	.incoming {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		background: var(--bg-1);
		border: 1px solid var(--line);
		border-radius: 4px;
		font-size: 0.8125rem;
	}

	.row.failed {
		border-color: var(--fail-dim);
	}

	.dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 50%;
		background: var(--signal);
		box-shadow: 0 0 6px 1px var(--signal-glow);
		flex-shrink: 0;
		animation: pulse 1.2s ease-in-out infinite;
	}

	.dot.fail {
		background: var(--fail);
		box-shadow: none;
		animation: none;
	}

	@media (prefers-reduced-motion: reduce) {
		.dot {
			animation: none;
		}
	}

	@keyframes pulse {
		0%,
		100% {
			opacity: 0.4;
		}
		50% {
			opacity: 1;
		}
	}

	.label-text {
		color: var(--text-muted);
		white-space: nowrap;
	}

	.row.failed .label-text {
		color: var(--fail);
	}

	.url {
		min-width: 0;
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--text-dim);
		font-size: 0.75rem;
	}

	.cancel {
		flex-shrink: 0;
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-1) var(--space-2);
		font-size: 0.6875rem;
		font-family: var(--font-mono);
		color: var(--text-muted);
		cursor: pointer;
	}

	.cancel:hover,
	.cancel:focus-visible {
		border-color: var(--fail);
		color: var(--fail);
	}

	.error {
		flex-basis: 100%;
		color: var(--fail);
		font-size: 0.75rem;
	}
</style>
