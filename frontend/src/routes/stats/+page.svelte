<!--
  THESIS: the admin's flight recorder, not a KPI wall. Two questions, kept apart: what holds
  downloads right now, and how the routes have done over a window; refuses the big-number tile
  grid and per-chart filters.
  OWN-WORLD: the signal-receiver faceplates of DESIGN.md unchanged: --bg-1 plates, ruled mono
  readouts, state colours only by meaning (settled done, waiting retried/held, fail a verdict),
  never amber (nothing here is this session's live track).
  STORY: the admin sees the queue depth and whether the breaker holds, then reads which route
  earns its place and when failures spiked against the breaker's holds.
  FIRST VIEWPORT: title row with refresh and "read at"; left a narrow "Right now" readout
  plate; right the window plate, its 24h/7d/30d switch in its own head, routes table first.
  FORM: "now | over window" split, candidate 3 of 7 on re-roll (seed 028199e0; first roll
  4b3f7154 assigned 7, re-rolled on product clarity), owner-approved; staging: a
  multi-channel recorder sharing one time axis.
  FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review,
  the verdict, and DESIGN.md
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import * as api from '$lib/api';
	import { relativeTime } from '$lib/attempts';
	import SubpageHeader from '$lib/components/SubpageHeader.svelte';
	import AdminOnlyNotice from '$lib/components/AdminOnlyNotice.svelte';
	import OutcomeBar from '$lib/components/stats/OutcomeBar.svelte';
	import FailureChannels from '$lib/components/stats/FailureChannels.svelte';
	import {
		formatRate,
		formatSpan,
		pathLabel,
		slotted,
		windowHeading,
		windowName
	} from '$lib/stats';
	import * as m from '$lib/paraglide/messages';
	import { errorText } from '$lib/i18n/errors';
	import { counted, formatClock, formatDateTime, formatNumber } from '$lib/i18n/format';
	import { trackStateLabel } from '$lib/i18n/labels';

	let { data } = $props();
	const isAdmin = $derived(data.session?.is_admin ?? false);

	const WINDOWS: api.StatsWindow[] = ['24h', '7d', '30d'];

	let selected = $state<api.StatsWindow>('24h');
	let stats = $state<api.AdminStats | null>(null);
	let loading = $state(false);
	let error = $state('');
	// A window switch while a read is in flight: only the newest read may land (DESIGN.md's
	// "a REST fetch that resolves out of order can clobber fresher state").
	let sequence = 0;

	async function load() {
		const mine = ++sequence;
		loading = true;
		error = '';
		try {
			const fresh = await api.getAdminStats(selected);
			if (mine !== sequence) return;
			stats = fresh;
		} catch (err) {
			if (mine !== sequence) return;
			error = errorText(err);
			// The switch didn't happen: the pressed window is the one still shown.
			if (stats !== null) selected = stats.window;
		} finally {
			if (mine === sequence) loading = false;
		}
	}

	function choose(next: api.StatsWindow) {
		if (next === selected) return;
		selected = next;
		void load();
	}

	onMount(() => {
		// A non-admin makes no admin request at all (F17): the page is the notice.
		if (isAdmin) void load();
	});

	const generated = $derived(stats === null ? 0 : Date.parse(stats.generated_at));
	const readAt = $derived(stats === null ? '' : formatClock(stats.generated_at));
	const shownWindow = $derived(stats?.window ?? selected);

	function clock(iso: string): string {
		const date = new Date(iso);
		const sameDay = new Date(generated).toDateString() === date.toDateString();
		return sameDay
			? formatClock(date)
			: formatDateTime(date, {
					month: 'short',
					day: 'numeric',
					hour: '2-digit',
					minute: '2-digit'
				});
	}

	const queueRows = $derived(
		stats === null
			? []
			: [
					{ key: 'waiting', value: stats.queue.counts.waiting },
					{ key: 'pending', value: stats.queue.counts.pending },
					{ key: 'queued', value: stats.queue.counts.queued },
					{ key: 'downloading', value: stats.queue.counts.downloading }
				]
	);
	const breakerNow = $derived.by(() => {
		if (stats === null) return null;
		const current = stats.breaker.current;
		if (current.paused)
			return { tone: 'fail', text: m.stats_now_paused(), detail: m.stats_now_paused_detail() };
		if (current.holding_until !== null)
			return {
				tone: 'waiting',
				text: m.stats_now_holding({ time: clock(current.holding_until) }),
				detail: m.stats_now_holding_detail()
			};
		return { tone: 'idle', text: m.stats_now_clear(), detail: m.stats_now_clear_detail() };
	});
	const proxiesOn = $derived(stats?.proxies.filter((p) => p.enabled).length ?? 0);
	const proxiesCooling = $derived(
		stats?.proxies.filter((p) => p.enabled && p.cooldown_until !== null).length ?? 0
	);
	const anyAttempts = $derived(stats?.network_paths.some((p) => p.attempts > 0) ?? false);
	const anyProxyAttempts = $derived(stats?.proxies.some((p) => p.attempts > 0) ?? false);

	const oldestLine = $derived(
		stats?.queue.oldest_waiting_since != null && stats.queue.oldest_waiting_age_seconds !== null
			? slotted(m.stats_oldest_waiting, {
					age: formatSpan(stats.queue.oldest_waiting_age_seconds),
					when: clock(stats.queue.oldest_waiting_since)
				})
			: null
	);
	const proxiesLine = $derived(
		proxiesCooling > 0
			? slotted(m.stats_proxies_on_cooling, {
					on: formatNumber(proxiesOn),
					cooling: formatNumber(proxiesCooling)
				})
			: slotted(m.stats_proxies_on, { on: formatNumber(proxiesOn) })
	);
</script>

<svelte:head>
	<title>{m.stats_title()}</title>
</svelte:head>

<div class="stage">
	<SubpageHeader current="stats" {isAdmin} />

	<main id="main" class="main">
		<div class="title-row">
			<h1 class="page-title">{m.stats_heading()}</h1>
			{#if isAdmin}
				<div class="read">
					<span class="read-at mono" role="status">
						{#if loading}{m.stats_reading()}{:else if readAt}{m.stats_read_at({
								time: readAt
							})}{/if}
					</span>
					<button type="button" class="btn small" disabled={loading} onclick={() => void load()}>
						{m.stats_refresh()}
					</button>
				</div>
			{/if}
		</div>

		{#if !isAdmin}
			<AdminOnlyNotice page="stats" />
		{:else}
			<p class="form-error" role="alert">
				{#if error}{m.stats_read_failed({ error })}{/if}
			</p>

			<div class="layout" class:stale={loading && stats !== null}>
				<section class="panel now" aria-labelledby="now-heading">
					<h2 id="now-heading" class="label">{m.stats_now_heading()}</h2>
					{#if stats === null}
						<p class="quiet">{loading ? m.stats_reading_status() : m.stats_nothing_read()}</p>
					{:else}
						<dl class="readout">
							{#each queueRows as row (row.key)}
								<div class="reading">
									<dt>{trackStateLabel(row.key)}</dt>
									<dd class="mono">{formatNumber(row.value)}</dd>
								</div>
							{/each}
						</dl>
						<p class="note">
							{#if oldestLine !== null}
								{#each oldestLine as part, i (i)}{#if part.key === 'age'}<span class="mono"
											>{part.text}</span
										>{:else if part.key === 'when'}<span class="mono quiet">{part.text}</span
										>{:else}{part.text}{/if}{/each}
							{:else}
								{m.stats_nothing_waiting()}
							{/if}
						</p>
						{#if breakerNow !== null}
							<div class="state">
								<p class="state-text cond-{breakerNow.tone}">{breakerNow.text}</p>
								<p class="quiet">{breakerNow.detail}</p>
							</div>
						{/if}
						<p class="note">
							{#if stats.proxies.length === 0}
								{m.stats_no_proxies()}
							{:else}
								{#each proxiesLine as part, i (i)}{#if part.key !== null}<span class="mono"
											>{part.text}</span
										>{:else}{part.text}{/if}{/each}
							{/if}
						</p>
					{/if}
				</section>

				<section class="panel window" aria-labelledby="window-heading" aria-busy={loading}>
					<header class="window-head">
						<h2 id="window-heading" class="label">{windowHeading(shownWindow)}</h2>
						<div class="choice-group values" role="group" aria-label={m.stats_window_label()}>
							{#each WINDOWS as option (option)}
								<button
									type="button"
									aria-pressed={selected === option}
									onclick={() => choose(option)}>{windowName(option)}</button
								>
							{/each}
						</div>
					</header>

					{#if stats === null}
						<p class="quiet">{loading ? m.stats_reading_status() : m.stats_nothing_read()}</p>
					{:else}
						<section class="block" aria-labelledby="routes-heading">
							<div class="block-head">
								<h3 id="routes-heading" class="block-title">{m.stats_routes_heading()}</h3>
								{#if anyAttempts}
									<p class="legend" aria-hidden="true">
										<span class="swatch completed"></span>{m.stats_legend_completed()}
										<span class="swatch failed"></span>{m.stats_legend_failed()}
										<span class="swatch not-found"></span>{m.stats_legend_not_found()}
									</p>
								{/if}
							</div>
							{#if anyAttempts}
								<!-- 2: the rate's definition, visible (a title attribute reaches no keyboard or touch). -->
								<p id="rate-definition" class="quiet">{m.stats_rate_definition()}</p>
							{:else}
								<p class="quiet">{m.stats_no_attempts()}</p>
							{/if}
							<table class="rates" aria-describedby={anyAttempts ? 'rate-definition' : undefined}>
								<thead>
									<tr>
										<th scope="col">{m.stats_col_route()}</th>
										<th scope="col" class="num">{m.stats_col_attempts()}</th>
										<th scope="col">{m.stats_col_outcome()}</th>
										<th scope="col" class="num">{m.stats_col_success()}</th>
									</tr>
								</thead>
								<tbody>
									{#each stats.network_paths as path (path.path)}
										<tr class:empty={path.attempts === 0}>
											<th scope="row" class="mono route">{pathLabel(path.path)}</th>
											<td class="num mono"
												>{formatNumber(path.attempts)}<span class="unit"
													>&nbsp;{m.stats_attempts_unit(counted(path.attempts))}</span
												></td
											>
											<td class="outcome">
												{#if path.attempts > 0}
													<OutcomeBar counts={path} />
													<span class="counts mono">
														{m.stats_outcome_counts({
															completed: formatNumber(path.completed),
															failed: formatNumber(path.failed),
															not_found: formatNumber(path.not_found)
														})}
													</span>
												{:else}
													<span class="quiet">{m.stats_not_used()}</span>
												{/if}
											</td>
											<td class="num mono rate">{formatRate(path.success_rate)}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</section>

						<section class="block" aria-labelledby="failures-heading">
							<div class="block-head">
								<h3 id="failures-heading" class="block-title">{m.stats_failures_heading()}</h3>
							</div>
							<FailureChannels {stats} />
						</section>

						<section class="block" aria-labelledby="proxies-heading">
							<div class="block-head">
								<h3 id="proxies-heading" class="block-title">{m.stats_proxies_heading()}</h3>
								{#if stats.proxies.length > 0}
									<p class="legend" aria-hidden="true">
										<span class="swatch completed"></span>{m.stats_legend_completed()}
										<span class="swatch failed"></span>{m.stats_legend_failed()}
										<span class="swatch not-found"></span>{m.stats_legend_not_found()}
									</p>
								{/if}
							</div>
							{#if stats.proxies.length === 0}
								<p class="quiet">{m.stats_no_proxies_detail()}</p>
							{:else}
								<table
									class="rates proxies"
									aria-describedby={anyProxyAttempts ? 'rate-definition' : undefined}
								>
									<thead>
										<tr>
											<th scope="col">{m.stats_col_proxy()}</th>
											<th scope="col">{m.stats_col_state()}</th>
											<th scope="col" class="num">{m.stats_col_attempts()}</th>
											<th scope="col">{m.stats_col_outcome()}</th>
											<th scope="col" class="num">{m.stats_col_success()}</th>
											<th scope="col">{m.stats_col_last_success()}</th>
										</tr>
									</thead>
									<tbody>
										<!-- Keyed by position: labels are host:port only (the plan's "redacted label only"),
										     and two proxies on one gateway share one. -->
										{#each stats.proxies as proxy, i (i)}
											<tr class:empty={proxy.attempts === 0}>
												<!-- i18n-ignore: a proxy's host:port label, shown as recorded -->
												<th scope="row" class="mono route">{proxy.label}</th>
												<td class="state-cell">
													{#if !proxy.enabled}
														<span class="quiet">{m.stats_proxy_off()}</span>
													{:else if proxy.cooldown_until !== null}
														<span class="cond-waiting"
															>{m.stats_proxy_cooling({ time: clock(proxy.cooldown_until) })}</span
														>
													{:else}
														<span>{m.stats_proxy_ready()}</span>
													{/if}
												</td>
												<td class="num mono"
													>{formatNumber(proxy.attempts)}<span class="unit"
														>&nbsp;{m.stats_attempts_unit(counted(proxy.attempts))}</span
													></td
												>
												<td class="outcome">
													{#if proxy.attempts > 0}
														<OutcomeBar counts={proxy} />
														<span class="counts mono">
															{formatNumber(proxy.completed)}<span class="sr-only"
																>{` ${m.stats_sr_completed()}`}</span
															>
															· {formatNumber(proxy.failed)}<span class="sr-only"
																>{` ${m.stats_sr_failed()}`}</span
															>
															· {formatNumber(proxy.not_found)}<span class="sr-only"
																>{` ${m.stats_sr_not_found()}`}</span
															>
														</span>
													{:else}
														<span class="quiet">{m.stats_not_used()}</span>
													{/if}
												</td>
												<td class="num mono rate">{formatRate(proxy.success_rate)}</td>
												<td class="mono last">
													<span class="unit">{m.stats_last_success_unit()}&nbsp;</span
													>{proxy.last_success_at === null
														? m.stats_never()
														: relativeTime(proxy.last_success_at, generated)}
												</td>
											</tr>
										{/each}
									</tbody>
								</table>
							{/if}
						</section>
					{/if}
				</section>
			</div>
		{/if}
	</main>
</div>

<style>
	.stage {
		max-width: 64rem;
		margin: 0 auto;
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.main {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		margin-top: var(--space-2);
	}

	.title-row {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-4);
	}

	.read {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}

	.read-at {
		font-size: var(--fs-meta);
		color: var(--text-dim);
	}

	/* Reserved at rest (DESIGN.md "Error / status text"): a failed refresh doesn't move the plates. */
	.form-error {
		min-height: 1.5em;
	}

	/* Desktop: a narrow "now" plate beside the window plate; below 1024 they stack, now first. */
	.layout {
		display: grid;
		grid-template-columns: 15rem minmax(0, 1fr);
		gap: var(--space-4);
		align-items: start;
		transition: opacity var(--dur-fast) var(--ease-signal);
	}

	/* A refetch keeps the frame (no skeleton, no jump): the old reading dims until the new
	   one lands. */
	.layout.stale {
		opacity: 0.55;
	}

	.panel {
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		min-width: 0;
	}

	.quiet {
		color: var(--text-muted);
		font-size: var(--fs-detail);
	}

	.note {
		font-size: var(--fs-detail);
		color: var(--text-muted);
		line-height: 1.5;
	}

	.note .mono {
		color: var(--text-primary);
	}

	.note .mono.quiet {
		color: var(--text-dim);
	}

	/* The queue as a ruled readout: words left, tabular figures right. */
	.readout {
		display: flex;
		flex-direction: column;
	}

	.reading {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--space-3);
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--line);
	}

	.reading:first-child {
		padding-top: 0;
	}

	.reading dt {
		color: var(--text-muted);
		font-size: var(--fs-detail);
	}

	.reading dd {
		font-size: var(--fs-lead);
		font-weight: var(--fw-medium);
		color: var(--text-primary);
	}

	.state {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding: var(--space-3) 0;
		border-top: 1px solid var(--line);
		border-bottom: 1px solid var(--line);
	}

	.state-text {
		font-size: var(--fs-body);
		font-weight: var(--fw-medium);
	}

	.state-text.cond-idle {
		color: var(--text-primary);
	}

	.window-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	.block {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding-top: var(--space-4);
		border-top: 1px solid var(--line);
	}

	.block-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-4);
	}

	.block-title {
		font-size: var(--fs-body);
		font-weight: var(--fw-medium);
	}

	.legend {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-2);
		font-size: var(--fs-meta);
		color: var(--text-muted);
	}

	.swatch {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 1px;
		margin-left: var(--space-2);
	}

	.swatch:first-child {
		margin-left: 0;
	}

	.swatch.completed {
		background: var(--settled);
	}

	.swatch.failed {
		background: var(--waiting);
	}

	.swatch.not-found {
		background: var(--fail);
	}

	.rates {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--fs-detail);
	}

	.rates th,
	.rates td {
		padding: var(--space-2) var(--space-3) var(--space-2) 0;
		text-align: left;
		vertical-align: middle;
		border-bottom: 1px solid var(--line);
	}

	.rates th:last-child,
	.rates td:last-child {
		padding-right: 0;
	}

	.rates thead th {
		font-family: var(--font-mono);
		font-size: var(--fs-label);
		font-weight: var(--fw-medium);
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--text-dim);
		padding-top: 0;
		white-space: nowrap;
	}

	.rates .num {
		text-align: right;
	}

	/* Only the phone's stacked row, which has no column head, needs the unit spelled out. */
	.rates .unit {
		display: none;
	}

	.route {
		font-weight: var(--fw-regular);
		font-size: var(--fs-detail);
		color: var(--text-primary);
		white-space: nowrap;
	}

	.outcome {
		width: 45%;
	}

	.outcome :global(.bar) {
		width: 100%;
	}

	.counts {
		display: block;
		margin-top: var(--space-1);
		font-size: var(--fs-label);
		color: var(--text-dim);
	}

	.rate {
		font-size: var(--fs-body);
		font-weight: var(--fw-medium);
		color: var(--text-primary);
	}

	tr.empty .route,
	tr.empty .rate,
	tr.empty td {
		color: var(--text-muted);
	}

	.proxies .outcome {
		width: 28%;
	}

	/* 6: one size across the state words ("switched off" is .quiet, whose size would win). */
	.state-cell .quiet {
		font-size: inherit;
	}

	.state-cell,
	.last {
		font-size: var(--fs-meta);
		white-space: nowrap;
	}

	.last {
		color: var(--text-muted);
	}

	/* Tablet: the plates stack; the readout runs across. */
	@media (max-width: 1023px) {
		.layout {
			grid-template-columns: minmax(0, 1fr);
		}

		.readout {
			flex-direction: row;
			flex-wrap: wrap;
			gap: 0 var(--space-6);
		}

		.reading {
			flex: 1 1 8rem;
			padding-top: var(--space-2);
		}

		.reading:first-child {
			padding-top: var(--space-2);
		}
	}

	/* Phone: 16px gutter; table rows become stacked readings. */
	@media (max-width: 640px) {
		.stage {
			padding: var(--space-4);
		}

		.panel {
			padding: var(--space-4);
		}

		.rates thead {
			position: absolute;
			width: 1px;
			height: 1px;
			overflow: hidden;
			clip: rect(0 0 0 0);
		}

		.rates tr {
			display: grid;
			grid-template-columns: minmax(0, 1fr) auto;
			column-gap: var(--space-3);
			row-gap: var(--space-1);
			padding: var(--space-3) 0;
			border-bottom: 1px solid var(--line);
		}

		.rates th,
		.rates td {
			border-bottom: none;
			padding: 0;
		}

		.rates .route {
			grid-column: 1;
		}

		.rates .rate {
			grid-column: 2;
			grid-row: 1;
		}

		.rates .outcome {
			grid-column: 1 / -1;
			width: auto;
		}

		.rates td.num:not(.rate) {
			grid-column: 2;
			grid-row: 2;
			font-size: var(--fs-meta);
			color: var(--text-muted);
		}

		.rates .unit {
			display: inline;
		}

		.proxies .state-cell,
		.proxies .last {
			grid-column: 1 / -1;
		}
	}
</style>
