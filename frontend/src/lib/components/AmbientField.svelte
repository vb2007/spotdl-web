<script lang="ts">
	import { onMount } from 'svelte';

	/** v40: the page's ambient light, one fixed layer behind every route (mounted once in
	 * `routes/+layout.svelte`). It replaces the static amber ellipse `body` used to paint, and
	 * keeps that ellipse's composition as its home: top-centre, half off-screen.
	 *
	 * `live` is the only input. The field is a neutral slate at rest and warms to amber only
	 * while something is genuinely receiving (DESIGN.md §2's amber rule: the layer is
	 * permanent chrome, so it may not be amber permanently). The caller decides what "live"
	 * means; see the layout for why that is `/` with ≥1 active track and nowhere else. */
	let { live = false }: { live?: boolean } = $props();

	let field: HTMLDivElement;
	let glow: HTMLDivElement;
	/** Whether the glow follows the pointer (a hovering fine pointer, motion allowed). */
	let following = $state(false);

	/** Time constant of the follow, in ms: the glow covers ~63% of the remaining distance
	 * every TAU. Long enough to read as light catching up, short enough not to feel like lag. */
	const TAU = 180;
	/** Below this distance (px) the glow snaps to its target and the frame loop stops. */
	const SETTLE = 0.5;

	onMount(() => {
		const finePointer = matchMedia('(hover: hover) and (pointer: fine)');
		const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');

		// The glow's transform is an offset from its CSS home (left 50%, top -10% of the
		// field), so (0, 0) is home and nothing here needs the viewport size except turning
		// a pointer position into an offset. ResizeObserver hands that size over without a
		// forced layout, so the frame loop itself never reads layout.
		let width = 0;
		let height = 0;
		const resize = new ResizeObserver(([entry]) => {
			width = entry.contentRect.width;
			height = entry.contentRect.height;
		});
		resize.observe(field);

		let x = 0;
		let y = 0;
		let targetX = 0;
		let targetY = 0;
		let frame = 0;
		let last = 0;

		function tick(now: number) {
			// Clamp dt so a long-throttled frame eases in rather than jumping to the target.
			const k = 1 - Math.exp(-Math.min(now - last, 64) / TAU);
			last = now;
			x += (targetX - x) * k;
			y += (targetY - y) * k;
			if (Math.abs(targetX - x) < SETTLE && Math.abs(targetY - y) < SETTLE) {
				x = targetX;
				y = targetY;
				frame = 0;
			} else {
				frame = requestAnimationFrame(tick);
			}
			glow.style.transform = `translate3d(${x}px, ${y}px, 0)`;
		}

		function wake() {
			if (frame || !following || document.hidden) return;
			if (x === targetX && y === targetY) return;
			last = performance.now();
			frame = requestAnimationFrame(tick);
		}

		function sleep() {
			cancelAnimationFrame(frame);
			frame = 0;
		}

		function onPointerMove(event: PointerEvent) {
			// A touch on a hybrid device still fires pointermove; the field never chases a tap.
			if (event.pointerType === 'touch') return;
			targetX = event.clientX - width / 2;
			targetY = event.clientY + height * 0.1;
			wake();
		}

		function onPointerOut(event: PointerEvent) {
			// The pointer left the window: drift back home rather than freeze at the edge.
			if (event.relatedTarget !== null) return;
			targetX = 0;
			targetY = 0;
			wake();
		}

		function onVisibilityChange() {
			if (document.hidden) sleep();
			else wake();
		}

		/** Following needs a hovering fine pointer and motion allowed. Otherwise the glow sits
		 * at home with no listener and no frame loop at all. */
		function configure() {
			const next = finePointer.matches && !reducedMotion.matches;
			if (next === following) return;
			following = next;
			if (following) {
				window.addEventListener('pointermove', onPointerMove, { passive: true });
				window.addEventListener('pointerout', onPointerOut, { passive: true });
			} else {
				window.removeEventListener('pointermove', onPointerMove);
				window.removeEventListener('pointerout', onPointerOut);
				sleep();
				x = y = targetX = targetY = 0;
				glow.style.transform = '';
			}
		}

		configure();
		finePointer.addEventListener('change', configure);
		reducedMotion.addEventListener('change', configure);
		document.addEventListener('visibilitychange', onVisibilityChange);

		return () => {
			sleep();
			resize.disconnect();
			finePointer.removeEventListener('change', configure);
			reducedMotion.removeEventListener('change', configure);
			document.removeEventListener('visibilitychange', onVisibilityChange);
			window.removeEventListener('pointermove', onPointerMove);
			window.removeEventListener('pointerout', onPointerOut);
		};
	});
</script>

<div class="ambient-field" bind:this={field} aria-hidden="true">
	<div class="glow" class:following bind:this={glow}>
		<span class="tone rest" class:off={live}></span>
		<span class="tone live" class:off={!live}></span>
	</div>
</div>

<style>
	.ambient-field {
		position: fixed;
		inset: 0;
		z-index: -1;
		pointer-events: none;
		overflow: hidden;
		contain: strict;
	}

	/* The old body ellipse's footprint (radii 540×300px, centred at 50% -10%), as an element
	   the frame loop can move by transform alone. */
	.glow {
		position: absolute;
		left: 50%;
		top: -10%;
		width: 72rem;
		height: 44rem;
		margin: -22rem 0 0 -36rem;
	}

	/* Promoted only while it can move, so the gradient is rasterized once and every frame
	   after that is compositor-only. A static field (touch, reduced motion) stays unpromoted. */
	.glow.following {
		will-change: transform;
	}

	/* Peak strength is a contrast budget, not taste: neither tone may be brighter at its
	   centre than the old amber ellipse (#161410, 1.067:1 over --bg-0), so text that sits
	   over the brightest point keeps exactly today's contrast (DESIGN.md §2, Ambient field).
	   Slate at 6% and amber at 5% both land on that luminance. */
	.tone {
		position: absolute;
		inset: 0;
		background: radial-gradient(
			closest-side,
			color-mix(in srgb, var(--tone) var(--peak), transparent),
			color-mix(in srgb, var(--tone) calc(var(--peak) * 0.82), transparent) 18%,
			color-mix(in srgb, var(--tone) calc(var(--peak) * 0.5), transparent) 42%,
			color-mix(in srgb, var(--tone) calc(var(--peak) * 0.2), transparent) 66%,
			color-mix(in srgb, var(--tone) calc(var(--peak) * 0.05), transparent) 86%,
			transparent
		);
		transition: opacity var(--dur-slow) var(--ease-signal);
	}

	.rest {
		--tone: var(--text-muted);
		--peak: 6%;
	}

	.live {
		--tone: var(--signal);
		--peak: 5%;
	}

	/* A crossfade, never both at full: the two tones' sum stays inside the budget above. */
	.tone.off {
		opacity: 0;
	}
</style>
