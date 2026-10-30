<script lang="ts">
	import type { RecordedWindow } from '$lib/api';
	import {
		axisTickEvery,
		bucketHeld,
		bucketLabel,
		errorTypeCondition,
		errorTypeLabel,
		failurePeak,
		formatSpan,
		holdGeometry,
		holdSpans,
		instantLabel
	} from '$lib/stats';
	import { counted, formatNumber } from '$lib/i18n/format';
	import * as m from '$lib/paraglide/messages';

	// v44: a multi-channel chart recorder. One channel per failure class that occurred, all on
	// one shared y-scale (so channels compare) and one time axis, with the breaker's holds as
	// the bottom channel on that same axis: a spike and the trip it caused line up vertically.
	// One crosshair reads every channel at once. The drawing is an image whose alternative is
	// the summary in its label and the table below it.
	// v66: a user's own stats (`/stats`'s "mine") carry no breaker: it holds everyone's downloads,
	// not theirs. Without one the recorder has no breaker channel, line or column, and draws
	// nothing at all when nothing failed (the scale line says so).
	let { stats }: { stats: RecordedWindow } = $props();
	const hasBreaker = $derived(stats.breaker !== undefined);

	const n = $derived(stats.failures.buckets.length);
	const peak = $derived(failurePeak(stats));
	// Explicit rows: the plot overlay spans every channel's strip, and auto-placement would
	// route the strips around it.
	const breakerRow = $derived(stats.failures.series.length + 1);
	// The last channel's row: the breaker's, or the last failure class's without one.
	const lastRow = $derived(hasBreaker ? breakerRow : stats.failures.series.length);
	const spans = $derived(holdSpans(stats));
	const tickEvery = $derived(axisTickEvery(stats));
	const unit = $derived(stats.bucket_seconds < 86400 ? 'hour' : 'day');
	const heldSeconds = $derived(
		spans.reduce(
			(sum, span) =>
				sum +
				Math.max(
					0,
					(Math.min(
						Date.parse(span.ongoing ? stats.generated_at : span.endedAt),
						Date.parse(stats.generated_at)
					) -
						Math.max(Date.parse(span.startedAt), Date.parse(stats.window_start))) /
						1000
				),
			0
		)
	);
	const breakerLine = $derived(
		spans.length === 0
			? m.stats_breaker_no_hold()
			: m.stats_breaker_held({
					span: formatSpan(heldSeconds),
					...counted(stats.breaker?.trips ?? 0)
				})
	);

	const summary = $derived.by(() => {
		if (stats.failures.series.length === 0)
			return hasBreaker
				? m.stats_summary_none({ breaker: breakerLine })
				: m.stats_no_failed_attempts();
		const parts = stats.failures.series.map((series) => {
			const most = Math.max(...series.counts);
			const at = series.counts.indexOf(most);
			const values = {
				type: errorTypeLabel(series.error_type),
				total: formatNumber(series.total),
				most: formatNumber(most),
				when: bucketLabel(stats, stats.failures.buckets[at], true)
			};
			return unit === 'hour' ? m.stats_summary_part_hour(values) : m.stats_summary_part_day(values);
		});
		if (!hasBreaker) {
			const values = { parts: parts.join('; ') };
			return unit === 'hour' ? m.stats_mine_summary_hour(values) : m.stats_mine_summary_day(values);
		}
		const values = { parts: parts.join('; '), breaker: breakerLine };
		return unit === 'hour' ? m.stats_summary_hour(values) : m.stats_summary_day(values);
	});

	// Crosshair: the bucket under the pointer, or none.
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

	// The pointer may still rest past the end of a shorter window after a keyboard switch
	// (no pointer event fires): the readout only ever shows a bucket this window has.
	const shown = $derived(hovered !== null && hovered < n ? hovered : null);

	function height(count: number): string {
		if (count === 0 || peak === 0) return '0';
		// A single failure stays visible next to a tall column.
		return `max(2px, ${(count / peak) * 100}%)`;
	}

	function holdLabel(span: (typeof spans)[number]): string {
		const step = span.stepSeconds !== null ? formatSpan(span.stepSeconds) : '';
		const verb = span.escalated ? m.stats_hold_escalated() : m.stats_hold_tripped();
		const end = span.ongoing
			? m.stats_hold_ongoing()
			: span.manual
				? m.stats_hold_released()
				: span.early
					? m.stats_hold_ended_early()
					: m.stats_hold_ran_out();
		return m.stats_hold_label({ verb, step, when: instantLabel(stats, span.startedAt), end });
	}
</script>

<div class="recorder">
	<p class="scale">
		{#if peak > 0}
			{unit === 'hour' ? m.stats_scale_hour(counted(peak)) : m.stats_scale_day(counted(peak))}
		{:else}
			{m.stats_no_failed_attempts()}
		{/if}
	</p>

	{#if lastRow > 0}
		<div
			class="channels"
			style:--n={n}
			role="img"
			aria-label={summary}
			onpointermove={onPointerMove}
			onpointerleave={() => (hovered = null)}
		>
			{#each stats.failures.series as series, row (series.error_type)}
				<span class="name mono" style:grid-row={row + 1}>
					<span class="key {errorTypeCondition(series.error_type)}"></span>{errorTypeLabel(
						series.error_type
					)}
				</span>
				<span class="strip" style:grid-row={row + 1}>
					{#each series.counts as count, i (i)}
						<span class="cell" class:hover={shown === i}>
							<span
								class="column {errorTypeCondition(series.error_type)}"
								style:height={height(count)}
							></span>
						</span>
					{/each}
				</span>
				<span class="total mono" style:grid-row={row + 1}>{formatNumber(series.total)}</span>
			{/each}

			{#if hasBreaker}
				<span class="name mono" style:grid-row={breakerRow}
					><span class="key key-hold"></span>{m.stats_channel_breaker()}</span
				>
				<span class="strip holds" style:grid-row={breakerRow}>
					{#each spans as span (span.startedAt)}
						<span
							class="hold"
							class:ongoing={span.ongoing}
							class:manual={span.manual}
							style:left="{holdGeometry(span, n).left * 100}%"
							style:width="{holdGeometry(span, n).width * 100}%"
						></span>
					{/each}
				</span>
				<!-- 4: no bare number here (every other total counts failures); the line below counts trips. -->
				<span class="total" style:grid-row={breakerRow}></span>
			{/if}

			<span class="axis" style:grid-row={lastRow + 1}>
				{#each stats.failures.buckets as bucket, i (bucket)}
					<span class="tick" class:minor={(i / tickEvery) % 2 === 1}
						>{i % tickEvery === 0 ? bucketLabel(stats, bucket) : ''}</span
					>
				{/each}
			</span>

			<!-- The plot area: the crosshair and its readout, over every channel's strip. -->
			<span class="plot" style:grid-row="1 / span {lastRow}" bind:this={plot}>
				{#if shown !== null}
					<span class="crosshair" style:left="{((shown + 0.5) / n) * 100}%"></span>
					<span
						class="readout"
						class:flip={shown > n / 2}
						style:left="{((shown + 0.5) / n) * 100}%"
					>
						<span class="when mono">{bucketLabel(stats, stats.failures.buckets[shown], true)}</span>
						{#each stats.failures.series as series (series.error_type)}
							<span class="row">
								<span class="line-key {errorTypeCondition(series.error_type)}"></span>
								<strong class="mono">{formatNumber(series.counts[shown])}</strong>
								<span class="series">{errorTypeLabel(series.error_type)}</span>
							</span>
						{/each}
						{#if hasBreaker}
							<span class="row">
								<span class="line-key key-hold"></span>
								<span class="series">
									{bucketHeld(stats, spans, shown)
										? m.stats_readout_breaker_held()
										: m.stats_readout_breaker_clear()}
								</span>
							</span>
						{/if}
					</span>
				{/if}
			</span>
		</div>
	{/if}

	{#if hasBreaker}
		<p class="breaker-line">{breakerLine}</p>
	{/if}

	{#if lastRow > 0}
		<details class="as-table">
			<summary>{m.stats_show_as_table()}</summary>
			<!-- Focusable, so a keyboard can scroll it (axe: scrollable-region-focusable). -->
			<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
			<div class="table-wrap" tabindex="0" role="region" aria-label={m.stats_tables_label()}>
				<table>
					<caption class="sr-only"
						>{hasBreaker
							? unit === 'hour'
								? m.stats_table_caption_hour()
								: m.stats_table_caption_day()
							: unit === 'hour'
								? m.stats_mine_table_caption_hour()
								: m.stats_mine_table_caption_day()}</caption
					>
					<thead>
						<tr>
							<th scope="col">{unit === 'hour' ? m.stats_col_hour() : m.stats_col_day()}</th>
							{#each stats.failures.series as series (series.error_type)}
								<th scope="col" class="mono">{errorTypeLabel(series.error_type)}</th>
							{/each}
							{#if hasBreaker}<th scope="col">{m.stats_col_breaker()}</th>{/if}
						</tr>
					</thead>
					<tbody>
						{#each stats.failures.buckets as bucket, i (bucket)}
							<tr>
								<th scope="row" class="mono">{bucketLabel(stats, bucket, true)}</th>
								{#each stats.failures.series as series (series.error_type)}
									<td class="mono">{formatNumber(series.counts[i])}</td>
								{/each}
								{#if hasBreaker}<td>{bucketHeld(stats, spans, i) ? m.stats_cell_held() : '—'}</td
									>{/if}
							</tr>
						{/each}
					</tbody>
				</table>
				{#if spans.length > 0}
					<table>
						<caption class="caption">{m.stats_holds_caption()}</caption>
						<thead>
							<tr
								><th scope="col">{m.stats_col_hold()}</th><th scope="col">{m.stats_col_until()}</th
								></tr
							>
						</thead>
						<tbody>
							{#each spans as span (span.startedAt)}
								<tr>
									<td>{holdLabel(span)}</td>
									<td class="mono">{instantLabel(stats, span.endedAt)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</div>
		</details>
	{/if}
</div>

<style>
	.recorder {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		min-width: 0;
	}

	.scale,
	.breaker-line {
		font-size: var(--fs-detail);
		color: var(--text-muted);
	}

	/* One grid for every channel, so each strip spans the same columns as the axis and the
	   plot overlay: name | strip | total. */
	.channels {
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
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--fs-meta);
		color: var(--text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		align-self: end;
		line-height: 1.2;
	}

	.key {
		flex: none;
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 1px;
	}

	.total {
		grid-column: 3;
		font-size: var(--fs-meta);
		color: var(--text-primary);
		text-align: right;
		align-self: end;
		line-height: 1.2;
	}

	.strip {
		grid-column: 2;
		display: grid;
		grid-template-columns: repeat(var(--n), minmax(0, 1fr));
		column-gap: 2px;
		height: 2.5rem;
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
	}

	.waiting {
		background: var(--waiting);
	}

	.fail {
		background: var(--fail);
	}

	.idle {
		background: var(--text-muted);
	}

	/* The breaker channel: holds as spans of the waiting colour (a hold is scheduled and
	   self-clearing, DESIGN.md §6), a cut-short one ending in a hard edge. */
	.holds {
		display: block;
		position: relative;
		height: 1.25rem;
	}

	/* 3: a short hold is drawn over whole buckets (holdGeometry), so it never reads as a tick. */
	.hold {
		position: absolute;
		top: 0;
		bottom: 0;
		background: var(--waiting-dim);
		border-top: 2px solid var(--waiting);
		border-radius: 2px 2px 0 0;
	}

	/* Still holding at the reading: its leading edge is drawn, it hasn't ended. */
	.hold.ongoing {
		border-right: 2px solid var(--waiting);
	}

	.hold.manual {
		box-shadow: inset -2px 0 0 var(--text-primary);
	}

	.key-hold {
		background: var(--waiting);
	}

	.axis {
		grid-column: 2;
		display: grid;
		grid-template-columns: repeat(var(--n), minmax(0, 1fr));
		column-gap: 2px;
		font-family: var(--font-mono);
		font-size: var(--fs-label);
		color: var(--text-dim);
		font-variant-numeric: tabular-nums;
		align-self: start;
	}

	.tick {
		white-space: nowrap;
		overflow: visible;
	}

	.plot {
		grid-column: 2;
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

	/* Tooltip rows key their series with a short stroke, not a box. */
	.line-key {
		width: 0.75rem;
		height: 2px;
		border-radius: 1px;
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
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
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

	.caption {
		text-align: left;
		color: var(--text-dim);
		padding-bottom: var(--space-1);
	}

	/* Phone: a slimmer name column, and every other axis label, so they never collide. */
	@media (max-width: 40em) {
		.channels {
			--name-col: 5.5rem;
			grid-template-columns: var(--name-col) minmax(0, 1fr) 2rem;
			column-gap: var(--space-2);
		}

		.tick.minor {
			visibility: hidden;
		}
	}

	@media (forced-colors: active) {
		.column,
		.hold,
		.key {
			background: CanvasText;
		}
	}
	/* v47 (F32): the disclosure is a control: a finger's height on touch. */
	@media (pointer: coarse) {
		/* Padding, not display:flex: a summary draws its open/closed marker only as a
		   list-item. */
		.as-table summary {
			padding-block: 0.75rem;
		}
	}
</style>
