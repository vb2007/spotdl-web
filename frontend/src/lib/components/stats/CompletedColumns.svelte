<script lang="ts">
	import type { MyStats } from '$lib/api';
	import { axisTickEvery, bucketLabel } from '$lib/stats';
	import { counted, formatNumber } from '$lib/i18n/format';
	import * as m from '$lib/paraglide/messages';
	import { stepCrosshair } from './crosshair';

	// v66: a user's completed tracks per bucket: one series, so no legend (the block's heading
	// names it), in the settled colour (DESIGN.md: completed = settled), on the failure
	// recorder's time axis and crosshair so the two strips read alike. The drawing is an image
	// whose alternative is the summary in its label and the table below it; the table is the
	// keyboard's way in, as on the recorder.
	// v67: `plain` (a non-admin) gets FailureChannels' wider phone name column, so a bucket stays
	// at the same x in both charts.
	let { stats, plain = false }: { stats: MyStats; plain?: boolean } = $props();
	const uid = $props.id();

	const counts = $derived(stats.completed.counts);
	const buckets = $derived(stats.completed.buckets);
	const n = $derived(buckets.length);
	const peak = $derived(Math.max(0, ...counts));
	const tickEvery = $derived(axisTickEvery(stats));
	const unit = $derived(stats.bucket_seconds < 86400 ? 'hour' : 'day');

	const summary = $derived.by(() => {
		if (stats.completed.total === 0) return m.stats_mine_completed_none();
		const at = counts.indexOf(peak);
		const values = {
			total: formatNumber(stats.completed.total),
			most: formatNumber(peak),
			when: bucketLabel(stats, buckets[at], true)
		};
		return unit === 'hour'
			? m.stats_mine_completed_summary_hour(values)
			: m.stats_mine_completed_summary_day(values);
	});

	let hovered = $state<number | null>(null);
	let plot: HTMLElement | undefined = $state();

	function onPointerMove(event: PointerEvent) {
		if (plot === undefined) return;
		const rect = plot.getBoundingClientRect();
		const x = event.clientX - rect.left;
		if (x < 0 || x > rect.width) {
			hovered = null;
			return;
		}
		hovered = Math.min(n - 1, Math.floor((x / rect.width) * n));
	}

	// A window switch can leave the pointer past the end of a shorter window.
	const shown = $derived(hovered !== null && hovered < n ? hovered : null);

	// v67 (U10): the crosshair by keyboard, as on the recorder.
	function onKeydown(event: KeyboardEvent) {
		const next = stepCrosshair(event, shown, n);
		if (next === undefined) return;
		event.preventDefault();
		event.stopPropagation();
		hovered = next;
	}

	const reading = $derived(
		shown === null
			? ''
			: `${bucketLabel(stats, buckets[shown], true)}: ${formatNumber(counts[shown])} ${m.stats_legend_completed()}`
	);

	function height(count: number): string {
		if (count === 0 || peak === 0) return '0';
		// A single track stays visible next to a tall column.
		return `max(2px, ${(count / peak) * 100}%)`;
	}
</script>

<div class="columns-chart">
	<p class="scale">
		{#if peak > 0}
			{unit === 'hour'
				? m.stats_mine_scale_hour(counted(peak))
				: m.stats_mine_scale_day(counted(peak))}
		{:else}
			{m.stats_mine_completed_none()}
		{/if}
	</p>

	{#if peak > 0}
		<!-- v67 (U10): a slider over the buckets, as on the recorder (FailureChannels). -->
		<div
			class="chart"
			class:plain
			style:--n={n}
			role="slider"
			aria-roledescription={m.stats_chart_role()}
			aria-label={summary}
			aria-describedby="{uid}-keys"
			aria-orientation="horizontal"
			aria-valuemin={0}
			aria-valuemax={n - 1}
			aria-valuenow={shown ?? n - 1}
			aria-valuetext={reading ||
				(unit === 'hour' ? m.stats_chart_unread_hour() : m.stats_chart_unread_day())}
			tabindex="0"
			onpointermove={onPointerMove}
			onpointerdown={onPointerMove}
			onpointerleave={(event) => {
				if (event.pointerType !== 'touch') hovered = null;
			}}
			onkeydown={onKeydown}
			onblur={(event) => {
				// Focus into a dialog (the help overlay) comes back here: keep the reading.
				if (!(event.relatedTarget instanceof Element && event.relatedTarget.closest('dialog')))
					hovered = null;
			}}
		>
			<span class="name" class:mono={!plain} title={m.stats_legend_completed()}
				><span class="key"></span><span class="name-text">{m.stats_legend_completed()}</span></span
			>
			<span class="strip">
				{#each counts as count, i (i)}
					<span class="cell" class:hover={shown === i}>
						<span class="column" style:height={height(count)}></span>
					</span>
				{/each}
			</span>
			<span class="total mono">{formatNumber(stats.completed.total)}</span>
			<span class="axis">
				{#each buckets as bucket, i (bucket)}
					<span class="tick" class:minor={(i / tickEvery) % 2 === 1}
						>{i % tickEvery === 0 ? bucketLabel(stats, bucket) : ''}</span
					>
				{/each}
			</span>
			<span class="plot" bind:this={plot}>
				{#if shown !== null}
					<span class="crosshair" style:left="{((shown + 0.5) / n) * 100}%"></span>
					<span
						class="readout"
						class:flip={shown > n / 2}
						style:left="{((shown + 0.5) / n) * 100}%"
					>
						<span class="when mono">{bucketLabel(stats, buckets[shown], true)}</span>
						<span class="row">
							<span class="line-key"></span>
							<strong class="mono">{formatNumber(counts[shown])}</strong>
							<span class="series">{m.stats_legend_completed()}</span>
						</span>
					</span>
				{/if}
			</span>
		</div>
		<p class="sr-only" id="{uid}-keys">
			{unit === 'hour' ? m.stats_chart_keys_hour() : m.stats_chart_keys_day()}
		</p>

		<details class="as-table">
			<summary>{m.stats_show_as_table()}</summary>
			<!-- Focusable, so a keyboard can scroll it (axe: scrollable-region-focusable). -->
			<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
			<div
				class="table-wrap"
				tabindex="0"
				role="region"
				aria-label={m.stats_mine_completed_table()}
			>
				<table>
					<caption class="sr-only"
						>{unit === 'hour'
							? m.stats_mine_completed_caption_hour()
							: m.stats_mine_completed_caption_day()}</caption
					>
					<thead>
						<tr>
							<th scope="col">{unit === 'hour' ? m.stats_col_hour() : m.stats_col_day()}</th>
							<th scope="col">{m.stats_legend_completed()}</th>
						</tr>
					</thead>
					<tbody>
						{#each buckets as bucket, i (bucket)}
							<tr>
								<th scope="row" class="mono">{bucketLabel(stats, bucket, true)}</th>
								<td class="mono">{formatNumber(counts[i])}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</details>
	{/if}
</div>

<style>
	.columns-chart {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		min-width: 0;
	}

	.scale {
		font-size: var(--fs-detail);
		color: var(--text-muted);
	}

	/* The recorder's grid (FailureChannels): name | strip | total, so this channel sits on the
	   same x-extent as the failure channels below it and a bucket is at the same place in both. */
	.chart {
		--name-col: 8.5rem;
		position: relative;
		display: grid;
		grid-template-columns: var(--name-col) minmax(0, 1fr) 2.5rem;
		column-gap: var(--space-3);
		row-gap: var(--space-2);
		align-items: end;
		touch-action: pan-y;
	}

	.name {
		grid-column: 1;
		grid-row: 1;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--fs-meta);
		color: var(--text-muted);
		min-width: 0;
		line-height: 1.2;
	}

	/* v67 (U14): the ellipsis needs a box of its own (on the flex container it never applied). */
	.name-text {
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.chart:focus-visible {
		outline-offset: var(--space-2);
	}

	.key {
		flex: none;
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 1px;
		background: var(--settled);
	}

	.strip {
		grid-column: 2;
		grid-row: 1;
		display: grid;
		grid-template-columns: repeat(var(--n), minmax(0, 1fr));
		column-gap: 2px;
		height: 4rem;
		border-bottom: 1px solid var(--line-bright);
	}

	.cell {
		display: flex;
		align-items: flex-end;
		justify-content: center;
		height: 100%;
	}

	.cell.hover {
		background: color-mix(in srgb, var(--text-primary) 4%, transparent);
	}

	.column {
		width: min(100%, 24px);
		border-radius: 3px 3px 0 0;
		background: var(--settled);
	}

	.total {
		grid-column: 3;
		grid-row: 1;
		font-size: var(--fs-meta);
		color: var(--text-primary);
		text-align: right;
		line-height: 1.2;
	}

	.axis {
		grid-column: 2;
		grid-row: 2;
		display: grid;
		grid-template-columns: repeat(var(--n), minmax(0, 1fr));
		column-gap: 2px;
		font-family: var(--font-mono);
		font-size: var(--fs-label);
		color: var(--text-dim);
		font-variant-numeric: tabular-nums;
	}

	.tick {
		white-space: nowrap;
		overflow: visible;
	}

	.plot {
		grid-column: 2;
		grid-row: 1;
		position: relative;
		align-self: stretch;
		pointer-events: none;
	}

	.crosshair {
		position: absolute;
		top: 0;
		bottom: 0;
		width: 1px;
		background: var(--text-muted);
	}

	.readout {
		position: absolute;
		top: 0;
		transform: translateX(var(--space-3));
		z-index: 2;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 11rem;
		padding: var(--space-2) var(--space-3);
		background: var(--bg-3);
		border: 1px solid var(--line-bright);
		border-radius: 4px;
		box-shadow: var(--shadow-plate);
		font-size: var(--fs-meta);
	}

	.readout.flip {
		transform: translateX(calc(-100% - var(--space-3)));
	}

	.when {
		color: var(--text-muted);
	}

	.row {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		white-space: nowrap;
	}

	.row strong {
		min-width: 1.5rem;
		text-align: right;
		font-weight: var(--fw-strong);
		color: var(--text-primary);
	}

	.series {
		color: var(--text-muted);
	}

	.line-key {
		width: 0.75rem;
		height: 2px;
		border-radius: 1px;
		background: var(--settled);
	}

	.as-table summary {
		cursor: pointer;
		font-size: var(--fs-meta);
		color: var(--text-muted);
		text-decoration: underline;
		text-decoration-color: var(--line-control);
		text-underline-offset: 0.3em;
		width: max-content;
	}

	@media (hover: hover) {
		.as-table summary:hover {
			color: var(--text-primary);
		}
	}

	.table-wrap {
		margin-top: var(--space-3);
		max-height: 24rem;
		overflow: auto;
	}

	table {
		border-collapse: collapse;
		font-size: var(--fs-meta);
	}

	th,
	td {
		padding: var(--space-1) var(--space-3) var(--space-1) 0;
		text-align: left;
		border-bottom: 1px solid var(--line);
		white-space: nowrap;
	}

	thead th {
		color: var(--text-dim);
		font-weight: var(--fw-medium);
	}

	tbody th {
		font-weight: var(--fw-regular);
		color: var(--text-muted);
	}

	@media (max-width: 40em) {
		.chart {
			--name-col: 5.5rem;
			grid-template-columns: var(--name-col) minmax(0, 1fr) 2rem;
			column-gap: var(--space-2);
		}

		/* FailureChannels' translated-label column, so the two charts' buckets line up. */
		.chart.plain {
			--name-col: 8rem;
		}

		.tick.minor {
			visibility: hidden;
		}
	}

	/* v67: the disclosure is a control: a finger's height on touch, as on the recorder (v47,
	   F32; this copy of its style had missed the rule). */
	@media (pointer: coarse) {
		.as-table summary {
			padding-block: 0.75rem;
			min-height: 2.75rem;
		}
	}

	@media (forced-colors: active) {
		.column,
		.key,
		.line-key {
			background: CanvasText;
		}
	}
</style>
