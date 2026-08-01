<script lang="ts">
	import type { Job } from '$lib/api';

	let { jobs }: { jobs: Job[] } = $props();

	const SOURCE_LABEL: Record<Job['source_type'], string> = {
		track: 'track',
		album: 'album',
		playlist: 'playlist',
		artist: 'artist',
		search: 'search'
	};
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
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--text-dim);
		font-size: 0.75rem;
	}
</style>
