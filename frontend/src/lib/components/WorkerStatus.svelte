<script lang="ts">
	import { onMount } from 'svelte';
	import * as api from '$lib/api';
	import { worker } from '$lib/stores/worker';
	import Countdown from '$lib/components/Countdown.svelte';

	const { status } = worker;

	let busy = $state(false);
	let error = $state('');

	const POLL_MS = 5000;

	let breakerActive = $derived(
		$status?.breaker_tripped_until != null &&
			new Date($status.breaker_tripped_until).getTime() > Date.now()
	);

	async function handleToggle() {
		busy = true;
		error = '';
		try {
			if ($status?.paused) {
				await worker.resume();
			} else {
				await worker.pause();
			}
		} catch (err) {
			error = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		} finally {
			busy = false;
		}
	}

	async function handleRelease() {
		busy = true;
		error = '';
		try {
			await worker.release();
		} catch (err) {
			error = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		} finally {
			busy = false;
		}
	}

	onMount(() => {
		worker.refresh();
		// No dedicated SSE event exists for worker/breaker state (v10 plan) -- a plain
		// poll is the simplest way for a naturally-tripping breaker (5 consecutive
		// AudioProviderErrors, no user action involved) to still surface here without
		// the user having to reload.
		const id = setInterval(() => worker.refresh(), POLL_MS);
		return () => clearInterval(id);
	});
</script>

<section class="panel worker" aria-label="Worker controls">
	<div class="row">
		<span class="label">Receiver power</span>
		<button
			type="button"
			class="toggle"
			aria-pressed={$status?.paused ?? false}
			disabled={busy || $status === null}
			onclick={handleToggle}
		>
			{$status?.paused ? 'resume' : 'pause'}
		</button>
	</div>

	{#if breakerActive}
		<div class="row breaker">
			<span class="cond-fail mono">breaker tripped — backing off</span>
			{#if $status?.breaker_tripped_until}
				<Countdown scheduledAt={$status.breaker_tripped_until} label="clears in" />
			{/if}
			<button type="button" class="release" disabled={busy} onclick={handleRelease}>
				release now
			</button>
		</div>
	{/if}

	<p class="status-error mono" role="alert">{error}</p>
</section>

<style>
	.worker {
		padding: var(--space-3) var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	.toggle {
		background: var(--bg-2);
		border: 1px solid var(--line-bright);
		border-radius: 4px;
		padding: var(--space-1) var(--space-3);
		font-family: var(--font-mono);
		font-size: 0.75rem;
		letter-spacing: 0.04em;
		color: var(--text-muted);
		cursor: pointer;
	}

	.toggle:hover:not(:disabled),
	.toggle:focus-visible {
		border-color: var(--waiting);
		color: var(--text-primary);
	}

	/* aria-pressed=true means the worker is paused -- a stopped receiver, not a live
	   signal, so this stays off the reserved --signal amber (see DESIGN.md §2). */
	.toggle[aria-pressed='true'] {
		border-color: var(--fail-dim);
		color: var(--fail);
	}

	.toggle:disabled {
		opacity: 0.6;
		cursor: default;
	}

	.breaker {
		padding-top: var(--space-2);
		border-top: 1px solid var(--line);
	}

	.release {
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-1) var(--space-2);
		font-family: var(--font-mono);
		font-size: 0.6875rem;
		color: var(--text-muted);
		cursor: pointer;
	}

	.release:hover:not(:disabled),
	.release:focus-visible {
		border-color: var(--fail);
		color: var(--fail);
	}

	.release:disabled {
		opacity: 0.6;
		cursor: default;
	}

	.status-error {
		min-height: 1rem;
		margin: 0;
		color: var(--fail);
		font-size: 0.8125rem;
	}
</style>
