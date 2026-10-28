<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { beforeNavigate, goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import { keepFocus, keepFocusOnHeading } from '$lib/stores/confirm';
	import SubpageHeader from '$lib/components/SubpageHeader.svelte';
	import { helpOpen, shortcutsEnabled } from '$lib/keyboard/registry';
	import * as m from '$lib/paraglide/messages';
	import { errorText } from '$lib/i18n/errors';
	import { clockExample, formatClock, formatNumber } from '$lib/i18n/format';
	import {
		applyClock,
		applyLanguagePreference,
		clockPreference,
		detectLocale,
		languagePreference,
		type Clock
	} from '$lib/i18n/locale.svelte';
	import type { Locale } from '$lib/paraglide/runtime';
	import LanguageSwitch from '$lib/components/LanguageSwitch.svelte';
	import RichText from '$lib/components/RichText.svelte';
	import ApiKeys from '$lib/components/ApiKeys.svelte';
	import { guardUnsavedEdits } from '$lib/unsavedGuard';
	import { leavingSession, setLeavingSession } from '$lib/session';

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
	// v46: errors are kept as the message to render, not its text, so a language switch on this
	// page re-renders a standing error in the new language like everything around it.
	type Shown = (() => string) | null;
	let error = $state<Shown>(null);
	let daysError = $state<Shown>(null);
	// A hundred years. The backend takes any positive number, but the hourly retention sweep
	// computes now - days, which overflows past year 1 and stops it for every user (found,
	// not fixed in the backend: v48).
	const MAX_DAYS = 36_500;
	let loggingOut = $state(false);
	let logoutError = $state<Shown>(null);

	// The mode and the number both count: switching to "automatically" with the days field
	// cleared is a change even though no number is there yet.
	const dirty = $derived(
		saved !== null &&
			(neverArchive !== (saved.retention_days === null) ||
				(!neverArchive && days !== saved.retention_days))
	);

	// v62 (F6): with every preference saved on choice (F7), only a typed value not yet
	// committed is unsaved: retention's days, or a key's name not yet created.
	let keyNameTyped = $state(false);
	// A choice already being saved isn't unsaved (review round 3). Within the app, a valid number
	// typed and not yet committed is committed on the way out (leaving the field does that
	// anyway, and the guard's own question would: live review), so only what can't be saved is
	// asked about: an invalid value, a choice whose save failed (review round 6), a key name.
	// An unloading page can't finish a save (the request dies with it), so there anything not
	// saved is asked about (review round 6).
	const retentionSaveable = () => error === null && (neverArchive || !daysInvalid());
	guardUnsavedEdits(
		(unloading) => (dirty && !saving && (unloading || !retentionSaveable())) || keyNameTyped
	);
	beforeNavigate((navigation) => {
		if (navigation.willUnload || leavingSession()) return;
		if (dirty && !saving && retentionSaveable()) saveRetention(false);
	});

	function syncForm(settings: api.RetentionSettings) {
		saved = settings;
		neverArchive = settings.retention_days === null;
		if (settings.retention_days !== null) days = settings.retention_days;
	}

	// v47: a failed first read says what failed and can be retried here (it took a reload).
	let loadError = $state<Shown>(null);
	function loadRetention() {
		loadError = null;
		api
			.getRetentionSettings()
			.then(syncForm)
			.catch((err) => {
				loadError = () => m.account_retention_load_failed({ error: errorText(err) });
			});
	}

	onMount(loadRetention);

	function retryRetention() {
		loadRetention();
		keepFocusOnHeading('retention-heading');
	}

	// v62 (F7): one save model on /account (owner's decision): a preference is saved the moment
	// it's chosen, as the shortcut, language and time-format switches always were. Retention's
	// mode saves on its press; the number of days when it's committed (Enter, or leaving the
	// field), checked first. Nothing is held for a save button, so "Unsaved changes" now means
	// only a number typed and not yet committed (or one that failed its check).
	function daysInvalid(): boolean {
		return typeof days !== 'number' || !Number.isInteger(days) || days < 1 || days > MAX_DAYS;
	}

	async function showDaysError(refocus: boolean) {
		daysError = () => m.account_retention_days_invalid({ max: formatNumber(MAX_DAYS) });
		// A commit on leaving the field (blur) keeps focus where the user took it (review round
		// 4); the field's error is on it for when they come back.
		if (!refocus) return;
		// Nothing is sent, so focus the field: its error is read out from there.
		await tick();
		const field = document.getElementById('retention-days');
		// Already focused: leave and come back so its new error is read.
		if (field === document.activeElement) field?.blur();
		field?.focus();
	}

	// A choice made while a save is under way (the days field's commit on blur runs as the
	// mode button is pressed): saved right after it, never dropped (review round 2).
	let saveAgain = false;

	async function saveRetention(refocus = true) {
		daysError = null;
		if (saving) {
			saveAgain = true;
			return;
		}
		if (!dirty) return;
		if (!neverArchive && daysInvalid()) return showDaysError(refocus);
		// Saving disables the field or button that had focus: give it back afterwards.
		const from = document.activeElement instanceof HTMLElement ? document.activeElement : null;
		saving = true;
		error = null;
		// v42's late-write guard: a sign-out meanwhile resets the store.
		const resets = queue.getResetCount();
		try {
			const settings = await api.updateRetentionSettings(neverArchive ? null : days);
			if (queue.getResetCount() !== resets) {
				saveAgain = false;
				return;
			}
			// A choice made meanwhile is saved next: the form keeps it, only what's saved moves
			// (review round 3: syncForm put the older answer back over it).
			if (saveAgain) saved = settings;
			else syncForm(settings);
			savedAt = new Date();
		} catch (err) {
			error = () => errorText(err);
		} finally {
			saving = false;
		}
		await keepFocus(from);
		if (saveAgain) {
			saveAgain = false;
			// v42's late-write guard for the queued choice too (review round 4): a sign-out or
			// another identity meanwhile means it isn't this session's to send.
			if (queue.getResetCount() === resets) await saveRetention();
		}
	}

	function chooseMode(never: boolean) {
		neverArchive = never;
		saveRetention();
	}

	// Enter in the field: the form's only submit, with no button of its own.
	function onSubmit(event: SubmitEvent) {
		event.preventDefault();
		saveRetention();
	}

	// v45: the single-key shortcut switch (WCAG 2.1.4), stored per user server-side so it
	// follows them to every device. It applies the moment the server has it; another device
	// picks it up from /api/auth/me on its next load.
	let keyboardSaving = $state(false);
	let keyboardError = $state<Shown>(null);
	let keyboardSavedAt = $state<Date | null>(null);

	async function setShortcuts(enabled: boolean) {
		// Always sent, even for the choice shown as pressed: another device may have changed
		// it since this page read it (the PATCH is idempotent).
		if (keyboardSaving) return;
		const from = document.activeElement instanceof HTMLElement ? document.activeElement : null;
		keyboardSaving = true;
		keyboardError = null;
		try {
			const saved = await api.updateKeyboardSettings(enabled);
			shortcutsEnabled.set(saved.keyboard_shortcuts);
			keyboardSavedAt = new Date();
		} catch (err) {
			keyboardError = () => errorText(err);
		} finally {
			keyboardSaving = false;
		}
		await keepFocus(from);
	}

	// v46: the interface language, saved to the profile so it follows the user to every
	// device (and, once signed in, wins over the browser's language). Like the shortcut
	// switch it applies once the server has it; the page then re-renders in place.
	let languageSaving = $state(false);
	let languageError = $state<Shown>(null);
	let languageSavedAt = $state<Date | null>(null);

	async function setLanguage(next: Locale | null) {
		// Always sent, even for the choice shown as pressed: another device may have changed it
		// since this page read it (the PATCH is idempotent). `null` is automatic.
		if (languageSaving) return;
		const from = document.activeElement instanceof HTMLElement ? document.activeElement : null;
		languageSaving = true;
		languageError = null;
		// A sign-out (or another identity) while the save is in flight resets the store; the
		// late answer must not then set the signed-out page's language (v42's late-write guard).
		const resets = queue.getResetCount();
		try {
			const saved = await api.updateLanguageSettings(next);
			if (queue.getResetCount() !== resets) return;
			applyLanguagePreference(saved.language);
			languageSavedAt = new Date();
		} catch (err) {
			languageError = () => errorText(err);
		} finally {
			languageSaving = false;
		}
		await keepFocus(from);
	}

	// v46 (owner's rule, PR #68): the time format, by the language's rules: automatic (the
	// browser's region) until pinned here, saved to the profile, applied once the server has it.
	let clockSaving = $state(false);
	let clockError = $state<Shown>(null);
	let clockSavedAt = $state<Date | null>(null);
	// The examples read the minute this page shows, ticking so they stay true.
	let now = $state(new Date());
	$effect(() => {
		const id = setInterval(() => (now = new Date()), 30_000);
		return () => clearInterval(id);
	});
	const CLOCK_CHOICES: { value: Clock | null; label: (example: string) => string }[] = [
		{ value: null, label: (example) => m.account_clock_auto({ example }) },
		{ value: '12h', label: (example) => m.account_clock_12h({ example }) },
		{ value: '24h', label: (example) => m.account_clock_24h({ example }) }
	];

	async function setClock(next: Clock | null) {
		if (clockSaving) return;
		const from = document.activeElement instanceof HTMLElement ? document.activeElement : null;
		clockSaving = true;
		clockError = null;
		const resets = queue.getResetCount();
		try {
			const saved = await api.updateClockSettings(next);
			if (queue.getResetCount() !== resets) return;
			applyClock(saved.clock);
			clockSavedAt = new Date();
		} catch (err) {
			clockError = () => errorText(err);
		} finally {
			clockSaving = false;
		}
		await keepFocus(from);
	}

	// v43 (F31): the account page could not sign out; it now does, the way `/` does.
	async function onLogout() {
		loggingOut = true;
		logoutError = null;
		try {
			await api.logout();
		} catch (err) {
			// A 401 means the session is already gone: that's signed out, not a failure.
			if (!(err instanceof api.ApiError && err.status === 401)) {
				logoutError = () => errorText(err);
				loggingOut = false;
				return;
			}
		}
		// The module-level queue store outlives this navigation; clear it before leaving so
		// the next identity on this tab never sees a flash of these rows.
		queue.reset();
		// v62 (F6): the session is gone, so nothing unsaved here can be saved: never held.
		setLeavingSession(true);
		try {
			await goto(resolve('/login'));
		} finally {
			setLeavingSession(false);
		}
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
			<p class="form-error" role="alert">{logoutError?.()}</p>
		</section>

		<!-- Preferences: one group per setting. v45 added the keyboard-shortcut switch; v46 the
		     language switch and the time format, as further groups. -->
		<section class="panel section" aria-labelledby="preferences-heading">
			<h2 id="preferences-heading" class="label">{m.account_preferences()}</h2>

			<div class="group" role="group" aria-labelledby="retention-heading">
				<h3 id="retention-heading" class="group-title">{m.account_retention_heading()}</h3>
				<p class="hint">{m.account_retention_hint()}</p>

				{#if saved === null}
					{#if loadError}
						<!-- Announced by the always-present error line below, not as an inserted alert. -->
						<div class="load-failed">
							<p>{loadError()}</p>
							<button type="button" class="btn small" onclick={retryRetention}
								>{m.account_retention_try_again()}</button
							>
						</div>
					{:else}
						<p class="hint">{m.account_retention_loading()}</p>
					{/if}
				{:else}
					<form class="retention-form" onsubmit={onSubmit} novalidate>
						<div class="form-field">
							<span class="label" id="retention-mode-label">{m.account_retention_mode()}</span>
							<div class="choice-group" role="group" aria-labelledby="retention-mode-label">
								<button
									type="button"
									aria-pressed={!neverArchive}
									onclick={() => chooseMode(false)}
								>
									{m.account_retention_auto()}
								</button>
								<button type="button" aria-pressed={neverArchive} onclick={() => chooseMode(true)}>
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
									onchange={() => saveRetention(false)}
									disabled={saving || neverArchive}
									aria-invalid={daysError ? 'true' : undefined}
									aria-describedby="retention-days-unit retention-days-hint retention-days-error"
								/>
								<span class="unit" id="retention-days-unit">{m.account_retention_unit()}</span>
							</div>
							<p class="field-hint" id="retention-days-hint">{m.account_retention_days_hint()}</p>
							<p id="retention-days-error" class="field-error">{daysError?.()}</p>
						</div>
					</form>
					<p class="save-state" class:saved={!saving && !dirty && savedAt !== null} role="status">
						{saving
							? m.common_saving_status()
							: dirty
								? m.common_unsaved_changes()
								: savedAt
									? m.common_saved_at({ time: formatClock(savedAt) })
									: ''}
					</p>
				{/if}
				<p class="form-error" class:sr-only={saved === null && loadError !== null} role="alert">
					{saved === null && loadError !== null ? loadError() : error?.()}
				</p>
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
				<p class="form-error" role="alert">{keyboardError?.()}</p>
			</div>

			<div class="group" role="group" aria-labelledby="language-heading">
				<h3 id="language-heading" class="group-title">{m.account_language_heading()}</h3>
				<p class="hint" id="language-hint">{m.account_language_hint()}</p>
				<div class="form-field">
					<span class="label" id="language-mode-label">{m.account_language_label()}</span>
					<LanguageSwitch
						preference={languagePreference.current}
						detected={detectLocale()}
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
				<p class="form-error" role="alert">{languageError?.()}</p>
			</div>

			<div class="group" role="group" aria-labelledby="clock-heading">
				<h3 id="clock-heading" class="group-title">{m.account_clock_heading()}</h3>
				<p class="hint" id="clock-hint">{m.account_clock_hint()}</p>
				<div class="form-field">
					<span class="label" id="clock-mode-label">{m.account_clock_label()}</span>
					<div
						class="choice-group clock-choice"
						role="group"
						aria-labelledby="clock-mode-label"
						aria-describedby="clock-hint"
					>
						{#each CLOCK_CHOICES as choice (choice.value)}
							<button
								type="button"
								aria-pressed={clockPreference.current === choice.value}
								disabled={clockSaving}
								onclick={() => setClock(choice.value)}
								>{choice.label(clockExample(now, choice.value))}</button
							>
						{/each}
					</div>
				</div>
				<p class="save-state" class:saved={clockSavedAt !== null} role="status">
					{clockSaving
						? m.common_saving_status()
						: clockSavedAt
							? m.common_saved_at({ time: formatClock(clockSavedAt) })
							: ''}
				</p>
				<p class="form-error" role="alert">{clockError?.()}</p>
			</div>
		</section>

		<!-- v53: keys for the browser extension (create, list, revoke). -->
		<ApiKeys onnametyped={(typed) => (keyNameTyped = typed)} />
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

	/* v47: the groups read apart from one another: a rule and more air between them than
	   inside one (they ran together at about the same 12px). */
	.group + .group {
		margin-top: var(--space-2);
		padding-top: var(--space-4);
		border-top: 1px solid var(--line);
	}

	.group-title {
		font-size: var(--fs-body);
		font-weight: var(--fw-medium);
	}

	.load-failed {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
		font-size: var(--fs-detail);
		color: var(--fail);
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

	@media (max-width: 40em) {
		.stage {
			padding: var(--space-4);
		}

		.section {
			padding: var(--space-4);
		}

		.retention-form {
			grid-template-columns: minmax(0, 1fr);
		}

		/* v46: three options with their examples don't fit a phone row (Hungarian least of
		   all), and a wrapped segmented control breaks its own edges: stack them instead. */
		.clock-choice {
			flex-direction: column;
			align-self: stretch;
		}

		.clock-choice button {
			text-align: left;
		}

		.clock-choice button + button {
			border-left: none;
			border-top: 1px solid var(--line-control);
		}

		.clock-choice button:first-child {
			border-radius: 3px 3px 0 0;
		}

		.clock-choice button:last-child {
			border-radius: 0 0 3px 3px;
		}
	}
</style>
