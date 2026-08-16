<script lang="ts">
	import { SvelteMap } from 'svelte/reactivity';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import Countdown from '$lib/components/Countdown.svelte';
	import type { TrackAttempt, TrackAttemptOutcome, TrackState } from '$lib/api';
	import type { LiveTrack } from '$lib/stores/queue';

	let { track, jobId }: { track: LiveTrack; jobId: string } = $props();

	let expanded = $state(false);

	// Attempt history (v24) is diagnostic, not part of the live queue -- fetched lazily on
	// first expand rather than carried in the queue store, and cached per track id so
	// re-collapsing/re-expanding the same row doesn't refetch.
	let attempts = $state<TrackAttempt[]>([]);
	let attemptsLoading = $state(false);
	let attemptsError = $state<string | null>(null);
	let attemptsLoadedFor = $state<string | null>(null);

	const ATTEMPT_OUTCOME_LABEL: Record<TrackAttemptOutcome, string> = {
		completed: 'completed',
		failed: 'failed',
		cancelled: 'cancelled',
		skipped_duplicate: 'already logged'
	};

	// Reuses the same signal-condition color mapping as the waterfall/spectrum log
	// (app.css's .cond-* classes, see STATE_COND above) so an outcome's color means the
	// same thing everywhere a track's status appears, not a second palette invented here.
	const ATTEMPT_OUTCOME_COND: Record<TrackAttemptOutcome, string> = {
		completed: 'cond-settled',
		failed: 'cond-fail',
		cancelled: 'cond-idle',
		skipped_duplicate: 'cond-settled'
	};

	function formatTimestamp(value: string): string {
		return new Date(value).toLocaleString();
	}

	async function loadAttempts() {
		if (attemptsLoadedFor === track.id) return;
		attemptsLoading = true;
		attemptsError = null;
		try {
			attempts = await api.getTrackAttempts(track.id);
			attemptsLoadedFor = track.id;
		} catch (err) {
			attemptsError = err instanceof api.ApiError ? err.message : 'Could not load attempt history.';
		} finally {
			attemptsLoading = false;
		}
	}

	function toggleExpanded() {
		expanded = !expanded;
		if (expanded) loadAttempts();
	}

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
	<button type="button" class="row" onclick={toggleExpanded} aria-expanded={expanded}>
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
			<div class="attempts">
				{#if attemptsLoading}
					<span class="attempts-status">loading attempt history…</span>
				{:else if attemptsError}
					<span class="attempts-status attempts-error">{attemptsError}</span>
				{:else if attempts.length > 0}
					<span class="attempts-heading">attempt history</span>
					<ul class="attempts-list">
						{#each attempts as attempt (attempt.id)}
							<li class="attempt">
								<span class="attempt-outcome {ATTEMPT_OUTCOME_COND[attempt.outcome]}"
									>{ATTEMPT_OUTCOME_LABEL[attempt.outcome]}</span
								>
								<span class="attempt-via">{attempt.proxy_id ? 'via proxy' : 'direct'}</span>
								<span class="attempt-time">{formatTimestamp(attempt.finished_at)}</span>
								{#if attempt.error_message}
									<span class="attempt-error">{attempt.error_message}</span>
								{/if}
							</li>
						{/each}
					</ul>
				{:else}
					<span class="attempts-status">no attempts yet</span>
				{/if}
			</div>
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

	/* Diagnostic, not a headline feature (v24) -- deliberately quieter than the rest of
	   the detail panel (smaller, dimmer) so it never competes with the track's current
	   state for attention. */
	.attempts {
		flex-basis: 100%;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.attempts-status {
		color: var(--text-dim);
		font-size: 0.75rem;
	}

	.attempts-error {
		color: var(--fail);
	}

	.attempts-heading {
		color: var(--text-dim);
		font-size: 0.6875rem;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}

	.attempts-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: 0.75rem;
	}

	.attempt {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		color: var(--text-dim);
	}

	.attempt-outcome {
		font-weight: 600;
	}

	.attempt-error {
		color: var(--fail);
		flex-basis: 100%;
		white-space: normal;
		overflow-wrap: anywhere;
	}
</style>
