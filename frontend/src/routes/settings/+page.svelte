<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import { confirmAction } from '$lib/stores/confirm';
	import Countdown from '$lib/components/Countdown.svelte';
	import WorkerStatus from '$lib/components/WorkerStatus.svelte';
	import SubpageHeader from '$lib/components/SubpageHeader.svelte';
	import AdminOnlyNotice from '$lib/components/AdminOnlyNotice.svelte';

	let { data } = $props();
	const isAdmin = $derived(data.session?.is_admin ?? false);

	// v43 (F19): one page, five sections, and an in-page index (anchors, no sub-routes, so
	// no nginx change). Each section saves on its own: they are separate endpoints.
	const SECTIONS = [
		{ id: 'worker', label: 'Worker' },
		{ id: 'output', label: 'Output' },
		{ id: 'library', label: 'Library' },
		{ id: 'alerts', label: 'Alerts' },
		{ id: 'proxies', label: 'Proxies' }
	] as const;
	let activeSection = $state<string>('worker');

	function errorText(err: unknown, fallback = 'Could not reach the server.'): string {
		return err instanceof api.ApiError ? err.message : fallback;
	}

	function clockTime(date: Date): string {
		return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
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
			: 'Enter a filename template, for example {artists} - {title}.{output-ext}.';
		if (outputTemplateError) return;
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
		{ key: 'library_target_dir', label: 'Library folder' },
		{ key: 'library_folder_template', label: 'Folder template' },
		{ key: 'library_quarantine_dir', label: 'Quarantine folder' }
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
			if (!libraryForm[key].trim()) errors[key] = `${label} can't be empty.`;
		}
		libraryFieldErrors = errors;
		if (Object.keys(errors).length > 0) return;
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
	const ALERT_TOGGLES: { key: AlertToggleKey; label: string; hint: string }[] = [
		{
			key: 'alerts_breaker_enabled',
			label: 'Breaker trip / release',
			hint: 'Downloads hold after repeated rate limits, and resume.'
		},
		{
			key: 'alerts_spike_enabled',
			label: 'Failure spike',
			hint: 'The latest attempts all failed the same way, within the window below.'
		},
		{
			key: 'alerts_beat_stale_enabled',
			label: 'Beat stale',
			hint: "The scheduler hasn't ticked for longer than the limit below."
		},
		{
			key: 'alerts_library_enabled',
			label: 'Library sweep',
			hint: 'A sweep finished or crashed.'
		}
	];

	// Mirrors the backend's _ALERT_BOUNDS (routers/settings.py), for an inline answer before
	// the request; the backend stays the real check.
	const ALERT_NUMBERS: {
		key: AlertNumberKey;
		label: string;
		unit: string;
		min: number;
		max: number;
	}[] = [
		{
			key: 'alert_spike_threshold',
			label: 'Spike: failures in a row',
			unit: 'attempts',
			min: 2,
			max: 1000
		},
		{
			key: 'alert_spike_window_minutes',
			label: 'Spike window',
			unit: 'minutes',
			min: 1,
			max: 7 * 24 * 60
		},
		{
			key: 'alert_beat_stale_seconds',
			label: 'Beat stale after',
			unit: 'seconds',
			min: 90,
			max: 7 * 24 * 3600
		},
		{
			key: 'alert_cooldown_minutes',
			label: 'Repeat an alert at most every',
			unit: 'minutes',
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
				errors[key] = 'Enter a number.';
			} else if (!Number.isInteger(value) || value < min || value > max) {
				errors[key] = `Use a whole number from ${min.toLocaleString()} to ${max.toLocaleString()}.`;
			}
		}
		alertFieldErrors = errors;
		if (Object.keys(errors).length > 0) return;
		alertSaving = true;
		alertError = '';
		try {
			alertSettings = await api.updateAlertSettings(alertForm);
			syncAlertForm(alertSettings);
			alertSavedAt = new Date();
		} catch (err) {
			alertError = errorText(err);
		} finally {
			alertSaving = false;
		}
	}

	async function onTestAlert() {
		alertTesting = true;
		alertTestResult = '';
		alertError = '';
		try {
			await api.sendTestAlert();
			alertTestResult = 'Test alert sent. Check the Matrix room.';
		} catch (err) {
			alertError = errorText(err);
		} finally {
			alertTesting = false;
		}
	}

	// --- Proxy pool --------------------------------------------------------------------

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

	async function loadProxies() {
		proxiesLoading = true;
		proxiesError = '';
		try {
			proxyList = await api.listProxies();
		} catch (err) {
			proxiesError = errorText(err);
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

	async function onAddProxy(event: SubmitEvent) {
		event.preventDefault();
		const url = newProxyUrl.trim();
		if (!url) {
			addProxyError = 'Paste a proxy address first.';
			return;
		}
		if (!PROXY_URL_RE.test(url)) {
			addProxyError =
				"That address won't work: it needs a literal IPv4 address, not a hostname, like http://203.0.113.7:8080.";
			return;
		}
		addingProxy = true;
		addProxyError = '';
		try {
			const proxy = await api.createProxy(url);
			proxyList = [...proxyList, proxy];
			newProxyUrl = '';
		} catch (err) {
			addProxyError = errorText(err, 'Could not add this proxy.');
		} finally {
			addingProxy = false;
		}
	}

	async function toggleProxy(proxy: api.Proxy) {
		proxyBusy = { ...proxyBusy, [proxy.id]: true };
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
	}

	async function removeProxy(proxy: api.Proxy) {
		// Only ever called for source=manual -- the "remove" control isn't rendered for
		// source=file rows at all (see markup below). A real, permanent delete: the row
		// disappears from the list rather than being merged back in updated.
		// v43 (F08): permanent, so it asks first.
		const confirmed = await confirmAction({
			title: 'Remove this proxy?',
			subject: proxy.url,
			body: "It's deleted from the pool, and no download uses it again. You can add it back later.",
			confirmLabel: 'remove proxy',
			cancelLabel: 'keep proxy'
		});
		if (!confirmed) return;
		proxyBusy = { ...proxyBusy, [proxy.id]: true };
		proxiesError = '';
		try {
			await api.deleteProxy(proxy.id);
			proxyList = proxyList.filter((p) => p.id !== proxy.id);
			// The row (and the focused button) is gone: land on the list's own heading.
			document.getElementById('proxies-heading')?.focus();
		} catch (err) {
			proxiesError = errorText(err);
		} finally {
			const { [proxy.id]: _unused, ...rest } = proxyBusy;
			proxyBusy = rest;
		}
	}

	function formatTimestamp(value: string): string {
		return new Date(value).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' });
	}

	function isFuture(value: string | null): boolean {
		return value != null && new Date(value).getTime() > Date.now();
	}

	onMount(() => {
		// A non-admin gets the notice and nothing else: no admin request is ever made (F17).
		if (!isAdmin) return;
		loadOutputSettings().catch((err) => (outputError = errorText(err)));
		loadLibrarySettings().catch((err) => (libraryError = errorText(err)));
		loadAlertSettings().catch((err) => (alertError = errorText(err)));
		loadProxies();
		const poll = setInterval(refreshProxiesSilently, PROXY_POLL_MS);

		// The index marks the section being read: the last one whose top has passed a line
		// a third of the way down the viewport.
		const observer = new IntersectionObserver(
			() => {
				const line = window.innerHeight / 3;
				let current: string = SECTIONS[0].id;
				for (const { id } of SECTIONS) {
					const el = document.getElementById(id);
					if (el && el.getBoundingClientRect().top <= line) current = id;
				}
				activeSection = current;
			},
			{ threshold: [0, 0.25, 0.5, 0.75, 1], rootMargin: '0px 0px -60% 0px' }
		);
		for (const { id } of SECTIONS) {
			const el = document.getElementById(id);
			if (el) observer.observe(el);
		}

		return () => {
			clearInterval(poll);
			observer.disconnect();
		};
	});
</script>

<svelte:head>
	<title>spotdl-web — settings</title>
</svelte:head>

<div class="stage">
	<SubpageHeader title="Settings" current="settings" {isAdmin} />

	<main id="main" class="main">
		{#if !isAdmin}
			<AdminOnlyNotice what="The worker, output, library, alert and proxy setup" />
		{:else}
			<nav class="index" aria-label="Settings sections">
				<ul>
					{#each SECTIONS as section (section.id)}
						<li>
							<a
								href="#{section.id}"
								aria-current={activeSection === section.id ? 'location' : undefined}
								>{section.label}</a
							>
						</li>
					{/each}
				</ul>
			</nav>

			<div class="sections">
				<section id="worker" class="panel section" aria-labelledby="worker-heading">
					<header class="section-head">
						<h2 id="worker-heading" class="label">Worker control</h2>
						<p class="section-hint">One worker downloads for everyone, one track at a time.</p>
					</header>
					<WorkerStatus />
				</section>

				<section id="output" class="panel section" aria-labelledby="output-heading">
					<header class="section-head">
						<h2 id="output-heading" class="label">Output defaults</h2>
						<p class="section-hint">Used from the next download on. No restart needed.</p>
					</header>

					{#if outputOptions === null}
						{#if !outputError}<p class="section-hint">Loading output options…</p>{/if}
					{:else}
						<form class="grid" onsubmit={onOutputSubmit} novalidate>
							<div class="form-field">
								<span class="label" id="format-label">Format</span>
								<div class="choice-group" role="group" aria-labelledby="format-label">
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
								<span class="label">Bitrate</span>
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
								<label class="label" for="output-template">Filename template</label>
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
									spotdl fills each <code>{'{placeholder}'}</code> per track.
								</p>
								<p id="output-template-error" class="field-error">{outputTemplateError}</p>
							</div>

							<div class="save-row wide">
								<button type="submit" class="btn" disabled={outputSaving || outputSettings === null}
									>{outputSaving ? 'saving…' : 'save'}</button
								>
								<p class="save-state" class:saved={!outputDirty && outputSavedAt} role="status">
									{outputDirty
										? 'Unsaved changes'
										: outputSavedAt
											? `Saved at ${clockTime(outputSavedAt)}`
											: ''}
								</p>
							</div>
						</form>
					{/if}
					<p class="form-error" role="alert">{outputError}</p>
				</section>

				<section id="library" class="panel section" aria-labelledby="library-heading">
					<header class="section-head">
						<h2 id="library-heading" class="label">Library sort &amp; move</h2>
						<p class="section-hint">
							Where a sweep files finished downloads. Run one from the
							<a href={resolve('/library')}>library page</a>.
						</p>
					</header>

					{#if librarySettings === null}
						{#if !libraryError}<p class="section-hint">Loading library settings…</p>{/if}
					{:else}
						<form class="grid" onsubmit={onLibrarySubmit} novalidate>
							{#each LIBRARY_TEXT_FIELDS.slice(0, 2) as field (field.key)}
								<div class="form-field wide">
									<label class="label" for={field.key}>{field.label}</label>
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
								<span class="label" id="quarantine-label">A download the library already has</span>
								<div class="choice-group" role="group" aria-labelledby="quarantine-label">
									<button
										type="button"
										aria-pressed={libraryForm.library_quarantine_enabled}
										disabled={librarySaving}
										onclick={() => (libraryForm.library_quarantine_enabled = true)}
									>
										quarantine
									</button>
									<button
										type="button"
										aria-pressed={!libraryForm.library_quarantine_enabled}
										disabled={librarySaving}
										onclick={() => (libraryForm.library_quarantine_enabled = false)}
									>
										delete
									</button>
								</div>
								<p class="field-hint">
									The downloaded copy is moved aside or deleted; the library's own file is never
									touched.
								</p>
							</div>

							<div class="form-field">
								<label class="label" for="library_quarantine_dir">Quarantine folder</label>
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
									>{librarySaving ? 'saving…' : 'save'}</button
								>
								<p class="save-state" class:saved={!libraryDirty && librarySavedAt} role="status">
									{libraryDirty
										? 'Unsaved changes'
										: librarySavedAt
											? `Saved at ${clockTime(librarySavedAt)}`
											: ''}
								</p>
							</div>
						</form>
					{/if}
					<p class="form-error" role="alert">{libraryError}</p>
				</section>

				<section id="alerts" class="panel section" aria-labelledby="alerts-heading">
					<header class="section-head">
						<h2 id="alerts-heading" class="label">Alerts</h2>
						{#if alertSettings === null}
							{#if !alertError}<p class="section-hint">Loading alert settings…</p>{/if}
						{:else if alertSettings.configured}
							<p class="section-hint">
								Matrix alerts are on. Switch off any category you don't want; the same alert repeats
								at most once per the interval below.
							</p>
						{:else}
							<p class="section-hint">
								Matrix alerts are off. Set <code>MATRIX_HOMESERVER_URL</code>,
								<code>MATRIX_ACCESS_TOKEN</code> and <code>MATRIX_ROOM_ID</code> in
								<code>.env</code> to turn them on.
							</p>
						{/if}
					</header>

					{#if alertSettings !== null}
						<form class="alert-form" onsubmit={onAlertSubmit} novalidate>
							<fieldset class="group">
								<legend class="label">Send an alert when</legend>
								<ul class="toggle-list">
									{#each ALERT_TOGGLES as toggle (toggle.key)}
										<li class="toggle-row">
											<div class="toggle-text">
												<span class="toggle-name" id="{toggle.key}-label">{toggle.label}</span>
												<span class="field-hint" id="{toggle.key}-hint">{toggle.hint}</span>
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
													on
												</button>
												<button
													type="button"
													aria-pressed={alertForm[toggle.key] === false}
													disabled={alertSaving}
													onclick={() => (alertForm = { ...alertForm, [toggle.key]: false })}
												>
													off
												</button>
											</div>
										</li>
									{/each}
								</ul>
							</fieldset>

							<fieldset class="group">
								<legend class="label">Thresholds</legend>
								<div class="grid">
									{#each ALERT_NUMBERS as field (field.key)}
										<div class="form-field">
											<label class="label" for={field.key}>{field.label}</label>
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
												<span class="unit mono" id="{field.key}-unit">{field.unit}</span>
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
									>{alertSaving ? 'saving…' : 'save'}</button
								>
								<button
									type="button"
									class="btn"
									disabled={alertTesting || !alertSettings.configured}
									onclick={onTestAlert}
								>
									{alertTesting ? 'sending…' : 'send test alert'}
								</button>
								<p class="save-state" class:saved={!alertDirty && alertSavedAt} role="status">
									{alertDirty
										? 'Unsaved changes'
										: alertSavedAt
											? `Saved at ${clockTime(alertSavedAt)}`
											: ''}
								</p>
							</div>
							<p class="save-state saved" role="status">{alertTestResult}</p>
						</form>
					{/if}
					<p class="form-error" role="alert">{alertError}</p>
				</section>

				<section id="proxies" class="panel section" aria-labelledby="proxies-heading">
					<header class="section-head">
						<h2 id="proxies-heading" class="label" tabindex="-1">Proxy pool</h2>
						<p class="section-hint">
							Proxies from <code>proxies.txt</code> and those added here are used equally, after a direct
							attempt and its wait. Addresses are shown with their credentials hidden.
						</p>
					</header>

					<form class="add-proxy" onsubmit={onAddProxy} novalidate>
						<div class="form-field">
							<label class="label" for="new-proxy">Add a proxy</label>
							<div class="add-row">
								<input
									id="new-proxy"
									class="well"
									type="text"
									spellcheck="false"
									autocomplete="off"
									placeholder="http://user:pass@203.0.113.7:8080"
									bind:value={newProxyUrl}
									disabled={addingProxy}
									aria-invalid={addProxyError ? 'true' : undefined}
									aria-describedby="new-proxy-hint new-proxy-error"
								/>
								<button type="submit" class="btn" disabled={addingProxy}
									>{addingProxy ? 'adding…' : 'add proxy'}</button
								>
							</div>
							<p id="new-proxy-hint" class="field-hint">
								<code>http(s)://[user:pass@]ipv4[:port]</code>, with a literal IPv4 address.
							</p>
							<p id="new-proxy-error" class="field-error" role="alert">{addProxyError}</p>
						</div>
					</form>

					{#if proxiesLoading}
						<p class="section-hint">Loading proxies…</p>
					{:else if proxiesError && proxyList.length === 0}
						<!-- Nothing read: never claim "no proxies" over a failed load. -->
						<p class="section-hint">
							Couldn't read the proxy pool.
							<button type="button" class="btn small" onclick={loadProxies}>try again</button>
						</p>
					{:else if proxyList.length === 0}
						<p class="section-hint">No proxies yet. Every attempt goes out directly.</p>
					{:else}
						<ul class="proxy-list" aria-label="Proxies">
							{#each proxyList as proxy (proxy.id)}
								<li class="proxy-row" class:off={!proxy.enabled}>
									<span class="url mono">{proxy.url}</span>
									<span class="health">
										<span class="source mono" class:manual={proxy.source === 'manual'}
											>{proxy.source === 'manual' ? 'added here' : 'proxies.txt'}</span
										>
										<span class="fact mono">
											{proxy.consecutive_failures === 0
												? 'no recent failures'
												: `${proxy.consecutive_failures} failed in a row`}
										</span>
										<span class="fact mono">
											{proxy.last_success_at
												? `last worked ${formatTimestamp(proxy.last_success_at)}`
												: 'never worked yet'}
										</span>
										{#if isFuture(proxy.cooldown_until)}
											<span class="fact"
												><Countdown
													scheduledAt={proxy.cooldown_until ?? ''}
													label="resting"
													dueLive={false}
													dueText="rested"
												/></span
											>
										{/if}
									</span>
									<span class="controls">
										<span class="state mono" class:on={proxy.enabled}
											>{proxy.enabled ? 'in use' : 'switched off'}</span
										>
										<button
											type="button"
											class="btn small"
											disabled={proxyBusy[proxy.id]}
											aria-label="{proxy.enabled ? 'switch off' : 'switch on'} {proxy.url}"
											onclick={() => toggleProxy(proxy)}
										>
											{proxy.enabled ? 'switch off' : 'switch on'}
										</button>
										{#if proxy.source === 'manual'}
											<button
												type="button"
												class="btn small danger"
												disabled={proxyBusy[proxy.id]}
												aria-label="remove {proxy.url}"
												onclick={() => removeProxy(proxy)}
											>
												remove
											</button>
										{/if}
									</span>
								</li>
							{/each}
						</ul>
					{/if}
					<p class="form-error" role="alert">{proxiesError}</p>
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
		font-family: var(--font-mono);
		font-size: var(--fs-detail);
		color: var(--text-muted);
		text-decoration: none;
	}

	.index a:hover {
		color: var(--text-primary);
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

	.section-hint {
		font-size: var(--fs-detail);
		color: var(--text-muted);
		max-width: 68ch;
	}

	code {
		font-family: var(--font-mono);
		font-size: 0.95em;
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

	.group legend {
		padding: 0;
		margin-bottom: var(--space-3);
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

	.with-unit {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.with-unit input {
		flex: 1 1 auto;
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
		color: var(--waiting);
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

	@media (max-width: 1023px) {
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

	@media (max-width: 640px) {
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
