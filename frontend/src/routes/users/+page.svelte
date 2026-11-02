<!--
	v69: who may sign in (the login allowlist), the admin's only. An address added here signs in
	on its next attempt, with no restart; removing one signs that person out everywhere at once,
	revokes their extension keys and holds their jobs that haven't started (the backend's
	services/allowlist.py). ADMIN_EMAIL is always allowed and has no remove control.
	Shaped with impeccable (v69): /account's API-key rows and form vocabulary, nothing new.
-->
<script lang="ts">
	import { onMount, tick } from 'svelte';
	import SubpageHeader from '$lib/components/SubpageHeader.svelte';
	import AdminOnlyNotice from '$lib/components/AdminOnlyNotice.svelte';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import { confirmAction, keepFocus, keepFocusOnHeading } from '$lib/stores/confirm';
	import * as m from '$lib/paraglide/messages';
	import { errorText } from '$lib/i18n/errors';
	import { counted, formatDateTime } from '$lib/i18n/format';

	let { data } = $props();
	const isAdmin = $derived(data.session?.is_admin ?? false);

	type Shown = (() => string) | null;

	let rows = $state<api.AllowlistRow[] | null>(null);
	let loadError = $state<Shown>(null);

	let email = $state('');
	let adding = $state(false);
	let fieldError = $state<Shown>(null);
	// The add's outcome stays in its own panel, by the field focus returns to (critique); the
	// list's panel reports removals.
	let addError = $state<Shown>(null);
	let addStatus = $state<Shown>(null);
	let error = $state<Shown>(null);
	let status = $state<Shown>(null);
	let busy = $state<Record<string, boolean>>({});

	// Codes about the typed address itself: said under the field, like the local check.
	const FIELD_CODES = new Set(['invalid_email', 'email_already_allowed']);

	/** The backend's minimal check (services/allowlist.py `validate_email`), answered before any
	 * request: one `@`, something before it, a dot inside the domain, no whitespace. The backend
	 * stays the real check. */
	function looksLikeEmail(value: string): boolean {
		if (value.length > 254 || /\s/.test(value)) return false;
		const parts = value.split('@');
		if (parts.length !== 2 || !parts[0]) return false;
		const domain = parts[1];
		return domain.includes('.') && !domain.startsWith('.') && !domain.endsWith('.');
	}

	function load(): Promise<void> {
		loadError = null;
		// A sign-out while the request is in flight: the list is the previous identity's.
		const resets = queue.getResetCount();
		return api
			.listAllowlist()
			.then((answer) => {
				if (queue.getResetCount() !== resets) return;
				rows = answer.items;
			})
			.catch((err) => {
				if (queue.getResetCount() !== resets) return;
				loadError = () => m.users_load_failed({ error: errorText(err) });
			});
	}

	onMount(() => {
		// A non-admin gets AdminOnlyNotice and no admin request at all (v43, F17).
		if (isAdmin) load();
	});

	async function focusField() {
		await keepFocus(document.getElementById('users-add-email') as HTMLInputElement | null);
	}

	async function onAdd(event: SubmitEvent) {
		event.preventDefault();
		fieldError = null;
		addError = null;
		addStatus = null;
		const typed = email.trim();
		if (!typed || !looksLikeEmail(typed.toLowerCase())) {
			fieldError = typed ? () => m.error_invalid_email() : () => m.users_email_required();
			await tick();
			await focusField();
			return;
		}
		adding = true;
		const resets = queue.getResetCount();
		try {
			const added = await api.addAllowedEmail(typed);
			if (queue.getResetCount() !== resets) return;
			email = '';
			addStatus =
				added.resumed_jobs > 0
					? () => m.users_added_resumed({ email: added.email, ...counted(added.resumed_jobs) })
					: () => m.users_added({ email: added.email });
			await load();
		} catch (err) {
			if (err instanceof api.ApiError && err.code && FIELD_CODES.has(err.code)) {
				fieldError = () => errorText(err);
			} else {
				addError = () => errorText(err);
			}
		} finally {
			adding = false;
		}
		// Adding disabled the field that had focus: back to it, for the next address.
		await tick();
		await focusField();
	}

	async function remove(row: api.AllowlistRow) {
		const confirmed = await confirmAction({
			title: m.users_remove_title(),
			subject: row.username ? `${row.username} · ${row.email}` : row.email,
			body: m.users_remove_body(),
			confirmLabel: m.users_remove_confirm(),
			cancelLabel: m.users_remove_cancel()
		});
		if (!confirmed || !rows?.some((r) => r.email === row.email)) {
			return keepFocusOnHeading('users-list-heading');
		}
		busy = { ...busy, [row.email]: true };
		error = null;
		status = null;
		const resets = queue.getResetCount();
		try {
			await api.removeAllowedEmail(row.email);
			if (queue.getResetCount() !== resets) return;
			status = () => m.users_removed({ email: row.email });
		} catch (err) {
			// Removed meanwhile (another tab): it's gone either way, and the list says so below.
			if (!(err instanceof api.ApiError && err.status === 404)) error = () => errorText(err);
		} finally {
			const { [row.email]: _unused, ...rest } = busy;
			busy = rest;
		}
		await load();
		await keepFocusOnHeading('users-list-heading');
	}
</script>

<svelte:head>
	<title>{m.users_title()}</title>
</svelte:head>

<div class="stage">
	<SubpageHeader current="users" {isAdmin} />

	<main id="main" class="main">
		<h1 class="page-title">{m.users_heading()}</h1>
		{#if !isAdmin}
			<AdminOnlyNotice page="users" />
		{:else}
			<section class="panel section" aria-labelledby="users-add-heading">
				<h2 id="users-add-heading" class="label">{m.users_add_heading()}</h2>
				<form class="add" onsubmit={onAdd} novalidate>
					<div class="form-field">
						<label class="label" for="users-add-email">{m.users_add_label()}</label>
						<div class="add-row">
							<input
								id="users-add-email"
								class="well"
								type="email"
								inputmode="email"
								autocomplete="off"
								autocapitalize="off"
								spellcheck="false"
								maxlength="254"
								placeholder={m.users_add_placeholder()}
								bind:value={email}
								disabled={adding}
								aria-invalid={fieldError ? 'true' : undefined}
								aria-describedby="users-add-hint users-add-error"
							/>
							<button type="submit" class="btn" disabled={adding}>
								{adding ? m.users_adding() : m.users_add_button()}
							</button>
						</div>
						<p id="users-add-error" class="field-error" role="alert">{fieldError?.()}</p>
						<p id="users-add-hint" class="field-hint">{m.users_add_hint()}</p>
					</div>
				</form>
				<p class="save-state" role="status">{addStatus?.()}</p>
				<p class="form-error" role="alert">{addError?.()}</p>
			</section>

			<section class="panel section" aria-labelledby="users-list-heading">
				<div class="list-head">
					<h2 id="users-list-heading" class="label">{m.users_list_heading()}</h2>
					{#if rows !== null}
						<span class="count mono">{m.users_count(counted(rows.length))}</span>
					{/if}
				</div>

				{#if rows === null}
					{#if loadError}
						<div class="load-failed">
							<p>{loadError()}</p>
							<button
								type="button"
								class="btn small"
								onclick={() => {
									load();
									keepFocusOnHeading('users-list-heading');
								}}>{m.users_try_again()}</button
							>
						</div>
					{:else}
						<p class="hint">{m.users_loading()}</p>
					{/if}
				{:else}
					<ul class="user-list" aria-labelledby="users-list-heading">
						{#each rows as row (row.email)}
							<li class="user-row" class:admin={row.is_admin_email}>
								<span class="name">
									<!-- An address is mono wherever it shows; a name is Sans. -->
									<span class="who" class:mono={!row.username}>{row.username ?? row.email}</span>
									{#if row.is_admin_email}
										<span class="badge">{m.users_admin_badge()}</span>
									{/if}
								</span>
								<span class="facts">
									{#if row.username}
										<span class="address mono">{row.email}</span>
									{/if}
									<span class="fact"
										>{row.last_login_at
											? m.users_last_signed_in({ when: formatDateTime(row.last_login_at) })
											: m.users_never_signed_in()}</span
									>
									{#if row.is_admin_email}
										<span class="fact">{m.users_admin_note()}</span>
									{:else if row.added_by && row.added_at}
										<span class="fact"
											>{m.users_added_by({
												who: row.added_by,
												when: formatDateTime(row.added_at)
											})}</span
										>
									{:else}
										<!-- No adder: the migration's import from the old env list. -->
										<span class="fact">{m.users_imported()}</span>
									{/if}
									{#if row.held_jobs > 0}
										<span class="fact held">{m.users_held_jobs(counted(row.held_jobs))}</span>
									{/if}
								</span>
								{#if !row.is_admin_email}
									<span class="controls">
										<button
											type="button"
											class="btn small danger"
											disabled={busy[row.email]}
											aria-label={m.users_remove_named({ email: row.email })}
											data-remove={row.email}
											onclick={() => remove(row)}>{m.users_remove()}</button
										>
									</span>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
				<p class="save-state" role="status">{status?.()}</p>
				<p class="form-error" role="alert">{error?.()}</p>
			</section>
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
		gap: var(--space-5);
		margin-top: var(--space-2);
		max-width: 44rem;
	}

	.section {
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.hint {
		font-size: var(--fs-detail);
		color: var(--text-muted);
	}

	.add-row {
		display: flex;
		gap: var(--space-2);
	}

	.add-row input {
		flex: 1 1 auto;
		min-width: 0;
	}

	.list-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-3);
	}

	.count {
		font-size: var(--fs-meta);
		color: var(--text-dim);
	}

	.load-failed {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
		font-size: var(--fs-detail);
		color: var(--fail);
	}

	.user-list {
		list-style: none;
		margin: 0;
		padding: 0;
		border-top: 1px solid var(--line);
	}

	/* Two lines, as /account's key rows: who, then the facts; remove at the right (under both
	   on a phone). */
	.user-row {
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
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-1) var(--space-2);
		min-width: 0;
	}

	.who {
		font-size: var(--fs-detail);
		font-weight: var(--fw-medium);
		color: var(--text-primary);
		overflow-wrap: anywhere;
	}

	/* The admin's address: a role, printed on the faceplate, never amber (nothing is live). */
	.badge {
		font-size: var(--fs-meta);
		color: var(--text-muted);
		border: 1px solid var(--line-control);
		border-radius: 2px;
		padding: 0 var(--space-1);
		line-height: 1.4;
	}

	.facts {
		grid-area: facts;
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-3);
		min-width: 0;
	}

	.address {
		font-size: var(--fs-meta);
		color: var(--text-muted);
		overflow-wrap: anywhere;
	}

	.fact {
		font-size: var(--fs-meta);
		color: var(--text-muted);
	}

	/* Held jobs wait for the address to come back: the waiting condition's colour. */
	.fact.held {
		color: var(--waiting);
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

		.add-row {
			flex-direction: column;
		}

		.user-row {
			grid-template-columns: minmax(0, 1fr);
			grid-template-areas: 'name' 'facts' 'controls';
		}

		.controls {
			justify-content: stretch;
		}

		.controls .btn {
			flex: 1 1 auto;
		}
	}
</style>
