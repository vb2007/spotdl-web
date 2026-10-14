<script lang="ts">
	import { queue } from '$lib/stores/queue';
	import TrackRow from '$lib/components/TrackRow.svelte';

	let { jobId, isAdmin, total }: { jobId: string; isAdmin: boolean; total: number } = $props();

	const { expanded } = queue;
	let state = $derived($expanded[jobId]);
</script>

<!-- v41: the job's tracks hang off a rail in its chevron column, indented by exactly one
     lead column (F02), on the panel's own surface rather than a darker well. -->
<div class="job-tracks" id="job-tracks-{jobId}">
	{#if state === undefined || state.loading}
		<p class="hint mono">Loading tracks…</p>
	{:else if state.error}
		<p class="hint fail mono" role="alert">{state.error}</p>
	{:else if state.items.length === 0}
		<p class="hint mono">No tracks.</p>
	{:else}
		<ul class="rows" aria-label="Tracks">
			{#each state.items as track (track.id)}
				<TrackRow {track} {jobId} {isAdmin} />
			{/each}
		</ul>
		{#if state.nextCursor}
			<!-- aria-disabled, not disabled: disabling the focused button would drop keyboard
			     focus to the page while the next page loads. -->
			<button
				type="button"
				class="load-more mono"
				aria-disabled={state.loadingMore}
				onclick={() => {
					if (!state.loadingMore) queue.loadMoreExpandedTracks(jobId);
				}}
			>
				{state.loadingMore ? 'loading…' : 'load more tracks'}
				<span class="shown"
					>{state.items.length.toLocaleString()} of {total.toLocaleString()} shown</span
				>
			</button>
		{/if}
	{/if}
</div>

<style>
	.job-tracks {
		position: relative;
		border-top: 1px solid var(--line);
		padding-left: calc(var(--row-pad-x) + var(--row-nest));
	}

	/* The nesting rail: centered under the job's chevron, 1px, the full height of the list. */
	.job-tracks::before {
		content: '';
		position: absolute;
		top: 0;
		bottom: var(--space-3);
		left: calc(var(--row-pad-x) + var(--col-lead) / 2);
		width: 1px;
		background: var(--line-bright);
	}

	.hint {
		margin: 0;
		padding: var(--space-3) 0 var(--space-3) var(--cell-inset);
		color: var(--text-muted);
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
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		width: 100%;
		background: transparent;
		border: none;
		border-top: 1px solid var(--line);
		padding: var(--space-2) var(--row-pad-x) var(--space-3) var(--cell-inset);
		font-size: 0.75rem;
		color: var(--text-primary);
		text-align: left;
		cursor: pointer;
	}

	.shown {
		color: var(--text-muted);
	}

	.load-more:hover:not([aria-disabled='true']),
	.load-more:focus-visible {
		background: var(--bg-2);
	}

	.load-more[aria-disabled='true'] {
		opacity: 0.6;
		cursor: default;
	}

	/* A phone's track rows drop the state inset (TrackRow.svelte), so the hints follow. */
	@media (max-width: 640px) {
		.hint,
		.load-more {
			padding-left: 0;
		}
	}
</style>
