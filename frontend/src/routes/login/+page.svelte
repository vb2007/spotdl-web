<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';

	let email = $state('');
	let password = $state('');
	let submitting = $state(false);
	let errorMessage = $state('');

	async function onsubmit(event: SubmitEvent) {
		event.preventDefault();
		submitting = true;
		errorMessage = '';
		try {
			await api.login(email, password);
			await goto(resolve('/'));
		} catch (err) {
			// "Invalid credentials." is deliberately generic for a real 401 — matches
			// the backend's non-disclosure between an unknown/wrong-password upstream
			// account and an allowlist rejection. Anything else (CORS misconfigured,
			// the API unreachable, a 5xx) is a categorically different problem and
			// must not be reported as "wrong password" — that reads as a lie to
			// whoever's actually blocked by a config/network issue, not a bad
			// credential.
			errorMessage =
				err instanceof api.ApiError && err.status === 401
					? 'Invalid credentials.'
					: 'Could not reach the server. Check your connection and try again.';
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>spotdl-web — sign in</title>
</svelte:head>

<main class="stage">
	<div class="ident">
		<span class="label">SPOTDL // WEB</span>
		<span class="label dim">SIGNAL RECEIVER</span>
	</div>

	<form class="panel" {onsubmit}>
		<div class="dial" aria-hidden="true">
			{#each Array(21) as _, i (i)}
				<span class="tick" class:major={i % 5 === 0}>
					{#if i % 5 === 0}
						<span class="freq mono">{(88 + (i / 5) * 4).toFixed(1)}</span>
					{/if}
				</span>
			{/each}
			<span class="needle" class:sweeping={submitting}></span>
		</div>

		<h1 class="mono">TUNE IN</h1>

		<label class="field">
			<span class="label">Email</span>
			<input
				type="email"
				name="email"
				autocomplete="email"
				required
				bind:value={email}
				disabled={submitting}
			/>
		</label>

		<label class="field">
			<span class="label">Password</span>
			<input
				type="password"
				name="password"
				autocomplete="current-password"
				required
				bind:value={password}
				disabled={submitting}
				aria-describedby="login-error"
			/>
		</label>

		<button type="submit" class="connect" disabled={submitting}>
			{submitting ? 'CONNECTING…' : 'CONNECT'}
		</button>

		<p id="login-error" class="error mono" role="alert" aria-live="polite">
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
		font-size: 0.5625rem;
		color: var(--text-dim);
		white-space: nowrap;
	}

	.tick.major {
		height: 0.875rem;
		border-left-color: var(--text-dim);
	}

	.needle {
		position: absolute;
		bottom: -1px;
		left: 0;
		width: 2px;
		height: 1.5rem;
		background: var(--signal);
		box-shadow: 0 0 6px 1px var(--signal-glow);
		transform: translateX(0);
	}

	.needle.sweeping {
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

	h1 {
		font-size: 0.8125rem;
		letter-spacing: 0.16em;
		color: var(--text-muted);
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	input {
		background: var(--bg-0);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-3);
		box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.5);
	}

	input:focus-visible {
		border-color: var(--signal-dim);
	}

	.connect {
		margin-top: var(--space-2);
		background: var(--bg-2);
		border: 1px solid var(--line-bright);
		border-radius: 4px;
		padding: var(--space-3);
		font-family: var(--font-mono);
		font-weight: 600;
		letter-spacing: 0.08em;
		cursor: pointer;
		transition: background var(--dur-fast) var(--ease-signal);
	}

	.connect:hover:not(:disabled),
	.connect:focus-visible {
		background: var(--bg-3);
		border-color: var(--signal);
		box-shadow: 0 0 12px -2px var(--signal-glow);
	}

	.connect:disabled {
		color: var(--text-dim);
		cursor: progress;
	}

	.error {
		min-height: 1.25rem;
		color: var(--fail);
		font-size: 0.8125rem;
		text-align: center;
	}
</style>
