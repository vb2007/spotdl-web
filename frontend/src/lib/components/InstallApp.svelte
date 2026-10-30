<!--
	v65: /account's "install the app" entry, its own section (v66 adds a block of its own to
	/account in the same wave). Discreet: it shows only where it can do something. Chromium
	offers the install (`beforeinstallprompt`, caught by app.html): a button. Firefox on Android
	and Safari on iOS never offer it and install from their own menus: one line saying how. In
	the installed app it says so, with the build the service worker serves. Anywhere else (a
	desktop Firefox, a Chromium that hasn't offered) nothing at all.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import * as m from '$lib/paraglide/messages';
	import {
		installHint,
		installPrompt,
		onInstallPromptChange,
		promptInstall,
		runningInstalled,
		serviceWorkerVersion
	} from '$lib/install';

	let offered = $state(false);
	let installed = $state(false);
	let justInstalled = $state(false);
	let hint = $state<'ios' | 'firefox' | null>(null);
	let version = $state<string | null>(null);
	let prompting = $state(false);

	async function readVersion(): Promise<void> {
		version = await serviceWorkerVersion();
	}

	onMount(() => {
		installed = runningInstalled();
		offered = installPrompt() !== null;
		hint = installHint(navigator.userAgent, navigator.maxTouchPoints);
		readVersion();
		// A new build's worker takes over while the page is open: show its build.
		navigator.serviceWorker?.addEventListener('controllerchange', readVersion);
		const stop = onInstallPromptChange(() => (offered = installPrompt() !== null));
		return () => {
			stop();
			navigator.serviceWorker?.removeEventListener('controllerchange', readVersion);
		};
	});

	async function install(): Promise<void> {
		prompting = true;
		try {
			justInstalled = (await promptInstall()) === 'accepted';
		} finally {
			prompting = false;
		}
	}
</script>

{#if installed || offered || justInstalled || hint !== null}
	<section class="panel section" aria-labelledby="install-heading">
		<h2 id="install-heading" class="label">{m.install_heading()}</h2>
		{#if installed}
			<p class="hint">{m.install_running()}</p>
		{:else}
			<p class="hint" id="install-hint">{m.install_hint()}</p>
			{#if offered}
				<div>
					<button
						type="button"
						class="btn"
						disabled={prompting}
						aria-describedby="install-hint"
						onclick={install}>{m.install_button()}</button
					>
				</div>
			{:else if !justInstalled && hint === 'ios'}
				<p class="hint">{m.install_hint_ios()}</p>
			{:else if !justInstalled && hint === 'firefox'}
				<p class="hint">{m.install_hint_firefox()}</p>
			{/if}
			<p class="save-state saved" role="status">{justInstalled ? m.install_done() : ''}</p>
		{/if}
		{#if version}
			<p class="version mono">{m.install_version({ version })}</p>
		{/if}
	</section>
{/if}

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

	.version {
		font-size: var(--fs-meta);
		color: var(--text-dim);
	}
</style>
