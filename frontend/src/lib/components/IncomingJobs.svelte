<script lang="ts">
	import { tick } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import { link } from '$lib/stores/link';
	import { confirmAction } from '$lib/stores/confirm';
	import type { Job } from '$lib/api';
	import * as m from '$lib/paraglide/messages';
	import { counted } from '$lib/i18n/format';
	import { errorText } from '$lib/i18n/errors';

	/** `allUsers`: the admin's all-users scope, where rows can be someone else's -- they
	 * then carry their owner, and "try again" (which submits as *this* session) is offered
	 * only on the viewer's own. */
	let {
		jobs,
		allUsers = false,
		sessionEmail = '',
		isAdmin = false
	}: { jobs: Job[]; allUsers?: boolean; sessionEmail?: string; isAdmin?: boolean } = $props();

	// v46: functions, not strings, so a language switch re-renders them. The failure line is
	// one sentence per source type: Hungarian inflects the noun ("ezt az albumot").
	const SOURCE_LABEL: Record<Job['source_type'], () => string> = {
		track: m.incoming_source_track,
		album: m.incoming_source_album,
		playlist: m.incoming_source_playlist,
		artist: m.incoming_source_artist,
		search: m.incoming_source_search
	};
	const UNREADABLE: Record<Job['source_type'], () => string> = {
		track: m.incoming_unreadable_track,
		album: m.incoming_unreadable_album,
		playlist: m.incoming_unreadable_playlist,
		artist: m.incoming_unreadable_artist,
		search: m.incoming_unreadable_search
	};

	let tuning = $derived(jobs.filter((j) => j.state === 'expanding'));
	// Newest *failure* first: the one that just failed is the one the user is looking at.
	// A job has no failure timestamp, so this page records when each failed row first
	// appeared (a slow artist submitted before a quick bad link fails later, and must not
	// fold away behind it). Rows already failed on load tie, and fall back to created_at.
	const failedSeenAt = new SvelteMap<string, number>();
	let seenInScope: boolean | null = null;
	$effect(() => {
		// A scope switch reloads the whole overlay: everything in it is "already failed on
		// load" again, so stamps from the previous scope mustn't outrank it.
		if (seenInScope !== allUsers) {
			failedSeenAt.clear();
			seenInScope = allUsers;
		}
		// One stamp per batch, so rows arriving together tie (and fall back to created_at).
		const now = Date.now();
		for (const j of jobs) {
			if (j.state !== 'expanding' && !failedSeenAt.has(j.id)) failedSeenAt.set(j.id, now);
		}
	});
	let failed = $derived(
		jobs
			.filter((j) => j.state !== 'expanding')
			.sort(
				(a, b) =>
					(failedSeenAt.get(b.id) ?? 0) - (failedSeenAt.get(a.id) ?? 0) ||
					Date.parse(b.created_at) - Date.parse(a.created_at)
			)
	);

	// v42 (F27): failed reads pile up (they stay until dismissed), and in the all-users
	// scope they're often days old. The newest always shows; older ones fold into one line.
	let showOlder = $state(false);
	let newestFailed = $derived(failed[0]);
	let olderFailed = $derived(failed.slice(1));

	let incomingSection = $state<HTMLElement>();
	let rowError = $state<Record<string, { state: string; message: string }>>({});
	let lostNotice = $state('');
	let busy = $state<Record<string, boolean>>({});
	// Rows whose link was already submitted again: never offered twice, even if the dismiss
	// that follows fails and leaves the row up.
	let resubmitted = $state<Record<string, boolean>>({});

	// Keyed by the row's state too: an error belongs to the action it came from, so a row
	// that changes group (a tuning row whose expansion then fails) doesn't carry a stale
	// "could not cancel" under its new, different actions.
	function setError(jobId: string, message: string) {
		const state = jobs.find((j) => j.id === jobId)?.state ?? '';
		rowError = { ...rowError, [jobId]: { state, message } };
	}

	function errorFor(job: Job): string {
		const e = rowError[job.id];
		return e && e.state === job.state ? e.message : '';
	}

	/** `then`: where focus goes once the row (and its focused button) is gone. */
	async function handleCancel(jobId: string, then: 'next-dismiss' | 'submit') {
		// Where this row's dismiss sits among them, so focus can stay at that place.
		const position = dismissButtons().findIndex((b) => b.dataset.job === jobId);
		const wasTuning = jobs.some((j) => j.id === jobId && j.state === 'expanding');
		acting = true;
		try {
			await queue.cancelJob(jobId);
		} catch (err) {
			const message = errorText(err, m.incoming_cancel_failed);
			await tick();
			acting = false;
			if (!jobs.some((j) => j.id === jobId)) {
				// The row left meanwhile, so its error has no row to sit on, and no other row's
				// button is the right place for focus. Only a tuning row leaves by moving into
				// the queue (its expansion finished); a failed row that left was dismissed or
				// archived elsewhere, so there is nothing left to say about it.
				if (wasTuning) {
					lostNotice = m.incoming_cancel_moved({ message });
					const shown = lostNotice;
					setTimeout(() => {
						if (lostNotice === shown) lostNotice = '';
					}, 10_000);
				}
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
		acting = false;
		keepFocus(then, undefined, position);
	}

	// v43 (F08): cancelling a submission still being read is a job cancel, so it asks first.
	// Dismissing a failed row doesn't: that job is already over.
	// One question and its server re-read per submission at a time.
	const cancelAsking: Record<string, true> = {};
	async function confirmCancelTuning(job: Job) {
		if (cancelAsking[job.id]) return;
		cancelAsking[job.id] = true;
		try {
			await confirmCancelTuningFlow(job);
		} finally {
			delete cancelAsking[job.id];
		}
	}

	async function confirmCancelTuningFlow(job: Job) {
		const session = queue.getResetCount();
		const confirmed = await confirmAction({
			title: m.incoming_confirm_title(),
			subject: job.source_url,
			body: m.incoming_confirm_body(),
			confirmLabel: m.incoming_confirm_yes(),
			cancelLabel: m.incoming_confirm_no()
		});
		if (!confirmed) {
			// Kept or Esc: the row may have left meanwhile (it finished reading or failed).
			keepFocus('submit');
			return;
		}
		// Another identity took over meanwhile: this answer belongs to the previous session.
		if (queue.getResetCount() !== session) return;
		// The question can outlive the reading: once the job has moved into the queue, its
		// cancel there asks about the job as it now is. The server decides, as JobRow's does:
		// this panel follows the stream, which may be down, and cancel_job would relabel a job
		// that finished meanwhile "cancelled".
		let current: Job | undefined = jobs.find((j) => j.id === job.id);
		try {
			current = await api.getJob(job.id);
		} catch {
			// Unreadable: the panel's own state decides.
		}
		if (queue.getResetCount() !== session) return;
		if (current?.state !== 'expanding') {
			// Failed meanwhile (the row stays here as failed), or gone from this panel: it
			// finished reading into the queue, or was cancelled elsewhere.
			lostNotice = current?.state === 'failed' ? m.incoming_lost_failed() : m.incoming_lost_moved();
			const shown = lostNotice;
			setTimeout(() => {
				if (lostNotice === shown) lostNotice = '';
			}, 10_000);
			keepFocus('submit');
			return;
		}
		await handleCancel(job.id, 'submit');
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
		if (document.activeElement && document.activeElement !== document.body) {
			// Focus is still somewhere real. Forget the remembered button only if focus has
			// left the panel; a button that kept focus (a failed cancel) stays remembered.
			if (!incomingSection?.contains(document.activeElement)) lastFocus = null;
			return;
		}
		const buttons = dismissButtons();
		// The row that moved into the removed one's place, else the one above it.
		const atPosition = buttons[Math.max(position, 0)] ?? buttons[buttons.length - 1];
		const next =
			(ownJobId && buttons.find((b) => b.dataset.job === ownJobId)) ||
			(then === 'next-dismiss' ? atPosition : undefined);
		// Focus is being placed deliberately: drop the old memory first (Firefox and WebKit
		// fire no focusout when the focused button is removed), and let this focus() call's
		// own focusin record the new button if it is one of ours.
		lastFocus = null;
		// The submit box is the next step for a keyboard user, but a programmatic focus on a
		// text input opens a phone's on-screen keyboard: touch gets the queue heading instead.
		// i18n-ignore: a media query
		const fallback = window.matchMedia('(pointer: coarse)').matches
			? document.getElementById('queue-heading')
			: document.getElementById('submit-url');
		(next ?? fallback)?.focus();
	}

	/** Submits the same link again as a new job, then dismisses the failed one -- what a
	 * user would do by pasting it again, in one step. */
	async function handleRetry(job: Job) {
		busy = { ...busy, [job.id]: true };
		// A logout while the POST is in flight resets the store; the new job then belongs to
		// the previous identity and must not land in the next one's overlay.
		const session = queue.getResetCount();
		try {
			const created = await api.createJob(job.source_url);
			if (queue.getResetCount() !== session) return;
			queue.addJob(created);
			resubmitted = { ...resubmitted, [job.id]: true };
		} catch (err) {
			setError(job.id, errorText(err, m.incoming_retry_failed));
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
	// True while the user's own cancel/dismiss is in flight: keepFocus places focus then.
	let acting = false;

	function onFocusIn(event: FocusEvent) {
		const button = (event.target as HTMLElement).closest<HTMLButtonElement>('button[data-act]');
		lastFocus = button ? { act: button.dataset.act ?? '', job: button.dataset.job ?? '' } : null;
	}

	function onFocusOut(event: FocusEvent) {
		const left = event.target as HTMLElement;
		setTimeout(() => {
			// Focus went somewhere real, or the user clicked away from a button that still
			// exists: nothing to restore. A re-created row's button is no longer connected.
			// (Focus moving to another button in this section keeps the memory: its own
			// focusin has already recorded the new button.)
			const now = document.activeElement;
			const inside = now !== null && incomingSection?.contains(now);
			if ((now !== document.body && !inside) || (now === document.body && left.isConnected))
				lastFocus = null;
		});
	}

	$effect(() => {
		void jobs;
		restoreFocus();
	});

	async function restoreFocus() {
		await tick();
		const remembered = lastFocus;
		if (!remembered || acting || document.activeElement !== document.body) return;
		if (remembered.act === 'older') {
			// The summary row went away (the older pile emptied): the newest row's dismiss,
			// else the submit box.
			lastFocus = null;
			keepFocus('next-dismiss');
			return;
		}
		if (!jobs.some((j) => j.id === remembered.job)) {
			// A live update removed the focused row (its expansion finished, or another tab
			// dismissed it): the next dismiss if it was one, else the submit box.
			lastFocus = null;
			keepFocus(remembered.act === 'dismiss' ? 'next-dismiss' : 'submit');
			return;
		}
		if (!incomingSection?.isConnected) return;
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
		<span class="mono state">{UNREADABLE[job.source_type]?.() ?? job.source_type}</span>
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
			<span class="reason">{m.incoming_unreadable_hint()}</span>
		{/if}
		<span class="actions">
			{#if isOwn(job) && !resubmitted[job.id]}
				<button
					type="button"
					class="action"
					disabled={busy[job.id]}
					aria-label={m.incoming_retry_label({ url: job.source_url })}
					data-act="retry"
					data-job={job.id}
					onclick={() => handleRetry(job)}>{m.incoming_retry()}</button
				>
			{/if}
			<button
				type="button"
				class="action"
				aria-label={m.incoming_dismiss_label({ url: job.source_url })}
				data-act="dismiss"
				data-job={job.id}
				disabled={busy[job.id]}
				onclick={() => handleCancel(job.id, 'next-dismiss')}>{m.incoming_dismiss()}</button
			>
		</span>
		{#if errorFor(job)}
			<span class="error" role="alert">{errorFor(job)}</span>
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
		<h2 id="incoming-heading" class="sr-only">{m.incoming_heading()}</h2>
		<ul class="rows" aria-label={m.incoming_heading()}>
			{#each tuning as job (job.id)}
				<li class="row">
					<!-- Without the live link the row may be stale: no amber, no pulse. -->
					<span class="dot" class:stale={$link !== 'live'} aria-hidden="true"></span>
					<span class="mono state"
						>{m.incoming_tuning({
							source: SOURCE_LABEL[job.source_type]?.() ?? job.source_type
						})}</span
					>
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
							aria-label={m.incoming_cancel_label({ url: job.source_url })}
							data-act="cancel"
							data-job={job.id}
							onclick={() => confirmCancelTuning(job)}>{m.incoming_cancel()}</button
						>
					</span>
					{#if errorFor(job)}
						<span class="error" role="alert">{errorFor(job)}</span>
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
					<span class="summary-text">{m.incoming_older(counted(olderFailed.length))}</span>
					<span class="actions">
						<button
							type="button"
							class="action"
							aria-expanded={showOlder}
							data-act="older"
							aria-label={showOlder
								? m.incoming_older_hide_label(counted(olderFailed.length))
								: m.incoming_older_show_label(counted(olderFailed.length))}
							onclick={() => (showOlder = !showOlder)}
							>{showOlder ? m.incoming_older_hide() : m.incoming_older_show()}</button
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
