// v66: a browser notification when one of the user's own jobs settles (done, complete or
// partial), from the in-page Notification API. No push service: it works while a dashboard tab
// (or the installed app) is open.
//
// Whose events: only the user's own. A dashboard in `mine` (always, for a non-admin) passes its
// own stream's events in (`observe`): that stream is the user's channel only. An admin whose
// dashboard shows `all` or `others` gets every user's events there, and those carry no owner
// (v17), so for them this module opens a stream of its own in `mine` (`setOwnStream`). It never
// announces anybody else's job.
//
// One tab announces: every dashboard tab receives the same event (the same `ts`), offers it on
// a `BroadcastChannel`, and after a short window the lowest tab id among the offers shows it.
// The notification's `tag` is the job's, so even two tabs without the channel replace each
// other's notification rather than stacking.
//
// The preference is server-side (`job_notifications`, `/account`). Every `/me` the pages read
// carries it, and it's taken as is until this tab saves (or hears another tab save): from then
// on a `/me` may have been read before that save (a hover preload), so the page asks the server
// afresh instead, and a save made meanwhile wins (live review round 2: ignoring every later
// `/me` kept a change made on another device out of the tab for its lifetime).
import { writable, get } from 'svelte/store';
import * as api from '$lib/api';
import * as m from '$lib/paraglide/messages';
import { formatNumber } from '$lib/i18n/format';

const CHANNEL = 'spotdl-web:job-notifications';
/** How long a tab collects the other tabs' offers before deciding. A background tab's timer can
 * run late (throttling); that only makes it wait longer, never announce twice. */
const CLAIM_WINDOW_MS = 400;
/** Decided events are remembered this long, so a late offer for one is ignored. */
const REMEMBER_MS = 10 * 60_000;
const OWN_STREAM_RETRY_MAX_MS = 30_000;
/** The server's heartbeat (stream.py, 15 s) plus a margin: a stream silent longer is dead, as
 * the dashboard's own stream decides (v62, F4). */
const OWN_STREAM_SILENT_MS = 18_000;

export type Permission = NotificationPermission | 'unsupported';

/** The user's saved switch, as this tab knows it. */
export const jobNotifications = writable(false);

type Message =
	| { type: 'offer'; key: string; tab: string }
	| { type: 'shown'; key: string }
	| { type: 'pref'; email: string; enabled: boolean };

const tabId =
	typeof crypto !== 'undefined' && 'randomUUID' in crypto
		? crypto.randomUUID()
		: `${Date.now()}-${Math.random()}`;

let adoptedFor: string | null = null;
/** This tab saved the switch, or heard another tab save it, since it adopted the identity. */
let knownLocally = false;
/** Counts this tab's saves and the ones it heard: a fresh read started before the latest is stale. */
let saves = 0;
let channel: BroadcastChannel | null | undefined;
/** Offers seen per event key, own included. */
const offers = new Map<string, { tabs: Set<string>; at: number }>();
/** Event keys some tab has decided (shown, or this tab's own decision), with when. */
const decided = new Map<string, number>();
let onActivate: ((jobId: string) => void) | null = null;
let ownStream: EventSource | null = null;
let ownStreamWanted = false;
let ownStreamTimer: ReturnType<typeof setTimeout> | undefined;
let ownStreamDelay = 1000;
/** When the own stream last said anything (an open, an event, a heartbeat). */
let ownHeardAt = 0;

export function supported(): boolean {
	return typeof window !== 'undefined' && 'Notification' in window;
}

export function permission(): Permission {
	return supported() ? Notification.permission : 'unsupported';
}

/** Asks the browser; call it from the user's own click (browsers ignore it otherwise). */
export async function requestPermission(): Promise<Permission> {
	if (!supported()) return 'unsupported';
	try {
		return await Notification.requestPermission();
	} catch {
		return Notification.permission;
	}
}

function shared(): BroadcastChannel | null {
	if (channel === undefined) {
		channel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel(CHANNEL);
		channel?.addEventListener('message', (event: MessageEvent<Message>) => receive(event.data));
	}
	return channel;
}

function receive(message: Message) {
	prune();
	if (message.type === 'offer') {
		noteOffer(message.key, message.tab);
	} else if (message.type === 'shown') {
		decided.set(message.key, Date.now());
	} else if (message.type === 'pref' && message.email === adoptedFor) {
		knownLocally = true;
		saves += 1;
		jobNotifications.set(message.enabled);
	}
}

function noteOffer(key: string, tab: string) {
	const seen = offers.get(key) ?? { tabs: new Set<string>(), at: Date.now() };
	seen.tabs.add(tab);
	offers.set(key, seen);
}

/** Forgets decisions and offers past `REMEMBER_MS`, an offer never decided here included (its
 * announcing tab closed meanwhile, say): nothing grows for the tab's lifetime. */
function prune() {
	const cutoff = Date.now() - REMEMBER_MS;
	for (const [key, at] of decided) if (at < cutoff) decided.delete(key);
	for (const [key, offer] of offers) if (offer.at < cutoff && !decided.has(key)) offers.delete(key);
}

/** The session's identity and saved switch, from a `/me` read. A new identity starts with
 * nothing remembered; the same one takes the value unless this tab knows a newer one. Opens the
 * channel, so this tab hears the other tabs' offers and saves from now on. */
export function adopt(email: string, enabled: boolean) {
	shared();
	if (adoptedFor !== email) {
		reset();
		adoptedFor = email;
	} else if (knownLocally) {
		const turn = saves;
		void api
			.getJobNotificationSettings()
			.then((fresh) => {
				if (turn === saves && adoptedFor === email) jobNotifications.set(fresh.job_notifications);
			})
			.catch(() => {});
		return;
	}
	jobNotifications.set(enabled);
}

/** After `/account` saved the switch: this tab and the user's other open tabs follow it. */
export function setEnabled(enabled: boolean) {
	knownLocally = true;
	saves += 1;
	jobNotifications.set(enabled);
	if (adoptedFor !== null) shared()?.postMessage({ type: 'pref', email: adoptedFor, enabled });
}

/** Forgets everything of the session (sign-out, another identity): nothing of one user's
 * reaches the next. The click handler is the mounted page's, set and cleared by it. */
export function reset() {
	adoptedFor = null;
	knownLocally = false;
	saves += 1;
	jobNotifications.set(false);
	offers.clear();
	decided.clear();
	setOwnStream(false);
}

/** Whether a `job.status` event is one of the user's jobs settling: into `settled:*`, from a
 * status the server knows wasn't settled (no `prev_status` at all means it doesn't know what the
 * job left, and a job archived is old news). */
export function isSettle(event: api.JobStatusEvent): boolean {
	if (event.archived || !event.status.startsWith('settled:')) return false;
	if (event.prev_status === undefined) return false;
	return event.prev_status === null || !event.prev_status.startsWith('settled:');
}

/** The dashboard's handler for a click on a notification: shows the job. */
export function setActivate(handler: ((jobId: string) => void) | null) {
	onActivate = handler;
}

/** An event from one of the user's own streams. */
export function observe(event: api.StreamEvent) {
	if (event.type !== 'job.status' || !isSettle(event)) return;
	if (!get(jobNotifications) || permission() !== 'granted') return;
	void offer(`${event.job_id}|${event.status}|${event.ts}`, event.job_id);
}

async function offer(key: string, jobId: string) {
	prune();
	if (decided.has(key)) return;
	noteOffer(key, tabId);
	shared()?.postMessage({ type: 'offer', key, tab: tabId });
	await new Promise((resolve) => setTimeout(resolve, CLAIM_WINDOW_MS));
	if (decided.has(key)) return;
	decided.set(key, Date.now());
	const lowest = [...(offers.get(key)?.tabs ?? [])].sort()[0];
	if (lowest !== tabId) return;
	shared()?.postMessage({ type: 'shown', key });
	await show(jobId);
}

async function show(jobId: string) {
	let job: api.Job;
	try {
		// Only ever an id from one of this user's own `mine` streams (an admin could read anyone's).
		job = await api.getJob(jobId);
	} catch {
		return;
	}
	if (!get(jobNotifications) || permission() !== 'granted') return;
	const counts = job.track_counts;
	const done = (counts.completed ?? 0) + (counts.skipped_duplicate ?? 0);
	const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
	// `renotify` is in the spec and Chromium, not in TypeScript's DOM types.
	const options: NotificationOptions & { renotify?: boolean } = {
		body: m.notify_job_done({ done: formatNumber(done), total: formatNumber(total) }),
		tag: `spotdl-web-job-${job.id}`,
		// A watched job (v63) settling again replaces its notification: say so, don't swap it in
		// silently (review round 4).
		renotify: true,
		lang: document.documentElement.lang || undefined
	};
	try {
		const notification = new Notification(job.title, options);
		notification.onclick = () => {
			window.focus();
			onActivate?.(job.id);
			notification.close();
		};
	} catch {
		// Chrome on Android shows notifications only from a service worker (the constructor
		// throws there): through the installed app's, if there is one. Its click opens the app
		// rather than this tab's row.
		const registration = await navigator.serviceWorker?.getRegistration().catch(() => undefined);
		await registration?.showNotification(job.title, options).catch(() => {});
	}
}

/** An admin whose dashboard isn't in `mine` needs a stream of their own events: open while
 * wanted (and this browser may show notifications at all), closed otherwise. Reconnects with
 * backoff, as the dashboard's stream does, and `checkOwnStream` restarts a silent one. */
export function setOwnStream(wanted: boolean) {
	ownStreamWanted = wanted;
	if (!wanted) {
		clearTimeout(ownStreamTimer);
		ownStreamTimer = undefined;
		ownStream?.close();
		ownStream = null;
		ownStreamDelay = 1000;
		return;
	}
	// A retry already armed is replaced by this connection, never added to it (review round 2).
	clearTimeout(ownStreamTimer);
	ownStreamTimer = undefined;
	if (ownStream === null) connectOwnStream();
}

/** The dashboard's watchdog, on its 5 s poll, `online` and a return to the tab (review round
 * 3): a stream the network dropped under it (a laptop's sleep) is silent, not closed, so it
 * starts over; and one not open yet because the browser hadn't allowed notifications opens
 * once it has (the permission can be granted from another tab). */
export function checkOwnStream() {
	if (!ownStreamWanted) return;
	if (ownStream !== null) {
		if (Date.now() - ownHeardAt <= OWN_STREAM_SILENT_MS) return;
		ownStream.close();
		ownStream = null;
		ownStreamDelay = 1000;
	} else if (ownStreamTimer !== undefined) {
		return;
	}
	connectOwnStream();
}

function retryOwnStream() {
	ownStream = null;
	clearTimeout(ownStreamTimer);
	ownStreamTimer = setTimeout(() => {
		ownStreamTimer = undefined;
		connectOwnStream();
	}, ownStreamDelay);
	ownStreamDelay = Math.min(ownStreamDelay * 2, OWN_STREAM_RETRY_MAX_MS);
}

function connectOwnStream() {
	if (!ownStreamWanted || ownStream !== null || permission() !== 'granted') return;
	const stream = api.createEventSource('mine');
	ownStream = stream;
	ownHeardAt = Date.now();
	// v42's rule for a stream: it belongs to the session it was opened under. Every (re)open
	// checks whose session the cookie is now, and events pass only once that's the adopted
	// identity (another tab's sign-in would otherwise reconnect it onto someone else's channel).
	const identity = adoptedFor;
	let verified = false;
	stream.addEventListener('heartbeat', () => {
		if (ownStream === stream) ownHeardAt = Date.now();
	});
	stream.onopen = async () => {
		verified = false;
		ownHeardAt = Date.now();
		let email: string;
		try {
			email = (await api.me()).email;
		} catch {
			// Can't tell (a blip, or the session ended): start over later and check again, rather
			// than stay connected and deaf (review round 3). The layout handles a session that ended.
			stream.close();
			if (ownStream === stream) retryOwnStream();
			return;
		}
		if (ownStream !== stream) return stream.close();
		if (identity === null || email !== identity || adoptedFor !== identity) {
			// Someone else's session now: stop for good (the dashboard reloads the tab for it), so
			// the watchdog doesn't reopen it every poll.
			stream.close();
			ownStream = null;
			ownStreamWanted = false;
			return;
		}
		verified = true;
		ownStreamDelay = 1000;
	};
	stream.onmessage = (event) => {
		if (ownStream !== stream) return stream.close();
		ownHeardAt = Date.now();
		if (!verified || adoptedFor !== identity) return;
		try {
			observe(JSON.parse(event.data) as api.StreamEvent);
		} catch {
			// A malformed event is no reason to stop listening.
		}
	};
	stream.onerror = () => {
		if (ownStream !== stream) return stream.close();
		if (stream.readyState !== EventSource.CLOSED) return;
		// A 401 or 502 closes an EventSource for good: open a new one later.
		retryOwnStream();
	};
}
