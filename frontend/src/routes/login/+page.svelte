<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { goto, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { consumeSessionEnded } from '$lib/stores/sessionEnded';
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

	let emailInput: HTMLInputElement | undefined = $state();
	// v47: the session ended under this tab, found by a request's 401 (page state) or by the
	// layout on a navigation (the module flag).
	const sessionEnded = consumeSessionEnded();
	// The status region is on the page from the start and its sentence arrives after it (a
	// region inserted together with its text often goes unannounced), once the layout has
	// moved focus to the heading.
	let endedText = $state('');
	// Its line is held from the first paint whenever it applies, so the sentence arriving (or
	// an error clearing it) never moves the fields under a finger.
	const showEnded = page.state.sessionEnded === true || sessionEnded;
	onMount(() => {
		if (!showEnded) return;
		// Read once: cleared from this history entry, so Back to it later (after a deliberate
		// sign-out) doesn't say the session ended.
		if (page.state.sessionEnded) replaceState('', {});
		const timer = setTimeout(() => (endedText = m.login_session_ended()), 250);
		return () => clearTimeout(timer);
	});
	// v47: which field the form's own check found empty, for aria-invalid.
	let missing = $state<'email' | 'password' | null>(null);

	async function onsubmit(event: SubmitEvent) {
		event.preventDefault();
		// v47: the form's own check, in the page's language and its error line (`novalidate`:
		// the browser's bubble spoke the browser's language and sat outside the design).
		if (!email.trim() || !password) {
			// Emptied first, so a second press with the same gap is announced again.
			errorMessage = '';
			await tick();
			errorMessage = m.login_error_missing();
			credentialsRejected = false;
			missing = email.trim() ? 'password' : 'email';
			(email.trim() ? passwordInput : emailInput)?.focus();
			return;
		}
		missing = null;
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
			// v47: a 500 is the service answering with a problem; a 502/503/504 is the proxy in
			// front saying the api isn't there (a deploy, a restart), which is "couldn't reach",
			// the same words the layout's unreachable screen uses for it.
			const status = err instanceof api.ApiError ? err.status : 0;
			errorMessage = credentialsRejected
				? m.login_error_rejected()
				: status >= 500 && ![502, 503, 504].includes(status)
					? m.login_error_server()
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

	<form class="panel" {onsubmit} novalidate>
		<div class="dial" aria-hidden="true">
			<!-- v47: each tick at its own fraction of the dial, the last one at its end. -->
			{#each Array(21) as _, i (i)}
				<span
					class="tick"
					class:major={i % 5 === 0}
					class:first={i === 0}
					class:last={i === 20}
					style:left="calc((100% - 1px) * {i / 20})"
				>
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
			<!-- v47: arrived here because the session ended mid-page (a 401), not by signing out. -->
			<p class="ended" class:reserved={showEnded} role="status">
				{errorMessage ? '' : endedText}
			</p>
		</div>

		<label class="form-field">
			<span class="label">{m.login_email()}</span>
			<input
				bind:this={emailInput}
				class="well"
				type="email"
				name="email"
				autocomplete="email"
				required
				bind:value={email}
				oninput={() => missing === 'email' && (missing = null)}
				disabled={submitting}
				aria-invalid={credentialsRejected || missing === 'email' ? 'true' : undefined}
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
				oninput={() => missing === 'password' && (missing = null)}
				disabled={submitting}
				aria-invalid={credentialsRejected || missing === 'password' ? 'true' : undefined}
				aria-describedby="login-error"
			/>
		</label>

		<button type="submit" class="btn connect" disabled={submitting} bind:this={connectButton}>
			{submitting ? m.login_connecting() : m.login_connect()}
		</button>

		<!-- One live region: role="alert" alone (it was also aria-live="polite", F31). -->
		<p id="login-error" class="error" role="alert">
			{errorMessage}
		</p>
	</form>
</main>

<style>
	/* v47: anchored near the top, not centred, so the error line growing under the button never
	   moves the whole card. */
	.stage {
		min-height: 100dvh;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: flex-start;
		gap: var(--space-6);
		padding: clamp(var(--space-5), 16vh, 10rem) var(--space-5) var(--space-5);
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
		border-bottom: 1px solid var(--line);
		margin-bottom: var(--space-4);
	}

	.tick {
		position: absolute;
		bottom: 0;
		height: 0.5rem;
		border-left: 1px solid var(--line-bright);
	}

	.freq {
		position: absolute;
		top: 100%;
		left: 50%;
		transform: translateX(-50%);
		margin-top: var(--space-1);
		font-size: var(--fs-label);
		color: var(--text-dim);
		white-space: nowrap;
	}

	/* The end labels stay inside the dial instead of overhanging the column. */
	.tick.first .freq {
		left: 0;
		transform: none;
	}

	.tick.last .freq {
		left: auto;
		right: 0;
		transform: none;
	}

	.tick.major {
		height: 0.875rem;
		border-left-color: var(--text-dim);
	}

	/* F10 (the v40 verdict): at rest the needle is muted chrome with no glow. It takes the
	   amber and its glow only while sweeping, the one moment the dial is really tuning.
	   v47 (F33): it moves by transform, not `left`. The element spans the dial less the
	   needle's own width, the visible needle is its ::before, and translateX(100%) carries
	   it to the far end with no layout per frame. */
	.needle {
		position: absolute;
		bottom: -1px;
		left: 0;
		width: calc(100% - 2px);
		height: 1.5rem;
		pointer-events: none;
	}

	.needle::before {
		content: '';
		position: absolute;
		inset: 0 auto 0 0;
		width: 2px;
		background: var(--text-muted);
	}

	.needle.sweeping {
		animation: sweep 1.4s var(--ease-signal) infinite;
	}

	.needle.sweeping::before {
		background: var(--signal);
		box-shadow: 0 0 6px 1px var(--signal-glow);
	}

	@media (prefers-reduced-motion: reduce) {
		.needle.sweeping {
			animation: none;
			opacity: 0.6;
		}
	}

	@keyframes sweep {
		0% {
			transform: translateX(0);
		}
		50% {
			transform: translateX(100%);
		}
		100% {
			transform: translateX(0);
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

	/* v47: the app's one button, a size up: the form's single action. */
	.connect {
		margin-top: var(--space-2);
		padding: var(--space-3);
	}

	.connect:disabled {
		cursor: progress;
	}

	.ended {
		font-size: var(--fs-detail);
		color: var(--text-primary);
	}

	.ended.reserved {
		min-height: 1.5em;
	}

	.ended:empty:not(.reserved) {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
	}

	.error {
		min-height: 1.25rem;
		color: var(--fail);
		font-size: var(--fs-detail);
	}
</style>
