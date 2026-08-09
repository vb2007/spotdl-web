<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import Countdown from '$lib/components/Countdown.svelte';

	let outputSettings = $state<api.OutputSettings | null>(null);
	let outputOptions = $state<api.OutputOptions | null>(null);
	let outputForm = $state<api.EditableOutputSettings>({
		default_format: '',
		default_bitrate: '',
		output_template: ''
	});
	let outputSaving = $state(false);
	let outputSaved = $state(false);
	let outputError = $state('');

	let proxyList = $state<api.Proxy[]>([]);
	let proxiesLoading = $state(true);
	let proxiesError = $state('');
	let newProxyUrl = $state('');
	let addingProxy = $state(false);
	let addProxyError = $state('');
	let proxyBusy = $state<Record<string, boolean>>({});

	// Mirrors the backend's real gate (app.services.proxies.PROXY_URL_RE, verified
	// against the installed spotdl's own Downloader source) -- this copy is purely for
	// immediate form feedback; the backend enforces the actual rule and is the one that
	// matters if the two ever drift.
	const PROXY_URL_RE =
		/^(http|https):\/\/(?:(\w+)(?::(\w+))?@)?(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?$/;

	function syncOutputForm(settings: api.OutputSettings) {
		outputForm = {
			default_format: settings.default_format,
			default_bitrate: settings.default_bitrate,
			output_template: settings.output_template
		};
	}

	async function loadOutputSettings() {
		[outputSettings, outputOptions] = await Promise.all([
			api.getOutputSettings(),
			api.getOutputOptions()
		]);
		syncOutputForm(outputSettings);
	}

	async function loadProxies() {
		proxiesLoading = true;
		proxiesError = '';
		try {
			proxyList = await api.listProxies();
		} catch (err) {
			proxiesError = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		} finally {
			proxiesLoading = false;
		}
	}

	const PROXY_POLL_MS = 5000;

	// No SSE event exists for proxy stats (cooldown_until expiring, consecutive_failures
	// climbing) -- v14's audit flagged the page as only ever refreshing on mount or a
	// self-triggered toggle. Same plain-poll approach as WorkerStatus.svelte's breaker
	// check, but a silent variant: reusing loadProxies() verbatim would flip
	// proxiesLoading on every tick and re-flash "Loading..." over a page the user is
	// actively looking at.
	async function refreshProxiesSilently() {
		// Skip a tick while a toggle/remove/add is in flight -- a poll landing mid-request
		// must not visually clobber that row before the user's own action resolves.
		if (addingProxy || Object.keys(proxyBusy).length > 0) return;
		try {
			proxyList = await api.listProxies();
		} catch {
			// A transient poll failure isn't worth surfacing as a page-level error --
			// loadProxies()'s own error path already covers the initial-load case.
		}
	}

	onMount(() => {
		loadOutputSettings().catch((err) => {
			outputError = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		});
		loadProxies();

		const id = setInterval(refreshProxiesSilently, PROXY_POLL_MS);
		return () => clearInterval(id);
	});

	async function onOutputSubmit(event: SubmitEvent) {
		event.preventDefault();
		outputSaving = true;
		outputSaved = false;
		outputError = '';
		try {
			outputSettings = await api.updateOutputSettings(outputForm);
			syncOutputForm(outputSettings);
			outputSaved = true;
		} catch (err) {
			outputError = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		} finally {
			outputSaving = false;
		}
	}

	async function onAddProxy(event: SubmitEvent) {
		event.preventDefault();
		const url = newProxyUrl.trim();
		if (!url) {
			addProxyError = 'Paste a proxy URL first.';
			return;
		}
		if (!PROXY_URL_RE.test(url)) {
			addProxyError =
				'Must look like http(s)://[user:pass@]<ipv4>[:port] -- a literal IPv4 address, not a hostname.';
			return;
		}
		addingProxy = true;
		addProxyError = '';
		try {
			const proxy = await api.createProxy(url);
			proxyList = [...proxyList, proxy];
			newProxyUrl = '';
		} catch (err) {
			addProxyError = err instanceof api.ApiError ? err.message : 'Could not add this proxy.';
		} finally {
			addingProxy = false;
		}
	}

	async function toggleProxy(proxy: api.Proxy) {
		proxyBusy = { ...proxyBusy, [proxy.id]: true };
		try {
			const updated = await api.setProxyEnabled(proxy.id, !proxy.enabled);
			proxyList = proxyList.map((p) => (p.id === updated.id ? updated : p));
		} catch (err) {
			proxiesError = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		} finally {
			const { [proxy.id]: _unused, ...rest } = proxyBusy;
			proxyBusy = rest;
		}
	}

	async function removeProxy(proxy: api.Proxy) {
		// Only ever called for source=manual -- the "remove" control isn't rendered for
		// source=file rows at all (see markup below). A real, permanent delete: the row
		// disappears from the list rather than being merged back in updated.
		proxyBusy = { ...proxyBusy, [proxy.id]: true };
		try {
			await api.deleteProxy(proxy.id);
			proxyList = proxyList.filter((p) => p.id !== proxy.id);
		} catch (err) {
			proxiesError = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		} finally {
			const { [proxy.id]: _unused, ...rest } = proxyBusy;
			proxyBusy = rest;
		}
	}

	function formatTimestamp(value: string | null): string {
		if (!value) return '—';
		return new Date(value).toLocaleString();
	}

	function isFuture(value: string | null): boolean {
		return value != null && new Date(value).getTime() > Date.now();
	}
</script>

<svelte:head>
	<title>spotdl-web — settings</title>
</svelte:head>

<main class="stage">
	<header>
		<div class="ident">
			<span class="label">SPOTDL // WEB</span>
			<span class="label dim">SETTINGS</span>
		</div>
		<a class="back mono" href={resolve('/')}>‹ back to queue</a>
	</header>

	<section class="panel output-settings">
		<h2 class="label">Output defaults</h2>
		<p class="hint mono">Applies to the next download — no restart needed.</p>

		{#if outputOptions === null}
			<p class="hint mono">Loading options…</p>
		{:else}
			<form class="output-form" onsubmit={onOutputSubmit}>
				<div class="field">
					<span class="label" id="format-label">Format</span>
					<div class="option-group" role="group" aria-labelledby="format-label">
						{#each outputOptions.formats as fmt (fmt)}
							<button
								type="button"
								aria-pressed={outputForm.default_format === fmt}
								disabled={outputSaving}
								onclick={() => (outputForm.default_format = fmt)}
							>
								{fmt}
							</button>
						{/each}
					</div>
				</div>

				<label class="field">
					<span class="label">Bitrate</span>
					<select bind:value={outputForm.default_bitrate} disabled={outputSaving}>
						{#each outputOptions.bitrates as rate (rate)}
							<option value={rate}>{rate}</option>
						{/each}
					</select>
				</label>

				<label class="field wide">
					<span class="label">Filename template</span>
					<input type="text" bind:value={outputForm.output_template} disabled={outputSaving} />
				</label>

				<button type="submit" class="save" disabled={outputSaving || outputSettings === null}>
					{outputSaving ? 'SAVING…' : 'SAVE'}
				</button>
			</form>
		{/if}

		{#if outputSaved && !outputSaving}
			<p class="saved mono" role="status">Saved.</p>
		{/if}
		<p class="form-error mono" role="alert">{outputError}</p>
	</section>

	<section class="panel proxy-settings">
		<h2 class="label">Proxy pool</h2>
		<p class="hint mono">
			File-managed (<code>proxies.txt</code>) and UI-managed proxies are both drawn from equally.
			URLs are shown with credentials redacted. Expected format:
			<code>http(s)://[user:pass@]&lt;ipv4&gt;[:port]</code> — a literal IPv4 address, not a hostname.
		</p>

		<form class="add-proxy" onsubmit={onAddProxy}>
			<input
				type="text"
				placeholder="Proxy URL"
				bind:value={newProxyUrl}
				disabled={addingProxy}
				aria-label="New proxy URL, e.g. http(s)://[user:pass@]<ipv4>[:port]"
				aria-describedby="add-proxy-error"
			/>
			<button type="submit" disabled={addingProxy}>{addingProxy ? 'ADDING…' : 'ADD'}</button>
		</form>
		<p id="add-proxy-error" class="form-error mono" role="alert">{addProxyError}</p>

		{#if proxiesLoading}
			<p class="hint mono">Loading…</p>
		{:else if proxyList.length === 0}
			<p class="hint mono">No proxies configured — every attempt goes out direct.</p>
		{:else}
			<ul class="proxy-list">
				{#each proxyList as proxy (proxy.id)}
					<li class="proxy-row" class:disabled={!proxy.enabled}>
						<span class="source-badge mono" class:manual={proxy.source === 'manual'}
							>{proxy.source}</span
						>
						<span class="url mono">{proxy.url}</span>
						<span class="stat mono">
							{proxy.consecutive_failures} fail{proxy.consecutive_failures === 1 ? '' : 's'}
						</span>
						<span class="stat mono">last ok: {formatTimestamp(proxy.last_success_at)}</span>
						{#if isFuture(proxy.cooldown_until)}
							<Countdown scheduledAt={proxy.cooldown_until ?? ''} label="cooldown" />
						{/if}
						<button
							type="button"
							class="toggle"
							aria-pressed={proxy.enabled}
							disabled={proxyBusy[proxy.id]}
							onclick={() => toggleProxy(proxy)}
						>
							{proxy.enabled ? 'enabled' : 'disabled'}
						</button>
						{#if proxy.source === 'manual'}
							<button
								type="button"
								class="remove"
								disabled={proxyBusy[proxy.id]}
								onclick={() => removeProxy(proxy)}
							>
								remove
							</button>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
		<p class="form-error mono" role="alert">{proxiesError}</p>
	</section>
</main>

<style>
	.stage {
		max-width: 64rem;
		margin: 0 auto;
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}

	header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-4);
		flex-wrap: wrap;
	}

	.ident {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.ident .dim {
		color: var(--text-dim);
	}

	.back {
		color: var(--text-muted);
		font-size: 0.8125rem;
		text-decoration: none;
	}

	.back:hover,
	.back:focus-visible {
		color: var(--signal-dim);
	}

	.output-settings,
	.proxy-settings {
		padding: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.hint {
		margin: 0;
		color: var(--text-dim);
		font-size: 0.75rem;
	}

	.output-form {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: var(--space-3);
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.field.wide {
		grid-column: 1 / -1;
	}

	/* Same ≤640px breakpoint QueueTable.svelte's mobile stacked layout already
	   established (DESIGN.md §6) -- below it, a 2-column grid squeezed format's 6
	   toggle buttons and the bitrate select into two narrow lanes with nothing left
	   over, confirmed by an actual mobile screenshot before this fix, not assumed. */
	@media (max-width: 640px) {
		.output-form {
			grid-template-columns: 1fr;
		}

		.add-proxy {
			flex-direction: column;
			align-items: stretch;
		}

		/* The filename template's default value (34 chars) is real content, not
		   placeholder text, so it can't just be shortened -- confirmed by an actual
		   mobile screenshot that it clipped its final character at the base size. */
		input[type='text'] {
			font-size: 0.8125rem;
		}
	}

	/* Same "1-at-a-time active" toggle-group convention as QueueTable.svelte's filter
	   tabs (DESIGN.md §6) -- reused here rather than inventing a second pattern for the
	   same interaction. */
	.option-group {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.option-group button {
		background: var(--bg-2);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-1) var(--space-3);
		font-family: var(--font-mono);
		font-size: 0.75rem;
		color: var(--text-muted);
		cursor: pointer;
	}

	.option-group button[aria-pressed='true'] {
		border-color: var(--signal);
		color: var(--text-primary);
	}

	.option-group button:hover:not(:disabled),
	.option-group button:focus-visible {
		border-color: var(--signal-dim);
	}

	.option-group button:disabled {
		opacity: 0.6;
		cursor: default;
	}

	input[type='text'],
	select {
		background: var(--bg-0);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-3);
		box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.5);
		font-family: var(--font-mono);
		color: var(--text-primary);
	}

	input[type='text']:focus-visible,
	select:focus-visible {
		border-color: var(--signal-dim);
	}

	.save {
		grid-column: 1 / -1;
		justify-self: start;
		background: var(--bg-2);
		border: 1px solid var(--line-bright);
		border-radius: 4px;
		padding: var(--space-3) var(--space-4);
		font-family: var(--font-mono);
		font-weight: 600;
		letter-spacing: 0.06em;
		cursor: pointer;
	}

	.save:hover:not(:disabled),
	.save:focus-visible {
		border-color: var(--signal);
		background: var(--bg-3);
	}

	.save:disabled {
		opacity: 0.6;
		cursor: default;
	}

	.saved {
		margin: 0;
		color: var(--settled);
		font-size: 0.8125rem;
	}

	.form-error {
		min-height: 1rem;
		margin: 0;
		color: var(--fail);
		font-size: 0.8125rem;
	}

	.add-proxy {
		display: flex;
		gap: var(--space-3);
	}

	.add-proxy input {
		flex: 1;
		min-width: 0;
		background: var(--bg-0);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-3);
		box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.5);
		font-family: var(--font-mono);
	}

	.add-proxy input:focus-visible {
		border-color: var(--signal-dim);
	}

	.add-proxy button {
		background: var(--bg-2);
		border: 1px solid var(--line-bright);
		border-radius: 4px;
		padding: var(--space-3) var(--space-4);
		font-family: var(--font-mono);
		font-weight: 600;
		letter-spacing: 0.06em;
		cursor: pointer;
		white-space: nowrap;
	}

	.add-proxy button:hover:not(:disabled),
	.add-proxy button:focus-visible {
		border-color: var(--signal);
		background: var(--bg-3);
	}

	.proxy-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.proxy-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3);
		background: var(--bg-1);
		border: 1px solid var(--line);
		border-radius: 4px;
		font-size: 0.8125rem;
	}

	.proxy-row.disabled {
		opacity: 0.6;
	}

	.source-badge {
		flex-shrink: 0;
		padding: 0.125rem var(--space-2);
		border: 1px solid var(--line);
		border-radius: 3px;
		font-size: 0.6875rem;
		letter-spacing: 0.06em;
		color: var(--text-dim);
	}

	.source-badge.manual {
		color: var(--waiting);
		border-color: var(--waiting-dim);
	}

	.url {
		min-width: 12rem;
		flex: 1;
		color: var(--text-primary);
	}

	.stat {
		color: var(--text-muted);
		font-size: 0.75rem;
		white-space: nowrap;
	}

	.toggle,
	.remove {
		flex-shrink: 0;
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-1) var(--space-2);
		font-size: 0.6875rem;
		font-family: var(--font-mono);
		color: var(--text-muted);
		cursor: pointer;
	}

	.toggle[aria-pressed='true'] {
		border-color: var(--settled-dim);
		color: var(--settled);
	}

	.toggle[aria-pressed='false'] {
		border-color: var(--fail-dim);
		color: var(--fail);
	}

	.toggle:hover:not(:disabled),
	.toggle:focus-visible,
	.remove:hover:not(:disabled),
	.remove:focus-visible {
		border-color: var(--signal-dim);
		color: var(--text-primary);
	}

	.toggle:disabled,
	.remove:disabled {
		opacity: 0.6;
		cursor: default;
	}
</style>
