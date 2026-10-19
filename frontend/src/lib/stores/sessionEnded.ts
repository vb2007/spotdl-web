/** v47: the session ended under this tab, found by the layout's load on a navigation (a
 * redirect can't carry page state), so `/login` can say why once, as it does when a request's
 * 401 sends the tab there. Kept in sessionStorage (this tab only) so it survives the reload `/`
 * does when the store is reset under it; a page without storage just doesn't say why.
 * Consumed by the first read. */
const KEY = 'spotdl:session-ended';

export function markSessionEnded(): void {
	try {
		sessionStorage.setItem(KEY, '1');
	} catch {
		// No storage: /login only loses the reason.
	}
}

export function consumeSessionEnded(): boolean {
	try {
		const was = sessionStorage.getItem(KEY) === '1';
		sessionStorage.removeItem(KEY);
		return was;
	} catch {
		return false;
	}
}
