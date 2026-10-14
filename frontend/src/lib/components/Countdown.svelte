<script lang="ts">
	import { formatCountdown } from '$lib/attempts';

	// `dueLive`: whether "due now" may take the live amber. A waiting track that's due is
	// still waiting (the next beat pass, or a pause, decides), so TrackRow turns it off.
	// `dueText`: replaces the whole line once due, so a caller never reads "<label> due now".
	let {
		scheduledAt,
		label = 'next scan in',
		dueLive = true,
		dueText
	}: { scheduledAt: string; label?: string; dueLive?: boolean; dueText?: string } = $props();

	let now = $state(Date.now());

	$effect(() => {
		const id = setInterval(() => {
			now = Date.now();
		}, 1000);
		return () => clearInterval(id);
	});

	let remainingMs = $derived(new Date(scheduledAt).getTime() - now);
</script>

<span class="mono countdown" class:due={dueLive && remainingMs <= 0}>
	{#if dueText !== undefined && remainingMs <= 0}
		{dueText}
	{:else}
		{label}
		{formatCountdown(remainingMs)}
	{/if}
</span>

<style>
	.countdown {
		font-size: 0.8125rem;
		color: var(--waiting);
	}

	.countdown.due {
		color: var(--signal);
	}
</style>
