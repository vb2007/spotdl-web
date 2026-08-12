<script lang="ts">
	import { queue } from '$lib/stores/queue';
	import TrackRow from '$lib/components/TrackRow.svelte';

	let { jobId }: { jobId: string } = $props();

	const { expanded } = queue;
	let state = $derived($expanded[jobId]);
</script>

<div class="job-tracks">
	{#if state === undefined || state.loading}
		<p class="hint mono">Loading tracks…</p>
	{:else if state.error}
		<p class="hint fail mono" role="alert">{state.error}</p>
	{:else if state.items.length === 0}
		<p class="hint mono">No tracks.</p>
	{:else}
		<ul class="rows">
			{#each state.items as track (track.id)}
				<TrackRow {track} {jobId} />
			{/each}
		</ul>
		{#if state.nextCursor}
			<button
				type="button"
				class="load-more"
				disabled={state.loadingMore}
				onclick={() => queue.loadMoreExpandedTracks(jobId)}
			>
				{state.loadingMore ? 'loading…' : 'load more tracks'}
			</button>
		{/if}
	{/if}
</div>

<style>
	.job-tracks {
		border-top: 1px solid var(--line);
		background: var(--bg-0);
	}

	.hint {
		margin: 0;
		padding: var(--space-3) var(--space-4);
		color: var(--text-dim);
		font-size: 0.8125rem;
	}

	.hint.fail {
		color: var(--fail);
	}

	.rows {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
	}

	.load-more {
		display: block;
		width: 100%;
		background: var(--bg-1);
		border: none;
		border-top: 1px solid var(--line);
		padding: var(--space-2);
		font-family: var(--font-mono);
		font-size: 0.75rem;
		color: var(--text-muted);
		cursor: pointer;
	}

	.load-more:hover:not(:disabled),
	.load-more:focus-visible {
		color: var(--signal-dim);
	}

	.load-more:disabled {
		opacity: 0.6;
		cursor: default;
	}
</style>
