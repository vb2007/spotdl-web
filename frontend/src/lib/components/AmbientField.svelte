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
	/** Slate's peak per unit of amber peak. Luminance-equal over --bg-0 is ~1.25, but after
	 * 8-bit rounding that can land slate one code value brighter than amber at some heights;
	 * 1.15 keeps slate at or under amber's rendered luminance across the measured range (up to
	 * 2560×1440); far taller viewports can differ by one blue code value (see `peaks`). */
	const SLATE_PER_AMBER = 1.15;

	/** Peak strength is a contrast budget, not taste. The old body ellipse's centre sat
	 * off-screen (-10%), so the brightest pixel anyone saw was its top edge, which dims as the
	 * viewport grows taller: amber at 5% × (1 − 0.1·height / 300px), a 300px linear falloff.
	 * The new peak sits under the cursor, over any text, so it is held to exactly that visible
	 * maximum: text under the brightest point keeps today's contrast on every viewport. */
	function peaks(height: number): { live: string; rest: string } {
		const amber = Math.max(0, 0.05 * (1 - (0.1 * height) / 300));
		return {
			live: `${(amber * 100).toFixed(2)}%`,
			rest: `${(amber * SLATE_PER_AMBER * 100).toFixed(2)}%`
		};
	}

	onMount(() => {
		const finePointer = matchMedia('(hover: hover) and (pointer: fine)');
		const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');

		// The glow's transform is an offset from its CSS home (left 50%, top -10% of the
		// field), so (0, 0) is home and the viewport size only turns a pointer position into
		// an offset (and sets the peaks). ResizeObserver hands that size over without a
		// forced layout, so the frame loop itself never reads layout. One read here seeds it,
		// so a pointer already moving at mount aims right before the first observation lands.
		let width = innerWidth;
		let height = innerHeight;

		let x = 0;
		let y = 0;
		let targetX = 0;
		let targetY = 0;
		/** The last pointer position inside the window, or null once it left (target: home). */
		let pointer: { x: number; y: number } | null = null;
		let frame = 0;
		/** The previous frame's timestamp; -1 means the loop was just woken. */
		let last = -1;

		/** Turns the pointer position into the glow's offset from home. Also re-run on resize:
		 * home moves with the viewport, so a still pointer would otherwise end up off-centre. */
		function aim() {
			targetX = pointer ? pointer.x - width / 2 : 0;
			targetY = pointer ? pointer.y + height * 0.1 : 0;
		}

		const resize = new ResizeObserver(([entry]) => {
			const dWidth = entry.contentRect.width - width;
			const dHeight = entry.contentRect.height - height;
			width = entry.contentRect.width;
			height = entry.contentRect.height;
			const peak = peaks(height);
			field.style.setProperty('--live-peak', peak.live);
			field.style.setProperty('--rest-peak', peak.rest);
			if (!following || !pointer) return;
			// Home just moved with the viewport (a maximize, a scrollbar appearing). Shift the
			// offset by the opposite amount, before this frame paints, so the glow stays where it
			// was on screen instead of lurching off the cursor and easing back.
			x -= dWidth / 2;
			y += dHeight * 0.1;
			glow.style.transform = `translate3d(${x}px, ${y}px, 0)`;
			aim();
			wake();
		});
		resize.observe(field);

		function tick(now: number) {
			// The first frame after a wake has no previous timestamp (and a frame's timestamp can
			// precede the pointermove that woke it), so it counts as one 60Hz frame. Later
			// frames clamp dt so a long-throttled frame eases in rather than jumping.
			const dt = last < 0 ? 1000 / 60 : Math.min(Math.max(now - last, 0), 64);
			const k = 1 - Math.exp(-dt / TAU);
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
			last = -1;
			frame = requestAnimationFrame(tick);
		}

		function sleep() {
			cancelAnimationFrame(frame);
			frame = 0;
		}

		function onPointerMove(event: PointerEvent) {
			// A touch on a hybrid device still fires pointermove; the field never chases a tap.
			if (event.pointerType === 'touch') return;
			pointer = { x: event.clientX, y: event.clientY };
			aim();
			wake();
		}

		function onPointerOut(event: PointerEvent) {
			// The pointer left the window: drift back home rather than freeze at the edge. A
			// touch pointer also fires a null-relatedTarget pointerout after every tap on a
			// hybrid device; a tap never drives the field, so that one is ignored too.
			if (event.pointerType === 'touch' || event.relatedTarget !== null) return;
			pointer = null;
			aim();
			wake();
		}

		function onVisibilityChange() {
			if (document.hidden) sleep();
			else wake();
		}

		/** Following needs a hovering fine pointer and motion allowed. Otherwise the glow sits
		 * at home with no pointer listener and no frame loop at all. */
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
				pointer = null;
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

	/* About the old body ellipse's footprint (its visible radii were ~540×300px, centred at
	   50% -10%; these are 576×352px), as an element the frame loop can move by transform
	   alone. */
	.glow {
		position: absolute;
		left: 50%;
		top: -10%;
		width: 72rem;
		height: 44rem;
		margin: -22rem 0 0 -36rem;
	}

	/* Promoted only while it can move, so the gradient is rasterized once: each frame then
	   costs a one-element style update and a commit, with no layout and no repaint. A static
	   field (touch, reduced motion) stays unpromoted. */
	.glow.following {
		will-change: transform;
	}

	/* The peaks come from `peaks()` (the old glow's brightest visible pixel for this viewport
	   height); the fallbacks are its value at a 900px-tall viewport. */
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
		--peak: var(--rest-peak, 4.03%);
	}

	.live {
		--tone: var(--signal);
		--peak: var(--live-peak, 3.5%);
	}

	/* A crossfade, never both at full: the two tones' sum stays inside the budget above. */
	.tone.off {
		opacity: 0;
	}
</style>
