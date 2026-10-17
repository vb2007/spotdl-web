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
	import { formatRate, formatSpan, PATH_LABEL, WINDOW_HEADING } from '$lib/stats';

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
			error = err instanceof Error ? err.message : String(err);
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
	const readAt = $derived(
		stats === null
			? ''
			: new Date(stats.generated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
	);
	const shownWindow = $derived(stats?.window ?? selected);

	function clock(iso: string): string {
		const date = new Date(iso);
		const sameDay = new Date(generated).toDateString() === date.toDateString();
		return sameDay
			? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
			: date.toLocaleString([], {
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
					{ key: 'waiting', label: 'waiting', value: stats.queue.counts.waiting },
					{ key: 'pending', label: 'pending', value: stats.queue.counts.pending },
					{ key: 'queued', label: 'queued', value: stats.queue.counts.queued },
					{ key: 'downloading', label: 'downloading', value: stats.queue.counts.downloading }
				]
	);
	const breakerNow = $derived.by(() => {
		if (stats === null) return null;
		const current = stats.breaker.current;
		if (current.paused)
			return { tone: 'fail', text: 'Downloads paused', detail: 'until resumed in settings' };
		if (current.holding_until !== null)
			return {
				tone: 'waiting',
				text: `Breaker holding until ${clock(current.holding_until)}`,
				detail: 'after repeated rate limits; waiting tracks keep their place'
			};
		return { tone: 'idle', text: 'Breaker clear', detail: 'downloads run when due' };
	});
	const proxiesOn = $derived(stats?.proxies.filter((p) => p.enabled).length ?? 0);
	const proxiesCooling = $derived(
		stats?.proxies.filter((p) => p.enabled && p.cooldown_until !== null).length ?? 0
	);
	const anyAttempts = $derived(stats?.network_paths.some((p) => p.attempts > 0) ?? false);
</script>

<svelte:head>
	<title>spotdl-web — stats</title>
</svelte:head>

<div class="stage">
	<SubpageHeader current="stats" {isAdmin} />

	<main id="main" class="main">
		<div class="title-row">
			<h1 class="page-title">Download stats</h1>
			{#if isAdmin}
				<div class="read">
					<span class="read-at mono" role="status">
						{#if loading}reading…{:else if readAt}read at {readAt}{/if}
					</span>
					<button type="button" class="btn small" disabled={loading} onclick={() => void load()}>
						refresh
					</button>
				</div>
			{/if}
		</div>

		{#if !isAdmin}
			<AdminOnlyNotice
				what="Download statistics"
				reason="count every user's downloads together, so only the admin can see them."
			/>
		{:else}
			<p class="form-error" role="alert">
				{#if error}Couldn't read the stats: {error}{/if}
			</p>

			<div class="layout" class:stale={loading && stats !== null}>
				<section class="panel now" aria-labelledby="now-heading">
					<h2 id="now-heading" class="label">Right now</h2>
					{#if stats === null}
						<p class="quiet">{loading ? 'Reading…' : 'Nothing read yet.'}</p>
					{:else}
						<dl class="readout">
							{#each queueRows as row (row.key)}
								<div class="reading">
									<dt>{row.label}</dt>
									<dd class="mono">{row.value.toLocaleString()}</dd>
								</div>
							{/each}
						</dl>
						<p class="note">
							{#if stats.queue.oldest_waiting_since !== null && stats.queue.oldest_waiting_age_seconds !== null}
								Oldest waiting track was submitted
								<span class="mono">{formatSpan(stats.queue.oldest_waiting_age_seconds)}</span> ago
								<span class="mono quiet">({clock(stats.queue.oldest_waiting_since)})</span>.
							{:else}
								Nothing is waiting.
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
								No proxies configured.
							{:else}
								Proxies: <span class="mono">{proxiesOn}</span> switched on{#if proxiesCooling > 0},
									<span class="mono">{proxiesCooling}</span> cooling down{/if}.
							{/if}
						</p>
					{/if}
				</section>

				<section class="panel window" aria-labelledby="window-heading" aria-busy={loading}>
					<header class="window-head">
						<h2 id="window-heading" class="label">{WINDOW_HEADING[shownWindow]}</h2>
						<div class="choice-group" role="group" aria-label="Window">
							{#each WINDOWS as option (option)}
								<button
									type="button"
									aria-pressed={selected === option}
									onclick={() => choose(option)}>{option}</button
								>
							{/each}
						</div>
					</header>

					{#if stats === null}
						<p class="quiet">{loading ? 'Reading…' : 'Nothing read yet.'}</p>
					{:else}
						<section class="block" aria-labelledby="routes-heading">
							<div class="block-head">
								<h3 id="routes-heading" class="block-title">Routes</h3>
								<p class="legend" aria-hidden="true">
									<span class="swatch completed"></span>completed
									<span class="swatch failed"></span>failed, retried
									<span class="swatch not-found"></span>not found
								</p>
							</div>
							{#if !anyAttempts}
								<p class="quiet">No download attempts in this window.</p>
							{/if}
							<table class="rates">
								<thead>
									<tr>
										<th scope="col">Route</th>
										<th scope="col" class="num">Attempts</th>
										<th scope="col">Outcome</th>
										<th scope="col" class="num">
											<abbr title="completed ÷ (completed + failed); not found is left out"
												>Success</abbr
											>
										</th>
									</tr>
								</thead>
								<tbody>
									{#each stats.network_paths as path (path.path)}
										<tr class:empty={path.attempts === 0}>
											<th scope="row" class="mono route">{PATH_LABEL[path.path]}</th>
											<td class="num mono"
												>{path.attempts.toLocaleString()}<span class="unit">&nbsp;attempts</span
												></td
											>
											<td class="outcome">
												{#if path.attempts > 0}
													<OutcomeBar counts={path} />
													<span class="counts mono">
														{path.completed} completed · {path.failed} failed · {path.not_found} not found
													</span>
												{:else}
													<span class="quiet">not used</span>
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
								<h3 id="failures-heading" class="block-title">Failures and breaker holds</h3>
							</div>
							<FailureChannels {stats} />
						</section>

						<section class="block" aria-labelledby="proxies-heading">
							<div class="block-head">
								<h3 id="proxies-heading" class="block-title">Proxies</h3>
								{#if stats.proxies.length > 0}
									<p class="legend" aria-hidden="true">
										<span class="swatch completed"></span>completed
										<span class="swatch failed"></span>failed, retried
										<span class="swatch not-found"></span>not found
									</p>
								{/if}
							</div>
							{#if stats.proxies.length === 0}
								<p class="quiet">
									No proxies configured. Downloads go out directly; proxies are added in settings.
								</p>
							{:else}
								<table class="rates proxies">
									<thead>
										<tr>
											<th scope="col">Proxy</th>
											<th scope="col">State</th>
											<th scope="col" class="num">Attempts</th>
											<th scope="col">Outcome</th>
											<th scope="col" class="num">Success</th>
											<th scope="col">Last success</th>
										</tr>
									</thead>
									<tbody>
										{#each stats.proxies as proxy, i (i)}
											<tr class:empty={proxy.attempts === 0}>
												<th scope="row" class="mono route">{proxy.label}</th>
												<td class="state-cell">
													{#if !proxy.enabled}
														<span class="quiet">switched off</span>
													{:else if proxy.cooldown_until !== null}
														<span class="cond-waiting"
															>cooling until {clock(proxy.cooldown_until)}</span
														>
													{:else}
														<span>ready</span>
													{/if}
												</td>
												<td class="num mono"
													>{proxy.attempts.toLocaleString()}<span class="unit">&nbsp;attempts</span
													></td
												>
												<td class="outcome">
													{#if proxy.attempts > 0}
														<OutcomeBar counts={proxy} />
														<span class="counts mono">
															{proxy.completed} · {proxy.failed} · {proxy.not_found}
														</span>
													{:else}
														<span class="quiet">not used</span>
													{/if}
												</td>
												<td class="num mono rate">{formatRate(proxy.success_rate)}</td>
												<td class="mono last">
													<span class="unit">last success&nbsp;</span>{proxy.last_success_at ===
													null
														? 'never'
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

	.form-error:empty {
		display: none;
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
	}

	.rates abbr {
		text-decoration: underline dotted;
		text-underline-offset: 0.25em;
		cursor: help;
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
