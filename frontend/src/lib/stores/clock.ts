import { readable } from 'svelte/store';

/** v47 (F33): one 1s clock for every countdown on screen, instead of an interval per
 * Countdown (six open waiting tracks were six timers). It ticks only while something is
 * subscribed, and stops with the last one. */
export const clock = readable(Date.now(), (set) => {
	set(Date.now());
	const id = setInterval(() => set(Date.now()), 1000);
	return () => clearInterval(id);
});
