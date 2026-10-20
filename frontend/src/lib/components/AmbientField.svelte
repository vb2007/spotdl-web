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
	/** Below this distance (px) the glow snaps to its target and the glide ends. */
	const SETTLE = 0.5;
	/** Keyframe spacing of a glide, in ms. The compositor interpolates linearly between samples,
	 * so a glide is the exponential curve as a polyline: at one sample per two 60Hz frames it
	 * stays within ~0.4% of the distance still to go, invisible in a soft 576px gradient, and a
	 * retarget stays cheap (fewer keyframes to build per pointer move). */
	const STEP = 1000 / 30;
	/** Slate's peak per unit of amber peak. Luminance-equal over --bg-0 is ~1.25, but after
	 * 8-bit rounding that can land slate one code value brighter than amber at some heights;
	 * 1.15 keeps slate at or under amber's rendered luminance across the measured range (up to
	 * 2560×1440); far taller viewports can differ by one blue code value (DESIGN.md §6,
	 * Ambient field, "Contrast budget"). */
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
		// i18n-ignore: media queries
		const finePointer = matchMedia('(hover: hover) and (pointer: fine)');
		// i18n-ignore: a media query
		const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');

		// The glow's transform is an offset from its CSS home (left 50%, top -10% of the
		// field), so (0, 0) is home and the viewport size only turns a pointer position into
		// an offset (and sets the peaks). ResizeObserver hands that size over without a
		// forced layout, so moving the glow never reads layout. One read here seeds it,
		// so a pointer already moving at mount aims right before the first observation lands.
		// The root's client size excludes a classic scrollbar, matching the fixed field.
		let width = document.documentElement.clientWidth;
		let height = document.documentElement.clientHeight;

		/** The glow's resting offset from home while no glide runs (also its inline transform). */
		let x = 0;
		let y = 0;
		let targetX = 0;
		let targetY = 0;
		/** The last pointer position inside the window, or null once it left (target: home). */
		let pointer: { x: number; y: number } | null = null;
		/** A native drag (a link, a text selection) is in progress: the browser cancels the
		 * pointer and sends no pointermove until the drop. */
		let dragging = false;
		/** The running (or finished, held) glide: a Web Animation to the target, its keyframes
		 * sampled from the exponential approach. The compositor plays it, so the main thread does no
		 * per-frame work; a new target just replaces it. */
		let glide: { animation: Animation; points: [number, number][]; duration: number } | null = null;

		/** Turns the pointer position into the glow's offset from home. Also re-run on resize:
		 * home moves with the viewport, so a still pointer would otherwise end up off-centre. */
		function aim() {
			targetX = pointer ? pointer.x - width / 2 : 0;
			targetY = pointer ? pointer.y + height * 0.1 : 0;
		}

		/** Where the glow is right now. Read off the running glide's own clock and keyframes (the
		 * same linear interpolation the animation applies), never from computed style, so asking
		 * forces no style or layout. */
		function position(): [number, number] {
			if (!glide) return [x, y];
			const { points, duration } = glide;
			const time = Number(glide.animation.currentTime ?? 0);
			if (time >= duration) return points[points.length - 1];
			const at = (Math.max(time, 0) / duration) * (points.length - 1);
			const i = Math.floor(at);
			const f = at - i;
			const [x0, y0] = points[i];
			const [x1, y1] = points[i + 1];
			return [x0 + (x1 - x0) * f, y0 + (y1 - y0) * f];
		}

		/** Ends any glide and pins the glow at (nx, ny). */
		function place(nx: number, ny: number) {
			glide?.animation.cancel();
			glide = null;
			x = nx;
			y = ny;
			glow.style.transform = nx || ny ? `translate3d(${nx}px, ${ny}px, 0)` : '';
		}

		const resize = new ResizeObserver(([entry]) => {
			const dWidth = entry.contentRect.width - width;
			const dHeight = entry.contentRect.height - height;
			width = entry.contentRect.width;
			height = entry.contentRect.height;
			const peak = peaks(height);
			field.style.setProperty('--live-peak', peak.live);
			field.style.setProperty('--rest-peak', peak.rest);
			if (!following) return;
			// Home just moved with the viewport (a maximize, a scrollbar appearing). Wherever the
			// glow is off home (under the pointer, drifting back, or paused mid-drift in a hidden
			// tab), shift its offset by the opposite amount before this frame paints, so it stays
			// where it was on screen instead of lurching sideways. At home it moves with home.
			const [px, py] = position();
			if (px !== 0 || py !== 0) place(px - dWidth / 2, py + dHeight * 0.1);
			aim();
			wake();
		});
		resize.observe(field);

		/** Starts a glide from wherever the glow is now to the current target. Its keyframes are
		 * the exponential approach x(t) = target + (x0 − target)·e^(−t/TAU), sampled every STEP
		 * until both axes are within SETTLE, then the exact target (the snap). */
		function wake() {
			if (!following || document.hidden) return;
			const [fromX, fromY] = position();
			const dx = fromX - targetX;
			const dy = fromY - targetY;
			const distance = Math.max(Math.abs(dx), Math.abs(dy));
			if (distance < SETTLE) {
				place(targetX, targetY);
				return;
			}
			const duration = TAU * Math.log(distance / SETTLE);
			const steps = Math.max(1, Math.ceil(duration / STEP));
			const points: [number, number][] = [];
			for (let i = 0; i < steps; i++) {
				const decay = Math.exp(-((i / steps) * duration) / TAU);
				points.push([targetX + dx * decay, targetY + dy * decay]);
			}
			points.push([targetX, targetY]);
			glide?.animation.cancel();
			const animation = glow.animate(
				points.map(([px, py]) => ({ transform: `translate3d(${px}px, ${py}px, 0)` })),
				{ duration, fill: 'forwards' }
			);
			glide = { animation, points, duration };
		}

		/** A hidden tab freezes the glide where it is (the next wake resumes from there). */
		function sleep() {
			glide?.animation.pause();
		}

		function onPointerMove(event: PointerEvent) {
			// A touch on a hybrid device still fires pointermove; the field never chases a tap.
			if (event.pointerType === 'touch') return;
			dragging = false;
			pointer = { x: event.clientX, y: event.clientY };
			aim();
			wake();
		}

		function onPointerOut(event: PointerEvent) {
			// The pointer left the window: drift back home rather than freeze at the edge. A
			// touch pointer also fires a null-relatedTarget pointerout after every tap on a
			// hybrid device; a tap never drives the field, so that one is ignored too.
			// A native drag also cancels the pointer and fires a null-relatedTarget pointerout
			// while the cursor is still on the page, so that one doesn't count as leaving.
			if (event.pointerType === 'touch' || event.relatedTarget !== null || dragging) return;
			pointer = null;
			aim();
			wake();
		}

		function onPointerCancel(event: PointerEvent) {
			if (event.pointerType !== 'touch') dragging = true;
		}

		function onVisibilityChange() {
			if (document.hidden) sleep();
			else wake();
		}

		/** Following needs a hovering fine pointer and motion allowed. Otherwise the glow sits
		 * at home with no pointer listener and no animation at all. */
		function configure() {
			const next = finePointer.matches && !reducedMotion.matches;
			if (next === following) return;
			following = next;
			if (following) {
				window.addEventListener('pointermove', onPointerMove, { passive: true });
				window.addEventListener('pointerout', onPointerOut, { passive: true });
				window.addEventListener('pointercancel', onPointerCancel, { passive: true });
			} else {
				window.removeEventListener('pointermove', onPointerMove);
				window.removeEventListener('pointerout', onPointerOut);
				window.removeEventListener('pointercancel', onPointerCancel);
				pointer = null;
				dragging = false;
				targetX = targetY = 0;
				place(0, 0);
			}
		}

		configure();
		finePointer.addEventListener('change', configure);
		reducedMotion.addEventListener('change', configure);
		document.addEventListener('visibilitychange', onVisibilityChange);

		return () => {
			glide?.animation.cancel();
			resize.disconnect();
			finePointer.removeEventListener('change', configure);
			reducedMotion.removeEventListener('change', configure);
			document.removeEventListener('visibilitychange', onVisibilityChange);
			window.removeEventListener('pointermove', onPointerMove);
			window.removeEventListener('pointerout', onPointerOut);
			window.removeEventListener('pointercancel', onPointerCancel);
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
	   50% -10%; these are 576×352px), as an element a Web Animation can move by transform
	   alone. */
	.glow {
		position: absolute;
		left: 50%;
		top: -10%;
		width: 72rem;
		height: 44rem;
		margin: -22rem 0 0 -36rem;
	}

	/* Promoted only while it can move, so the gradient is rasterized once and a glide runs on
	   the compositor: only starting one costs a one-element style update, with no layout and no
	   repaint. A static field (touch, reduced motion) stays unpromoted. */
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
