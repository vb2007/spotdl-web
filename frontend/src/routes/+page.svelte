<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
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
	import { registerHandlers } from '$lib/keyboard/registry';
	import { collapseFocused, focusRowEl, kbList, listHandlers } from '$lib/keyboard/lists';

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
	// SSE stream so both REST and live data agree on scope. v42: it starts from the store's
	// own scope, which outlives this page (a trip to /settings and back): starting at "mine"
	// while the store still fetched all users mislabelled every foreign row as the admin's.
	// Never for a non-admin, whatever an earlier admin session on this tab left in the store.
	let allUsersView = $state(untrack(() => isAdmin) && queue.getAllUsers());

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
					? `${$page.items.length} of ${$page.totalEstimate >= 1000 ? '1000+' : $page.totalEstimate} ${$page.totalEstimate === 1 ? 'job' : 'jobs'}`
					: `${$page.items.length}${$page.nextCursor ? '+' : ''} ${$page.items.length === 1 && !$page.nextCursor ? 'track' : 'tracks'}`
	);

	// v42: both state buttons swap their own block out (loading replaces it), so focus is
	// handed to a target that stays: the search box, or the queue's heading.
	let controls: ReturnType<typeof QueueControls> | undefined = $state();

	function clearSearchAndFilters() {
		controls?.clearSearchAndFilters();
	}

	// v45: "load more" moves focus to the first row it loaded (where the user reads on), else
	// the queue's heading. Rows are found by item id, not DOM position: in tracks scope a new
	// page's tracks can join an earlier group. A pointer press leaves focus where it is unless
	// the last page took the button away from under it.
	async function loadMorePage(event: MouseEvent) {
		const button = event.currentTarget as HTMLElement;
		const fromKeyboard = event.detail === 0;
		await loadMoreRows(
			() => fromKeyboard || document.activeElement === document.body || !button.isConnected
		);
	}

	/** Loads the next page; `shouldFocus()` (asked once it's in) decides whether its first row
	 * takes focus. Whether there was a page to load. */
	async function loadMoreRows(shouldFocus: () => boolean = () => true): Promise<boolean> {
		if ($page.loading || $page.loadingMore || !$page.nextCursor) return false;
		const focusAtStart = document.activeElement;
		const known = new Set($page.items.map((item) => item.id));
		await queue.loadMore();
		await tick();
		// Focus the user moved somewhere else meanwhile is theirs.
		const moved =
			document.activeElement !== focusAtStart && document.activeElement !== document.body;
		if (moved || !shouldFocus()) return true;
		const fresh = $page.items.find((item) => !known.has(item.id));
		const row = fresh
			? document.querySelector<HTMLElement>(`[data-kb-row="${CSS.escape(fresh.id)}"]`)
			: null;
		if (!focusRowEl(row)) document.getElementById('queue-heading')?.focus();
		return true;
	}

	// v45: the dashboard's keys -- the lists', the queue controls', and Esc's two jobs here
	// (close the focused row, else clear and leave the search).
	$effect(() =>
		registerHandlers({
			...listHandlers({
				mainList: () => ($filters.scope === 'jobs' ? 'jobs' : 'tracks'),
				loadMore: () => loadMoreRows()
			}),
			search: () => focusField('queue-search'),
			submit: () => focusField('submit-url'),
			escape: (event) => {
				if (collapseFocused()) return true;
				const search = document.getElementById('queue-search');
				if (!search || event.target !== search) return false;
				controls?.clearSearch();
				search.blur();
				return true;
			},
			'scope-jobs': () => (controls?.setScope('jobs'), true),
			'scope-tracks': () => (controls?.setScope('tracks'), true),
			filters: () => controls?.focusFilters() ?? false,
			sort: () => (controls?.cycleSort(), true),
			archived: () => (controls?.toggleArchived(), true)
		})
	);

	// v45: where focus goes when the focused list empties out (its last row cancelled or
	// archived away): the queue's heading, once no reload is still bringing the list back.
	function listFallback(): HTMLElement | null {
		return $page.loading ? null : document.getElementById('queue-heading');
	}

	function focusField(id: string): boolean {
		const field = document.getElementById(id) as HTMLInputElement | null;
		if (!field || field.disabled) return false;
		field.focus();
		return true;
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
		// A logout while the POST is in flight resets the store; the created job then belongs
		// to the previous identity and must not land in the next one's overlay (v42 sweep).
		const session = queue.getResetCount();
		try {
			const job = await api.createJob(url.trim());
			if (queue.getResetCount() !== session) return;
			queue.addJob(job);
			url = '';
		} catch (err) {
			submitError = err instanceof api.ApiError ? err.message : 'Could not submit that URL.';
		} finally {
			submitting = false;
		}
		// The disabled input lost focus while sending; give it back for the next link.
		await tick();
		// Not on touch: refocusing the input would reopen the keyboard over what was just sent.
		if (document.activeElement === document.body && !window.matchMedia('(pointer: coarse)').matches)
			document.getElementById('submit-url')?.focus();
	}

	async function onLogout() {
		loggingOut = true;
		try {
			await api.logout();
		} catch (err) {
			// Still here and still signed in: the reload guard must work again.
			loggingOut = false;
			throw err;
		}
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
	// This page's own logout resets the store on purpose; outlived() must not reload then.
	let loggingOut = false;
	// The reset count this page mounted under; see connectStream's outlived(). Checked on
	// every poll too, so a reset is caught within 5s even while the stream is quiet.
	const mountedSession = queue.getResetCount();
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
		const stream = api.createEventSource(allUsersView);
		source = stream;
		// v42: the stream belongs to the session it was opened under. If the store is reset
		// meanwhile without this page logging out (an identity change in another tab, or a
		// session gone stale, caught by the layout -- possibly on a hover preload, with this
		// page still mounted), its events would refill the next identity's overlays and this
		// page's header and admin chrome describe someone else. Drop the event, stop the
		// stream, and reload: the layout then runs for whoever the session is now (or sends
		// the tab to /login), and nothing is left showing a dead link as "linked".
		// Against the count the page mounted under, not one captured here: a retry timer
		// firing after a reset must not open a stream that counts as current.
		const outlived = () => {
			if (queue.getResetCount() === mountedSession) return false;
			stream.close();
			clearTimeout(streamRetryTimer);
			if (!loggingOut) window.location.reload();
			return true;
		};
		// Events are applied only once this stream's identity check passed; anything dropped
		// before that is covered by the resync that follows it.
		let verified = false;
		const current = () => source === stream && stream.readyState === EventSource.OPEN;
		stream.onopen = async () => {
			// The browser can re-open this same EventSource: every opening is checked anew.
			verified = false;
			if (outlived()) return;
			// The cookie is shared across tabs: a reconnect sends whoever is signed in now.
			// If that isn't this page's identity, reload rather than adopt it under this
			// page's header and admin chrome (one request per (re)connect, not per row).
			try {
				const now = await api.me();
				if (now.email !== data.session?.email) {
					stream.close();
					window.location.reload();
					return;
				}
			} catch {
				// Can't tell (a blip): carry on; the layout and next reconnect check again.
			}
			// The stream may have dropped, or been replaced by a scope switch, meanwhile.
			if (outlived() || !current()) return;
			verified = true;
			link.set('live');
			awaitingResync = false;
			clearTimeout(resyncFallbackTimer);
			streamRetryDelayMs = 1000;
			// Per the v08 contract: resync full REST state on every connect/reconnect
			// rather than trying to replay whatever happened while disconnected.
			queue.reload();
		};
		stream.onmessage = (event) => {
			if (outlived() || !verified) return;
			queue.applyEvent(JSON.parse(event.data));
		};
		stream.onerror = () => {
			if (outlived()) return;
			// Either way the stream is down right now: the browser retrying on its own
			// (CONNECTING) or given up until the retry below (CLOSED).
			link.set('reconnecting');
			if (stream.readyState !== EventSource.CLOSED) {
				// Browser is already retrying on its own (readyState === CONNECTING).
				return;
			}
			stream.close();
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
		if (!loggingOut && queue.getResetCount() !== mountedSession) {
			window.location.reload();
			return;
		}
		worker.refresh().catch(() => {});
	}

	onMount(() => {
		// The store's scope outlives the page; a non-admin must never inherit an admin's.
		if (!isAdmin && queue.getAllUsers()) queue.setAllUsers(false);
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
				<a class="nav-link mono" href={resolve('/stats')}>stats</a>
			{/if}
			<a class="nav-link mono" href={resolve('/account')}>account</a>
			<span class="who mono" title={data.session?.email}
				>{api.displayName(data.session?.username ?? null, data.session?.email ?? '')}</span
			>
			<button type="button" class="logout mono" onclick={onLogout}>disconnect</button>
		</nav>
	</header>

	<!-- v42 (F29): the one main landmark; v45's skip link targets #main. No tabindex here:
	     a tabindex="-1" container takes focus on any click inside it and resets Tab order. -->
	<main id="main" class="main">
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
				bind:this={controls}
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
					{:else if $incomingJobs.some((j) => j.state === 'expanding' && (allUsersView || j.owner_email === data.session?.email))}
						<h3 class="state-title">
							{allUsersView ? 'A link is being read' : 'Your link is being read'}
						</h3>
						<p class="state-text">
							Its tracks appear here once Spotify has listed them, and each one downloads in the
							background.
						</p>
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
				<!-- v45: each list is one Tab stop (roving tabindex, lib/keyboard/lists.ts). -->
				<ul class="job-list" aria-label="Jobs" {@attach kbList('jobs', { fallback: listFallback })}>
					{#each $page.items as item (item.id)}
						<JobRow job={item as Job} allUsers={allUsersView} {isAdmin} />
					{/each}
				</ul>
			{:else}
				<ul
					class="job-list"
					aria-label="Tracks"
					{@attach kbList('tracks', { fallback: listFallback })}
				>
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
			<!-- Stays mounted (aria-disabled) through a background reload (a reconnect's resync),
			     so a keyboard user's focus on it isn't dropped to the page. -->
			{#if $page.nextCursor && !$page.error}
				<button
					type="button"
					class="load-more mono"
					aria-disabled={$page.loadingMore || $page.loading}
					onclick={loadMorePage}
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

	/* Wraps rather than truncating (the tooltip holding the full name is unreachable by
	   keyboard and touch), within a cap, so a long email-as-name can't squeeze the
	   masthead's status column off the desktop row. */
	.who {
		max-width: 20rem;
		color: var(--text-primary);
		overflow-wrap: anywhere;
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

	/* A searched link or URI is one unbreakable run; it must wrap, not scroll the page. */
	.state-title,
	.state-text {
		overflow-wrap: anywhere;
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
	.load-more:hover:not([aria-disabled='true']) {
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

	/* aria-disabled, not disabled: disabling the focused button would drop focus to the
	   page, and this button is also how a failed page is retried (v41's JobTrackList fix). */
	.load-more[aria-disabled='true'] {
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
