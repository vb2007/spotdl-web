<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import Waterfall from '$lib/components/Waterfall.svelte';
	import QueueTable from '$lib/components/QueueTable.svelte';

	const { activeTracks, trackList, jobs } = queue;

	let { data } = $props();

	let url = $state('');
	let submitting = $state(false);
	let submitError = $state('');

	async function onsubmit(event: SubmitEvent) {
		event.preventDefault();
		if (!url.trim()) return;
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

	onMount(() => {
		queue.loadAll();

		const source = api.createEventSource();
		source.onopen = () => {
			// Per the v08 contract: resync full REST state on every connect/reconnect
			// rather than trying to replay whatever happened while disconnected.
			queue.loadAll();
		};
		source.onmessage = (event) => {
			queue.applyEvent(JSON.parse(event.data));
		};

		return () => source.close();
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
			<span class="mono">{data.email}</span>
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
