<script lang="ts">
	import { SvelteMap } from 'svelte/reactivity';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import Countdown from '$lib/components/Countdown.svelte';
	import type { TrackState } from '$lib/api';
	import type { LiveTrack } from '$lib/stores/queue';

	let { track, jobId }: { track: LiveTrack; jobId: string } = $props();

	let expanded = $state(false);

	const CANCELLABLE_STATES = new Set<TrackState>([
		'pending',
		'queued',
		'downloading',
		'waiting',
		'lookup_failed'
	]);
	const RETRYABLE_STATES = new Set<TrackState>(['waiting', 'lookup_failed']);

	// v20: "no signal — given up" read as permanent even though a lookup_failed track is
	// never retried automatically only, not literally abandoned -- the terminal/no-retry
	// behavior itself is unchanged from v1, only this label was misleading.
	const STATE_LABEL: Record<TrackState, string> = {
		pending: 'pending',
		queued: 'queued',
		downloading: 'receiving',
		completed: 'logged',
		waiting: 'fading — waiting',
		lookup_failed: 'no signal — not found',
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
		skipped_duplicate: 'cond-settled',
		cancelled: 'cond-idle'
	};

	// Per-row transient feedback (e.g. "held behind the global pause") -- SvelteMap so
	// mutations are tracked without wholesale reassignment (see v09's reactivity gotcha).
	const notice = new SvelteMap<string, string>();

	function showNotice(text: string) {
		notice.set(track.id, text);
		setTimeout(() => {
			if (notice.get(track.id) === text) notice.delete(track.id);
		}, 4000);
	}

	async function handleCancel() {
		try {
			await queue.cancelTrack(track.id, jobId);
		} catch (err) {
			showNotice(err instanceof api.ApiError ? err.message : 'Could not cancel this track.');
		}
	}

	async function handleRetry() {
		try {
			const { breakerHeld } = await queue.retryTrack(track.id, jobId);
			showNotice(
				breakerHeld
					? 'held — global pause is active, will dispatch once it clears'
					: 'queued — dispatching on the next pass'
			);
		} catch (err) {
			showNotice(err instanceof api.ApiError ? err.message : 'Could not retry this track.');
		}
	}
</script>

<li>
	<button type="button" class="row" onclick={() => (expanded = !expanded)} aria-expanded={expanded}>
		<span class="cell state {STATE_COND[track.state]} mono">{STATE_LABEL[track.state]}</span>
		<span class="cell title">{track.title ?? 'Unknown title'}</span>
		<span class="cell artist">{track.artists?.join(', ') ?? '—'}</span>
		<span class="cell album">{track.album ?? '—'}</span>
		{#if track.state === 'downloading' && track.progress !== undefined}
			<span class="cell pct mono">{track.progress}%</span>
		{/if}
	</button>

	{#if expanded}
		<div class="detail mono">
			<span>passes attempted: {track.attempt_count}</span>
			{#if track.state === 'waiting' && track.scheduled_at}
				<Countdown scheduledAt={track.scheduled_at} />
			{/if}
			{#if track.last_error}
				<span class="last-error">last read: {track.last_error}</span>
			{/if}
			<div class="actions">
				{#if RETRYABLE_STATES.has(track.state)}
					<button type="button" class="action" onclick={handleRetry}> retry now </button>
				{/if}
				{#if CANCELLABLE_STATES.has(track.state)}
					<button type="button" class="action danger" onclick={handleCancel}> cancel track </button>
				{/if}
			</div>
			{#if notice.has(track.id)}
				<span class="notice" role="status">{notice.get(track.id)}</span>
			{/if}
		</div>
	{/if}
</li>

<style>
	li {
		border-bottom: 1px solid var(--line);
	}

	li:last-child {
		border-bottom: none;
	}

	.row {
		width: 100%;
		display: grid;
		grid-template-columns: 9rem minmax(0, 1.5fr) minmax(0, 1fr) minmax(0, 1fr) 3rem;
		gap: var(--space-3);
		align-items: center;
		padding: var(--space-2) var(--space-2);
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

	.cell.pct {
		text-align: right;
		color: var(--signal);
		font-size: 0.75rem;
	}

	/* Same one-cell-per-line mobile collapse QueueTable established (DESIGN.md §6) --
	   squeezing columns or pairing them onto shared grid tracks both failed on real,
	   varied-length data; every cell gets its own full-width line, nothing competes
	   for width. */
	@media (max-width: 640px) {
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

		.cell.pct {
			order: 5;
			text-align: left;
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

	@media (max-width: 640px) {
		.detail {
			padding-left: var(--space-2);
		}
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
