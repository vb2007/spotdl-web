<!--
  v59 (O6): the alert outbox as a log, newest first: what reached the Matrix room, what is still
  trying, what was given up, and what was held back. Its own plate under the two /stats plates
  (owner's choice): it isn't scoped by the window switch. Colour by meaning on DESIGN.md's five
  conditions: sent = settled, retrying = waiting, given up = fail, held back and a first send
  still due = idle. Never amber: nothing here is this session's live track.
  One request per page (`GET /api/admin/alerts`); "show older" appends the next cursor page.
  The page's refresh re-reads the first page (`readToken`), newest read wins.
-->
<script lang="ts">
	import { tick } from 'svelte';
	import * as api from '$lib/api';
	import * as m from '$lib/paraglide/messages';
	import { errorText } from '$lib/i18n/errors';
	import { formatClock, formatDateTime, formatNumber } from '$lib/i18n/format';

	let { readToken }: { readToken: number } = $props();

	let items = $state<api.AlertHistoryItem[]>([]);
	let nextCursor = $state<string | null>(null);
	let configured = $state(true);
	let read = $state(false);
	let loading = $state(false);
	let loadingOlder = $state(false);
	let error = $state('');
	let olderError = $state('');
	// A refresh while a read (or an older page) is in flight: only the newest may land.
	let sequence = 0;

	async function readFirst() {
		const mine = ++sequence;
		loading = true;
		loadingOlder = false;
		error = '';
		olderError = '';
		try {
			const page = await api.getAlertHistory();
			if (mine !== sequence) return;
			items = page.items;
			nextCursor = page.next_cursor;
			configured = page.configured;
			read = true;
		} catch (err) {
			if (mine !== sequence) return;
			error = errorText(err);
		} finally {
			if (mine === sequence) loading = false;
		}
	}

	async function readOlder(event: MouseEvent) {
		if (loading || loadingOlder || nextCursor === null) return;
		// A keyboard press (detail 0) moves focus on to the first row it loaded, where the
		// reader goes next; a pointer press leaves it on the button.
		const fromKeyboard = event.detail === 0;
		const mine = sequence;
		loadingOlder = true;
		olderError = '';
		try {
			const page = await api.getAlertHistory(nextCursor);
			if (mine !== sequence) return;
			const firstNew = page.items[0]?.id;
			items = [...items, ...page.items];
			nextCursor = page.next_cursor;
			if (fromKeyboard && firstNew !== undefined) {
				await tick();
				document.querySelector<HTMLElement>(`[data-alert-row="${CSS.escape(firstNew)}"]`)?.focus();
			}
		} catch (err) {
			if (mine !== sequence) return;
			olderError = errorText(err);
		} finally {
			if (mine === sequence) loadingOlder = false;
		}
	}

	$effect(() => {
		// Re-read whenever the page asks (its first load, and each refresh).
		void readToken;
		void readFirst();
	});

	const today = $derived(new Date().toDateString());

	function when(iso: string): string {
		const date = new Date(iso);
		return date.toDateString() === today
			? formatClock(date)
			: formatDateTime(date, {
					month: 'short',
					day: 'numeric',
					hour: '2-digit',
					minute: '2-digit'
				});
	}

	const CATEGORY: Record<string, () => string> = {
		breaker: m.stats_alert_category_breaker,
		spike: m.stats_alert_category_spike,
		beat_stale: m.stats_alert_category_beat_stale,
		worker_down: m.stats_alert_category_worker_down,
		library: m.stats_alert_category_library,
		test: m.stats_alert_category_test
	};

	function category(item: api.AlertHistoryItem): string {
		return CATEGORY[item.category]?.() ?? item.category;
	}

	type Reading = { tone: string; word: string; at: string | null };

	function stateOf(item: api.AlertHistoryItem): Reading {
		switch (item.state) {
			case 'sent':
				return {
					tone: 'settled',
					word: m.stats_alert_state_sent(),
					at: item.sent_at ? when(item.sent_at) : null
				};
			case 'failed':
				return { tone: 'fail', word: m.stats_alert_state_failed(), at: null };
			case 'suppressed':
				return { tone: 'idle', word: m.stats_alert_state_suppressed(), at: null };
			default:
				// A first send still due reads as idle; one the homeserver refused is retrying.
				return item.attempts > 0 && item.last_error !== null
					? {
							tone: 'waiting',
							word: m.stats_alert_state_retrying(),
							at: item.next_attempt_at ? when(item.next_attempt_at) : null
						}
					: { tone: 'idle', word: m.stats_alert_state_due(), at: null };
		}
	}

	function atLabel(item: api.AlertHistoryItem, at: string): string {
		return item.state === 'sent'
			? m.stats_alert_sent_at({ time: at })
			: m.stats_alert_next_try({ time: at });
	}

	// The room's own label ("[spotdl-web (dev)] ") is the same on every row; the message is what
	// follows it.
	function message(body: string): string {
		return body.replace(/^\[spotdl-web[^\]]*\]\s*/, '');
	}
</script>

<section class="panel alerts" aria-labelledby="alerts-heading" aria-busy={loading}>
	<header class="alerts-head">
		<h2 id="alerts-heading" class="label">{m.stats_alerts_heading()}</h2>
		<p class="quiet intro">{configured ? m.stats_alerts_intro() : m.stats_alerts_off()}</p>
	</header>

	{#if error}
		<p class="form-error" role="alert">{m.stats_alerts_read_failed({ error })}</p>
		<button type="button" class="btn small retry" onclick={() => void readFirst()}
			>{m.stats_alerts_try_again()}</button
		>
	{:else if !read}
		<p class="quiet" role="status">{m.stats_alerts_loading()}</p>
	{:else if items.length === 0}
		<p class="quiet">{m.stats_alerts_empty()}</p>
	{:else}
		<table class="log" class:stale={loading}>
			<thead>
				<tr>
					<th scope="col">{m.stats_alerts_col_time()}</th>
					<th scope="col">{m.stats_alerts_col_category()}</th>
					<th scope="col">{m.stats_alerts_col_state()}</th>
					<th scope="col" class="num">{m.stats_alerts_col_attempts()}</th>
					<th scope="col">{m.stats_alerts_col_message()}</th>
				</tr>
			</thead>
			<tbody>
				{#each items as item (item.id)}
					{@const reading = stateOf(item)}
					<tr data-alert-row={item.id} tabindex="-1">
						<td class="mono time"
							><time datetime={item.created_at}>{when(item.created_at)}</time></td
						>
						<th scope="row" class="category">{category(item)}</th>
						<td class="state">
							<span class="cond-{reading.tone} word">{reading.word}</span>
							{#if reading.at !== null}<span class="at mono">{atLabel(item, reading.at)}</span>{/if}
						</td>
						<td class="num mono attempts"
							>{formatNumber(item.attempts)}<span class="unit"
								>&nbsp;{m.stats_alerts_attempts_unit()}</span
							></td
						>
						<td class="message">
							<!-- i18n-ignore: the alert's own text, as it was sent (alerts stay untranslated) -->
							<span lang="en">{message(item.body_preview)}</span>
							{#if item.last_error !== null}
								<span class="reason"
									><span class="reason-label"
										>{item.state === 'suppressed'
											? m.stats_alert_reason_held()
											: m.stats_alert_reason_error()}</span
									>
									<!-- i18n-ignore: the homeserver's or the cooldown's own words -->
									<span lang="en" class="mono">{item.last_error}</span></span
								>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
		{#if nextCursor !== null || olderError}
			<div class="older">
				{#if nextCursor !== null}
					<button
						type="button"
						class="btn small"
						aria-disabled={loadingOlder || loading}
						onclick={readOlder}
						>{loadingOlder ? m.stats_alerts_older_loading() : m.stats_alerts_older()}</button
					>
				{/if}
				<p class="form-error" role="alert">
					{#if olderError}{m.stats_alerts_older_failed({ error: olderError })}{/if}
				</p>
			</div>
		{/if}
	{/if}
</section>

<style>
	.panel {
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		min-width: 0;
	}

	.alerts-head {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.quiet {
		color: var(--text-muted);
		font-size: var(--fs-detail);
	}

	.intro {
		max-width: 68ch;
	}

	.retry {
		align-self: flex-start;
	}

	.log {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--fs-detail);
		transition: opacity var(--dur-fast) var(--ease-signal);
	}

	/* A refresh keeps the frame and dims the old reading, as the plates above do. */
	.log.stale {
		opacity: 0.55;
	}

	.log th,
	.log td {
		padding: var(--space-2) var(--space-3) var(--space-2) 0;
		text-align: left;
		vertical-align: baseline;
		border-bottom: 1px solid var(--line);
	}

	.log th:last-child,
	.log td:last-child {
		padding-right: 0;
	}

	.log thead th {
		font-family: var(--font-mono);
		font-size: var(--fs-label);
		font-weight: var(--fw-medium);
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--text-dim);
		padding-top: 0;
		white-space: nowrap;
	}

	.log .num {
		text-align: right;
	}

	.time {
		font-size: var(--fs-meta);
		color: var(--text-muted);
		white-space: nowrap;
	}

	.category {
		font-weight: var(--fw-medium);
		color: var(--text-primary);
		white-space: nowrap;
	}

	.state {
		white-space: nowrap;
	}

	.word {
		font-weight: var(--fw-medium);
	}

	.word.cond-idle {
		color: var(--text-muted);
	}

	.at {
		display: block;
		font-size: var(--fs-meta);
		color: var(--text-dim);
	}

	.attempts {
		color: var(--text-primary);
	}

	/* Only the phone's stacked row, which has no column head, spells the unit out. */
	.unit {
		display: none;
	}

	.message {
		width: 100%;
		color: var(--text-primary);
		line-height: 1.45;
		overflow-wrap: anywhere;
	}

	.reason {
		display: block;
		margin-top: var(--space-1);
		font-size: var(--fs-meta);
		color: var(--text-muted);
	}

	.reason-label {
		color: var(--text-dim);
	}

	tr[tabindex='-1']:focus-visible {
		outline-offset: -3px;
	}

	.older {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	.older .form-error {
		margin: 0;
	}

	/* Phone: 16px gutter; each row becomes a stacked reading (time, alert and state, then the
	   message), the units spelled out. */
	@media (max-width: 40em) {
		.panel {
			padding: var(--space-4);
		}

		.log thead {
			position: absolute;
			width: 1px;
			height: 1px;
			overflow: hidden;
			clip: rect(0 0 0 0);
		}

		.log tr {
			display: grid;
			grid-template-columns: auto minmax(0, 1fr) auto;
			column-gap: var(--space-3);
			row-gap: var(--space-1);
			padding: var(--space-3) 0;
			border-bottom: 1px solid var(--line);
		}

		.log th,
		.log td {
			border-bottom: none;
			padding: 0;
		}

		.log .time {
			grid-column: 1;
			grid-row: 1;
		}

		.log .category {
			grid-column: 2;
			grid-row: 1;
			white-space: normal;
		}

		.log .state {
			grid-column: 3;
			grid-row: 1;
			text-align: right;
		}

		.log .attempts {
			grid-column: 3;
			grid-row: 2;
			font-size: var(--fs-meta);
			color: var(--text-muted);
		}

		.log .message {
			grid-column: 1 / 3;
			grid-row: 2;
		}

		.unit {
			display: inline;
		}
	}
</style>
