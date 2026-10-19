/** v47: the session ended under this tab, found by the layout's load on a navigation (a
 * redirect can't carry page state), so `/login` can say why once, as it does when a request's
 * 401 sends the tab there. Consumed by the first read. */
let ended = false;

export function markSessionEnded(): void {
	ended = true;
}

export function consumeSessionEnded(): boolean {
	const was = ended;
	ended = false;
	return was;
}
