<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import Waterfall from '$lib/components/Waterfall.svelte';
	import QueueTable from '$lib/components/QueueTable.svelte';
	import IncomingJobs from '$lib/components/IncomingJobs.svelte';
	import WorkerStatus from '$lib/components/WorkerStatus.svelte';

	const { activeTracks, trackList, jobs, incomingJobs } = queue;

	let { data } = $props();
	// Nullable per +layout.ts's type -- in practice never null here, since its `load`
	// redirects to /login before this page ever renders without a session. Falling back
	// to false/undefined rather than asserting non-null keeps this reactive to `data`
	// the same way the template's direct `data.session?.email` access already is.
	const isAdmin = $derived(data.session?.is_admin ?? false);

	// Admin-only (v17): mine/all-users scope. Off by default even for an admin --
	// switching it clears the queue store (see queue.setAllUsers) and reconnects the
	// SSE stream so both REST and live data agree on scope.
	let allUsersView = $state(false);

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
			queue.loadAll();
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
	 * clearing the accumulated store (queue.setAllUsers), a fresh REST load, and a fresh
	 * stream connection carrying the new all_users flag -- the existing connection has
	 * no way to change what channel it's subscribed to mid-flight. */
	async function onScopeChange(next: boolean) {
		if (next === allUsersView) return;
		allUsersView = next;
		queue.setAllUsers(next);
		clearTimeout(streamRetryTimer);
		streamRetryDelayMs = 1000;
		source?.close();
		await queue.loadAll();
		connectStream();
	}

	onMount(() => {
		queue.loadAll();
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
			<span class="mono">{data.session?.email}</span>
			<button type="button" class="logout" onclick={onLogout}>disconnect</button>
		</div>
	</header>

	{#if isAdmin}
		<div class="scope-toggle" role="group" aria-label="Viewing scope">
			<button type="button" aria-pressed={!allUsersView} onclick={() => onScopeChange(false)}>
				mine
			</button>
			<button type="button" aria-pressed={allUsersView} onclick={() => onScopeChange(true)}>
				all users
			</button>
		</div>
	{/if}

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

	<Waterfall tracks={$activeTracks} />
	<QueueTable tracks={$trackList} jobs={$jobs} />
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

	/* Same role=group + aria-pressed toggle-tab pattern as QueueTable.svelte's state
	   filters (DESIGN.md §6) -- but the pressed state maps to --line-bright, not
	   --signal: this switches a view scope, not a live/active condition, and DESIGN.md
	   §2 reserves amber exclusively for the latter. */
	.scope-toggle {
		display: flex;
		gap: var(--space-2);
	}

	.scope-toggle button {
		background: var(--bg-2);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-1) var(--space-3);
		font-family: var(--font-mono);
		font-size: 0.75rem;
		color: var(--text-muted);
		cursor: pointer;
	}

	.scope-toggle button[aria-pressed='true'] {
		border-color: var(--line-bright);
		color: var(--text-primary);
	}

	.scope-toggle button:hover:not([aria-pressed='true']),
	.scope-toggle button:focus-visible {
		border-color: var(--waiting-dim);
	}

	.ident .dim {
		color: var(--text-dim);
	}

	.session {
		display: flex;
		align-items: center;
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
</style>
