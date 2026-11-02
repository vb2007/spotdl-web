/** v67 (U10): the stats charts' crosshair by keyboard. A focused chart steps its crosshair one
 * bucket per arrow key, jumps to an end with Home/End, and clears it with Esc. The keys are
 * listed in the help overlay as `chart-step` (keyboard/bindings.ts, handled here, not by the
 * registry). Returns the bucket to show, `null` to clear, or `undefined` when the key isn't the
 * chart's (the event then goes on to the page's own handlers). */
export function stepCrosshair(
	event: KeyboardEvent,
	current: number | null,
	n: number
): number | null | undefined {
	if (n === 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return undefined;
	switch (event.key) {
		// From nothing picked, either arrow starts on the newest bucket: the value the chart (a
		// slider) reports while nothing is picked, so a first arrow never moves the other way.
		case 'ArrowRight':
		case 'ArrowUp':
			return current === null ? n - 1 : Math.min(n - 1, current + 1);
		case 'ArrowLeft':
		case 'ArrowDown':
			return current === null ? n - 1 : Math.max(0, current - 1);
		case 'Home':
			return 0;
		case 'End':
			return n - 1;
		case 'Escape':
			// Nothing shown: Esc is the page's (closing an overlay, leaving a field).
			return current === null ? undefined : null;
		default:
			return undefined;
	}
}
