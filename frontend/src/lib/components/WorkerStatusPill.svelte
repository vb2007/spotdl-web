<script lang="ts">
	import { onMount } from 'svelte';
	import { worker } from '$lib/stores/worker';
	import Countdown from '$lib/components/Countdown.svelte';

	// v25: the dashboard-visible half of what used to be the full WorkerStatus panel --
	// read-only (pause/resume and breaker-release moved to /settings, admin-only), but
	// still visible to every user so a stalled queue is still explained (the original
	// reason this was ever shown to non-admins, v17). Same 5s poll as before; no SSE
	// event exists for worker/breaker state.
	const { status } = worker;

	const POLL_MS = 5000;

	let breakerActive = $derived(
		$status?.breaker_tripped_until != null &&
			new Date($status.breaker_tripped_until).getTime() > Date.now()
	);
	let paused = $derived($status?.paused ?? false);

	onMount(() => {
		worker.refresh();
		const id = setInterval(() => worker.refresh(), POLL_MS);
		return () => clearInterval(id);
	});
</script>

<div class="pill mono" role="status">
	{#if breakerActive}
		<span class="cond-fail">breaker tripped</span>
		{#if $status?.breaker_tripped_until}
			<Countdown scheduledAt={$status.breaker_tripped_until} label="clears in" />
		{/if}
	{:else if paused}
		<span class="cond-fail">receiver paused</span>
	{:else}
		<span class="cond-idle">receiving</span>
	{/if}
</div>

<style>
	/* Quiet by default (--text-muted via .cond-idle) -- amber is reserved for something
	   genuinely live right now (DESIGN.md §2), and "not paused, breaker clear" is not
	   that. Paused/tripped reuse --fail, the same token the old toggle's aria-pressed
	   state and breaker banner already used, so the color still means the same thing. */
	.pill {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2);
		font-size: 0.75rem;
	}

	@media (max-width: 640px) {
		.pill {
			flex-basis: 100%;
		}
	}
</style>
