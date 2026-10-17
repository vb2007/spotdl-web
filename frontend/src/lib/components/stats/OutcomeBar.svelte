<script lang="ts">
	import type { OutcomeCounts } from '$lib/api';

	// v44: one route's or proxy's attempts as a part-to-whole bar, normalized to the row's
	// own attempts (the question is "how often does this route work", not "how busy is it";
	// the count sits beside it as text). Segment colours are DESIGN.md's conditions:
	// completed settled, failed (the ladder retries it) waiting, not found (a verdict) fail.
	// Decorative: every number it draws is also in the row's text, so it's aria-hidden.
	let { counts }: { counts: OutcomeCounts } = $props();

	const segments = $derived(
		[
			{ key: 'completed', value: counts.completed },
			{ key: 'failed', value: counts.failed },
			{ key: 'not-found', value: counts.not_found }
		].filter((segment) => segment.value > 0)
	);
</script>

<span class="bar well" aria-hidden="true">
	{#each segments as segment (segment.key)}
		<span class="segment {segment.key}" style:flex-grow={segment.value}></span>
	{/each}
</span>

<style>
	/* A meter is read by its fill, so the well keeps the quiet --line edge (DESIGN.md §6). */
	.bar {
		display: flex;
		gap: 2px;
		height: 0.75rem;
		padding: 2px;
		border-color: var(--line);
		min-width: 0;
	}

	.segment {
		flex-basis: 0;
		min-width: 2px;
		border-radius: 1px;
	}

	.segment:first-child {
		border-top-left-radius: 2px;
		border-bottom-left-radius: 2px;
	}

	.segment:last-child {
		border-top-right-radius: 2px;
		border-bottom-right-radius: 2px;
	}

	.completed {
		background: var(--settled);
	}

	.failed {
		background: var(--waiting);
	}

	.not-found {
		background: var(--fail);
	}

	@media (forced-colors: active) {
		.segment {
			background: CanvasText;
		}
	}
</style>
