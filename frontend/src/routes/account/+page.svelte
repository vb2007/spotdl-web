<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';

	let { data } = $props();

	// v19: per-user retention, open to every user (unlike /settings, which stays
	// admin-only) -- this route exists specifically so a non-admin has somewhere to
	// reach it (v17's require_admin gate on /settings is the real enforcement either
	// way; this route just gives every user a page of their own).
	let loaded = $state(false);
	let neverArchive = $state(true);
	let days = $state(30);
	let saving = $state(false);
	let saved = $state(false);
	let error = $state('');

	function syncForm(settings: api.RetentionSettings) {
		neverArchive = settings.retention_days === null;
		if (settings.retention_days !== null) days = settings.retention_days;
	}

	onMount(() => {
		api
			.getRetentionSettings()
			.then((r) => {
				syncForm(r);
				loaded = true;
			})
			.catch((err) => {
				error = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
			});
	});

	async function onSubmit(event: SubmitEvent) {
		event.preventDefault();
		saving = true;
		saved = false;
		error = '';
		try {
			const result = await api.updateRetentionSettings(neverArchive ? null : days);
			syncForm(result);
			saved = true;
		} catch (err) {
			error = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		} finally {
			saving = false;
		}
	}
</script>

<svelte:head>
	<title>spotdl-web — account</title>
</svelte:head>

<main class="stage">
	<header>
		<div class="ident">
			<span class="label">SPOTDL // WEB</span>
			<span class="label dim">ACCOUNT</span>
		</div>
		<a class="back mono" href={resolve('/')}>‹ back to queue</a>
	</header>

	<section class="panel identity">
		<h2 class="label">Signed in as</h2>
		<p class="mono" title={data.session?.email}>
			{api.displayName(data.session?.username ?? null, data.session?.email ?? '')}
		</p>
	</section>

	<section class="panel retention">
		<h2 class="label">Log retention</h2>
		<p class="hint mono">
			Settled jobs older than this are soft-archived automatically (hourly sweep) -- never deleted,
			and never while a track is still active or waiting on the retry ladder. Archived jobs stay
			reachable with the "show archived" toggle and can always be restored.
		</p>

		{#if !loaded && !error}
			<p class="hint mono">Loading…</p>
		{:else}
			<form class="retention-form" onsubmit={onSubmit}>
				<div class="field">
					<span class="label" id="retention-mode-label">Mode</span>
					<div class="option-group" role="group" aria-labelledby="retention-mode-label">
						<button
							type="button"
							aria-pressed={!neverArchive}
							disabled={saving}
							onclick={() => (neverArchive = false)}
						>
							auto-archive
						</button>
						<button
							type="button"
							aria-pressed={neverArchive}
							disabled={saving}
							onclick={() => (neverArchive = true)}
						>
							never
						</button>
					</div>
				</div>

				<label class="field">
					<span class="label">After (days)</span>
					<input
						type="number"
						min="1"
						bind:value={days}
						disabled={saving || neverArchive}
						aria-label="Archive after this many days of inactivity"
					/>
				</label>

				<button type="submit" class="save" disabled={saving}>
					{saving ? 'SAVING…' : 'SAVE'}
				</button>
			</form>
		{/if}

		{#if saved && !saving}
			<p class="saved mono" role="status">Saved.</p>
		{/if}
		<p class="form-error mono" role="alert">{error}</p>
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

	.identity,
	.retention {
		padding: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.identity p {
		color: var(--text-primary);
	}

	.hint {
		margin: 0;
		color: var(--text-dim);
		font-size: 0.75rem;
	}

	.retention-form {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: var(--space-3);
		align-items: end;
	}

	@media (max-width: 640px) {
		.retention-form {
			grid-template-columns: 1fr;
		}
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

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

	input[type='number'] {
		background: var(--bg-0);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-3);
		box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.5);
		font-family: var(--font-mono);
		color: var(--text-primary);
	}

	input[type='number']:focus-visible {
		border-color: var(--signal-dim);
	}

	input[type='number']:disabled {
		opacity: 0.6;
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
</style>
