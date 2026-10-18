<script lang="ts">
	import { formatCountdown } from '$lib/attempts';
	import * as m from '$lib/paraglide/messages';

	// `dueLive`: whether "due now" may take the live amber. A waiting track that's due is
	// still waiting (the next beat pass, or a pause, decides), so TrackRow turns it off.
	// `dueText`: replaces the whole line once due, so a caller never reads "<label> due now".
	// v46: no default `label` value: a default is evaluated once, so it would keep the language
	// the component mounted in. An unset label falls back at render time instead.
	let {
		scheduledAt,
		label,
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
		{label ?? m.time_next_scan_in()}
		<span class="time">{formatCountdown(remainingMs)}</span>
	{/if}
</span>

<style>
	.countdown {
		font-size: var(--fs-detail);
		color: var(--waiting);
	}

	/* v46: a reading wraps as a whole ("2 nap 02:59:37"), never between its days and clock;
	   Hungarian's longer labels wrap it on a phone. */
	.time {
		white-space: nowrap;
	}

	.countdown.due {
		color: var(--signal);
	}
</style>
