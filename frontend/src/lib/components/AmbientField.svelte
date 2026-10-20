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
	/** How long every glide lasts, in ms: by then the exponential approach is within SETTLE of
	 * its target from up to 4000px away. One fixed length lets every glide share one easing. */
	const HORIZON = TAU * Math.log(4000 / SETTLE);
	/** The glide's sample times, in ms. A glide is two keyframes (from, target) eased by
	 * EASING, the exponential approach as a `linear()` polyline through these samples: one per
	 * 60Hz frame for the first 200ms (the frames a retarget during movement actually shows, so
	 * each lands on a sample, not mid-chord), then one per two frames to 700ms, then 50ms apart,
	 * where under 2% of the distance is left and a chord's error stays under a pixel. */
	const SAMPLES = [
		...Array.from({ length: 12 }, (_, i) => (i * 1000) / 60),
		...Array.from({ length: 15 }, (_, i) => 200 + (i * 1000) / 30),
		...Array.from({ length: Math.ceil((HORIZON - 700) / 50) }, (_, i) => 700 + i * 50),
		HORIZON
	];
	/** Progress (0 → 1) at each sample: 1 − e^(−t/TAU), scaled to land exactly on 1 at HORIZON
	 * (the snap). */
	const PROGRESS = SAMPLES.map((t) => (1 - Math.exp(-t / TAU)) / (1 - Math.exp(-HORIZON / TAU)));
	const EASING = `linear(${PROGRESS.map((p, i) => `${+p.toFixed(5)} ${+((SAMPLES[i] / HORIZON) * 100).toFixed(3)}%`).join(', ')})`;
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
		/** The running (or finished, held) glide: a two-keyframe Web Animation from where the glow
		 * was to the target, eased by EASING. The compositor plays it, so the main thread does no
		 * per-frame work. It takes over once the pointer stops; while it moves, the frame loop
		 * below runs instead. */
		let glide: { animation: Animation; from: [number, number]; to: [number, number] } | null = null;
		/** A browser without CSS linear() easing (Safari before 17.2) never hands off to a glide:
		 * the frame loop runs to the snap, as in v40. */
		const linearEasing = CSS.supports('animation-timing-function', 'linear(0, 1)');
		/** The frame loop while the pointer moves (0 when it isn't scheduled). */
		let frame = 0;
		/** The previous frame's timestamp; -1 means the loop was just woken. */
		let last = -1;
		/** A wake (a pointer move, a leave, a resize) came in since the last frame. */
		let moved = false;
		/** The timestamp of the last frame that had a wake. */
		let wokeAt = 0;
		/** The display's frame interval for resuming from a glide: the shortest of the loop's last
		 * three measured frames, so one dropped frame doesn't stretch it. */
		let interval = 1000 / 60;
		const recent: number[] = [];
		/** `last` is a real frame's timestamp (not a wake's synthetic start), so its dt is a
		 * measurement. */
		let measured = false;
		/** A wake came in during a glide: the next frame pins the glide where it was one frame
		 * earlier and steps from there toward the new target, as v40's loop would have. */
		let repin = false;
		/** Set by pin() when it ends a glide mid-way: that moment's time, so the loop resumes from
		 * the glide's clock instead of taking a whole first-frame step on top of it. */
		let resume = -1;

		/** Turns the pointer position into the glow's offset from home. Also re-run on resize:
		 * home moves with the viewport, so a still pointer would otherwise end up off-centre. */
		function aim() {
			targetX = pointer ? pointer.x - width / 2 : 0;
			targetY = pointer ? pointer.y + height * 0.1 : 0;
		}

		/** Where the glow is right now. Read off the running glide's own clock through the same
		 * polyline the easing applies, never from computed style, so asking forces no style or
		 * layout. */
		function position(at?: number): [number, number] {
			if (!glide) return [x, y];
			const { from, to } = glide;
			const current = at ?? glide.animation.currentTime;
			// Cancelled from outside: the glow shows its inline transform again.
			if (current === null) return [x, y];
			const time = Number(current);
			if (time >= HORIZON) return to;
			let i = 0;
			while (SAMPLES[i + 1] <= time) i++;
			const f = Math.max(time - SAMPLES[i], 0) / (SAMPLES[i + 1] - SAMPLES[i]);
			const p = PROGRESS[i] + (PROGRESS[i + 1] - PROGRESS[i]) * f;
			return [from[0] + (to[0] - from[0]) * p, from[1] + (to[1] - from[1]) * p];
		}

		/** Whether a glide position is within SETTLE of the glide's target: where v40's loop had
		 * already snapped and stopped, while the glide runs on to HORIZON. */
		function settled([px, py]: [number, number]): boolean {
			return !!glide && Math.abs(glide.to[0] - px) < SETTLE && Math.abs(glide.to[1] - py) < SETTLE;
		}

		/** Ends a running glide where it is, so a resize (or a hidden tab) carries on from there.
		 * Within SETTLE of its target it counts as at rest, exactly on the target, as in v40. */
		function pin() {
			if (!glide) return;
			const at = position();
			if (settled(at)) {
				resume = -1;
				place(glide.to[0], glide.to[1]);
				return;
			}
			// The loop resumes from this moment on the glide's clock (a resize runs inside the
			// frame, where the timeline reads that frame's time), not with a fresh first frame.
			const now = document.timeline.currentTime;
			resume = now !== null ? Number(now) : -1;
			place(at[0], at[1]);
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
			pin();
			if (x !== 0 || y !== 0) place(x - dWidth / 2, y + dHeight * 0.1);
			aim();
			wake();
		});
		resize.observe(field);

		/** Starts a glide from (fromX, fromY) to the current target at time `start`: the
		 * exponential approach x(t) = target + (x0 − target)·e^(−t/TAU), as two keyframes and
		 * EASING, landing exactly on the target at HORIZON (the snap). */
		function glideFrom(fromX: number, fromY: number, start: number) {
			if (Math.max(Math.abs(fromX - targetX), Math.abs(fromY - targetY)) <= SETTLE) {
				place(targetX, targetY);
				return;
			}
			glide?.animation.cancel();
			const from: [number, number] = [fromX, fromY];
			const to: [number, number] = [targetX, targetY];
			const animation = glow.animate(
				[
					{ transform: `translate3d(${fromX}px, ${fromY}px, 0)` },
					{ transform: `translate3d(${targetX}px, ${targetY}px, 0)` }
				],
				{ duration: HORIZON, easing: EASING, fill: 'forwards' }
			);
			// Pinned, not left to the browser: an unpinned start time resolves a frame late, which
			// would hold `from` for a frame.
			animation.startTime = start;
			glide = { animation, from, to };
		}

		/** One frame of the follow while the pointer moves, exactly v40's loop. Retargeting a Web
		 * Animation on every move costs more main-thread time than this step (each new animation
		 * restyles the glow twice), so the loop runs while moves keep coming, and once ~50ms (three
		 * 60Hz frames, at any refresh rate) pass without one, so slow, sparse moves don't start and
		 * cancel a glide each time, it hands the rest of the approach to a compositor glide. The
		 * glide starts from the last frame's position, back-dated by this frame's step, so this
		 * frame shows exactly what the loop would have drawn. */
		function tick(now: number) {
			frame = 0;
			if (repin && glide) {
				// Where the glide was one frame ago, the frame v40's loop would have stepped from.
				// Read here, not in the pointermove: inside a frame Chrome's clock may already read
				// this frame's time, and off a 60Hz display it's only an estimate.
				const start = Number(glide.animation.startTime);
				const from = Math.max(now - interval, start);
				const at = position(from - start);
				if (settled(at)) {
					// v40 was at rest by then: a wake from rest, whose first frame counts as 1/60s.
					place(glide.to[0], glide.to[1]);
					last = -1;
				} else {
					place(at[0], at[1]);
					last = from;
				}
				measured = false;
			}
			repin = false;
			// The first frame after a wake from rest has no previous timestamp (and a frame's
			// timestamp can precede the pointermove that woke it), so it counts as one 60Hz frame;
			// a wake mid-glide resumes from the glide's own clock instead (the repin above, or
			// pin() for a resize). Later frames
			// clamp dt so a long-throttled frame eases in rather than jumping.
			const dt = last < 0 ? 1000 / 60 : Math.min(Math.max(now - last, 0), 64);
			if (measured && dt > 0 && dt < 40) {
				recent.push(dt);
				if (recent.length > 3) recent.shift();
				interval = Math.min(...recent);
			}
			last = now;
			measured = true;
			if (moved) wokeAt = now;
			moved = false;
			// 45, not 50: frame timestamps jitter, and the third 60Hz frame mustn't slip to a fourth.
			if (now - wokeAt >= 45 && linearEasing) {
				glideFrom(x, y, now - dt);
				return;
			}
			const k = 1 - Math.exp(-dt / TAU);
			const nx = x + (targetX - x) * k;
			const ny = y + (targetY - y) * k;
			if (Math.abs(targetX - nx) < SETTLE && Math.abs(targetY - ny) < SETTLE) {
				place(targetX, targetY);
				return;
			}
			place(nx, ny);
			frame = requestAnimationFrame(tick);
		}

		/** Follows the current target from wherever the glow is now (mid-glide included). */
		function wake() {
			if (!following || document.hidden) return;
			moved = true;
			if (glide) repin = true;
			if (!frame) {
				last = resume;
				measured = false;
				frame = requestAnimationFrame(tick);
			}
			resume = -1;
		}

		/** A hidden tab stops the loop and pins the glow where it is. A glide's pause() would only
		 * take effect on the next frame, which a hidden tab doesn't render, so its clock would run
		 * on. The approach has no memory, so following again on return is the same curve. */
		function sleep() {
			cancelAnimationFrame(frame);
			frame = 0;
			pin();
			resume = -1;
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
				cancelAnimationFrame(frame);
				frame = 0;
				place(0, 0);
			}
		}

		configure();
		finePointer.addEventListener('change', configure);
		reducedMotion.addEventListener('change', configure);
		document.addEventListener('visibilitychange', onVisibilityChange);

		return () => {
			cancelAnimationFrame(frame);
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
