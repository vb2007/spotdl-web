<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import { keepFocus } from '$lib/stores/confirm';
	import SubpageHeader from '$lib/components/SubpageHeader.svelte';
	import { helpOpen, shortcutsEnabled } from '$lib/keyboard/registry';

	let { data } = $props();
	const isAdmin = $derived(data.session?.is_admin ?? false);
	const email = $derived(data.session?.email ?? '');
	const username = $derived(data.session?.username ?? null);

	// v19: per-user retention, open to every user (unlike /settings, which stays
	// admin-only) -- this route exists specifically so a non-admin has somewhere to
	// reach it (v17's require_admin gate on /settings is the real enforcement either
	// way; this route just gives every user a page of their own).
	let saved = $state<api.RetentionSettings | null>(null);
	let neverArchive = $state(true);
	let days = $state<number | null>(30);
	let saving = $state(false);
	let savedAt = $state<Date | null>(null);
	let error = $state('');
	let daysError = $state('');
	// A hundred years. The backend takes any positive number, but the hourly retention sweep
	// computes now - days, which overflows past year 1 and stops it for every user (found,
	// not fixed in the backend: v48).
	const MAX_DAYS = 36_500;
	let loggingOut = $state(false);
	let logoutError = $state('');

	// The mode and the number both count: switching to "automatically" with the days field
	// cleared is a change even though no number is there yet.
	const dirty = $derived(
		saved !== null &&
			(neverArchive !== (saved.retention_days === null) ||
				(!neverArchive && days !== saved.retention_days))
	);

	function syncForm(settings: api.RetentionSettings) {
		saved = settings;
		neverArchive = settings.retention_days === null;
		if (settings.retention_days !== null) days = settings.retention_days;
	}

	onMount(() => {
		api
			.getRetentionSettings()
			.then(syncForm)
			.catch((err) => {
				error = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
			});
	});

	async function onSubmit(event: SubmitEvent) {
		event.preventDefault();
		daysError = '';
		if (!neverArchive) {
			daysError =
				typeof days !== 'number' || !Number.isInteger(days) || days < 1 || days > MAX_DAYS
					? `Enter a whole number of days from 1 to ${MAX_DAYS.toLocaleString()}.`
					: '';
			if (daysError) {
				// Nothing is sent, so focus the field: its error is read out from there.
				await tick();
				const field = document.getElementById('retention-days');
				// Already focused: leave and come back so its new error is read.
				if (field === document.activeElement) field?.blur();
				field?.focus();
				return;
			}
		}
		// Saving disables the field or button that had focus: give it back afterwards.
		const from = document.activeElement instanceof HTMLElement ? document.activeElement : null;
		saving = true;
		error = '';
		try {
			syncForm(await api.updateRetentionSettings(neverArchive ? null : days));
			savedAt = new Date();
		} catch (err) {
			error = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		} finally {
			saving = false;
		}
		await keepFocus(from);
	}

	// v45: the single-key shortcut switch (WCAG 2.1.4), stored per user server-side so it
	// follows them to every device. It applies the moment the server has it; another device
	// picks it up from /api/auth/me on its next load.
	let keyboardSaving = $state(false);
	let keyboardError = $state('');
	let keyboardSavedAt = $state<Date | null>(null);

	async function setShortcuts(enabled: boolean) {
		// Always sent, even for the choice shown as pressed: another device may have changed
		// it since this page read it (the PATCH is idempotent).
		if (keyboardSaving) return;
		const from = document.activeElement instanceof HTMLElement ? document.activeElement : null;
		keyboardSaving = true;
		keyboardError = '';
		try {
			const saved = await api.updateKeyboardSettings(enabled);
			shortcutsEnabled.set(saved.keyboard_shortcuts);
			keyboardSavedAt = new Date();
		} catch (err) {
			keyboardError = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		} finally {
			keyboardSaving = false;
		}
		await keepFocus(from);
	}

	// v43 (F31): the account page could not sign out; it now does, the way `/` does.
	async function onLogout() {
		loggingOut = true;
		logoutError = '';
		try {
			await api.logout();
		} catch (err) {
			// A 401 means the session is already gone: that's signed out, not a failure.
			if (!(err instanceof api.ApiError && err.status === 401)) {
				logoutError = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
				loggingOut = false;
				return;
			}
		}
		// The module-level queue store outlives this navigation; clear it before leaving so
		// the next identity on this tab never sees a flash of these rows.
		queue.reset();
		await goto(resolve('/login'));
	}
</script>

<svelte:head>
	<title>spotdl-web — account</title>
</svelte:head>

<div class="stage">
	<SubpageHeader current="account" {isAdmin} />

	<main id="main" class="main">
		<h1 class="page-title">Account</h1>
		<section class="panel section" aria-labelledby="identity-heading">
			<h2 id="identity-heading" class="label">Signed in</h2>
			<div class="identity">
				<div class="who">
					<!-- F31: the email is on the page, not only in a tooltip. -->
					<p class="name">{api.displayName(username, email)}</p>
					{#if username !== null}
						<p class="email mono">{email}</p>
					{/if}
					{#if isAdmin}
						<p class="role">Admin of this server</p>
					{/if}
				</div>
				<button type="button" class="btn" disabled={loggingOut} onclick={onLogout}>
					{loggingOut ? 'disconnecting…' : 'disconnect'}
				</button>
			</div>
			<p class="form-error" role="alert">{logoutError}</p>
		</section>

		<!-- Preferences: one group per setting. v45 added the keyboard-shortcut switch; v46 adds
		     the language switch here, as a further group. -->
		<section class="panel section" aria-labelledby="preferences-heading">
			<h2 id="preferences-heading" class="label">Preferences</h2>

			<div class="group" role="group" aria-labelledby="retention-heading">
				<h3 id="retention-heading" class="group-title">Log retention</h3>
				<p class="hint">
					Finished jobs (done, failed or cancelled) are archived once nothing has happened in them
					for this long. Archived jobs are hidden, never deleted, and come back with “show
					archived”. A job still downloading or waiting is never archived.
				</p>

				{#if saved === null}
					{#if !error}<p class="hint">Loading your retention setting…</p>{/if}
				{:else}
					<form class="retention-form" onsubmit={onSubmit} novalidate>
						<div class="form-field">
							<span class="label" id="retention-mode-label">Archive finished jobs</span>
							<div class="choice-group" role="group" aria-labelledby="retention-mode-label">
								<button
									type="button"
									aria-pressed={!neverArchive}
									disabled={saving}
									onclick={() => (neverArchive = false)}
								>
									automatically
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

						<div class="form-field">
							<!-- F30: the accessible name is the visible label (WCAG 2.5.3). -->
							<label class="label" for="retention-days">After</label>
							<div class="with-unit">
								<input
									id="retention-days"
									class="well"
									type="number"
									inputmode="numeric"
									min="1"
									max={MAX_DAYS}
									step="1"
									bind:value={days}
									disabled={saving || neverArchive}
									aria-invalid={daysError ? 'true' : undefined}
									aria-describedby="retention-days-unit retention-days-error"
								/>
								<span class="unit mono" id="retention-days-unit">days without activity</span>
							</div>
							<p id="retention-days-error" class="field-error">{daysError}</p>
						</div>

						<div class="save-row wide">
							<button type="submit" class="btn" disabled={saving}>
								{saving ? 'saving…' : 'save'}
							</button>
							<p class="save-state" class:saved={!dirty && savedAt} role="status">
								{dirty
									? 'Unsaved changes'
									: savedAt
										? `Saved at ${savedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
										: ''}
							</p>
						</div>
					</form>
				{/if}
				<p class="form-error" role="alert">{error}</p>
			</div>

			<div class="group" role="group" aria-labelledby="keyboard-heading">
				<h3 id="keyboard-heading" class="group-title">Keyboard shortcuts</h3>
				<p class="hint" id="keyboard-hint">
					Single keys do things on the queue: <kbd>j</kbd> and <kbd>k</kbd> move between rows,
					<kbd>x</kbd> cancels, <kbd>h</kbd> lists them all. Switch them off if they get in the way of
					a screen reader or speech input. Tab, the arrow keys, Enter and Esc work either way.
				</p>
				<div class="form-field">
					<span class="label" id="keyboard-mode-label">Single-key shortcuts</span>
					<div class="keyboard-row">
						<div
							class="choice-group"
							role="group"
							aria-labelledby="keyboard-mode-label"
							aria-describedby="keyboard-hint"
						>
							<button
								type="button"
								aria-pressed={$shortcutsEnabled}
								disabled={keyboardSaving}
								onclick={() => setShortcuts(true)}
							>
								on
							</button>
							<button
								type="button"
								aria-pressed={!$shortcutsEnabled}
								disabled={keyboardSaving}
								onclick={() => setShortcuts(false)}
							>
								off
							</button>
						</div>
						<button type="button" class="btn" onclick={() => helpOpen.set(true)}
							>show shortcuts</button
						>
					</div>
				</div>
				<p class="save-state" class:saved={keyboardSavedAt !== null} role="status">
					{keyboardSaving
						? 'Saving…'
						: keyboardSavedAt
							? `Saved at ${keyboardSavedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
							: ''}
				</p>
				<p class="form-error" role="alert">{keyboardError}</p>
			</div>
		</section>
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

	.identity {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--space-3) var(--space-5);
	}

	.who {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}

	.name {
		font-size: var(--fs-lead);
		font-weight: var(--fw-medium);
		overflow-wrap: anywhere;
	}

	.email {
		font-size: var(--fs-detail);
		color: var(--text-muted);
		overflow-wrap: anywhere;
	}

	.role {
		font-size: var(--fs-detail);
		color: var(--text-muted);
	}

	.group {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.group-title {
		font-size: var(--fs-body);
		font-weight: var(--fw-medium);
	}

	.hint {
		font-size: var(--fs-detail);
		color: var(--text-muted);
		max-width: 68ch;
	}

	.retention-form {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-3) var(--space-4);
		align-items: start;
	}

	.wide {
		grid-column: 1 / -1;
	}

	.with-unit {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.with-unit input {
		flex: 0 1 7rem;
	}

	.unit {
		font-size: var(--fs-meta);
		color: var(--text-muted);
	}

	.keyboard-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	@media (max-width: 640px) {
		.stage {
			padding: var(--space-4);
		}

		.section {
			padding: var(--space-4);
		}

		.retention-form {
			grid-template-columns: minmax(0, 1fr);
		}
	}
</style>
