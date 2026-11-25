<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { goto, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { consumeSessionEnded } from '$lib/stores/sessionEnded';
	import { clearProgress } from '$lib/stores/progressCache';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import * as m from '$lib/paraglide/messages';
	import { counted, formatNumber } from '$lib/i18n/format';
	import { apiErrorText, mfaExpiredText } from '$lib/i18n/errors';
	import { safeNext } from '$lib/nextPath';

	let email = $state('');
	let password = $state('');
	let submitting = $state(false);
	let errorMessage = $state('');
	// Only a 401 says the credentials are wrong; an unreachable server says nothing about them.
	let credentialsRejected = $state(false);
	let passwordInput: HTMLInputElement | undefined = $state();
	let connectButton: HTMLButtonElement | undefined = $state();

	let emailInput: HTMLInputElement | undefined = $state();
	// v67: a share opened signed out (v65) comes back here with `next=/share…`: say it's waiting,
	// or the person coming from the share sheet takes it for lost.
	const forShare = (safeNext(page.url.searchParams.get('next')) ?? '').startsWith('/share');
	// v47: the session ended under this tab, found by a request's 401 (page state) or by the
	// layout on a navigation (the module flag).
	const sessionEnded = consumeSessionEnded();
	// The status region is on the page from the start and its sentence arrives after it (a
	// region inserted together with its text often goes unannounced), once the layout has
	// moved focus to the heading.
	let endedText = $state('');
	// Its line is held from the first paint whenever it applies, so the sentence arriving (or
	// an error clearing it) never moves the fields under a finger.
	const showEnded = page.state.sessionEnded === true || sessionEnded !== null;
	// v69: the admin removed this address (the stream or a request's 401 said so, here or in
	// another tab, or on this tab's reload).
	const accessRemoved = page.state.accessRemoved === true || sessionEnded === 'access_removed';
	onMount(() => {
		if (!showEnded) return;
		// Read once: cleared from this history entry, so Back to it later (after a deliberate
		// sign-out) doesn't say the session ended.
		if (page.state.sessionEnded) replaceState('', {});
		const timer = setTimeout(() => {
			// A fast password step may already have answered it (v71's second step).
			if (step === 'password')
				endedText = accessRemoved ? m.login_access_removed() : m.login_session_ended();
		}, 250);
		return () => clearTimeout(timer);
	});
	// v47: which field the form's own check found empty, for aria-invalid.
	let missing = $state<'email' | 'password' | null>(null);

	// v71: a right password on an account with MFA on brings the second step into the same card:
	// a method choice (upstream's order) and one code field. The upstream challenge stays on the
	// server, keyed by an httponly cookie; this page only knows which methods it offers.
	let step = $state<'password' | 'mfa'>('password');
	let methods = $state<api.MfaMethod[]>([]);
	let method = $state<api.MfaMethod>('totp');
	let code = $state('');
	let codeMissing = $state(false);
	let codeRejected = $state(false);
	let codeInput: HTMLInputElement | undefined = $state();
	// The email code: sending, then the line saying it went; a resend waits out upstream's
	// cooldown, counted down from the `retry_after` its 429 gave.
	let sending = $state(false);
	// A send for this challenge went through (its code works until the step ends), or was at
	// least tried (its answer may be lost while upstream mailed a code all the same).
	let codeSent = $state(false);
	let sendTried = $state(false);
	let sentText = $state('');
	let resendIn = $state(0);
	let resendTimer: ReturnType<typeof setInterval> | undefined;
	onMount(() => () => clearInterval(resendTimer));

	const METHOD_LABEL: Record<api.MfaMethod, () => string> = {
		totp: m.login_mfa_method_totp,
		email: m.login_mfa_method_email,
		recovery: m.login_mfa_method_recovery
	};
	const METHOD_HINT: Record<api.MfaMethod, () => string> = {
		totp: m.login_mfa_hint_totp,
		email: m.login_mfa_hint_email,
		recovery: m.login_mfa_hint_recovery
	};
	// The codes the backend gives a sentence of their own (i18n/errors.ts); 401 and 429 keep
	// this page's own words below.
	const OWN_SENTENCE = new Set([
		'account_suspended',
		'mfa_unsupported',
		'mfa_code_invalid',
		'mfa_method_off',
		'mail_unavailable',
		'login_unavailable'
	]);

	function countDownResend(seconds: number) {
		clearInterval(resendTimer);
		// To a deadline, not by ticks: a phone suspends the tab while its mail app is open.
		const until = Date.now() + seconds * 1000;
		resendIn = seconds;
		resendTimer = setInterval(() => {
			resendIn = Math.max(0, Math.ceil((until - Date.now()) / 1000));
			if (resendIn > 0) return;
			clearInterval(resendTimer);
			// The "earlier sign-in" and "on its way" lines spoke of this countdown; a sent code's
			// line holds for the whole challenge, so it stays (a change would read as a new mail).
			if (!codeSent) sentText = '';
		}, 1000);
	}

	async function toSecondStep(offered: api.MfaMethod[]) {
		step = 'mfa';
		// The password was accepted: "your session ended" has been answered.
		endedText = '';
		methods = offered;
		method = offered[0];
		code = '';
		sentText = '';
		codeSent = sendTried = false;
		codeRejected = codeMissing = false;
		await tick();
		codeInput?.focus();
	}

	/** Back to the password (the fields keep what was typed), saying why when the step ended. */
	async function toPasswordStep(reason = '') {
		step = 'password';
		clearInterval(resendTimer);
		resendIn = 0;
		errorMessage = reason;
		credentialsRejected = false;
		await tick();
		connectButton?.focus();
	}

	function chooseMethod(next: api.MfaMethod) {
		if (next === method) return;
		method = next;
		code = '';
		errorMessage = '';
		codeRejected = codeMissing = false;
	}

	async function sendCode() {
		const triedBefore = sendTried;
		sending = true;
		sendTried = true;
		errorMessage = '';
		// Emptied first, so the same sentence arriving again is announced again.
		sentText = codeSent ? m.login_mfa_sent() : '';
		await tick();
		try {
			await api.sendMfaEmail();
			codeSent = true;
			sentText = '';
			await tick();
			sentText = m.login_mfa_sent();
		} catch (err) {
			if (err instanceof api.ApiError && err.code === 'mfa_expired') {
				// Re-enabled first: the password step's focus goes to CONNECT.
				sending = false;
				await toPasswordStep(mfaExpiredText(String(err.params.reason ?? '')));
				return;
			}
			// A definite "nothing was mailed" (a 400, a 429, the mail not sent) leaves no code for
			// this challenge; only an answer that never arrived may have mailed one.
			const definite =
				err instanceof api.ApiError &&
				(err.status === 400 || err.status === 429 || err.code === 'mail_unavailable');
			if (definite) sendTried = triedBefore;
			// Upstream's cooldown belongs to the account, not this challenge. With a code sent for
			// this challenge, it still works and its line stays; with none even tried, the mail that
			// set the cooldown was for an earlier sign-in, whose code no longer works: say so.
			if (err instanceof api.ApiError && err.params.reason === 'resendCooldown') {
				countDownResend(Number(err.params.retry_after) || 60);
				// Emptied first, so the sentence is announced even when it repeats.
				sentText = '';
				await tick();
				sentText = codeSent
					? m.login_mfa_cooldown_still_works()
					: triedBefore
						? m.login_mfa_cooldown_wait()
						: m.login_mfa_cooldown_earlier();
			} else {
				// A refused resend leaves the challenge's earlier code working (and its line); one whose
				// answer was lost may have replaced it, which upstream alone knows.
				errorMessage = failureText(err);
			}
		} finally {
			sending = false;
		}
		codeInput?.focus();
	}

	// v53: the app's own login limit answers 429 `rate_limited` with how long it holds (up to
	// 15 minutes), so it says that; any other 429 (from in front of the app) keeps the old words.
	function loginLimitText(err: unknown): string {
		const retryAfter =
			err instanceof api.ApiError && err.code === 'rate_limited'
				? Number(err.params.retry_after)
				: 0;
		if (!(retryAfter > 0)) return m.login_error_rate_limited();
		return m.login_error_rate_limited_for(counted(Math.ceil(retryAfter / 60)));
	}

	/** What a failed sign-in (either step) says. v71: a code with its own sentence first; then a
	 * 401 is the credentials, a 429 the limit, a 5xx the server, anything else unreachable. */
	function failureText(err: unknown): string {
		const status = err instanceof api.ApiError ? err.status : 0;
		if (err instanceof api.ApiError && err.code && OWN_SENTENCE.has(err.code))
			return apiErrorText(err);
		if (status === 401) return m.login_error_rejected();
		if (status === 429) return loginLimitText(err);
		// v47: a 500 is the service answering with a problem; a 502/503/504 is the proxy in
		// front saying the api isn't there (a deploy, a restart), which is "couldn't reach",
		// the same words the layout's unreachable screen uses for it.
		return status >= 500 && ![502, 503, 504].includes(status)
			? m.login_error_server()
			: m.login_error_unreachable();
	}

	async function signedIn() {
		// v34.2: a fresh identity never inherits another's cached progress ids -- the
		// logout reset can't run when the last session simply expired in a closed tab.
		clearProgress();
		// v65: back to what sent here (a share opened signed out), if it's a path of this
		// site; read from `location`, since `replaceState` can leave `page.url` stale (v54).
		const next = safeNext(new URLSearchParams(window.location.search).get('next'));
		// The share replaces this /login entry (the redirect that brought here replaced the
		// share's own): a Back then leaves, never re-running the login to a live confirm.
		if (next) {
			// eslint-disable-next-line svelte/no-navigation-without-resolve -- `next` is a same-origin path safeNext checked, query included, which resolve() can't type
			await goto(next, { replaceState: true });
		} else {
			await goto(resolve('/'));
		}
	}

	async function onsubmit(event: SubmitEvent) {
		event.preventDefault();
		if (step === 'mfa') return verify();
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
			const answer = await api.login(email, password);
			if ('mfa_required' in answer) {
				submitting = false;
				await toSecondStep(answer.methods);
				return;
			}
			await signedIn();
		} catch (err) {
			// The 401 copy is deliberately generic — it matches
			// the backend's non-disclosure between an unknown/wrong-password upstream
			// account and an allowlist rejection. Anything else (CORS misconfigured,
			// the API unreachable, a 5xx) is a categorically different problem and
			// must not be reported as "wrong password" — that reads as a lie to
			// whoever's actually blocked by a config/network issue, not a bad
			// credential.
			credentialsRejected = err instanceof api.ApiError && err.status === 401;
			errorMessage = failureText(err);
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

	async function verify() {
		if (sending) return;
		// An email code only exists once one was sent for this challenge: before that, any code is
		// a wrong one upstream, a try spent for nothing.
		if (method === 'email' && !sendTried) {
			errorMessage = '';
			await tick();
			errorMessage = m.login_mfa_send_first();
			codeInput?.focus();
			return;
		}
		if (!code.trim()) {
			errorMessage = '';
			await tick();
			errorMessage = m.login_mfa_missing();
			codeMissing = true;
			codeInput?.focus();
			return;
		}
		// The shape upstream accepts (spaces, and a recovery code's dash, don't count): anything
		// else would only spend one of the challenge's 5 tries.
		const bare = code.replace(method === 'recovery' ? /[\s-]/g : /\s/g, '');
		if (method === 'recovery' ? !/^[a-z2-7]{10}$/i.test(bare) : !/^\d{6}$/.test(bare)) {
			errorMessage = '';
			await tick();
			errorMessage =
				method === 'recovery' ? m.login_mfa_format_recovery() : m.login_mfa_format_digits();
			codeMissing = true;
			codeInput?.focus();
			return;
		}
		codeMissing = codeRejected = false;
		submitting = true;
		errorMessage = '';
		try {
			await api.verifyMfa(method, code.trim());
			await signedIn();
		} catch (err) {
			submitting = false;
			const apiErr = err instanceof api.ApiError ? err : null;
			// The challenge is gone (expired, tries used up, replaced), or the last try just
			// failed: only a new password step starts another.
			if (apiErr?.code === 'mfa_expired') {
				await toPasswordStep(mfaExpiredText(String(apiErr.params.reason ?? '')));
				return;
			}
			if (apiErr?.code === 'mfa_code_invalid' && Number(apiErr.params.attempts_left) === 0) {
				await toPasswordStep(m.login_mfa_expired_tries());
				return;
			}
			// Off the allowlist since the password step: refused as a password would be.
			if (apiErr?.code === 'invalid_credentials') {
				await toPasswordStep(m.login_error_rejected());
				return;
			}
			codeRejected = apiErr?.code === 'mfa_code_invalid';
			errorMessage = failureText(err);
			await tick();
			if (codeRejected) {
				codeInput?.focus();
				codeInput?.select();
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
			{#if step === 'mfa'}
				<h1 class="mono">{m.login_mfa_heading()}</h1>
				<p class="hint">{m.login_mfa_account({ email: email.trim() })}</p>
			{:else}
				<h1 class="mono">{m.login_heading()}</h1>
				<!-- v43 (F31): which account this wants. -->
				<p class="hint">{m.login_hint()}</p>
			{/if}
			{#if forShare}
				<p class="hint">{m.login_share_waiting()}</p>
			{/if}
			<!-- v47: arrived here because the session ended mid-page (a 401), not by signing out. -->
			<p class="ended" class:reserved={showEnded} role="status">
				{errorMessage ? '' : endedText}
			</p>
		</div>

		{#if step === 'mfa'}
			{#if methods.length > 1}
				<div class="methods">
					<span class="label" id="mfa-methods-label">{m.login_mfa_methods()}</span>
					<div class="choice-group" role="group" aria-labelledby="mfa-methods-label">
						{#each methods as option (option)}
							<button
								type="button"
								aria-pressed={method === option}
								disabled={submitting || sending}
								onclick={() => chooseMethod(option)}>{METHOD_LABEL[option]()}</button
							>
						{/each}
					</div>
				</div>
			{/if}

			<label class="form-field">
				<!-- Named by its label alone: the hint inside this label describes it instead. -->
				<span class="label" id="mfa-code-label">{m.login_mfa_code()}</span>
				<input
					bind:this={codeInput}
					class="well code"
					class:reading={method !== 'recovery'}
					type="text"
					name="code"
					autocomplete="one-time-code"
					inputmode={method === 'recovery' ? 'text' : 'numeric'}
					autocapitalize="off"
					spellcheck="false"
					bind:value={code}
					oninput={() => (codeMissing = false)}
					disabled={submitting}
					aria-invalid={codeRejected || codeMissing ? 'true' : undefined}
					aria-labelledby="mfa-code-label"
					aria-describedby="mfa-hint login-error"
				/>
				<span class="field-hint" id="mfa-hint">{METHOD_HINT[method]()}</span>
			</label>

			{#if method === 'email'}
				<div class="send-row">
					<button
						type="button"
						class="btn small"
						disabled={submitting || sending || resendIn > 0}
						onclick={sendCode}
					>
						{sending
							? m.login_mfa_sending()
							: resendIn > 0
								? (codeSent ? m.login_mfa_resend_in : m.login_mfa_send_in)(counted(resendIn))
								: codeSent
									? m.login_mfa_resend()
									: m.login_mfa_send()}
					</button>
					<span class="sent" role="status">{sentText}</span>
				</div>
			{/if}
		{:else}
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
		{/if}

		<button
			type="submit"
			class="btn connect"
			disabled={submitting || sending}
			bind:this={connectButton}
		>
			{#if step === 'mfa'}
				{submitting ? m.login_mfa_verifying() : m.login_mfa_verify()}
			{:else}
				{submitting ? m.login_connecting() : m.login_connect()}
			{/if}
		</button>

		{#if step === 'mfa'}
			<button
				type="button"
				class="back"
				disabled={submitting || sending}
				onclick={() => toPasswordStep()}
			>
				{m.login_mfa_back()}
			</button>
		{/if}

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

	/* v47: clipped sideways: the needle moves by transform across a box the dial's width, which
	   at mid-sweep would otherwise widen the page on a phone. Clip, not hidden: the frequency
	   labels below the dial still show. */
	.dial {
		position: relative;
		overflow-x: clip;
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
		/* v71: the second step echoes the typed address, which may have no break point. */
		overflow-wrap: anywhere;
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

	/* v71: the second step. The method choice sits on its own line under its label. */
	.methods {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	/* The card's width, split evenly, so three methods never wrap into a broken edge; a long
	   label (hu) wraps inside its own segment instead. */
	.methods .choice-group {
		display: flex;
		flex-wrap: nowrap;
		align-self: stretch;
	}

	.methods .choice-group button {
		flex: 1 1 0;
		min-width: 0;
		padding-inline: var(--space-2);
		text-wrap: balance;
	}

	/* A phone's narrow card can't hold "authenticator" or "helyreállító kód" in a third of its
	   width: the segments stack, one per line, the edge between them on top instead. */
	@media (max-width: 24rem) {
		.methods .choice-group {
			flex-direction: column;
		}

		.methods .choice-group button + button {
			border-left: none;
			border-top: 1px solid var(--line-control);
		}

		.methods .choice-group button:first-child {
			border-radius: 3px 3px 0 0;
		}

		.methods .choice-group button:last-child {
			border-radius: 0 0 3px 3px;
		}
	}

	/* A 6-digit code is a reading: mono, spaced, so a mistyped digit stands out. */
	.code.reading {
		font-family: var(--font-mono);
		font-variant-numeric: tabular-nums;
		letter-spacing: 0.3em;
	}

	.send-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	.sent {
		font-size: var(--fs-meta);
		color: var(--text-muted);
	}

	/* The way back is a quiet text action under the one real button, not a second button. */
	.back {
		align-self: center;
		background: none;
		border: none;
		padding: var(--space-1) var(--space-2);
		font-size: var(--fs-detail);
		color: var(--text-muted);
		text-decoration: underline;
		text-underline-offset: 0.2em;
		cursor: pointer;
	}

	@media (hover: hover) {
		.back:hover:not(:disabled) {
			color: var(--text-primary);
		}
	}

	.back:disabled {
		color: var(--text-dim);
		cursor: default;
	}

	@media (pointer: coarse) {
		.back {
			min-height: 2.75rem;
		}
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
