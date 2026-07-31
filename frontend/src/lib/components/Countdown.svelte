<script lang="ts">
	let { scheduledAt }: { scheduledAt: string } = $props();

	let now = $state(Date.now());

	$effect(() => {
		const id = setInterval(() => {
			now = Date.now();
		}, 1000);
		return () => clearInterval(id);
	});

	let remainingMs = $derived(new Date(scheduledAt).getTime() - now);

	function format(ms: number): string {
		if (ms <= 0) return 'due now';
		const totalSeconds = Math.floor(ms / 1000);
		const h = Math.floor(totalSeconds / 3600);
		const m = Math.floor((totalSeconds % 3600) / 60);
		const s = totalSeconds % 60;
		const pad = (n: number) => String(n).padStart(2, '0');
		return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
	}
</script>

<span class="mono countdown" class:due={remainingMs <= 0}>
	next scan in {format(remainingMs)}
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
