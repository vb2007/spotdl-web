<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import { keepFocus } from '$lib/stores/confirm';
	import SubpageHeader from '$lib/components/SubpageHeader.svelte';
	import { helpOpen, shortcutsEnabled } from '$lib/keyboard/registry';
	import * as m from '$lib/paraglide/messages';
	import { errorText } from '$lib/i18n/errors';
	import { formatClock, formatNumber } from '$lib/i18n/format';
	import { applyLocale, locale } from '$lib/i18n/locale.svelte';
	import type { Locale } from '$lib/paraglide/runtime';
	import LanguageSwitch from '$lib/components/LanguageSwitch.svelte';
	import RichText from '$lib/components/RichText.svelte';

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
				error = errorText(err);
			});
	});

	async function onSubmit(event: SubmitEvent) {
		event.preventDefault();
		daysError = '';
		if (!neverArchive) {
			daysError =
				typeof days !== 'number' || !Number.isInteger(days) || days < 1 || days > MAX_DAYS
					? m.account_retention_days_invalid({ max: formatNumber(MAX_DAYS) })
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
			error = errorText(err);
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
			keyboardError = errorText(err);
		} finally {
			keyboardSaving = false;
		}
		await keepFocus(from);
	}

	// v46: the interface language, saved to the profile so it follows the user to every
	// device (and wins over the browser's language and any /login choice). Like the shortcut
	// switch it applies once the server has it; the page then re-renders in place.
	let languageSaving = $state(false);
	let languageError = $state('');
	let languageSavedAt = $state<Date | null>(null);

	async function setLanguage(next: Locale) {
		// Always sent, even for the language shown: until now it may only have been the
		// browser's, and saving it is what makes it follow the user.
		if (languageSaving) return;
		const from = document.activeElement instanceof HTMLElement ? document.activeElement : null;
		languageSaving = true;
		languageError = '';
		try {
			const saved = await api.updateLanguageSettings(next);
			if (saved.language) applyLocale(saved.language);
			languageSavedAt = new Date();
		} catch (err) {
			languageError = errorText(err);
		} finally {
			languageSaving = false;
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
				logoutError = errorText(err);
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
	<title>{m.account_title()}</title>
</svelte:head>

<div class="stage">
	<SubpageHeader current="account" {isAdmin} />

	<main id="main" class="main">
		<h1 class="page-title">{m.account_heading()}</h1>
		<section class="panel section" aria-labelledby="identity-heading">
			<h2 id="identity-heading" class="label">{m.account_signed_in()}</h2>
			<div class="identity">
				<div class="who">
					<!-- F31: the email is on the page, not only in a tooltip. -->
					<p class="name">{api.displayName(username, email)}</p>
					{#if username !== null}
						<p class="email mono">{email}</p>
					{/if}
					{#if isAdmin}
						<p class="role">{m.account_role_admin()}</p>
					{/if}
				</div>
				<button type="button" class="btn" disabled={loggingOut} onclick={onLogout}>
					{loggingOut ? m.account_disconnecting() : m.account_disconnect()}
				</button>
			</div>
			<p class="form-error" role="alert">{logoutError}</p>
		</section>

		<!-- Preferences: one group per setting. v45 added the keyboard-shortcut switch; v46 the
		     language switch, as a further group. -->
		<section class="panel section" aria-labelledby="preferences-heading">
			<h2 id="preferences-heading" class="label">{m.account_preferences()}</h2>

			<div class="group" role="group" aria-labelledby="retention-heading">
				<h3 id="retention-heading" class="group-title">{m.account_retention_heading()}</h3>
				<p class="hint">{m.account_retention_hint()}</p>

				{#if saved === null}
					{#if !error}<p class="hint">{m.account_retention_loading()}</p>{/if}
				{:else}
					<form class="retention-form" onsubmit={onSubmit} novalidate>
						<div class="form-field">
							<span class="label" id="retention-mode-label">{m.account_retention_mode()}</span>
							<div class="choice-group" role="group" aria-labelledby="retention-mode-label">
								<button
									type="button"
									aria-pressed={!neverArchive}
									disabled={saving}
									onclick={() => (neverArchive = false)}
								>
									{m.account_retention_auto()}
								</button>
								<button
									type="button"
									aria-pressed={neverArchive}
									disabled={saving}
									onclick={() => (neverArchive = true)}
								>
									{m.account_retention_never()}
								</button>
							</div>
						</div>

						<div class="form-field">
							<!-- F30: the accessible name is the visible label (WCAG 2.5.3). -->
							<label class="label" for="retention-days">{m.account_retention_after()}</label>
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
								<span class="unit mono" id="retention-days-unit">{m.account_retention_unit()}</span>
							</div>
							<p id="retention-days-error" class="field-error">{daysError}</p>
						</div>

						<div class="save-row wide">
							<button type="submit" class="btn" disabled={saving}>
								{saving ? m.common_saving() : m.common_save()}
							</button>
							<p class="save-state" class:saved={!dirty && savedAt} role="status">
								{dirty
									? m.common_unsaved_changes()
									: savedAt
										? m.common_saved_at({ time: formatClock(savedAt) })
										: ''}
							</p>
						</div>
					</form>
				{/if}
				<p class="form-error" role="alert">{error}</p>
			</div>

			<div class="group" role="group" aria-labelledby="keyboard-heading">
				<h3 id="keyboard-heading" class="group-title">{m.account_keyboard_heading()}</h3>
				<p class="hint" id="keyboard-hint"><RichText text={m.account_keyboard_hint()} /></p>
				<div class="form-field">
					<span class="label" id="keyboard-mode-label">{m.account_keyboard_mode()}</span>
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
								{m.account_keyboard_on()}
							</button>
							<button
								type="button"
								aria-pressed={!$shortcutsEnabled}
								disabled={keyboardSaving}
								onclick={() => setShortcuts(false)}
							>
								{m.account_keyboard_off()}
							</button>
						</div>
						<button type="button" class="btn" onclick={() => helpOpen.set(true)}
							>{m.account_keyboard_show()}</button
						>
					</div>
				</div>
				<p class="save-state" class:saved={keyboardSavedAt !== null} role="status">
					{keyboardSaving
						? m.common_saving_status()
						: keyboardSavedAt
							? m.common_saved_at({ time: formatClock(keyboardSavedAt) })
							: ''}
				</p>
				<p class="form-error" role="alert">{keyboardError}</p>
			</div>

			<div class="group" role="group" aria-labelledby="language-heading">
				<h3 id="language-heading" class="group-title">{m.account_language_heading()}</h3>
				<p class="hint" id="language-hint">{m.account_language_hint()}</p>
				<div class="form-field">
					<span class="label" id="language-mode-label">{m.account_language_label()}</span>
					<LanguageSwitch
						current={locale.current}
						onchoose={setLanguage}
						disabled={languageSaving}
						labelledby="language-mode-label"
						describedby="language-hint"
					/>
				</div>
				<p class="save-state" class:saved={languageSavedAt !== null} role="status">
					{languageSaving
						? m.common_saving_status()
						: languageSavedAt
							? m.common_saved_at({ time: formatClock(languageSavedAt) })
							: ''}
				</p>
				<p class="form-error" role="alert">{languageError}</p>
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
