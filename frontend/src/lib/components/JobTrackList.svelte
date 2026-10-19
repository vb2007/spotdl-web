<script lang="ts">
	import { queue } from '$lib/stores/queue';
	import TrackRow from '$lib/components/TrackRow.svelte';
	import { tick } from 'svelte';
	import { focusRowEl, itemOf, kbList, rowAt, rowItemById } from '$lib/keyboard/lists';
	import { keepFocus } from '$lib/stores/confirm';
	import * as m from '$lib/paraglide/messages';
	import { errorText } from '$lib/i18n/errors';
	import { formatNumber } from '$lib/i18n/format';

	// v47: `unreadable` (the job failed before any track was read) says why the list is empty
	// instead of a bare "No tracks.". It carries `job.error` for the admin only: the raw
	// expansion error is operator detail (v39 outcome 3), as in IncomingJobs; a non-admin gets
	// the sentence alone ('').
	let {
		jobId,
		isAdmin,
		total,
		unreadable = null
	}: { jobId: string; isAdmin: boolean; total: number; unreadable?: string | null } = $props();

	const { expanded } = queue;
	let state = $derived($expanded[jobId]);

	// v45: "load more tracks" from the keyboard (Enter on it, or End/Shift+G on the last
	// track, which clicks it) moves focus to the first track it loaded. A pointer press leaves
	// focus where it is.
	async function loadMore(event: MouseEvent) {
		if (state.loadingMore) return;
		const known = new Set(state.items.map((t) => t.id));
		const fromKeyboard = event.detail === 0;
		const button = event.currentTarget as HTMLElement;
		const jobRow = rowAt(button);
		const jobItem = jobRow ? itemOf(jobRow) : null;
		const focusAtStart = document.activeElement;
		await queue.loadMoreExpandedTracks(jobId);
		await tick();
		if (!fromKeyboard) return;
		// Focus the user moved somewhere else meanwhile (into a field, say) is theirs. The last
		// page takes this button away with focus on it, and the job list then hands focus to the
		// job itself: that isn't the user's move.
		const active = document.activeElement;
		const rehomed = !button.isConnected && active === jobItem;
		const moved = active !== focusAtStart && active !== document.body && !rehomed;
		if (moved) return;
		// Only rows appended to the same list: a failed page adds none, and a re-read of the
		// job's tracks meanwhile replaced the list.
		const items = $expanded[jobId]?.items ?? [];
		const appended = items.slice(0, known.size).every((t) => known.has(t.id));
		const fresh = appended ? items.find((t) => !known.has(t.id)) : undefined;
		if (fresh) focusRowEl(document.querySelector<HTMLElement>(`[data-kb-row="${fresh.id}"]`));
	}
</script>

<!-- v41: the job's tracks hang off a rail in its chevron column, indented by exactly one
     lead column (F02), on the panel's own surface rather than a darker well. -->
<div class="job-tracks" id="job-tracks-{jobId}">
	{#if state === undefined || state.loading}
		<p class="hint">{m.job_tracks_loading()}</p>
	{:else if state.error && state.items.length === 0}
		<!-- v47: what failed, the reason, and a way to retry it here (it took a collapse and
		     re-open before). -->
		<div class="hint fail" role="alert">
			<p>{m.job_tracks_failed()} {errorText(state.error.err)}</p>
			<button
				type="button"
				class="retry"
				onclick={() => {
					queue.loadExpandedTracks(jobId);
					// The block (and this button) goes while it loads: focus goes back to the job.
					keepFocus(rowItemById(jobId));
				}}>{m.job_tracks_retry()}</button
			>
		</div>
	{:else if state.items.length === 0}
		{#if unreadable !== null}
			<p class="hint">
				{m.job_tracks_unreadable()}
				{#if unreadable}<span class="reason mono" lang="en">{unreadable}</span>{/if}
			</p>
		{:else}
			<p class="hint">{m.job_tracks_empty()}</p>
		{/if}
	{:else}
		<!-- v45: one Tab stop (roving), reached through its open job. -->
		<ul
			class="rows"
			aria-label={m.job_tracks_label()}
			{@attach kbList(`job-tracks:${jobId}`, {
				// Tracks that don't come back (their re-read failed): the job itself.
				fallback: () => (state?.loading ? null : rowItemById(jobId))
			})}
		>
			{#each state.items as track (track.id)}
				<TrackRow {track} {jobId} {isAdmin} />
			{/each}
		</ul>
		{#if state.nextCursor}
			<!-- aria-disabled, not disabled: disabling the focused button would drop keyboard
			     focus to the page while the next page loads. -->
			<button
				type="button"
				class="load-more"
				data-kb-load-more
				aria-disabled={state.loadingMore}
				onclick={loadMore}
			>
				{state.loadingMore ? m.job_tracks_loading_more() : m.job_tracks_load_more()}
				<span class="shown"
					>{m.job_tracks_shown({
						shown: formatNumber(state.items.length),
						total: formatNumber(total)
					})}</span
				>
			</button>
		{/if}
		<!-- A failed read keeps the rows already on screen: a "load more" (the button above
		     retries it) or a re-read of the list (a cancel's), which offers its own retry when
		     there's no next page to load. v47: one sentence for both, since either can fail. -->
		<p class="hint fail" role="alert">
			{state.error ? `${m.job_tracks_failed()} ${errorText(state.error.err)}` : ''}
		</p>
		{#if state.error && !state.nextCursor}
			<button
				type="button"
				class="retry stale-retry"
				onclick={() => {
					queue.loadExpandedTracks(jobId);
					keepFocus(rowItemById(jobId));
				}}>{m.job_tracks_retry()}</button
			>
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
		font-size: var(--fs-detail);
	}

	.hint.fail {
		color: var(--fail);
	}

	.hint p {
		margin: 0;
	}

	.reason {
		color: var(--text-muted);
		overflow-wrap: anywhere;
	}

	.stale-retry {
		margin: 0 0 var(--space-3) var(--cell-inset);
	}

	.retry {
		margin-top: var(--space-2);
		background: var(--bg-2);
		border: 1px solid var(--line-control);
		border-radius: 4px;
		padding: var(--space-1) var(--space-3);
		font-size: var(--fs-detail);
		font-weight: var(--fw-medium);
		line-height: 1.25;
		color: var(--text-primary);
		cursor: pointer;
	}

	@media (hover: hover) {
		.retry:hover {
			background: var(--bg-3);
			border-color: var(--text-muted);
		}
	}

	.retry:active {
		background: var(--bg-3);
	}

	/* Empty, it stays in the accessibility tree and takes no room. v47: not display:none,
	   since an alert whose element was display:none isn't announced by every screen reader
	   when its text arrives. */
	.hint.fail:empty {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		overflow: hidden;
		clip-path: inset(50%);
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
		font-size: var(--fs-detail);
		font-weight: var(--fw-medium);
		color: var(--text-primary);
		text-align: left;
		cursor: pointer;
	}

	.shown {
		color: var(--text-muted);
	}

	/* v42: a --bg-2 fill no longer reads on the faceplate; hover underlines instead. */
	.load-more:focus-visible {
		text-decoration: underline;
		text-underline-offset: 0.2em;
	}

	@media (hover: hover) {
		.load-more:hover:not([aria-disabled='true']) {
			text-decoration: underline;
			text-underline-offset: 0.2em;
		}
	}

	/* v47: dimmed text, not opacity (an opacity-faded control drops under 4.5:1). */
	.load-more[aria-disabled='true'] {
		color: var(--text-dim);
		cursor: default;
	}

	/* A phone's track rows drop the state inset (TrackRow.svelte), so the hints follow. */
	/* v42 (F32): a finger needs a 44px target; a mouse keeps the dense row. */
	@media (pointer: coarse) {
		.retry,
		.load-more {
			min-height: 2.75rem;
		}
	}

	@media (max-width: 40em) {
		.hint,
		.load-more {
			padding-left: 0;
		}
	}
</style>
