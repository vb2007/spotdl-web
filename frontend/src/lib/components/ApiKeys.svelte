<!--
	v53: /account's "browser extension keys" section. A key is the Firefox extension's fallback
	when this browser's session cookie doesn't reach the API: it can queue Spotify links, read
	those jobs and say whose it is, nothing else (backend/app/routers/auth.py). Create (named), list (prefix, created,
	last used) and revoke. The whole key exists only in the create answer, so it's shown once,
	here, with a copy control, until "done" or leaving the page.
-->
<script lang="ts">
	import { onMount, tick } from 'svelte';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import { confirmAction, keepFocus, keepFocusOnHeading } from '$lib/stores/confirm';
	import * as m from '$lib/paraglide/messages';
	import { errorText } from '$lib/i18n/errors';
	import { formatDateTime, formatNumber } from '$lib/i18n/format';

	// The longest name the backend takes (services/api_keys.py LABEL_MAX_LENGTH), in code
	// points, as the backend counts. The field's own `maxlength` counts UTF-16 units, so it is
	// only a backstop (it would cut an emoji in half): the check below says so instead.
	const LABEL_MAX = 64;
	const FIELD_MAX = LABEL_MAX * 4;

	type Shown = (() => string) | null;

	let keys = $state<api.ApiKey[] | null>(null);
	let maxActive = $state(10);
	let loadError = $state<Shown>(null);

	let label = $state('');
	let creating = $state(false);
	let labelError = $state<Shown>(null);
	let error = $state<Shown>(null);
	let status = $state<Shown>(null);
	// The one key this page has just created, whole: never stored, never fetched again.
	let fresh = $state<{ id: string; label: string; key: string } | null>(null);
	let copied = $state<'yes' | 'failed' | null>(null);
	let busy = $state<Record<string, boolean>>({});

	const atLimit = $derived(keys !== null && keys.length >= maxActive);

	function load(): Promise<void> {
		loadError = null;
		const resets = queue.getResetCount();
		return api
			.listApiKeys()
			.then((list) => {
				if (queue.getResetCount() !== resets) return;
				keys = list.keys;
				maxActive = list.max_active;
			})
			.catch((err) => {
				loadError = () => m.account_keys_load_failed({ error: errorText(err) });
			});
	}

	onMount(load);

	async function onCreate(event: SubmitEvent) {
		event.preventDefault();
		labelError = null;
		error = null;
		status = null;
		// Spaces as the backend treats them (services/api_keys.py `_collapse_spaces`): space
		// separators off the ends, each run inside down to one space. Anything else (a tab, a BOM)
		// is the backend's to judge, so it gets the backend's message rather than vanishing here.
		const name = label.replace(/^\p{Zs}+|\p{Zs}+$/gu, '').replace(/\p{Zs}+/gu, ' ');
		if (!name || [...name].length > LABEL_MAX) {
			labelError = () => m.error_api_key_label_invalid({ max: formatNumber(LABEL_MAX) });
			await tick();
			const field = document.getElementById('api-key-label');
			if (field === document.activeElement) field?.blur();
			field?.focus();
			return;
		}
		creating = true;
		let madeKey = false;
		// A sign-out while the request is in flight: the key belongs to the previous identity,
		// and this page must not show it to whoever is here next (v42's late-write guard).
		const resets = queue.getResetCount();
		try {
			const created = await api.createApiKey(name);
			if (queue.getResetCount() !== resets) return;
			const { key, ...row } = created;
			keys = [row, ...(keys ?? []).filter((k) => k.id !== row.id)];
			fresh = { id: row.id, label: row.label, key };
			copied = null;
			label = '';
			madeKey = true;
		} catch (err) {
			// The name itself was refused: say so under the field, like the local check does.
			if (err instanceof api.ApiError && err.code === 'api_key_label_invalid') {
				labelError = () => errorText(err);
			} else error = () => errorText(err);
			// At the limit by another tab's count: show the keys the server has, not this tab's.
			// Awaited: whether focus can go back to the field depends on what it says.
			if (err instanceof api.ApiError && err.code === 'api_key_limit_reached') await load();
		} finally {
			creating = false;
		}
		await tick();
		if (madeKey) {
			document.getElementById('api-key-fresh')?.focus();
			return;
		}
		// Creating disabled the field that had focus: back to it to try again, or to the
		// section's heading when it stays disabled (the limit reached meanwhile).
		await focusNameOrHeading();
	}

	async function focusNameOrHeading() {
		const field = document.getElementById('api-key-label') as HTMLInputElement | null;
		if (field && !field.disabled) await keepFocus(field);
		else await keepFocusOnHeading('keys-heading');
	}

	async function copyKey() {
		if (!fresh) return;
		try {
			await navigator.clipboard.writeText(fresh.key);
			copied = 'yes';
		} catch {
			copied = 'failed';
			// The fallback is selecting it by hand: put the selection there already.
			const field = document.getElementById('api-key-fresh') as HTMLInputElement | null;
			field?.focus();
			field?.select();
		}
	}

	async function dismissFresh() {
		fresh = null;
		copied = null;
		await tick();
		// "done" itself is gone: the name field, or the heading at the key limit.
		const field = document.getElementById('api-key-label') as HTMLInputElement | null;
		if (field && !field.disabled) field.focus();
		else await keepFocusOnHeading('keys-heading');
	}

	async function revoke(key: api.ApiKey) {
		const confirmed = await confirmAction({
			title: m.account_keys_revoke_title(),
			subject: `${key.label} · sdw_${key.prefix}…`,
			body: m.account_keys_revoke_body(),
			confirmLabel: m.account_keys_revoke_confirm(),
			cancelLabel: m.account_keys_revoke_cancel()
		});
		if (!confirmed || !keys?.some((k) => k.id === key.id)) {
			return keepFocusOnHeading('keys-heading');
		}
		busy = { ...busy, [key.id]: true };
		error = null;
		status = null;
		try {
			await api.revokeApiKey(key.id);
			keys = (keys ?? []).filter((k) => k.id !== key.id);
			if (fresh?.id === key.id) fresh = null;
			status = () => m.account_keys_revoked({ label: key.label });
		} catch (err) {
			// Revoked meanwhile (another tab): it's gone either way.
			if (err instanceof api.ApiError && err.status === 404) {
				keys = (keys ?? []).filter((k) => k.id !== key.id);
			} else {
				error = () => errorText(err);
			}
		} finally {
			const { [key.id]: _unused, ...rest } = busy;
			busy = rest;
		}
		await keepFocusOnHeading('keys-heading');
	}
</script>

<section class="panel section" aria-labelledby="keys-heading">
	<h2 id="keys-heading" class="label">{m.account_keys_heading()}</h2>
	<p class="hint" id="keys-hint">{m.account_keys_hint()}</p>

	<form class="create" onsubmit={onCreate} novalidate>
		<div class="form-field">
			<label class="label" for="api-key-label">{m.account_keys_name()}</label>
			<div class="create-row">
				<input
					id="api-key-label"
					class="well"
					type="text"
					autocomplete="off"
					maxlength={FIELD_MAX}
					placeholder={m.account_keys_name_placeholder()}
					bind:value={label}
					disabled={creating || atLimit}
					aria-invalid={labelError ? 'true' : undefined}
					aria-describedby="keys-hint api-key-label-error api-key-limit"
				/>
				<button type="submit" class="btn" disabled={creating || atLimit}>
					{creating ? m.account_keys_creating() : m.account_keys_create()}
				</button>
			</div>
			<p id="api-key-label-error" class="field-error" role="alert">{labelError?.()}</p>
			<p id="api-key-limit" class="field-hint">{atLimit ? m.account_keys_limit() : ''}</p>
		</div>
	</form>

	{#if fresh}
		<div class="fresh" role="group" aria-labelledby="api-key-fresh-heading">
			<h3 id="api-key-fresh-heading" class="group-title">
				{m.account_keys_new_heading()} <span class="fresh-name">{fresh.label}</span>
			</h3>
			<p class="hint" id="api-key-fresh-hint">{m.account_keys_new_hint()}</p>
			<div class="form-field">
				<label class="sr-only" for="api-key-fresh">{m.account_keys_new_label()}</label>
				<div class="create-row">
					<input
						id="api-key-fresh"
						class="well key"
						type="text"
						readonly
						spellcheck="false"
						autocomplete="off"
						value={fresh.key}
						aria-describedby="api-key-fresh-hint"
						onfocus={(event) => event.currentTarget.select()}
					/>
					<button type="button" class="btn" onclick={copyKey}>
						{copied === 'yes' ? m.account_keys_copied() : m.account_keys_copy()}
					</button>
					<button type="button" class="btn" onclick={dismissFresh}>{m.account_keys_done()}</button>
				</div>
			</div>
			<p class="save-state" class:saved={copied === 'yes'} role="status">
				{copied === 'yes'
					? m.account_keys_copied()
					: copied === 'failed'
						? m.account_keys_copy_failed()
						: ''}
			</p>
		</div>
	{/if}

	{#if keys === null}
		{#if loadError}
			<div class="load-failed">
				<p>{loadError()}</p>
				<button
					type="button"
					class="btn small"
					onclick={() => {
						load();
						keepFocusOnHeading('keys-heading');
					}}>{m.account_keys_try_again()}</button
				>
			</div>
		{:else}
			<p class="hint">{m.account_keys_loading()}</p>
		{/if}
	{:else if keys.length === 0}
		<p class="hint">{m.account_keys_empty()}</p>
	{:else}
		<div class="list-head">
			<h3 class="group-title" id="keys-list-heading">{m.account_keys_list_label()}</h3>
			<span class="count mono"
				>{m.account_keys_count({
					active: formatNumber(keys.length),
					max: formatNumber(maxActive)
				})}</span
			>
		</div>
		<ul class="key-list" aria-labelledby="keys-list-heading">
			{#each keys as key (key.id)}
				<li class="key-row">
					<span class="name">{key.label}</span>
					<span class="facts">
						<!-- i18n-ignore: the key's own fixed prefix, the same in every language -->
						<span class="prefix mono">sdw_{key.prefix}…</span>
						<span class="fact"
							>{m.account_keys_created({ when: formatDateTime(key.created_at) })}</span
						>
						<span class="fact"
							>{key.last_used_at
								? m.account_keys_last_used({ when: formatDateTime(key.last_used_at) })
								: m.account_keys_never_used()}</span
						>
					</span>
					<span class="controls">
						<button
							type="button"
							class="btn small danger"
							disabled={busy[key.id]}
							aria-label={m.account_keys_revoke_named({ label: key.label })}
							data-revoke={key.id}
							onclick={() => revoke(key)}>{m.account_keys_revoke()}</button
						>
					</span>
				</li>
			{/each}
		</ul>
	{/if}
	<p class="save-state" role="status">{status?.()}</p>
	<p class="form-error" class:sr-only={keys === null && loadError !== null} role="alert">
		{keys === null && loadError !== null ? loadError() : error?.()}
	</p>
</section>

<style>
	.section {
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.hint {
		font-size: var(--fs-detail);
		color: var(--text-muted);
		max-width: 68ch;
	}

	.group-title {
		font-size: var(--fs-body);
		font-weight: var(--fw-medium);
	}

	.create-row {
		display: flex;
		gap: var(--space-2);
	}

	.create-row input {
		flex: 1 1 auto;
	}

	/* The new key: a recess holding the one copy of it, set off from the list by a rule, the
	   way /account's preference groups read apart (v47). Neutral, never amber: a fresh key is
	   not a live condition. */
	.fresh {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-4) 0;
		border-top: 1px solid var(--line);
		border-bottom: 1px solid var(--line);
	}

	.fresh-name {
		color: var(--text-muted);
		font-weight: var(--fw-regular);
		overflow-wrap: anywhere;
	}

	.key {
		color: var(--text-primary);
		letter-spacing: 0.02em;
	}

	.load-failed {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
		font-size: var(--fs-detail);
		color: var(--fail);
	}

	.list-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-3);
		margin-top: var(--space-2);
	}

	.count {
		font-size: var(--fs-meta);
		color: var(--text-dim);
	}

	.key-list {
		list-style: none;
		margin: 0;
		padding: 0;
		border-top: 1px solid var(--line);
	}

	/* Two lines, as /settings' proxy rows: the name, then what it is and how it's been used;
	   revoke at the right (under both on a phone). */
	.key-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		grid-template-areas:
			'name controls'
			'facts controls';
		align-items: center;
		gap: var(--space-1) var(--space-3);
		padding: var(--space-3) 0;
		border-bottom: 1px solid var(--line);
	}

	.name {
		grid-area: name;
		font-size: var(--fs-detail);
		font-weight: var(--fw-medium);
		color: var(--text-primary);
		overflow-wrap: anywhere;
	}

	.facts {
		grid-area: facts;
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-3);
	}

	.prefix {
		font-size: var(--fs-meta);
		color: var(--text-muted);
	}

	.fact {
		font-size: var(--fs-meta);
		color: var(--text-muted);
	}

	.controls {
		grid-area: controls;
		display: flex;
		justify-content: flex-end;
	}

	@media (max-width: 40em) {
		.section {
			padding: var(--space-4);
		}

		.create-row {
			flex-direction: column;
		}

		.key-row {
			grid-template-columns: minmax(0, 1fr);
			grid-template-areas: 'name' 'facts' 'controls';
		}

		.controls {
			justify-content: flex-start;
		}
	}
</style>
