<script lang="ts">
	import { SvelteMap, SvelteSet } from 'svelte/reactivity';
	import Countdown from '$lib/components/Countdown.svelte';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import type { Job, TrackState } from '$lib/api';
	import type { LiveTrack } from '$lib/stores/queue';

	let { tracks, jobs }: { tracks: LiveTrack[]; jobs: Record<string, Job> } = $props();

	type Filter = 'all' | 'waiting' | 'lookup_failed';
	let filter = $state<Filter>('all');
	const expanded = new SvelteSet<string>();

	function toggle(id: string) {
		if (expanded.has(id)) expanded.delete(id);
		else expanded.add(id);
	}

	const CANCELLABLE_STATES = new Set<TrackState>([
		'pending',
		'queued',
		'downloading',
		'waiting',
		'lookup_failed',
		'failed'
	]);
	const RETRYABLE_STATES = new Set<TrackState>(['waiting', 'lookup_failed', 'failed']);

	// Per-row transient feedback (e.g. "held behind the global pause") -- SvelteMap so
	// mutations are tracked without wholesale reassignment (see v09's reactivity gotcha).
	const notice = new SvelteMap<string, string>();

	function showNotice(id: string, text: string) {
		notice.set(id, text);
		setTimeout(() => {
			if (notice.get(id) === text) notice.delete(id);
		}, 4000);
	}

	async function handleCancelTrack(id: string) {
		try {
			await queue.cancelTrack(id);
		} catch (err) {
			showNotice(id, err instanceof api.ApiError ? err.message : 'Could not cancel this track.');
		}
	}

	async function handleCancelJob(jobId: string, trackId: string) {
		try {
			await queue.cancelJob(jobId);
		} catch (err) {
			showNotice(trackId, err instanceof api.ApiError ? err.message : 'Could not cancel this job.');
		}
	}

	async function handleRetry(id: string) {
		try {
			const { breakerHeld } = await queue.retryTrack(id);
			showNotice(
				id,
				breakerHeld
					? 'held — global pause is active, will dispatch once it clears'
					: 'queued — dispatching on the next pass'
			);
		} catch (err) {
			showNotice(id, err instanceof api.ApiError ? err.message : 'Could not retry this track.');
		}
	}

	const STATE_LABEL: Record<TrackState, string> = {
		pending: 'pending',
		queued: 'queued',
		downloading: 'receiving',
		completed: 'logged',
		waiting: 'fading — waiting',
		lookup_failed: 'no signal — given up',
		failed: 'lost',
		skipped_duplicate: 'already logged',
		cancelled: 'cancelled'
	};

	const STATE_COND: Record<TrackState, string> = {
		pending: 'cond-idle',
		queued: 'cond-idle',
		downloading: 'cond-live',
		completed: 'cond-settled',
		waiting: 'cond-waiting',
		lookup_failed: 'cond-fail',
		failed: 'cond-fail',
		skipped_duplicate: 'cond-settled',
		cancelled: 'cond-idle'
	};

	let waitingCount = $derived(tracks.filter((t) => t.state === 'waiting').length);
	let lookupFailedCount = $derived(tracks.filter((t) => t.state === 'lookup_failed').length);

	let visible = $derived(filter === 'all' ? tracks : tracks.filter((t) => t.state === filter));
</script>

<section class="panel log" aria-label="Full queue log">
	<div class="head">
		<span class="label">Spectrum log</span>
		<div class="filters" role="group" aria-label="Filter by state">
			<button type="button" aria-pressed={filter === 'all'} onclick={() => (filter = 'all')}>
				all <span class="mono">{tracks.length}</span>
			</button>
			<button
				type="button"
				aria-pressed={filter === 'waiting'}
				onclick={() => (filter = 'waiting')}
			>
				waiting <span class="mono">{waitingCount}</span>
			</button>
			<button
				type="button"
				aria-pressed={filter === 'lookup_failed'}
				onclick={() => (filter = 'lookup_failed')}
			>
				given up <span class="mono">{lookupFailedCount}</span>
			</button>
		</div>
	</div>

	{#if visible.length === 0}
		<p class="empty label dim">nothing here</p>
	{:else}
		<ul class="rows">
			{#each visible as track (track.id)}
				<li>
					<button
						type="button"
						class="row"
						onclick={() => toggle(track.id)}
						aria-expanded={expanded.has(track.id)}
					>
						<span class="cell state {STATE_COND[track.state]} mono">{STATE_LABEL[track.state]}</span
						>
						<span class="cell title">{track.title ?? 'Unknown title'}</span>
						<span class="cell artist">{track.artists?.join(', ') ?? '—'}</span>
						<span class="cell album">{track.album ?? '—'}</span>
						<span class="cell job mono">{jobs[track.job_id]?.source_type ?? '—'}</span>
					</button>

					{#if expanded.has(track.id)}
						<div class="detail mono">
							<span>passes attempted: {track.attempt_count}</span>
							{#if track.state === 'waiting' && track.scheduled_at}
								<Countdown scheduledAt={track.scheduled_at} />
							{/if}
							{#if track.last_error}
								<span class="last-error">last read: {track.last_error}</span>
							{/if}
							{#if RETRYABLE_STATES.has(track.state) || CANCELLABLE_STATES.has(track.state)}
								<div class="actions">
									{#if RETRYABLE_STATES.has(track.state)}
										<button type="button" class="action" onclick={() => handleRetry(track.id)}>
											retry now
										</button>
									{/if}
									{#if CANCELLABLE_STATES.has(track.state)}
										<button
											type="button"
											class="action danger"
											onclick={() => handleCancelTrack(track.id)}
										>
											cancel track
										</button>
										<button
											type="button"
											class="action danger"
											onclick={() => handleCancelJob(track.job_id, track.id)}
										>
											cancel whole job
										</button>
									{/if}
								</div>
							{/if}
							{#if notice.has(track.id)}
								<span class="notice" role="status">{notice.get(track.id)}</span>
							{/if}
						</div>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.log {
		padding: var(--space-4) var(--space-5) var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	.filters {
		display: flex;
		gap: var(--space-2);
	}

	.filters button {
		background: var(--bg-2);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-1) var(--space-3);
		font-size: 0.75rem;
		color: var(--text-muted);
		cursor: pointer;
	}

	.filters button[aria-pressed='true'] {
		border-color: var(--signal);
		color: var(--text-primary);
	}

	.empty {
		padding: var(--space-5) 0;
		text-align: center;
	}

	.rows {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
	}

	.rows li {
		border-bottom: 1px solid var(--line);
	}

	.rows li:last-child {
		border-bottom: none;
	}

	.row {
		width: 100%;
		display: grid;
		grid-template-columns: 9rem minmax(0, 1.5fr) minmax(0, 1fr) minmax(0, 1fr) 6rem;
		gap: var(--space-3);
		align-items: center;
		padding: var(--space-3) var(--space-2);
		background: transparent;
		border: none;
		text-align: left;
		cursor: pointer;
		color: inherit;
	}

	.row:hover {
		background: var(--bg-2);
	}

	.cell {
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.cell.state {
		font-size: 0.75rem;
		letter-spacing: 0.04em;
	}

	.cell.artist,
	.cell.album {
		color: var(--text-muted);
		font-size: 0.875rem;
	}

	.cell.job {
		font-size: 0.6875rem;
		color: var(--text-dim);
		text-transform: uppercase;
	}

	/* Five fixed-plus-flexible columns have no room left on a phone-width viewport —
	   collapse to a stacked layout instead of squeezing every column to unreadable
	   slivers. Legibility of the log outranks a uniform grid here (v09 plan). */
	@media (max-width: 640px) {
		/* Pairing cells onto shared grid columns (e.g. title+job, artist+album)
		   turned out to have the same failure mode as the original 5-column grid one
		   level down: an `auto` column sized to the longest album name in that row
		   starved its neighboring column, silently truncating a *different* row's
		   title/artist even though the row as a whole had visual room to spare. Every
		   cell gets its own full-width line instead — more lines per row, but nothing
		   ever competes with anything else for width. */
		.row {
			display: flex;
			flex-direction: column;
			align-items: stretch;
			gap: var(--space-1);
		}

		.cell {
			width: 100%;
			text-align: left;
		}

		.cell.state {
			order: 1;
			overflow: visible;
			white-space: normal;
		}

		.cell.title {
			order: 2;
		}

		.cell.artist {
			order: 3;
		}

		.cell.album {
			order: 4;
		}

		.cell.job {
			order: 5;
		}

		.detail {
			padding-left: var(--space-2);
		}
	}

	.detail {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-4);
		padding: 0 var(--space-2) var(--space-3) 9rem;
		font-size: 0.8125rem;
		color: var(--text-muted);
	}

	.last-error {
		color: var(--fail);
		white-space: normal;
		overflow-wrap: anywhere;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		flex-basis: 100%;
	}

	.action {
		background: var(--bg-2);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-1) var(--space-3);
		font-size: 0.75rem;
		color: var(--text-muted);
		cursor: pointer;
	}

	.action:hover,
	.action:focus-visible {
		border-color: var(--waiting);
		color: var(--text-primary);
	}

	.action.danger:hover,
	.action.danger:focus-visible {
		border-color: var(--fail);
		color: var(--fail);
	}

	.notice {
		flex-basis: 100%;
		color: var(--waiting);
	}
</style>
