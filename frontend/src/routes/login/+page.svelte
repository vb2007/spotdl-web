<script lang="ts">
	import { tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { clearProgress } from '$lib/stores/progressCache';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import * as m from '$lib/paraglide/messages';
	import { formatNumber } from '$lib/i18n/format';

	let email = $state('');
	let password = $state('');
	let submitting = $state(false);
	let errorMessage = $state('');
	// Only a 401 says the credentials are wrong; an unreachable server says nothing about them.
	let credentialsRejected = $state(false);
	let passwordInput: HTMLInputElement | undefined = $state();
	let connectButton: HTMLButtonElement | undefined = $state();

	async function onsubmit(event: SubmitEvent) {
		event.preventDefault();
		submitting = true;
		errorMessage = '';
		credentialsRejected = false;
		try {
			await api.login(email, password);
			// v34.2: a fresh identity never inherits another's cached progress ids -- the
			// logout reset can't run when the last session simply expired in a closed tab.
			clearProgress();
			await goto(resolve('/'));
		} catch (err) {
			// The 401 copy is deliberately generic — it matches
			// the backend's non-disclosure between an unknown/wrong-password upstream
			// account and an allowlist rejection. Anything else (CORS misconfigured,
			// the API unreachable, a 5xx) is a categorically different problem and
			// must not be reported as "wrong password" — that reads as a lie to
			// whoever's actually blocked by a config/network issue, not a bad
			// credential.
			credentialsRejected = err instanceof api.ApiError && err.status === 401;
			errorMessage =
				err instanceof api.ApiError && err.status === 401
					? m.login_error_rejected()
					: m.login_error_unreachable();
			submitting = false;
			// v43 (F31): after rejected credentials, back to the field to fix; after a server
			// that couldn't be reached, back on CONNECT to try again (nothing to fix). The
			// controls were disabled while connecting, so wait for them to re-enable first.
			await tick();
			if (credentialsRejected) {
				passwordInput?.focus();
				passwordInput?.select();
			} else {
				connectButton?.focus();
			}
		}
	}
</script>

<svelte:head>
	<title>{m.login_title()}</title>
</svelte:head>

<main id="main" class="stage">
	<!-- v46: no language switch here (owner's rule, PR #68): signed out, the page speaks the
	     browser's language; a preference is picked on /account and applies once signed in. -->
	<div class="ident">
		<!-- i18n-ignore: the wordmark is a name, the same in every language. -->
		<span class="label">SPOTDL // WEB</span>
		<span class="label dim">{m.login_ident_receiver()}</span>
	</div>

	<form class="panel" {onsubmit}>
		<div class="dial" aria-hidden="true">
			{#each Array(21) as _, i (i)}
				<span class="tick" class:major={i % 5 === 0}>
					{#if i % 5 === 0}
						<span class="freq mono"
							>{formatNumber(88 + (i / 5) * 4, { minimumFractionDigits: 1 })}</span
						>
					{/if}
				</span>
			{/each}
			<span class="needle" class:sweeping={submitting}></span>
		</div>

		<div class="heading">
			<h1 class="mono">{m.login_heading()}</h1>
			<!-- v43 (F31): which account this wants. -->
			<p class="hint">{m.login_hint()}</p>
		</div>

		<label class="form-field">
			<span class="label">{m.login_email()}</span>
			<input
				class="well"
				type="email"
				name="email"
				autocomplete="email"
				required
				bind:value={email}
				disabled={submitting}
				aria-invalid={credentialsRejected ? 'true' : undefined}
				aria-describedby="login-error"
			/>
		</label>

		<label class="form-field">
			<span class="label">{m.login_password()}</span>
			<input
				bind:this={passwordInput}
				class="well"
				type="password"
				name="password"
				autocomplete="current-password"
				required
				bind:value={password}
				disabled={submitting}
				aria-invalid={credentialsRejected ? 'true' : undefined}
				aria-describedby="login-error"
			/>
		</label>

		<button type="submit" class="connect" disabled={submitting} bind:this={connectButton}>
			{submitting ? m.login_connecting() : m.login_connect()}
		</button>

		<!-- One live region: role="alert" alone (it was also aria-live="polite", F31). -->
		<p id="login-error" class="error" role="alert">
			{errorMessage}
		</p>
	</form>
</main>

<style>
	.stage {
		min-height: 100dvh;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--space-6);
		padding: var(--space-5);
	}

	.ident {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-1);
	}

	.ident .dim {
		color: var(--text-dim);
	}

	.panel {
		width: 100%;
		max-width: 22rem;
		padding: var(--space-6) var(--space-5) var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.dial {
		position: relative;
		height: 2rem;
		display: flex;
		align-items: flex-end;
		gap: 0;
		border-bottom: 1px solid var(--line);
		margin-bottom: var(--space-4);
	}

	.tick {
		position: relative;
		flex: 1;
		height: 0.5rem;
		border-left: 1px solid var(--line-bright);
	}

	.freq {
		position: absolute;
		top: 100%;
		left: 50%;
		transform: translateX(-50%);
		margin-top: 3px;
		font-size: var(--fs-label);
		color: var(--text-dim);
		white-space: nowrap;
	}

	.tick.major {
		height: 0.875rem;
		border-left-color: var(--text-dim);
	}

	/* F10 (the v40 verdict): at rest the needle is muted chrome with no glow. It takes the
	   amber and its glow only while sweeping, the one moment the dial is really tuning. */
	.needle {
		position: absolute;
		bottom: -1px;
		left: 0;
		width: 2px;
		height: 1.5rem;
		background: var(--text-muted);
		transform: translateX(0);
	}

	.needle.sweeping {
		background: var(--signal);
		box-shadow: 0 0 6px 1px var(--signal-glow);
		animation: sweep 1.4s var(--ease-signal) infinite;
	}

	@media (prefers-reduced-motion: reduce) {
		.needle.sweeping {
			animation: none;
			opacity: 0.6;
		}
	}

	@keyframes sweep {
		0% {
			left: 0;
		}
		50% {
			left: calc(100% - 2px);
		}
		100% {
			left: 0;
		}
	}

	.heading {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	h1 {
		font-size: var(--fs-lead);
		font-weight: var(--fw-strong);
		letter-spacing: 0.16em;
		color: var(--text-primary);
	}

	.hint {
		font-size: var(--fs-detail);
		color: var(--text-muted);
	}

	/* The login's inputs are a touch taller than the settings forms': two fields, one task. */
	.form-field input {
		padding: var(--space-3);
	}

	.connect {
		margin-top: var(--space-2);
		background: var(--bg-2);
		border: 1px solid var(--line-control);
		border-radius: 4px;
		padding: var(--space-3);
		font-family: var(--font-mono);
		font-weight: 600;
		letter-spacing: 0.08em;
		cursor: pointer;
		transition: background var(--dur-fast) var(--ease-signal);
	}

	/* F10: no amber and no halo; focus is the global ring alone. */
	.connect:hover:not(:disabled) {
		background: var(--bg-3);
		border-color: var(--text-muted);
	}

	.connect:disabled {
		color: var(--text-dim);
		cursor: progress;
	}

	.error {
		min-height: 1.25rem;
		color: var(--fail);
		font-size: var(--fs-detail);
		text-align: center;
	}
</style>
