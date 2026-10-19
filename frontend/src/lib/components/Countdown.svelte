<script lang="ts">
	import { formatCountdown } from '$lib/attempts';
	import { clock } from '$lib/stores/clock';
	import * as m from '$lib/paraglide/messages';

	// `dueText`: replaces the whole line once due, so a caller never reads "<label> due now".
	// v46: no default `label` value: a default is evaluated once, so it would keep the language
	// the component mounted in. An unset label falls back at render time instead.
	// v47: no "due" amber any more. Every caller turned it off (a due wait is still waiting:
	// the next beat pass or a pause decides), so a new caller can't get amber by default.
	// The time ticks on the one shared clock (F33), and only the reading is mono: the label
	// is a word (DESIGN.md §3).
	let { scheduledAt, label, dueText }: { scheduledAt: string; label?: string; dueText?: string } =
		$props();

	let remainingMs = $derived(new Date(scheduledAt).getTime() - $clock);
</script>

<span class="countdown">
	{#if dueText !== undefined && remainingMs <= 0}
		{dueText}
	{:else}
		{label ?? m.time_next_scan_in()}
		<span class="time mono">{formatCountdown(remainingMs)}</span>
	{/if}
</span>

<style>
	/* v46/v47: the label and its reading stay together ("feloldásig 4:32", "2 nap 02:59:37");
	   Hungarian's longer labels used to strand the time on a line of its own on a phone. */
	.countdown {
		font-size: var(--fs-detail);
		color: var(--waiting);
		white-space: nowrap;
	}
</style>
