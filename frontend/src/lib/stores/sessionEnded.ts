/** v47: the session ended under this tab, found by the layout's load on a navigation (a
 * redirect can't carry page state), so `/login` can say why once, as it does when a request's
 * 401 sends the tab there. Kept in sessionStorage (this tab only) so it survives the reload `/`
 * does when the store is reset under it; a page without storage just doesn't say why.
 * Consumed by the first read. */
const KEY = 'spotdl:session-ended';

/** v69: `access_removed` -- the server said the session was ended by a removal from the
 * allowlist, so /login says that rather than "your session ended". */
export type SessionEndReason = 'ended' | 'access_removed';

export function markSessionEnded(reason: SessionEndReason = 'ended'): void {
	try {
		sessionStorage.setItem(KEY, reason === 'access_removed' ? reason : '1');
	} catch {
		// No storage: /login only loses the reason.
	}
}

export function consumeSessionEnded(): SessionEndReason | null {
	try {
		const was = sessionStorage.getItem(KEY);
		sessionStorage.removeItem(KEY);
		return was === 'access_removed' ? 'access_removed' : was === '1' ? 'ended' : null;
	} catch {
		return null;
	}
}
