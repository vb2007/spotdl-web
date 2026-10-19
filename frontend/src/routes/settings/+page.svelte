<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import { confirmAction, keepFocus, keepFocusOnHeading } from '$lib/stores/confirm';
	import Countdown from '$lib/components/Countdown.svelte';
	import WorkerStatus from '$lib/components/WorkerStatus.svelte';
	import SubpageHeader from '$lib/components/SubpageHeader.svelte';
	import AdminOnlyNotice from '$lib/components/AdminOnlyNotice.svelte';
	import * as m from '$lib/paraglide/messages';
	import { errorText } from '$lib/i18n/errors';
	import { counted, formatClock, formatDateTime, formatNumber } from '$lib/i18n/format';

	let { data } = $props();
	const isAdmin = $derived(data.session?.is_admin ?? false);

	// v43 (F19): one page, five sections, and an in-page index (anchors, no sub-routes, so
	// no nginx change). Each section saves on its own: they are separate endpoints.
	// v46: labels are message functions, called at render time, so a language switch reaches
	// them (a string built here once would stay in the language it was built in).
	const SECTIONS = [
		{ id: 'worker', label: m.settings_section_worker },
		{ id: 'output', label: m.settings_section_output },
		{ id: 'library', label: m.settings_section_library },
		{ id: 'alerts', label: m.settings_section_alerts },
		{ id: 'proxies', label: m.settings_section_proxies }
	] as const;
	let activeSection = $state<string>('worker');

	// v46: a sentence with inline <code> fragments (env names, file names, templates). The
	// message marks each with a named placeholder; each is filled with its own numbered
	// sentinel and split back out here, so a translation can put them in any order and the
	// fragments themselves (machine names) stay as they are.
	type CodePart = { text: string; code: boolean };
	function withCode<K extends string>(
		message: (slots: Record<K, string>) => string,
		codes: Record<K, string>
	): CodePart[] {
		const names = Object.keys(codes) as K[];
		const slots = Object.fromEntries(names.map((name, i) => [name, `\uE000${i}\uE000`]));
		return message(slots as Record<K, string>)
			.split(/\uE000(\d+)\uE000/)
			.map((piece, i) =>
				i % 2 ? { text: codes[names[Number(piece)]], code: true } : { text: piece, code: false }
			)
			.filter((part) => part.text !== '');
	}

	// The fragments are machine names and formats, shown as they are in every language.
	const TEMPLATE_PLACEHOLDER = '{placeholder}';
	const TEMPLATE_EXAMPLE = '{artists} - {title}.{output-ext}';
	const PROXIES_FILE = 'proxies.txt';

	const templateHint = $derived(
		withCode(m.settings_output_template_hint, { placeholder: TEMPLATE_PLACEHOLDER })
	);
	const libraryHint = $derived(
		withCode(m.settings_library_hint, { link: m.settings_library_hint_link() })
	);
	const alertsOffHint = $derived(
		withCode(m.settings_alerts_off_hint, {
			homeserver: 'MATRIX_HOMESERVER_URL',
			token: 'MATRIX_ACCESS_TOKEN',
			room: 'MATRIX_ROOM_ID',
			env: '.env'
		})
	);
	const proxiesHint = $derived(withCode(m.settings_proxies_hint, { file: PROXIES_FILE }));
	const proxyFormatHint = $derived(
		withCode(m.settings_proxy_add_hint, { format: m.settings_proxy_format() })
	);

	// A failed check sends nothing, so nothing else would tell a screen reader: focus moves to
	// the first invalid field, whose error its aria-describedby then reads out.
	async function focusInvalid(id: string | undefined) {
		if (id === undefined) return;
		await tick();
		const field = document.getElementById(id);
		// Already focused (Enter pressed in it): focus() alone announces nothing, so leave and
		// come back, and the field is read again with its new error.
		if (field === document.activeElement) field?.blur();
		field?.focus();
	}

	// A save disables the control that had focus (its button, or the field Enter was pressed
	// in), which drops focus to <body>; it goes back there once the save is done.
	function focused(): HTMLElement | null {
		return document.activeElement instanceof HTMLElement ? document.activeElement : null;
	}

	// The add-proxy error is its own alert, so a field that already has focus needs nothing
	// more; a press of "add proxy" moves focus back to the field to fix.
	function focusUnlessFocused(id: string) {
		const field = document.getElementById(id);
		if (field && field !== document.activeElement) field.focus();
	}

	// --- Output defaults ---------------------------------------------------------------

	let outputSettings = $state<api.OutputSettings | null>(null);
	let outputOptions = $state<api.OutputOptions | null>(null);
	let outputForm = $state<api.EditableOutputSettings>({
		default_format: '',
		default_bitrate: '',
		output_template: ''
	});
	let outputSaving = $state(false);
	let outputSavedAt = $state<Date | null>(null);
	let outputError = $state('');
	let outputTemplateError = $state('');

	const outputDirty = $derived(
		outputSettings !== null &&
			(outputForm.default_format !== outputSettings.default_format ||
				outputForm.default_bitrate !== outputSettings.default_bitrate ||
				outputForm.output_template !== outputSettings.output_template)
	);

	function syncOutputForm(settings: api.OutputSettings) {
		outputForm = {
			default_format: settings.default_format,
			default_bitrate: settings.default_bitrate,
			output_template: settings.output_template
		};
	}

	// v47: a section whose first read failed says so in one sentence, with its own retry
	// (it took a reload before), and the save line below stays for save errors.
	function readOutput() {
		outputError = '';
		loadOutputSettings().catch((err) => (outputError = errorText(err)));
	}

	function readLibrary() {
		libraryError = '';
		loadLibrarySettings().catch((err) => (libraryError = errorText(err)));
	}

	function readAlerts() {
		alertError = '';
		loadAlertSettings().catch((err) => (alertError = errorText(err)));
	}

	// A retry button goes with its block: focus lands on the section's heading (v47).
	function retryOutput() {
		readOutput();
		keepFocusOnHeading('output-heading');
	}

	function retryLibrary() {
		readLibrary();
		keepFocusOnHeading('library-heading');
	}

	function retryAlerts() {
		readAlerts();
		keepFocusOnHeading('alerts-heading');
	}

	async function loadOutputSettings() {
		[outputSettings, outputOptions] = await Promise.all([
			api.getOutputSettings(),
			api.getOutputOptions()
		]);
		syncOutputForm(outputSettings);
	}

	async function onOutputSubmit(event: SubmitEvent) {
		event.preventDefault();
		// The backend accepts a blank template; spotdl would then write files with no name.
		outputTemplateError = outputForm.output_template.trim()
			? ''
			: m.settings_output_template_required({ example: TEMPLATE_EXAMPLE });
		if (outputTemplateError) return focusInvalid('output-template');
		const from = focused();
		outputSaving = true;
		outputError = '';
		try {
			outputSettings = await api.updateOutputSettings(outputForm);
			syncOutputForm(outputSettings);
			outputSavedAt = new Date();
		} catch (err) {
			outputError = errorText(err);
		} finally {
			outputSaving = false;
		}
		await keepFocus(from);
	}

	// --- Library sort & move -----------------------------------------------------------

	let librarySettings = $state<api.LibrarySettings | null>(null);
	let libraryForm = $state<api.EditableLibrarySettings>({
		library_target_dir: '',
		library_folder_template: '',
		library_quarantine_enabled: true,
		library_quarantine_dir: ''
	});
	let librarySaving = $state(false);
	let librarySavedAt = $state<Date | null>(null);
	let libraryError = $state('');
	let libraryFieldErrors = $state<Record<string, string>>({});

	const LIBRARY_TEXT_FIELDS = [
		{ key: 'library_target_dir', label: m.settings_library_target_dir },
		{ key: 'library_folder_template', label: m.settings_library_folder_template },
		{ key: 'library_quarantine_dir', label: m.settings_library_quarantine_dir }
	] as const;

	const libraryDirty = $derived(
		librarySettings !== null &&
			(Object.keys(libraryForm) as (keyof api.EditableLibrarySettings)[]).some(
				(key) => libraryForm[key] !== librarySettings?.[key]
			)
	);

	async function loadLibrarySettings() {
		librarySettings = await api.getLibrarySettings();
		libraryForm = { ...librarySettings };
	}

	async function onLibrarySubmit(event: SubmitEvent) {
		event.preventDefault();
		const errors: Record<string, string> = {};
		for (const { key, label } of LIBRARY_TEXT_FIELDS) {
			if (!libraryForm[key].trim())
				errors[key] = m.settings_library_field_empty({ field: label() });
		}
		libraryFieldErrors = errors;
		if (Object.keys(errors).length > 0) return focusInvalid(Object.keys(errors)[0]);
		const from = focused();
		librarySaving = true;
		libraryError = '';
		try {
			librarySettings = await api.updateLibrarySettings(libraryForm);
			libraryForm = { ...librarySettings };
			librarySavedAt = new Date();
		} catch (err) {
			libraryError = errorText(err);
		} finally {
			librarySaving = false;
		}
		await keepFocus(from);
	}

	// --- Alerts ------------------------------------------------------------------------

	let alertSettings = $state<api.AlertSettings | null>(null);
	let alertForm = $state<api.EditableAlertSettings>({
		alerts_breaker_enabled: true,
		alerts_spike_enabled: true,
		alerts_beat_stale_enabled: true,
		alerts_library_enabled: true,
		alert_spike_threshold: 5,
		alert_spike_window_minutes: 60,
		alert_beat_stale_seconds: 180,
		alert_cooldown_minutes: 60
	});
	let alertSaving = $state(false);
	let alertSavedAt = $state<Date | null>(null);
	let alertError = $state('');
	let alertFieldErrors = $state<Record<string, string>>({});
	let alertTesting = $state(false);
	let alertTestResult = $state('');

	type AlertToggleKey =
		| 'alerts_breaker_enabled'
		| 'alerts_spike_enabled'
		| 'alerts_beat_stale_enabled'
		| 'alerts_library_enabled';
	type AlertNumberKey =
		| 'alert_spike_threshold'
		| 'alert_spike_window_minutes'
		| 'alert_beat_stale_seconds'
		| 'alert_cooldown_minutes';

	// v43 (F19): what each category reports, so fourteen controls read as two short groups.
	const ALERT_TOGGLES: { key: AlertToggleKey; label: () => string; hint: () => string }[] = [
		{
			key: 'alerts_breaker_enabled',
			label: m.settings_alert_breaker,
			hint: m.settings_alert_breaker_hint
		},
		{
			key: 'alerts_spike_enabled',
			label: m.settings_alert_spike,
			hint: m.settings_alert_spike_hint
		},
		{
			key: 'alerts_beat_stale_enabled',
			label: m.settings_alert_beat_stale,
			hint: m.settings_alert_beat_stale_hint
		},
		{
			key: 'alerts_library_enabled',
			label: m.settings_alert_library,
			hint: m.settings_alert_library_hint
		}
	];

	// Mirrors the backend's _ALERT_BOUNDS (routers/settings.py), for an inline answer before
	// the request; the backend stays the real check.
	const ALERT_NUMBERS: {
		key: AlertNumberKey;
		label: () => string;
		unit: () => string;
		min: number;
		max: number;
	}[] = [
		{
			key: 'alert_spike_threshold',
			label: m.settings_alert_spike_threshold,
			unit: m.settings_alert_spike_threshold_unit,
			min: 2,
			max: 1000
		},
		{
			key: 'alert_spike_window_minutes',
			label: m.settings_alert_spike_window,
			unit: m.settings_alert_spike_window_unit,
			min: 1,
			max: 7 * 24 * 60
		},
		{
			key: 'alert_beat_stale_seconds',
			label: m.settings_alert_beat_stale_after,
			unit: m.settings_alert_beat_stale_unit,
			min: 90,
			max: 7 * 24 * 3600
		},
		{
			key: 'alert_cooldown_minutes',
			label: m.settings_alert_cooldown,
			unit: m.settings_alert_cooldown_unit,
			min: 1,
			max: 7 * 24 * 60
		}
	];

	const alertDirty = $derived(
		alertSettings !== null &&
			(Object.keys(alertForm) as (keyof api.EditableAlertSettings)[]).some(
				(key) => alertForm[key] !== alertSettings?.[key]
			)
	);

	function syncAlertForm(settings: api.AlertSettings) {
		const { configured: _configured, ...editable } = settings;
		alertForm = editable;
	}

	async function loadAlertSettings() {
		alertSettings = await api.getAlertSettings();
		syncAlertForm(alertSettings);
	}

	async function onAlertSubmit(event: SubmitEvent) {
		event.preventDefault();
		// A cleared number input binds to null, which the API reads as "unchanged".
		const errors: Record<string, string> = {};
		for (const { key, min, max } of ALERT_NUMBERS) {
			const value = alertForm[key];
			if (typeof value !== 'number' || Number.isNaN(value)) {
				errors[key] = m.settings_alert_number_required();
			} else if (!Number.isInteger(value) || value < min || value > max) {
				errors[key] = m.settings_alert_number_range({
					min: formatNumber(min),
					max: formatNumber(max)
				});
			}
		}
		alertFieldErrors = errors;
		if (Object.keys(errors).length > 0) return focusInvalid(Object.keys(errors)[0]);
		const from = focused();
		alertSaving = true;
		alertError = '';
		alertTestResult = '';
		try {
			alertSettings = await api.updateAlertSettings(alertForm);
			syncAlertForm(alertSettings);
			alertSavedAt = new Date();
		} catch (err) {
			alertError = errorText(err);
		} finally {
			alertSaving = false;
		}
		await keepFocus(from);
	}

	async function onTestAlert() {
		const from = focused();
		alertTesting = true;
		alertTestResult = '';
		alertError = '';
		try {
			await api.sendTestAlert();
			alertTestResult = m.settings_alerts_test_sent();
		} catch (err) {
			alertError = errorText(err);
		} finally {
			alertTesting = false;
		}
		await keepFocus(from);
	}

	// --- Proxy pool --------------------------------------------------------------------

	let proxyList = $state<api.Proxy[]>([]);
	let proxiesLoading = $state(true);
	let proxiesError = $state('');
	// The initial read's failure, apart from an action's: a later successful poll clears it.
	let proxiesLoadError = $state('');
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

	async function loadProxies() {
		proxiesLoading = true;
		proxiesLoadError = '';
		try {
			proxyList = await api.listProxies();
		} catch (err) {
			proxiesLoadError = errorText(err);
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
	let proxyMutations = 0;
	async function refreshProxiesSilently() {
		// Skip a tick while a toggle/remove/add is in flight -- a poll landing mid-request
		// must not visually clobber that row before the user's own action resolves.
		if (addingProxy || Object.keys(proxyBusy).length > 0) return;
		// ...nor may a poll that *started* before one land after it (a removed proxy would come
		// back for a tick).
		const before = proxyMutations;
		try {
			const list = await api.listProxies();
			if (proxyMutations === before) proxyList = list;
			proxiesLoadError = '';
		} catch {
			// A transient poll failure isn't worth surfacing as a page-level error --
			// loadProxies()'s own error path already covers the initial-load case.
		}
	}

	async function onAddProxy(event: SubmitEvent) {
		event.preventDefault();
		const url = newProxyUrl.trim();
		if (!url) {
			addProxyError = m.settings_proxy_add_empty();
			return focusUnlessFocused('new-proxy');
		}
		if (!PROXY_URL_RE.test(url)) {
			addProxyError = m.settings_proxy_add_invalid({ format: m.settings_proxy_format() });
			return focusUnlessFocused('new-proxy');
		}
		const from = focused();
		addingProxy = true;
		proxyMutations += 1;
		addProxyError = '';
		try {
			const proxy = await api.createProxy(url);
			proxyList = [...proxyList, proxy];
			newProxyUrl = '';
		} catch (err) {
			addProxyError = errorText(err, m.settings_proxy_add_failed);
		} finally {
			addingProxy = false;
		}
		await keepFocus(from);
	}

	async function toggleProxy(proxy: api.Proxy) {
		const from = focused();
		proxyBusy = { ...proxyBusy, [proxy.id]: true };
		proxyMutations += 1;
		proxiesError = '';
		try {
			const updated = await api.setProxyEnabled(proxy.id, !proxy.enabled);
			proxyList = proxyList.map((p) => (p.id === updated.id ? updated : p));
		} catch (err) {
			proxiesError = errorText(err);
		} finally {
			const { [proxy.id]: _unused, ...rest } = proxyBusy;
			proxyBusy = rest;
		}
		await keepFocus(from);
	}

	async function removeProxy(proxy: api.Proxy) {
		// Only ever called for source=manual -- the "remove" control isn't rendered for
		// source=file rows at all (see markup below). A real, permanent delete: the row
		// disappears from the list rather than being merged back in updated.
		// v43 (F08): permanent, so it asks first.
		const confirmed = await confirmAction({
			title: m.settings_proxy_remove_title(),
			subject: proxy.url,
			subjectIsAddress: true,
			body: m.settings_proxy_remove_body(),
			confirmLabel: m.settings_proxy_remove_confirm(),
			cancelLabel: m.settings_proxy_remove_cancel()
		});
		// Gone meanwhile (removed in another tab): nothing to remove.
		// Kept, Esc, or gone meanwhile (removed elsewhere): its row may have left, so focus
		// falls back to the list's heading.
		if (!confirmed || !proxyList.some((p) => p.id === proxy.id)) {
			return keepFocus(document.getElementById('proxies-heading'));
		}
		proxyBusy = { ...proxyBusy, [proxy.id]: true };
		proxyMutations += 1;
		proxiesError = '';
		try {
			await api.deleteProxy(proxy.id);
			proxyList = proxyList.filter((p) => p.id !== proxy.id);
			// The row (and the focused button) is gone: land on the list's own heading, unless
			// the user already moved on while the delete was in flight.
			await keepFocus(document.getElementById('proxies-heading'));
		} catch (err) {
			// A manual proxy that some attempt has used can't be hard-deleted: the attempt
			// history still references it and the backend answers 500 (a known backend limit,
			// not something to retry).
			proxiesError =
				err instanceof api.ApiError && err.status === 500
					? m.settings_proxy_remove_failed({ url: proxy.url })
					: errorText(err);
		} finally {
			const { [proxy.id]: _unused, ...rest } = proxyBusy;
			proxyBusy = rest;
		}
		// A failed removal disabled the focused button for the request: put focus back on it,
		// or on the list's heading.
		await keepFocus(
			// i18n-ignore: a selector
			document.querySelector<HTMLElement>(`#proxies button[data-remove="${proxy.id}"]`) ??
				document.getElementById('proxies-heading')
		);
	}

	function formatTimestamp(value: string): string {
		return formatDateTime(value, { dateStyle: 'short', timeStyle: 'short' });
	}

	function isFuture(value: string | null): boolean {
		return value != null && new Date(value).getTime() > Date.now();
	}

	onMount(() => {
		// A non-admin gets the notice and nothing else: no admin request is ever made (F17).
		if (!isAdmin) return;
		readOutput();
		readLibrary();
		readAlerts();
		loadProxies();
		const poll = setInterval(refreshProxiesSilently, PROXY_POLL_MS);

		// The index marks the section being read: the last one whose top has passed a line a
		// third of the way down the viewport, or the last section once the page can't scroll
		// further (a short final section never reaches the line). One read per frame at most.
		let frame = 0;
		const mark = () => {
			frame = 0;
			// v47: at most 10rem down, so a tall window doesn't mark the next section while the
			// first is still the one on screen.
			const line = Math.min(window.innerHeight / 3, 160);
			const atEnd =
				window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
			let current: string = SECTIONS[0].id;
			for (const { id } of SECTIONS) {
				const el = document.getElementById(id);
				if (el && el.getBoundingClientRect().top <= line) current = id;
			}
			// v47: at the top of the page the first section is the one being read, even when the
			// next one's top already sits above the line (a 900px-tall window marked Output).
			activeSection =
				window.scrollY < 8 ? SECTIONS[0].id : atEnd ? SECTIONS[SECTIONS.length - 1].id : current;
		};
		const onScroll = () => {
			if (!frame) frame = requestAnimationFrame(mark);
		};
		window.addEventListener('scroll', onScroll, { passive: true });
		window.addEventListener('resize', onScroll, { passive: true });
		mark();

		return () => {
			clearInterval(poll);
			cancelAnimationFrame(frame);
			window.removeEventListener('scroll', onScroll);
			window.removeEventListener('resize', onScroll);
		};
	});
</script>

<!-- v46: a sentence whose machine names (env vars, files, formats) stay code. -->
<!-- v47: one shape for a section whose first read failed: what, why, and a retry. -->
{#snippet loadFailed(error: string, retry: () => void)}
	<!-- Not an alert itself: the section's always-present error line announces it (an alert
	     inserted together with its text often isn't). -->
	<div class="load-failed">
		<p>{m.settings_section_load_failed({ error })}</p>
		<button type="button" class="btn small" onclick={retry}>{m.settings_proxies_try_again()}</button
		>
	</div>
{/snippet}

{#snippet coded(parts: CodePart[])}{#each parts as part, i (i)}{#if part.code}<code
				>{part.text}</code
			>{:else}{part.text}{/if}{/each}{/snippet}

<svelte:head>
	<title>{m.settings_title()}</title>
</svelte:head>

<div class="stage">
	<SubpageHeader current="settings" {isAdmin} />

	<main id="main" class="main" class:gated={!isAdmin}>
		<h1 class="page-title">{m.settings_heading()}</h1>
		{#if !isAdmin}
			<AdminOnlyNotice page="settings" />
		{:else}
			<nav class="index" aria-label={m.settings_index_label()}>
				<ul>
					{#each SECTIONS as section (section.id)}
						<li>
							<a
								href="#{section.id}"
								aria-current={activeSection === section.id ? 'location' : undefined}
								>{section.label()}</a
							>
						</li>
					{/each}
				</ul>
			</nav>

			<div class="sections">
				<section id="worker" class="panel section" aria-labelledby="worker-heading">
					<header class="section-head">
						<h2 id="worker-heading" class="label">{m.settings_worker_heading()}</h2>
						<p class="section-hint">{m.settings_worker_hint()}</p>
					</header>
					<WorkerStatus />
				</section>

				<section id="output" class="panel section" aria-labelledby="output-heading">
					<header class="section-head">
						<h2 id="output-heading" class="label">{m.settings_output_heading()}</h2>
						<p class="section-hint">{m.settings_output_hint()}</p>
					</header>

					{#if outputOptions === null}
						{#if outputError}
							{@render loadFailed(outputError, retryOutput)}
						{:else}
							<p class="section-hint">{m.settings_output_loading()}</p>
						{/if}
					{:else}
						<form class="grid" onsubmit={onOutputSubmit} novalidate>
							<div class="form-field">
								<span class="label" id="format-label">{m.settings_output_format()}</span>
								<div class="choice-group values" role="group" aria-labelledby="format-label">
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

							<label class="form-field">
								<span class="label">{m.settings_output_bitrate()}</span>
								<select
									class="well"
									bind:value={outputForm.default_bitrate}
									disabled={outputSaving}
								>
									{#each outputOptions.bitrates as rate (rate)}
										<option value={rate}>{rate}</option>
									{/each}
								</select>
							</label>

							<div class="form-field wide">
								<label class="label" for="output-template">{m.settings_output_template()}</label>
								<input
									id="output-template"
									class="well"
									type="text"
									spellcheck="false"
									bind:value={outputForm.output_template}
									disabled={outputSaving}
									aria-invalid={outputTemplateError ? 'true' : undefined}
									aria-describedby="output-template-hint output-template-error"
								/>
								<p id="output-template-hint" class="field-hint">
									{@render coded(templateHint)}
								</p>
								<p id="output-template-error" class="field-error">
									{outputTemplateError}
								</p>
							</div>

							<div class="save-row wide">
								<button type="submit" class="btn" disabled={outputSaving || outputSettings === null}
									>{outputSaving ? m.common_saving() : m.common_save()}</button
								>
								<p class="save-state" class:saved={!outputDirty && outputSavedAt} role="status">
									{outputDirty
										? m.common_unsaved_changes()
										: outputSavedAt
											? m.common_saved_at({ time: formatClock(outputSavedAt) })
											: ''}
								</p>
							</div>
						</form>
					{/if}
					<p class="form-error" class:sr-only={outputSettings === null} role="alert">
						{outputSettings !== null
							? outputError
							: outputError
								? m.settings_section_load_failed({ error: outputError })
								: ''}
					</p>
				</section>

				<section id="library" class="panel section" aria-labelledby="library-heading">
					<header class="section-head">
						<h2 id="library-heading" class="label">{m.settings_library_heading()}</h2>
						<p class="section-hint">
							{#each libraryHint as part, i (i)}{#if part.code}<a href={resolve('/library')}
										>{part.text}</a
									>{:else}{part.text}{/if}{/each}
						</p>
					</header>

					{#if librarySettings === null}
						{#if libraryError}
							{@render loadFailed(libraryError, retryLibrary)}
						{:else}
							<p class="section-hint">{m.settings_library_loading()}</p>
						{/if}
					{:else}
						<form class="grid" onsubmit={onLibrarySubmit} novalidate>
							{#each LIBRARY_TEXT_FIELDS.slice(0, 2) as field (field.key)}
								<div class="form-field wide">
									<label class="label" for={field.key}>{field.label()}</label>
									<input
										id={field.key}
										class="well"
										type="text"
										spellcheck="false"
										bind:value={libraryForm[field.key]}
										disabled={librarySaving}
										aria-invalid={libraryFieldErrors[field.key] ? 'true' : undefined}
										aria-describedby="{field.key}-error"
									/>
									<p id="{field.key}-error" class="field-error">
										{libraryFieldErrors[field.key] ?? ''}
									</p>
								</div>
							{/each}

							<div class="form-field">
								<span class="label" id="quarantine-label">{m.settings_library_duplicates()}</span>
								<div class="choice-group" role="group" aria-labelledby="quarantine-label">
									<button
										type="button"
										aria-pressed={libraryForm.library_quarantine_enabled}
										disabled={librarySaving}
										onclick={() => (libraryForm.library_quarantine_enabled = true)}
									>
										{m.settings_library_quarantine()}
									</button>
									<button
										type="button"
										aria-pressed={!libraryForm.library_quarantine_enabled}
										disabled={librarySaving}
										onclick={() => (libraryForm.library_quarantine_enabled = false)}
									>
										{m.settings_library_delete()}
									</button>
								</div>
								<p class="field-hint">{m.settings_library_duplicates_hint()}</p>
							</div>

							<div class="form-field">
								<label class="label" for="library_quarantine_dir"
									>{m.settings_library_quarantine_dir()}</label
								>
								<input
									id="library_quarantine_dir"
									class="well"
									type="text"
									spellcheck="false"
									bind:value={libraryForm.library_quarantine_dir}
									disabled={librarySaving}
									aria-invalid={libraryFieldErrors.library_quarantine_dir ? 'true' : undefined}
									aria-describedby="library_quarantine_dir-error"
								/>
								<p id="library_quarantine_dir-error" class="field-error">
									{libraryFieldErrors.library_quarantine_dir ?? ''}
								</p>
							</div>

							<div class="save-row wide">
								<button type="submit" class="btn" disabled={librarySaving}
									>{librarySaving ? m.common_saving() : m.common_save()}</button
								>
								<p class="save-state" class:saved={!libraryDirty && librarySavedAt} role="status">
									{libraryDirty
										? m.common_unsaved_changes()
										: librarySavedAt
											? m.common_saved_at({ time: formatClock(librarySavedAt) })
											: ''}
								</p>
							</div>
						</form>
					{/if}
					<p class="form-error" class:sr-only={librarySettings === null} role="alert">
						{librarySettings !== null
							? libraryError
							: libraryError
								? m.settings_section_load_failed({ error: libraryError })
								: ''}
					</p>
				</section>

				<section id="alerts" class="panel section" aria-labelledby="alerts-heading">
					<header class="section-head">
						<h2 id="alerts-heading" class="label">{m.settings_alerts_heading()}</h2>
						{#if alertSettings === null}
							{#if alertError}
								{@render loadFailed(alertError, retryAlerts)}
							{:else}
								<p class="section-hint">{m.settings_alerts_loading()}</p>
							{/if}
						{:else if alertSettings.configured}
							<p class="section-hint">{m.settings_alerts_on_hint()}</p>
						{:else}
							<p class="section-hint">
								{@render coded(alertsOffHint)}
							</p>
						{/if}
					</header>

					{#if alertSettings !== null}
						<form class="alert-form" onsubmit={onAlertSubmit} novalidate>
							<fieldset class="group">
								<legend class="group-title">{m.settings_alerts_send_when()}</legend>
								<ul class="toggle-list">
									{#each ALERT_TOGGLES as toggle (toggle.key)}
										<li class="toggle-row">
											<div class="toggle-text">
												<span class="toggle-name" id="{toggle.key}-label">{toggle.label()}</span>
												<span class="field-hint" id="{toggle.key}-hint">{toggle.hint()}</span>
											</div>
											<div
												class="choice-group"
												role="group"
												aria-labelledby="{toggle.key}-label"
												aria-describedby="{toggle.key}-hint"
											>
												<button
													type="button"
													aria-pressed={alertForm[toggle.key] === true}
													disabled={alertSaving}
													onclick={() => (alertForm = { ...alertForm, [toggle.key]: true })}
												>
													{m.settings_on()}
												</button>
												<button
													type="button"
													aria-pressed={alertForm[toggle.key] === false}
													disabled={alertSaving}
													onclick={() => (alertForm = { ...alertForm, [toggle.key]: false })}
												>
													{m.settings_off()}
												</button>
											</div>
										</li>
									{/each}
								</ul>
							</fieldset>

							<fieldset class="group">
								<legend class="group-title">{m.settings_alerts_thresholds()}</legend>
								<div class="grid">
									{#each ALERT_NUMBERS as field (field.key)}
										<div class="form-field">
											<label class="label" for={field.key}>{field.label()}</label>
											<div class="with-unit">
												<input
													id={field.key}
													class="well"
													type="number"
													inputmode="numeric"
													min={field.min}
													max={field.max}
													step="1"
													bind:value={alertForm[field.key]}
													disabled={alertSaving}
													aria-invalid={alertFieldErrors[field.key] ? 'true' : undefined}
													aria-describedby="{field.key}-unit {field.key}-error"
												/>
												<span class="unit" id="{field.key}-unit">{field.unit()}</span>
											</div>
											<p id="{field.key}-error" class="field-error">
												{alertFieldErrors[field.key] ?? ''}
											</p>
										</div>
									{/each}
								</div>
							</fieldset>

							<div class="save-row">
								<button type="submit" class="btn" disabled={alertSaving}
									>{alertSaving ? m.common_saving() : m.common_save()}</button
								>
								<button
									type="button"
									class="btn"
									disabled={alertTesting || !alertSettings.configured}
									onclick={onTestAlert}
								>
									{alertTesting ? m.settings_alerts_testing() : m.settings_alerts_test()}
								</button>
								<p class="save-state" class:saved={!alertDirty && alertSavedAt} role="status">
									{alertDirty
										? m.common_unsaved_changes()
										: alertSavedAt
											? m.common_saved_at({ time: formatClock(alertSavedAt) })
											: ''}
								</p>
							</div>
							<p class="save-state saved" role="status">{alertTestResult}</p>
						</form>
					{/if}
					<p class="form-error" class:sr-only={alertSettings === null} role="alert">
						{alertSettings !== null
							? alertError
							: alertError
								? m.settings_section_load_failed({ error: alertError })
								: ''}
					</p>
				</section>

				<section id="proxies" class="panel section" aria-labelledby="proxies-heading">
					<header class="section-head">
						<h2 id="proxies-heading" class="label" tabindex="-1">{m.settings_proxies_heading()}</h2>
						<p class="section-hint">
							{@render coded(proxiesHint)}
						</p>
					</header>

					<form class="add-proxy" onsubmit={onAddProxy} novalidate>
						<div class="form-field">
							<label class="label" for="new-proxy">{m.settings_proxy_add_label()}</label>
							<div class="add-row">
								<input
									id="new-proxy"
									class="well"
									type="text"
									spellcheck="false"
									autocomplete="off"
									placeholder={m.settings_proxy_add_placeholder()}
									bind:value={newProxyUrl}
									disabled={addingProxy}
									aria-invalid={addProxyError ? 'true' : undefined}
									aria-describedby="new-proxy-hint new-proxy-error"
								/>
								<button type="submit" class="btn" disabled={addingProxy}
									>{addingProxy ? m.settings_proxy_adding() : m.settings_proxy_add()}</button
								>
							</div>
							<p id="new-proxy-hint" class="field-hint">
								{@render coded(proxyFormatHint)}
							</p>
							<p id="new-proxy-error" class="field-error" role="alert">{addProxyError}</p>
						</div>
					</form>

					{#if proxiesLoading}
						<p class="section-hint">{m.settings_proxies_loading()}</p>
					{:else if proxiesLoadError && proxyList.length === 0}
						<!-- Nothing read: never claim "no proxies" over a failed load. -->
						<!-- Not an alert itself: the sr-only alert below (present from the start) announces it. -->
						<div class="load-failed">
							<p>{m.settings_proxies_load_failed({ error: proxiesLoadError })}</p>
							<button
								type="button"
								class="btn small"
								onclick={() => {
									loadProxies();
									keepFocusOnHeading('proxies-heading');
								}}>{m.settings_proxies_try_again()}</button
							>
						</div>
					{:else if proxyList.length === 0}
						<p class="section-hint">{m.settings_proxies_empty()}</p>
					{:else}
						<ul class="proxy-list" aria-label={m.settings_proxies_list_label()}>
							{#each proxyList as proxy (proxy.id)}
								<li class="proxy-row" class:off={!proxy.enabled}>
									<span class="url mono">{proxy.url}</span>
									<span class="health">
										<span class="source mono" class:manual={proxy.source === 'manual'}
											>{proxy.source === 'manual'
												? m.settings_proxy_source_manual()
												: PROXIES_FILE}</span
										>
										<span class="fact">
											{proxy.consecutive_failures === 0
												? m.settings_proxy_no_failures()
												: m.settings_proxy_failures(counted(proxy.consecutive_failures))}
										</span>
										<span class="fact">
											{proxy.last_success_at
												? m.settings_proxy_last_worked({
														when: formatTimestamp(proxy.last_success_at)
													})
												: m.settings_proxy_never_worked()}
										</span>
										{#if isFuture(proxy.cooldown_until)}
											<span class="fact"
												><Countdown
													scheduledAt={proxy.cooldown_until ?? ''}
													label={m.settings_proxy_resting()}
													dueText={m.settings_proxy_rested()}
												/></span
											>
										{/if}
									</span>
									<span class="controls">
										<span class="state mono" class:on={proxy.enabled}
											>{proxy.enabled
												? m.settings_proxy_switched_on()
												: m.settings_proxy_switched_off()}</span
										>
										<button
											type="button"
											class="btn small"
											disabled={proxyBusy[proxy.id]}
											aria-label={proxy.enabled
												? m.settings_proxy_switch_off_named({ url: proxy.url })
												: m.settings_proxy_switch_on_named({ url: proxy.url })}
											onclick={() => toggleProxy(proxy)}
										>
											{proxy.enabled ? m.settings_proxy_switch_off() : m.settings_proxy_switch_on()}
										</button>
										{#if proxy.source === 'manual'}
											<button
												type="button"
												class="btn small danger"
												disabled={proxyBusy[proxy.id]}
												aria-label={m.settings_proxy_remove_named({ url: proxy.url })}
												data-remove={proxy.id}
												onclick={() => removeProxy(proxy)}
											>
												{m.settings_proxy_remove()}
											</button>
										{/if}
									</span>
								</li>
							{/each}
						</ul>
					{/if}
					<p class="form-error" role="alert">{proxiesError}</p>
					<p class="sr-only" role="alert">
						{proxiesLoadError && proxyList.length === 0
							? m.settings_proxies_load_failed_alert()
							: ''}
					</p>
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

	/* Desktop: the index is a sticky column beside the sections. Below 1024px it is a
	   wrapping row of links above them (no sticky bar eating a phone's height). */
	.main {
		display: grid;
		grid-template-columns: 9rem minmax(0, 1fr);
		align-items: start;
		gap: var(--space-5);
		margin-top: var(--space-2);
	}

	.page-title {
		grid-column: 1 / -1;
	}

	/* A non-admin's page is the title and the notice, one column. */
	.main.gated {
		display: flex;
		flex-direction: column;
	}

	.index {
		position: sticky;
		top: var(--space-5);
	}

	.index ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		border-left: 1px solid var(--line);
	}

	.index a {
		display: block;
		padding: var(--space-1) var(--space-3);
		margin-left: -1px;
		border-left: 2px solid transparent;
		font-size: var(--fs-detail);
		color: var(--text-muted);
		text-decoration: none;
	}

	@media (hover: hover) {
		.index a:hover {
			color: var(--text-primary);
		}
	}

	/* Where you are: a mark in shape (the rail), not only in tone. Never amber. */
	.index a[aria-current='location'] {
		color: var(--text-primary);
		border-left-color: var(--text-muted);
	}

	.sections {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		min-width: 0;
	}

	.section {
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		scroll-margin-top: var(--space-5);
	}

	.section-head {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.load-failed {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
		font-size: var(--fs-detail);
		color: var(--fail);
	}

	.section-hint {
		font-size: var(--fs-detail);
		color: var(--text-muted);
		max-width: 68ch;
	}

	code {
		font-family: var(--font-mono);
		font-size: inherit;
		color: var(--text-primary);
		overflow-wrap: anywhere;
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-3) var(--space-4);
		align-items: start;
	}

	.wide {
		grid-column: 1 / -1;
	}

	/* Alerts: two plain groups, what to send and when. */
	.alert-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}

	.group {
		margin: 0;
		padding: 0;
		border: none;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	/* v47: a group inside a section is a heading of its own (Sans, body size, medium), as on
	   /account, not one more uppercase .label like the section's h2 and the field labels. */
	.group legend {
		padding: 0;
		margin-bottom: var(--space-2);
	}

	.group-title {
		font-size: var(--fs-body);
		font-weight: var(--fw-medium);
		color: var(--text-primary);
	}

	.toggle-list {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.toggle-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2) var(--space-4);
		padding: var(--space-3) 0;
		border-top: 1px solid var(--line);
	}

	.toggle-row:last-child {
		border-bottom: 1px solid var(--line);
	}

	.toggle-text {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}

	.toggle-name {
		font-size: var(--fs-body);
	}

	.toggle-row .choice-group {
		flex-shrink: 0;
	}

	/* v47: the unit has a column of its own, so every threshold input ends at the same x
	   whatever its unit's length ("attempts" / "minutes", Hungarian's longer ones). */
	.with-unit {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 5.5rem;
		align-items: center;
		gap: var(--space-2);
	}

	.unit {
		font-size: var(--fs-meta);
		color: var(--text-muted);
	}

	/* Proxies */
	.add-row {
		display: flex;
		gap: var(--space-2);
	}

	.add-row input {
		flex: 1 1 auto;
	}

	.proxy-list {
		list-style: none;
		margin: 0;
		padding: 0;
		border-top: 1px solid var(--line);
	}

	/* Two lines: the address, then where it came from and how it's doing; the controls
	   at the right (under both on a phone). */
	.proxy-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		grid-template-areas:
			'url controls'
			'health controls';
		align-items: center;
		gap: var(--space-1) var(--space-3);
		padding: var(--space-3) 0;
		border-bottom: 1px solid var(--line);
	}

	.source {
		font-size: var(--fs-meta);
		color: var(--text-dim);
	}

	.source.manual {
		/* Where it came from, not a state: never a .cond-* hue (waiting blue means scheduled). */
		color: var(--text-muted);
	}

	.url {
		grid-area: url;
		font-size: var(--fs-detail);
		color: var(--text-primary);
		overflow-wrap: anywhere;
	}

	.health {
		grid-area: health;
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-3);
	}

	.fact {
		font-size: var(--fs-meta);
		color: var(--text-muted);
	}

	.controls {
		grid-area: controls;
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: var(--space-2);
	}

	.state {
		font-size: var(--fs-meta);
		color: var(--text-muted);
	}

	.state.on {
		color: var(--settled);
	}

	/* v42's remainder: a switched-off row is said in words and drops its address to muted
	   text, never faded with opacity (which put 20 nodes under 4.5:1). */
	.proxy-row.off .url {
		color: var(--text-muted);
	}

	@media (max-width: 63.9375em) {
		.main {
			grid-template-columns: minmax(0, 1fr);
			gap: var(--space-4);
		}

		.index {
			position: static;
		}

		.index ul {
			flex-direction: row;
			flex-wrap: wrap;
			gap: var(--space-1) var(--space-2);
			border-left: none;
		}

		.index a {
			margin-left: 0;
			padding: var(--space-1) var(--space-2);
			border-left: none;
			border-bottom: 2px solid transparent;
		}

		.index a[aria-current='location'] {
			border-bottom-color: var(--text-muted);
		}
	}

	@media (max-width: 40em) {
		.stage {
			padding: var(--space-4);
		}

		.section {
			padding: var(--space-4);
			gap: var(--space-3);
		}

		.sections {
			gap: var(--space-4);
		}

		.alert-form {
			gap: var(--space-4);
		}

		.grid {
			grid-template-columns: minmax(0, 1fr);
		}

		.add-row {
			flex-direction: column;
		}

		.proxy-row {
			grid-template-columns: minmax(0, 1fr);
			grid-template-areas: 'url' 'health' 'controls';
		}

		.controls {
			justify-content: flex-start;
		}
	}

	@media (pointer: coarse) {
		.index a {
			display: inline-flex;
			align-items: center;
			min-height: 2.75rem;
		}
	}
</style>
