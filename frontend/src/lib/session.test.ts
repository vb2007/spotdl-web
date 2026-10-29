import { afterEach, describe, expect, it } from 'vitest';
import { announceSession, onSessionMessage, type SessionMessage } from '$lib/session';

/** Another tab: its own channel object on the same name. */
const otherTab = () => new BroadcastChannel('spotdl-session');
const settle = () => new Promise((done) => setTimeout(done, 20));

describe('v62 (F9) the session channel', () => {
	const cleanups: (() => void)[] = [];
	afterEach(() => cleanups.splice(0).forEach((undo) => undo()));

	it('delivers another tab’s sign-in and sign-out, and nothing else', async () => {
		const seen: SessionMessage[] = [];
		cleanups.push(onSessionMessage((m) => seen.push(m)));
		const tab = otherTab();
		cleanups.push(() => tab.close());

		tab.postMessage({ type: 'login', email: 'b@example.com' });
		tab.postMessage({ type: 'logout' });
		tab.postMessage({ type: 'login' });
		tab.postMessage('junk');
		await settle();

		expect(seen).toEqual([{ type: 'login', email: 'b@example.com' }, { type: 'logout' }]);
	});

	it('reaches the other tabs, never the tab that announced it', async () => {
		const own: SessionMessage[] = [];
		const theirs: unknown[] = [];
		cleanups.push(onSessionMessage((m) => own.push(m)));
		const tab = otherTab();
		tab.onmessage = (event) => theirs.push(event.data);
		cleanups.push(() => tab.close());

		announceSession({ type: 'logout' });
		await settle();

		expect(theirs).toEqual([{ type: 'logout' }]);
		expect(own).toEqual([]);
	});
});
