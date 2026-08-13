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
	import IncomingJobs from '$lib/components/IncomingJobs.svelte';
	import WorkerStatus from '$lib/components/WorkerStatus.svelte';
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

	// Admin-only (v17): mine/all-users scope. Off by default even for an admin --
	// switching it clears the queue store (see queue.setAllUsers) and reconnects the
	// SSE stream so both REST and live data agree on scope.
	let allUsersView = $state(false);

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

	function connectStream() {
		source = api.createEventSource(allUsersView);
		source.onopen = () => {
			streamRetryDelayMs = 1000;
			// Per the v08 contract: resync full REST state on every connect/reconnect
			// rather than trying to replay whatever happened while disconnected.
			queue.reload();
		};
		source.onmessage = (event) => {
			queue.applyEvent(JSON.parse(event.data));
		};
		source.onerror = () => {
			if (source?.readyState !== EventSource.CLOSED) {
				// Browser is already retrying on its own (readyState === CONNECTING).
				return;
			}
			source.close();
			streamRetryTimer = setTimeout(connectStream, streamRetryDelayMs);
			streamRetryDelayMs = Math.min(streamRetryDelayMs * 2, 30_000);
		};
	}

	/** Admin-only (v17): both REST and SSE must agree on scope, so switching requires
	 * clearing the accumulated store (queue.setAllUsers, which also reloads the current
	 * page under the new scope) and reconnecting the stream carrying the new all_users
	 * flag -- the existing connection has no way to change what channel it's subscribed
	 * to mid-flight. */
	async function onAllUsersChange(next: boolean) {
		if (next === allUsersView) return;
		allUsersView = next;
		clearTimeout(streamRetryTimer);
		streamRetryDelayMs = 1000;
		source?.close();
		queue.setAllUsers(next);
		connectStream();
	}

	onMount(() => {
		queue.reload();
		connectStream();

		return () => {
			clearTimeout(streamRetryTimer);
			source?.close();
		};
	});
</script>

<svelte:head>
	<title>spotdl-web — queue</title>
</svelte:head>

<main class="stage">
	<header>
		<div class="ident">
			<span class="label">SPOTDL // WEB</span>
			<span class="label dim">SIGNAL RECEIVER</span>
		</div>
		<div class="session">
			{#if isAdmin}
				<a class="settings-link mono" href={resolve('/settings')}>settings</a>
			{/if}
			<a class="settings-link mono" href={resolve('/account')}>account</a>
			<span class="mono">{data.session?.email}</span>
			<button type="button" class="logout" onclick={onLogout}>disconnect</button>
		</div>
	</header>

	<form class="panel submit" {onsubmit}>
		<span class="prompt mono" aria-hidden="true">&gt;</span>
		<input
			type="url"
			placeholder="paste a Spotify track / album / playlist / artist URL"
			bind:value={url}
			disabled={submitting}
			aria-label="Spotify URL to submit"
			aria-describedby="submit-error"
		/>
		<button type="submit" disabled={submitting}>{submitting ? 'SENDING…' : 'SUBMIT'}</button>
	</form>
	<p id="submit-error" class="submit-error mono" role="alert">{submitError}</p>

	<WorkerStatus {isAdmin} />

	<IncomingJobs jobs={$incomingJobs} />

	<Waterfall tracks={$activeTracks} busy={workerBusy} />

	<QueueControls
		{isAdmin}
		allUsers={allUsersView}
		{onAllUsersChange}
		countsByStatus={$page.countsByStatus}
	/>

	{#if $filters.scope === 'jobs' && $page.totalEstimate > 0}
		<p class="count-hint mono dim">
			{$page.items.length} of {$page.totalEstimate >= 1000 ? '1000+' : $page.totalEstimate}
		</p>
	{/if}

	{#if $page.loading}
		<p class="hint mono">Loading…</p>
	{:else if $page.error}
		<p class="hint fail mono" role="alert">{$page.error}</p>
	{:else if $page.items.length === 0}
		<p class="hint mono">Nothing here.</p>
	{:else if $filters.scope === 'jobs'}
		<ul class="job-list panel">
			{#each $page.items as item (item.id)}
				<JobRow job={item as Job} allUsers={allUsersView} />
			{/each}
		</ul>
	{:else}
		<ul class="job-list panel">
			{#each trackGroups as group (group.job.id)}
				<li class="track-group">
					<div class="group-header">
						<span class="title">{group.job.title}</span>
						<span class="source-type mono">{group.job.source_type}</span>
						{#if allUsersView}
							<span class="owner mono">{group.job.owner_email}</span>
						{/if}
					</div>
					<ul class="rows">
						{#each group.tracks as track (track.id)}
							<TrackRow {track} jobId={group.job.id} />
						{/each}
					</ul>
				</li>
			{/each}
		</ul>
	{/if}

	{#if $page.nextCursor}
		<button
			type="button"
			class="load-more panel"
			disabled={$page.loadingMore}
			onclick={() => queue.loadMore()}
		>
			{$page.loadingMore ? 'loading…' : 'load more'}
		</button>
	{/if}
</main>

<style>
	.stage {
		max-width: 64rem;
		margin: 0 auto;
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}

	header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-4);
		flex-wrap: wrap;
	}

	.ident {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.ident .dim {
		color: var(--text-dim);
	}

	.session {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-3);
		font-size: 0.8125rem;
		color: var(--text-muted);
	}

	.settings-link {
		color: var(--text-muted);
		text-decoration: none;
	}

	.settings-link:hover,
	.settings-link:focus-visible {
		color: var(--signal-dim);
	}

	.logout {
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-1) var(--space-3);
		color: var(--text-muted);
		cursor: pointer;
	}

	.logout:hover,
	.logout:focus-visible {
		border-color: var(--fail);
		color: var(--fail);
	}

	.submit {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
	}

	.prompt {
		color: var(--signal);
		font-weight: 600;
	}

	.submit input {
		flex: 1;
		min-width: 0;
		background: var(--bg-0);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-3);
		box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.5);
	}

	.submit input:focus-visible {
		border-color: var(--signal-dim);
	}

	.submit button {
		background: var(--bg-2);
		border: 1px solid var(--line-bright);
		border-radius: 4px;
		padding: var(--space-3) var(--space-4);
		font-family: var(--font-mono);
		font-weight: 600;
		letter-spacing: 0.06em;
		cursor: pointer;
		white-space: nowrap;
	}

	.submit button:hover:not(:disabled),
	.submit button:focus-visible {
		border-color: var(--signal);
		background: var(--bg-3);
		box-shadow: 0 0 12px -2px var(--signal-glow);
	}

	.submit-error {
		min-height: 1rem;
		margin-top: calc(var(--space-4) * -1);
		color: var(--fail);
		font-size: 0.8125rem;
	}

	.count-hint {
		margin: calc(var(--space-3) * -1) 0 0;
		color: var(--text-dim);
		font-size: 0.75rem;
	}

	.hint {
		margin: 0;
		padding: var(--space-5) 0;
		text-align: center;
		color: var(--text-dim);
	}

	.hint.fail {
		color: var(--fail);
	}

	.job-list {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.track-group {
		border-bottom: 1px solid var(--line);
	}

	.track-group:last-child {
		border-bottom: none;
	}

	.group-header {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		background: var(--bg-2);
	}

	.group-header .title {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-weight: 500;
		flex: 1;
	}

	.group-header .source-type {
		flex-shrink: 0;
		color: var(--text-dim);
		font-size: 0.6875rem;
		text-transform: uppercase;
	}

	.group-header .owner {
		flex-shrink: 0;
		color: var(--text-muted);
		font-size: 0.75rem;
	}

	.rows {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.load-more {
		background: var(--bg-1);
		border: 1px solid var(--line);
		padding: var(--space-3);
		font-family: var(--font-mono);
		font-size: 0.75rem;
		color: var(--text-muted);
		cursor: pointer;
		text-align: center;
	}

	.load-more:hover:not(:disabled),
	.load-more:focus-visible {
		border-color: var(--signal-dim);
		color: var(--text-primary);
	}

	.load-more:disabled {
		opacity: 0.6;
		cursor: default;
	}
</style>
