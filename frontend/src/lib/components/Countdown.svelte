<script lang="ts">
	import { formatCountdown } from '$lib/attempts';

	let { scheduledAt, label = 'next scan in' }: { scheduledAt: string; label?: string } = $props();

	let now = $state(Date.now());

	$effect(() => {
		const id = setInterval(() => {
			now = Date.now();
		}, 1000);
		return () => clearInterval(id);
	});

	let remainingMs = $derived(new Date(scheduledAt).getTime() - now);
</script>

<span class="mono countdown" class:due={remainingMs <= 0}>
	{label}
	{formatCountdown(remainingMs)}
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
