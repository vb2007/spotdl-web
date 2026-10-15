<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import { queue, groupTracksByJob } from '$lib/stores/queue';
	import type { Job } from '$lib/api';
	import type { LiveTrackWithJob } from '$lib/stores/queue';
	import { worker } from '$lib/stores/worker';
	import Waterfall from '$lib/components/Waterfall.svelte';
	import { link } from '$lib/stores/link';
	import IncomingJobs from '$lib/components/IncomingJobs.svelte';
	import WorkerStatusPill from '$lib/components/WorkerStatusPill.svelte';
	import QueueControls from '$lib/components/QueueControls.svelte';
	import JobRow from '$lib/components/JobRow.svelte';
	import TrackRow from '$lib/components/TrackRow.svelte';

	const { filters, page, incomingJobs, activeTracks } = queue;
	const { status: workerStatus } = worker;

	let { data } = $props();
	// Nullable per +layout.ts's type -- in practice never null here, since its `load`
	// redirects to /login before this page ever renders without a session. Falling back
	// to false/undefined rather than asserting non-null keeps this reactive to `data`
	// the same way the template's direct `data.session?.email` access already is.
	const isAdmin = $derived(data.session?.is_admin ?? false);

	let workerBusy = $derived($workerStatus?.busy ?? false);
	let workerPaused = $derived($workerStatus?.paused ?? false);
	// Only while it is still in the future (the backend's own `breaker_active` test); the
	// 5s poll below re-derives it, so a cleared hold drops out within one poll.
	let breakerUntil = $derived(
		$workerStatus?.breaker_tripped_until != null &&
			Date.parse($workerStatus.breaker_tripped_until) > Date.now()
			? $workerStatus.breaker_tripped_until
			: null
	);

	// v42 (F05): this page's own SSE link (`$link`), shown in the header and the Waterfall,
	// so a dropped stream never looks like a connected one; the layout reads it too.

	// Admin-only (v17): mine/all-users scope. Off by default even for an admin --
	// switching it clears the queue store (see queue.setAllUsers) and reconnects the
	// SSE stream so both REST and live data agree on scope.
	let allUsersView = $state(false);

	let filtersActive = $derived(
		$filters.q.trim() !== '' || $filters.status.length > 0 || $filters.state.length > 0
	);
	let scopeNoun = $derived($filters.scope === 'jobs' ? 'jobs' : 'tracks');
	let countText = $derived(
		$page.loading
			? 'Loading…'
			: $page.error
				? ''
				: $filters.scope === 'jobs'
					? `${$page.items.length} of ${$page.totalEstimate >= 1000 ? '1000+' : $page.totalEstimate} jobs`
					: `${$page.items.length}${$page.nextCursor ? '+' : ''} tracks`
	);

	// v42: both state buttons swap their own block out (loading replaces it), so focus is
	// handed to a target that stays: the search box, or the queue's heading.
	function clearSearchAndFilters() {
		queue.setFilters({ q: '', status: [], state: [] });
		document.getElementById('queue-search')?.focus();
	}

	function retryQueue() {
		queue.reload();
		document.getElementById('queue-heading')?.focus();
	}

	function focusSubmit() {
		document.getElementById('submit-url')?.focus();
	}

	let trackGroups = $derived(
		$filters.scope === 'tracks' ? groupTracksByJob($page.items as LiveTrackWithJob[]) : []
	);

	let url = $state('');
	let submitting = $state(false);
	let submitError = $state('');

	async function onsubmit(event: SubmitEvent) {
		event.preventDefault();
		if (!url.trim()) {
			submitError = 'Paste a URL first.';
			return;
		}
		submitting = true;
		submitError = '';
		try {
			const job = await api.createJob(url.trim());
			queue.addJob(job);
			url = '';
		} catch (err) {
			submitError = err instanceof api.ApiError ? err.message : 'Could not submit that URL.';
		} finally {
			submitting = false;
		}
	}

	async function onLogout() {
		await api.logout();
		// `queue` is a module-level singleton that survives this SPA navigation -- clear it
		// before leaving, so a different identity logging in on the same tab next can never
		// render a flash of this session's rows while its own reload() is still in flight.
		queue.reset();
		source?.close();
		await goto(resolve('/login'));
	}

	// v12: previously relied entirely on the browser's built-in EventSource auto-reconnect,
	// which only covers a network-level drop (a raw TCP reset, readyState -> CONNECTING,
	// retried automatically). Per spec, a response with a non-2xx status or the wrong
	// content-type "fails the connection" permanently instead (readyState -> CLOSED, never
	// retried) -- something that was previously rare (a restarting `api` container gives the
	// browser a raw reset directly) but became routine once the same-origin nginx proxy
	// (frontend/nginx.conf) sits in front: `api` restarting now means nginx answers with a
	// real 502 (text/html), permanently killing the stream until a manual reload. This also
	// fixes a pre-existing gap where a 401 after session expiry already killed the stream for
	// the same reason. Reconnect manually with capped exponential backoff whenever the
	// browser has actually given up.
	let streamRetryDelayMs = 1000;
	let streamRetryTimer: ReturnType<typeof setTimeout> | undefined;
	let source: EventSource | undefined;
	// v34.2: the stream's `onopen` is the only resync (see queue.reload). Mount and every
	// scope switch arm one fallback: if the stream hasn't opened when it fails outright
	// (a 502/401 closes it) or within RESYNC_FALLBACK_MS (a network-level failure keeps it
	// CONNECTING, which never reaches the CLOSED branch below), do one plain REST reload so
	// the page shows its data or its error instead of "Loading…" indefinitely. The
	// eventual `onopen` still resyncs as usual.
	const RESYNC_FALLBACK_MS = 5000;
	let awaitingResync = false;
	let resyncFallbackTimer: ReturnType<typeof setTimeout> | undefined;

	function armResyncFallback() {
		awaitingResync = true;
		clearTimeout(resyncFallbackTimer);
		resyncFallbackTimer = setTimeout(resyncFallback, RESYNC_FALLBACK_MS);
	}

	function resyncFallback() {
		clearTimeout(resyncFallbackTimer);
		if (!awaitingResync) return;
		awaitingResync = false;
		queue.reload();
	}

	function connectStream() {
		source = api.createEventSource(allUsersView);
		source.onopen = () => {
			link.set('live');
			awaitingResync = false;
			clearTimeout(resyncFallbackTimer);
			streamRetryDelayMs = 1000;
			// Per the v08 contract: resync full REST state on every connect/reconnect
			// rather than trying to replay whatever happened while disconnected.
			queue.reload();
		};
		source.onmessage = (event) => {
			queue.applyEvent(JSON.parse(event.data));
		};
		source.onerror = () => {
			// Either way the stream is down right now: the browser retrying on its own
			// (CONNECTING) or given up until the retry below (CLOSED).
			link.set('reconnecting');
			if (source?.readyState !== EventSource.CLOSED) {
				// Browser is already retrying on its own (readyState === CONNECTING).
				return;
			}
			source.close();
			resyncFallback();
			streamRetryTimer = setTimeout(connectStream, streamRetryDelayMs);
			streamRetryDelayMs = Math.min(streamRetryDelayMs * 2, 30_000);
		};
	}

	/** Admin-only (v17): both REST and SSE must agree on scope, so switching requires
	 * clearing the accumulated store (queue.setAllUsers) and reconnecting the stream
	 * carrying the new all_users flag -- the existing connection has no way to change what
	 * channel it's subscribed to mid-flight. The new stream's `onopen` loads the new
	 * scope. */
	async function onAllUsersChange(next: boolean) {
		if (next === allUsersView) return;
		allUsersView = next;
		link.set('connecting');
		clearTimeout(streamRetryTimer);
		streamRetryDelayMs = 1000;
		source?.close();
		queue.setAllUsers(next);
		armResyncFallback();
		connectStream();
	}

	// Worker/breaker state has no SSE event: the same 5s poll the v25 pill ran, now here
	// for every user (v42), since the Waterfall's status line and TrackRow's breaker-aware
	// countdown read it and the pill itself is admin-only. A failed poll keeps the last value.
	const WORKER_POLL_MS = 5000;

	function pollWorker() {
		worker.refresh().catch(() => {});
	}

	onMount(() => {
		link.set('connecting');
		queue.beginResync();
		armResyncFallback();
		connectStream();
		pollWorker();
		const workerPoll = setInterval(pollWorker, WORKER_POLL_MS);

		return () => {
			clearInterval(workerPoll);
			clearTimeout(streamRetryTimer);
			clearTimeout(resyncFallbackTimer);
			source?.close();
		};
	});
</script>

<svelte:head>
	<title>spotdl-web — queue</title>
</svelte:head>

<div class="stage">
	<header class="masthead">
		<div class="ident">
			<h1 class="wordmark">
				<span aria-hidden="true">SPOTDL // WEB</span><span class="sr-only">spotdl-web</span>
			</h1>
			<span class="label">signal receiver</span>
		</div>
		<div class="status">
			<span class="link mono" class:down={$link !== 'live'} role="status">
				<span class="link-dot" aria-hidden="true"></span>
				{$link === 'live'
					? 'linked'
					: $link === 'connecting'
						? 'linking…'
						: 'link lost — reconnecting'}
			</span>
			{#if isAdmin}
				<WorkerStatusPill />
			{/if}
		</div>
		<nav class="session" aria-label="Account">
			{#if isAdmin}
				<a class="nav-link mono" href={resolve('/library')}>library</a>
				<a class="nav-link mono" href={resolve('/settings')}>settings</a>
			{/if}
			<a class="nav-link mono" href={resolve('/account')}>account</a>
			<span class="who mono" title={data.session?.email}
				>{api.displayName(data.session?.username ?? null, data.session?.email ?? '')}</span
			>
			<button type="button" class="logout mono" onclick={onLogout}>disconnect</button>
		</nav>
	</header>

	<!-- v42 (F29): the one main landmark, focusable so v45's skip link can land on it. -->
	<main id="main" class="main" tabindex="-1">
		<div class="submit-area">
			<form class="panel submit" {onsubmit} aria-label="Submit a link">
				<span class="prompt mono" class:sending={submitting} aria-hidden="true">&gt;</span>
				<input
					id="submit-url"
					class="well"
					type="url"
					placeholder="paste a Spotify link — track, album, playlist or artist"
					bind:value={url}
					disabled={submitting}
					aria-label="Spotify URL to submit"
					aria-describedby="submit-error"
				/>
				<button type="submit" class="mono" disabled={submitting}
					>{submitting ? 'SENDING…' : 'SUBMIT'}</button
				>
			</form>
			<p id="submit-error" class="submit-error" role="alert">{submitError}</p>
		</div>

		<IncomingJobs
			jobs={$incomingJobs}
			allUsers={allUsersView}
			sessionEmail={data.session?.email ?? ''}
			{isAdmin}
		/>

		<Waterfall
			tracks={$activeTracks}
			busy={workerBusy}
			link={$link}
			{breakerUntil}
			paused={workerPaused}
			{isAdmin}
		/>

		<section class="panel queue" aria-labelledby="queue-heading">
			<QueueControls
				{isAdmin}
				allUsers={allUsersView}
				{onAllUsersChange}
				countsByStatus={$page.countsByStatus}
				countsByState={$page.countsByState}
				{countText}
			/>

			{#if $page.loading}
				<!-- Placeholder rows in the list's own rhythm; the head's "Loading…" says why. -->
				<ul class="skeleton" aria-hidden="true">
					{#each [0, 1, 2] as i (i)}
						<li><span class="bone badge"></span><span class="bone line"></span></li>
					{/each}
				</ul>
			{:else if $page.error}
				<div class="state" role="alert">
					<h3 class="state-title">Couldn't load the queue</h3>
					<p class="state-text">
						<span class="mono">{$page.error}</span>
					</p>
					<button type="button" class="state-action mono" onclick={retryQueue}>try again</button>
				</div>
			{:else if $page.items.length === 0}
				<div class="state">
					{#if filtersActive}
						<h3 class="state-title">
							No {scopeNoun} match {$filters.q.trim() ? `“${$filters.q.trim()}”` : 'these filters'}
						</h3>
						<p class="state-text">
							{$filters.includeArchived
								? 'Archived ones are included.'
								: 'Archived ones are hidden; show archived searches them too.'}
						</p>
						<button type="button" class="state-action mono" onclick={clearSearchAndFilters}
							>clear search and filters</button
						>
					{:else if allUsersView}
						<h3 class="state-title">Nobody has anything queued</h3>
						<p class="state-text">Every user's queue is empty in this view.</p>
					{:else}
						<h3 class="state-title">Your queue is empty</h3>
						<p class="state-text">
							Paste a Spotify link above. Each track downloads in the background, and a rate limit
							only means it waits its turn{$filters.includeArchived
								? '.'
								: '. Archived jobs stay under show archived.'}
						</p>
						<button type="button" class="state-action mono" onclick={focusSubmit}
							>paste a link</button
						>
					{/if}
				</div>
			{:else if $filters.scope === 'jobs'}
				<ul class="job-list" aria-label="Jobs">
					{#each $page.items as item (item.id)}
						<JobRow job={item as Job} allUsers={allUsersView} {isAdmin} />
					{/each}
				</ul>
			{:else}
				<ul class="job-list" aria-label="Tracks">
					{#each trackGroups as group (group.job.id)}
						<li class="track-group" aria-labelledby="group-title-{group.job.id}">
							<!-- v41: the job row's grid, minus the chevron -- its type sits in the badge
							     column and its title over the track titles below (F02). -->
							<div class="group-header">
								<span class="source-type mono">{group.job.source_type}</span>
								<span class="title" id="group-title-{group.job.id}" title={group.job.title}
									>{group.job.title}</span
								>
								{#if allUsersView}
									<span class="owner mono" title={group.job.owner_email}
										>{api.displayName(group.job.owner_username, group.job.owner_email)}</span
									>
								{/if}
							</div>
							<ul class="rows">
								{#each group.tracks as track (track.id)}
									<TrackRow {track} jobId={group.job.id} {isAdmin} />
								{/each}
							</ul>
						</li>
					{/each}
				</ul>
			{/if}

			<!-- A failed "load more" keeps the loaded rows (moreError, not error); this button
			     retries just that page. -->
			{#if $page.moreError}
				<p class="more-error" role="alert">
					Couldn't load more. <span class="mono">{$page.moreError}</span>
				</p>
			{/if}
			{#if $page.nextCursor && !$page.loading && !$page.error}
				<button
					type="button"
					class="load-more mono"
					disabled={$page.loadingMore}
					onclick={() => queue.loadMore()}
				>
					{$page.loadingMore ? 'loading…' : `load more ${scopeNoun}`}
				</button>
			{/if}
		</section>
	</main>
</div>

<style>
	.stage {
		max-width: 64rem;
		margin: 0 auto;
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}

	/* Masthead: ident left, the account nav right, the receiver's own status (link tell,
	   and the admin's worker pill) between them, pushed against the nav. */
	.masthead {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		grid-template-areas: 'ident status nav';
		align-items: center;
		gap: var(--space-2) var(--space-5);
	}

	.ident {
		grid-area: ident;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.wordmark {
		font-family: var(--font-mono);
		font-size: var(--fs-lead);
		font-weight: var(--fw-strong);
		letter-spacing: 0.14em;
		line-height: 1.2;
		color: var(--text-primary);
	}

	.status {
		grid-area: status;
		display: flex;
		align-items: baseline;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-4);
	}

	/* F05: the link tell. Linked is quiet (a filled dot, muted); down is the waiting blue
	   with a hollow ring, so it differs in shape as well as hue. Never amber: a link is
	   not a download. */
	.link {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--fs-meta);
		color: var(--text-muted);
	}

	.link-dot {
		width: 0.4375rem;
		height: 0.4375rem;
		border-radius: 50%;
		background: var(--text-muted);
	}

	.link.down {
		color: var(--waiting);
	}

	.link.down .link-dot {
		background: transparent;
		border: 1.5px solid var(--waiting);
		animation: link-pulse 2.4s ease-in-out infinite;
	}

	@keyframes link-pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.35;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.link.down .link-dot {
			animation: none;
		}
	}

	.session {
		grid-area: nav;
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: var(--space-1) var(--space-4);
		font-size: var(--fs-detail);
		color: var(--text-muted);
	}

	/* F10 (v40 verdict): a link is marked by its underline, never by amber. Hover only
	   brings the text up to primary. */
	.nav-link {
		color: var(--text-muted);
		text-decoration: underline;
		text-decoration-color: var(--line-control);
		text-underline-offset: 0.3em;
	}

	.nav-link:hover,
	.nav-link:focus-visible {
		color: var(--text-primary);
		text-decoration-color: currentColor;
	}

	.who {
		color: var(--text-primary);
		max-width: 14rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.logout {
		background: transparent;
		border: 1px solid var(--line-control);
		border-radius: 4px;
		padding: var(--space-1) var(--space-3);
		color: var(--text-muted);
		font-size: var(--fs-meta);
		cursor: pointer;
	}

	.logout:hover,
	.logout:focus-visible {
		border-color: var(--fail);
		color: var(--fail);
	}

	.main {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}

	/* Skip-link target: focus lands here programmatically, not as a visible stop. */
	.main:focus {
		outline: none;
	}

	.submit-area {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.submit {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
	}

	/* F10 (v40 verdict): muted at rest; amber only while a link is actually being sent. */
	.prompt {
		color: var(--text-muted);
		font-weight: var(--fw-strong);
	}

	.prompt.sending {
		color: var(--signal);
	}

	.submit input {
		flex: 1;
		min-width: 0;
		padding: var(--space-3);
	}

	.submit button {
		background: var(--bg-2);
		border: 1px solid var(--line-control);
		border-radius: 4px;
		padding: var(--space-3) var(--space-4);
		font-weight: var(--fw-strong);
		letter-spacing: 0.06em;
		cursor: pointer;
		white-space: nowrap;
	}

	/* F10: no amber and no halo; focus is the global ring alone. */
	.submit button:hover:not(:disabled) {
		background: var(--bg-3);
		border-color: var(--text-muted);
	}

	.submit-error {
		min-height: 1.25rem;
		padding: 0 var(--space-4);
		color: var(--fail);
		font-size: var(--fs-detail);
	}

	.submit-error:empty {
		min-height: 0;
	}

	.queue {
		display: flex;
		flex-direction: column;
	}

	.job-list {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	/* Loading: three still placeholder rows on the row grid -- no shimmer, the list is
	   seconds away and motion would only add noise. */
	.skeleton {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.skeleton li {
		display: grid;
		grid-template-columns: var(--col-state) minmax(0, 1fr);
		gap: var(--row-gap);
		align-items: center;
		padding: var(--space-4) var(--row-pad-x) var(--space-4) calc(var(--row-pad-x) + var(--row-nest));
		border-bottom: 1px solid var(--line);
	}

	.skeleton li:last-child {
		border-bottom: none;
	}

	.bone {
		display: block;
		height: 0.75rem;
		border-radius: 3px;
		background: var(--bg-3);
	}

	.bone.badge {
		width: 5rem;
	}

	.bone.line {
		width: 60%;
	}

	.skeleton li:nth-child(2) .bone.line {
		width: 45%;
	}

	.skeleton li:nth-child(3) .bone.line {
		width: 70%;
	}

	/* F26: empty and error states that say which case this is and what to do next. */
	.state {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-2);
		padding: var(--space-6) var(--space-5);
	}

	.state-title {
		font-size: var(--fs-title);
		font-weight: var(--fw-medium);
		line-height: 1.3;
	}

	.state-text {
		max-width: 60ch;
		color: var(--text-muted);
	}

	.state[role='alert'] .state-title {
		color: var(--fail);
	}

	.state-action,
	.load-more {
		background: var(--bg-2);
		border: 1px solid var(--line-control);
		border-radius: 4px;
		padding: var(--space-2) var(--space-4);
		font-size: var(--fs-meta);
		color: var(--text-primary);
		cursor: pointer;
	}

	.state-action {
		margin-top: var(--space-2);
	}

	.state-action:hover,
	.load-more:hover:not(:disabled) {
		background: var(--bg-3);
		border-color: var(--text-muted);
	}

	.load-more {
		margin: var(--space-3) var(--space-4);
		color: var(--text-muted);
	}

	.more-error {
		margin: var(--space-3) var(--space-4) 0;
		color: var(--fail);
		font-size: var(--fs-detail);
	}

	.load-more:disabled {
		opacity: 0.6;
		cursor: default;
	}

	.track-group {
		border-bottom: 1px solid var(--line);
	}

	.track-group:last-child {
		border-bottom: none;
	}

	.group-header {
		display: grid;
		grid-template-columns: var(--col-state) minmax(0, max-content) minmax(0, auto);
		column-gap: var(--row-gap);
		align-items: baseline;
		padding: var(--space-3) var(--row-pad-x) var(--space-2) calc(var(--row-pad-x) + var(--row-nest));
	}

	.group-header .title {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-weight: var(--fw-medium);
	}

	.group-header .source-type {
		padding-left: var(--cell-inset);
		color: var(--text-muted);
		font-size: var(--fs-label);
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}

	/* Shares the line with the title; a long owner (an email) ellipsizes rather than
	   crushing it. */
	.group-header .owner {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--text-muted);
		font-size: var(--fs-meta);
	}

	/* The same nesting as an open job's tracks (JobTrackList.svelte): one lead column in,
	   hanging off a rail where the job row's chevron would be. */
	.rows {
		position: relative;
		list-style: none;
		margin: 0;
		padding: 0 0 0 calc(var(--row-pad-x) + var(--row-nest));
	}

	.rows::before {
		content: '';
		position: absolute;
		top: 0;
		bottom: var(--space-3);
		left: calc(var(--row-pad-x) + var(--col-lead) / 2);
		width: 1px;
		background: var(--line-bright);
	}

	/* F32: finger-sized targets on touch screens, whatever the width. */
	@media (pointer: coarse) {
		.logout,
		.state-action,
		.load-more,
		.submit button,
		.submit input {
			min-height: 2.75rem;
		}

		.nav-link {
			display: inline-flex;
			align-items: center;
			min-height: 2.75rem;
		}
	}

	/* Tablet (F37): the masthead keeps ident and nav on one line and drops the status to
	   its own line under them, left-aligned under the ident, instead of squeezing three columns. */
	@media (max-width: 1023px) {
		.masthead {
			grid-template-columns: auto minmax(0, 1fr);
			grid-template-areas:
				'ident nav'
				'status status';
		}

		.status {
			justify-content: flex-start;
		}
	}

	/* Phone (F15): about a screen of chrome before the first job came down to the header
	   on two lines (ident + link tell, then the nav in one row), tighter page gutters, and
	   the controls' own trimmed rows. */
	@media (max-width: 640px) {
		.stage {
			padding: var(--space-4);
			gap: var(--space-4);
		}

		.main {
			gap: var(--space-4);
		}

		.masthead {
			grid-template-columns: auto minmax(0, 1fr);
			grid-template-areas:
				'ident status'
				'nav nav';
			align-items: start;
		}

		.wordmark {
			white-space: nowrap;
		}

		.ident .label {
			display: none;
		}

		.status {
			flex-direction: column;
			align-items: flex-end;
			gap: var(--space-1);
			text-align: right;
		}

		.session {
			justify-content: flex-start;
			gap: var(--space-1) var(--space-3);
		}

		.logout {
			margin-left: auto;
		}

		.submit {
			padding: var(--space-2) var(--space-3);
			gap: var(--space-2);
		}

		.submit input {
			padding: var(--space-2) var(--space-3);
		}

		.submit button {
			padding: var(--space-2) var(--space-3);
		}

		.state {
			padding: var(--space-5) var(--space-4);
		}

		/* Type and owner on the first line, the whole title on the second, as JobRow's
		   phone stack does; a long owner never takes the title's width. */
		.group-header {
			grid-template-columns: minmax(0, max-content) minmax(0, 1fr);
		}

		.group-header .source-type {
			grid-column: 1;
			grid-row: 1;
			padding-left: 0;
		}

		.group-header .owner {
			grid-column: 2;
			grid-row: 1;
		}

		.group-header .title {
			grid-column: 1 / -1;
			grid-row: 2;
		}
	}
</style>
