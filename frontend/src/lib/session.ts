/** v62 (F9): a sign-in or sign-out in one tab, pushed to the others.
 *
 * The session cookie is shared by every tab, so a sign-out (or another identity signing in) in
 * one tab changes who the others are, too. Until v62 a tab noticed only on its next request: a
 * 401 from its 5s worker poll (on `/`), a stream reconnect's `/api/auth/me` check, or the next
 * navigation. Those stay as the fallback; this tells the other tabs at once, through a
 * `BroadcastChannel`. A channel never receives its own messages, so the tab that acted isn't
 * told about itself. Where the browser has no `BroadcastChannel`, nothing is sent and the
 * fallback does it all.
 *
 * Messages carry the new identity's email only, no token or other data: every tab of the
 * origin can read them, and they already share the cookie that says the same.
 */

export type SessionMessage = { type: 'login'; email: string } | { type: 'logout' };

const CHANNEL = 'spotdl-session';
let channel: BroadcastChannel | null | undefined;

function shared(): BroadcastChannel | null {
	if (channel === undefined) {
		try {
			channel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel(CHANNEL);
		} catch {
			channel = null;
		}
	}
	return channel;
}

/** Tells the other tabs: called once the server has answered the sign-in or sign-out. */
export function announceSession(message: SessionMessage): void {
	try {
		shared()?.postMessage(message);
	} catch {
		// A closed channel or an unclonable message: the other tabs' fallback still catches it.
	}
}

/** Calls `handler` for every other tab's message; returns the unsubscribe. */
export function onSessionMessage(handler: (message: SessionMessage) => void): () => void {
	const target = shared();
	if (target === null) return () => {};
	const listener = (event: MessageEvent) => {
		const data = event.data as Partial<SessionMessage> | null;
		if (data?.type === 'logout') handler({ type: 'logout' });
		else if (data?.type === 'login' && typeof data.email === 'string')
			handler({ type: 'login', email: data.email });
	};
	target.addEventListener('message', listener);
	return () => target.removeEventListener('message', listener);
}

/** Set while this tab leaves because its session ended or changed (another tab's sign-out or
 * sign-in, a 401): a page's unsaved-edits guard (F6) lets that navigation through without
 * asking, since what it holds can't be saved by this session any more. */
let leaving = false;

export function leavingSession(): boolean {
	return leaving;
}

export function setLeavingSession(value: boolean): void {
	leaving = value;
}
