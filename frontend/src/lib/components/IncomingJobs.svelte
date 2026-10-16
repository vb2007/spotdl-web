<script lang="ts">
	import { tick } from 'svelte';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import { link } from '$lib/stores/link';
	import type { Job } from '$lib/api';

	/** `allUsers`: the admin's all-users scope, where rows can be someone else's -- they
	 * then carry their owner, and "try again" (which submits as *this* session) is offered
	 * only on the viewer's own. */
	let {
		jobs,
		allUsers = false,
		sessionEmail = '',
		isAdmin = false
	}: { jobs: Job[]; allUsers?: boolean; sessionEmail?: string; isAdmin?: boolean } = $props();

	const SOURCE_LABEL: Record<Job['source_type'], string> = {
		track: 'track',
		album: 'album',
		playlist: 'playlist',
		artist: 'artist',
		search: 'search'
	};

	let tuning = $derived(jobs.filter((j) => j.state === 'expanding'));
	// Newest first: the one just submitted is the one the user is looking for.
	let failed = $derived(
		jobs
			.filter((j) => j.state !== 'expanding')
			.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
	);

	// v42 (F27): failed reads pile up (they stay until dismissed), and in the all-users
	// scope they're often days old. The newest always shows; older ones fold into one line.
	let showOlder = $state(false);
	let newestFailed = $derived(failed[0]);
	let olderFailed = $derived(failed.slice(1));

	let incomingSection = $state<HTMLElement>();
	let rowError = $state<Record<string, string>>({});
	let lostNotice = $state('');
	let busy = $state<Record<string, boolean>>({});
	// Rows whose link was already submitted again: never offered twice, even if the dismiss
	// that follows fails and leaves the row up.
	let resubmitted = $state<Record<string, boolean>>({});

	function setError(jobId: string, message: string) {
		rowError = { ...rowError, [jobId]: message };
	}

	/** `then`: where focus goes once the row (and its focused button) is gone. */
	async function handleCancel(jobId: string, then: 'next-dismiss' | 'submit') {
		// Where this row's dismiss sits among them, so focus can stay at that place.
		const position = dismissButtons().findIndex((b) => b.dataset.job === jobId);
		try {
			await queue.cancelJob(jobId);
		} catch (err) {
			const message = err instanceof api.ApiError ? err.message : 'Could not cancel this job.';
			await tick();
			if (!jobs.some((j) => j.id === jobId)) {
				// The row left meanwhile (its expansion finished): its error has no row to sit
				// on, and no other row's button is the right place for focus.
				lostNotice = `${message} It has moved into the queue below; cancel it there.`;
				const shown = lostNotice;
				setTimeout(() => {
					if (lostNotice === shown) lostNotice = '';
				}, 10_000);
				keepFocus('submit');
				return;
			}
			setError(jobId, message);
			// The row stays; if its focused button went away meanwhile (a resubmit hides
			// "try again"), its own dismiss is the place to land.
			keepFocus('next-dismiss', jobId);
			return;
		}
		lostNotice = '';
		await tick();
		keepFocus(then, undefined, position);
	}

	function dismissButtons(): HTMLButtonElement[] {
		return incomingSection?.isConnected
			? [...incomingSection.querySelectorAll<HTMLButtonElement>('button[data-act="dismiss"]')]
			: [];
	}

	// After a dismiss, the next failed row's own "dismiss" (the same action, so clearing a
	// pile stays one key); after a cancel or a resubmit, the submit box. Never a different
	// job's cancel or retry, where a repeated Enter would act on the wrong submission.
	function keepFocus(then: 'next-dismiss' | 'submit', ownJobId?: string, position = 0) {
		if (document.activeElement && document.activeElement !== document.body) return;
		const buttons = dismissButtons();
		// The row that moved into the removed one's place, else the one above it.
		const atPosition = buttons[Math.max(position, 0)] ?? buttons[buttons.length - 1];
		const next =
			(ownJobId && buttons.find((b) => b.dataset.job === ownJobId)) ||
			(then === 'next-dismiss' ? atPosition : undefined);
		(next ?? document.getElementById('submit-url'))?.focus();
	}

	/** Submits the same link again as a new job, then dismisses the failed one -- what a
	 * user would do by pasting it again, in one step. */
	async function handleRetry(job: Job) {
		busy = { ...busy, [job.id]: true };
		try {
			queue.addJob(await api.createJob(job.source_url));
			resubmitted = { ...resubmitted, [job.id]: true };
		} catch (err) {
			setError(job.id, err instanceof api.ApiError ? err.message : 'Could not submit it again.');
			busy = { ...busy, [job.id]: false };
			// Disabling the focused "try again" dropped focus to the page; give it back.
			await tick();
			if (document.activeElement === document.body) {
				incomingSection
					?.querySelector<HTMLButtonElement>(`button[data-act="retry"][data-job="${job.id}"]`)
					?.focus();
			}
			return;
		}
		// Re-enabled before the dismiss, so a failed dismiss can hand focus to this row's
		// own (now usable) dismiss button.
		busy = { ...busy, [job.id]: false };
		await tick();
		await handleCancel(job.id, 'submit');
	}

	// v42: a row can move between the tuning, newest and older groups (it fails, or a newer
	// failure arrives) and is then re-created, which drops focus to the page. Remember the
	// focused button and put focus back on the same row's control, or on the summary
	// toggle if the row folded away. A row that was removed is keepFocus's job, not this.
	let lastFocus: { act: string; job: string } | null = null;

	function onFocusIn(event: FocusEvent) {
		const button = (event.target as HTMLElement).closest<HTMLButtonElement>('button[data-job]');
		lastFocus = button ? { act: button.dataset.act ?? '', job: button.dataset.job ?? '' } : null;
	}

	function onFocusOut(event: FocusEvent) {
		const left = event.target as HTMLElement;
		setTimeout(() => {
			// Focus went somewhere real, or the user clicked away from a button that still
			// exists: nothing to restore. A re-created row's button is no longer connected.
			if (document.activeElement !== document.body || left.isConnected) lastFocus = null;
		});
	}

	$effect(() => {
		void jobs;
		restoreFocus();
	});

	async function restoreFocus() {
		await tick();
		const remembered = lastFocus;
		if (!remembered || document.activeElement !== document.body) return;
		if (!jobs.some((j) => j.id === remembered.job) || !incomingSection?.isConnected) return;
		const target =
			incomingSection.querySelector<HTMLButtonElement>(
				`button[data-act="${remembered.act}"][data-job="${remembered.job}"]`
			) ??
			incomingSection.querySelector<HTMLButtonElement>(
				`button[data-act="dismiss"][data-job="${remembered.job}"]`
			) ??
			incomingSection.querySelector<HTMLButtonElement>('button[data-act="older"]');
		target?.focus();
	}

	function isOwn(job: Job): boolean {
		return !allUsers || job.owner_email === sessionEmail;
	}
</script>

{#snippet failedRow(job: Job)}
	<li class="row failed">
		<span class="dot fail" aria-hidden="true"></span>
		<span class="mono state">no signal — could not read this {SOURCE_LABEL[job.source_type]}</span>
		<span class="url mono" title={job.source_url}>{job.source_url}</span>
		{#if allUsers}
			<span class="owner mono" title={job.owner_email}
				>{api.displayName(job.owner_username, job.owner_email)}</span
			>
		{/if}
		<!-- The raw expansion error is operator detail (v39 outcome 3): the admin reads it,
		     everyone else gets the next step. -->
		{#if isAdmin && job.error}
			<span class="reason" title={job.error}>{job.error}</span>
		{:else if !isAdmin}
			<span class="reason">Check that the link opens in Spotify, then try again.</span>
		{/if}
		<span class="actions">
			{#if isOwn(job) && !resubmitted[job.id]}
				<button
					type="button"
					class="action"
					disabled={busy[job.id]}
					aria-label="try again {job.source_url}"
					data-act="retry"
					data-job={job.id}
					onclick={() => handleRetry(job)}>try again</button
				>
			{/if}
			<button
				type="button"
				class="action"
				aria-label="dismiss {job.source_url}"
				data-act="dismiss"
				data-job={job.id}
				disabled={busy[job.id]}
				onclick={() => handleCancel(job.id, 'next-dismiss')}>dismiss</button
			>
		</span>
		{#if rowError[job.id]}
			<span class="error" role="alert">{rowError[job.id]}</span>
		{/if}
	</li>
{/snippet}

{#if lostNotice}
	<p class="lost" role="alert">{lostNotice}</p>
{/if}

{#if jobs.length > 0}
	<section
		class="incoming panel"
		aria-labelledby="incoming-heading"
		bind:this={incomingSection}
		onfocusin={onFocusIn}
		onfocusout={onFocusOut}
	>
		<h2 id="incoming-heading" class="sr-only">Incoming submissions</h2>
		<ul class="rows" aria-label="Incoming submissions">
			{#each tuning as job (job.id)}
				<li class="row">
					<!-- Without the live link the row may be stale: no amber, no pulse. -->
					<span class="dot" class:stale={$link !== 'live'} aria-hidden="true"></span>
					<span class="mono state">tuning in {SOURCE_LABEL[job.source_type]}</span>
					<span class="url mono" title={job.source_url}>{job.source_url}</span>
					{#if allUsers}
						<span class="owner mono" title={job.owner_email}
							>{api.displayName(job.owner_username, job.owner_email)}</span
						>
					{/if}
					<span class="actions">
						<button
							type="button"
							class="action danger"
							aria-label="cancel {job.source_url}"
							data-act="cancel"
							data-job={job.id}
							onclick={() => handleCancel(job.id, 'submit')}>cancel</button
						>
					</span>
					{#if rowError[job.id]}
						<span class="error" role="alert">{rowError[job.id]}</span>
					{/if}
				</li>
			{/each}

			<!-- Keyed, so a newer failure arriving over SSE gets its own row and buttons
			     instead of taking over the one that has focus. -->
			{#each newestFailed ? [newestFailed] : [] as job (job.id)}
				{@render failedRow(job)}
			{/each}

			{#if olderFailed.length > 0}
				<li class="row summary">
					<span class="dot fail" aria-hidden="true"></span>
					<span class="summary-text"
						>{olderFailed.length} older link{olderFailed.length === 1 ? '' : 's'} couldn't be read</span
					>
					<span class="actions">
						<button
							type="button"
							class="action"
							aria-expanded={showOlder}
							data-act="older"
							aria-label="{showOlder
								? 'hide'
								: 'show'} {olderFailed.length} older failed link{olderFailed.length === 1
								? ''
								: 's'}"
							onclick={() => (showOlder = !showOlder)}>{showOlder ? 'hide' : 'show'}</button
						>
					</span>
				</li>
				{#if showOlder}
					{#each olderFailed as job (job.id)}
						{@render failedRow(job)}
					{/each}
				{/if}
			{/if}
		</ul>
	</section>
{/if}

<style>
	.incoming {
		padding: var(--space-1) 0;
	}

	.rows {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.row {
		display: grid;
		grid-template-columns: 0.5rem auto minmax(0, 1fr) auto auto;
		align-items: center;
		column-gap: var(--space-3);
		row-gap: var(--space-1);
		padding: var(--space-2) var(--space-4);
		font-size: var(--fs-detail);
	}

	.row + .row {
		border-top: 1px solid var(--line);
	}

	.row.summary {
		grid-template-columns: 0.5rem minmax(0, 1fr) auto;
	}

	.row.summary .actions {
		grid-column: auto;
	}

	.summary-text {
		color: var(--fail);
	}

	.dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 50%;
		background: var(--signal);
		box-shadow: 0 0 6px 1px var(--signal-glow);
		animation: pulse 1.2s ease-in-out infinite;
	}

	.dot.stale {
		background: var(--text-muted);
		box-shadow: none;
		animation: none;
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

	.state {
		color: var(--text-muted);
		white-space: nowrap;
	}

	.row.failed .state {
		color: var(--fail);
	}

	/* The link and owner wrap rather than truncate at every width: the link's tail (the
	   id) is what tells two failed links apart, and a tooltip is out of reach for keyboard
	   and touch. */
	.url {
		min-width: 0;
		overflow-wrap: anywhere;
		color: var(--text-dim);
		font-size: var(--fs-meta);
	}

	.owner {
		max-width: 12rem;
		overflow-wrap: anywhere;
		color: var(--text-muted);
		font-size: var(--fs-meta);
	}

	/* The actions hold the first line's end; the reason and any error flow onto the lines
	   under it (they come before the actions in reading order). */
	.row:not(.summary) .actions {
		grid-row: 1;
		grid-column: 5;
	}

	.row:not(.summary):not(:has(.owner)) .actions {
		grid-column: 4 / -1;
	}

	.actions {
		display: flex;
		gap: var(--space-2);
		justify-content: flex-end;
	}

	/* The reason and any error sit under the state and link, on their columns. */
	.reason,
	.error {
		grid-column: 2 / -1;
		min-width: 0;
	}

	/* Wraps rather than truncating: it is the next step (or, for the admin, the cause),
	   and a phone can't open a tooltip. */
	.reason {
		overflow-wrap: anywhere;
		color: var(--text-muted);
	}

	.error {
		color: var(--fail);
	}

	.lost {
		color: var(--fail);
		font-size: var(--fs-detail);
	}

	.action {
		background: var(--bg-2);
		border: 1px solid var(--line-control);
		border-radius: 4px;
		padding: var(--space-1) var(--space-3);
		font-family: var(--font-mono);
		font-size: var(--fs-meta);
		color: var(--text-muted);
		cursor: pointer;
		white-space: nowrap;
	}

	.action:hover:not(:disabled),
	.action:focus-visible {
		background: var(--bg-3);
		color: var(--text-primary);
	}

	/* Cancelling a submission is destructive: the same outline as v41's row cancel. */
	.action.danger {
		background: transparent;
		border-color: var(--fail-edge);
	}

	.action.danger:hover,
	.action.danger:focus-visible {
		background: transparent;
		border-color: var(--fail);
		color: var(--fail);
	}

	.action:disabled {
		opacity: 0.6;
		cursor: default;
	}

	@media (pointer: coarse) {
		.action {
			min-height: 2.75rem;
		}
	}

	/* Phone and tablet: the state, link, owner and reason each get the full width and the
	   actions go under them. At tablet widths the one-line grid left the link (the only thing
	   saying which link failed) a few pixels wide once a long state and two actions took
	   their room. */
	@media (max-width: 1023px) {
		.row:not(.summary) {
			grid-template-columns: 0.5rem minmax(0, 1fr) auto;
		}

		.row .state {
			white-space: normal;
		}

		.row .url,
		.row .owner,
		.reason,
		.error {
			grid-column: 2 / -1;
		}

		.row .owner {
			max-width: none;
		}

		.row:not(.summary) .actions,
		.row:not(.summary):not(:has(.owner)) .actions {
			grid-row: auto;
			grid-column: 2 / -1;
			justify-content: flex-start;
		}
	}
</style>
