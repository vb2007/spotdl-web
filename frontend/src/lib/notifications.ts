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
// carries it, and it's taken unless this tab already knows a newer value: one it saved, or one
// another tab saved and announced on the channel (a `/me` preloaded before that save mustn't
// undo it, as the layout does for the language).
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
let channel: BroadcastChannel | null | undefined;
/** Offers seen per event key, own included. */
const offers = new Map<string, Set<string>>();
/** Event keys some tab has decided (shown, or this tab's own decision), with when. */
const decided = new Map<string, number>();
let onActivate: ((jobId: string) => void) | null = null;
let ownStream: EventSource | null = null;
let ownStreamWanted = false;
let ownStreamTimer: ReturnType<typeof setTimeout> | undefined;
let ownStreamDelay = 1000;

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
		const seen = offers.get(message.key) ?? new Set<string>();
		seen.add(message.tab);
		offers.set(message.key, seen);
	} else if (message.type === 'shown') {
		decided.set(message.key, Date.now());
	} else if (message.type === 'pref' && message.email === adoptedFor) {
		knownLocally = true;
		jobNotifications.set(message.enabled);
	}
}

function prune() {
	const cutoff = Date.now() - REMEMBER_MS;
	for (const [key, at] of decided) {
		if (at < cutoff) {
			decided.delete(key);
			offers.delete(key);
		}
	}
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
		return;
	}
	jobNotifications.set(enabled);
}

/** After `/account` saved the switch: this tab and the user's other open tabs follow it. */
export function setEnabled(enabled: boolean) {
	knownLocally = true;
	jobNotifications.set(enabled);
	if (adoptedFor !== null) shared()?.postMessage({ type: 'pref', email: adoptedFor, enabled });
}

/** Forgets everything of the session (sign-out, another identity): nothing of one user's
 * reaches the next. The click handler is the mounted page's, set and cleared by it. */
export function reset() {
	adoptedFor = null;
	knownLocally = false;
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
	const seen = offers.get(key) ?? new Set<string>();
	seen.add(tabId);
	offers.set(key, seen);
	shared()?.postMessage({ type: 'offer', key, tab: tabId });
	await new Promise((resolve) => setTimeout(resolve, CLAIM_WINDOW_MS));
	if (decided.has(key)) return;
	decided.set(key, Date.now());
	const lowest = [...(offers.get(key) ?? [])].sort()[0];
	if (lowest !== tabId) return;
	shared()?.postMessage({ type: 'shown', key });
	await show(jobId);
}

async function show(jobId: string) {
	let job: api.Job;
	try {
		// Owner-scoped like every direct-id read: someone else's job is a 404.
		job = await api.getJob(jobId);
	} catch {
		return;
	}
	if (!get(jobNotifications) || permission() !== 'granted') return;
	const counts = job.track_counts;
	const done = (counts.completed ?? 0) + (counts.skipped_duplicate ?? 0);
	const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
	const options: NotificationOptions = {
		body: m.notify_job_done({ done: formatNumber(done), total: formatNumber(total) }),
		tag: `spotdl-web-job-${job.id}`,
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

/** An admin whose dashboard isn't in `mine` needs a stream of their own events: on while
 * wanted, closed otherwise. Reconnects with backoff, as the dashboard's stream does. */
export function setOwnStream(wanted: boolean) {
	ownStreamWanted = wanted;
	if (!wanted) {
		clearTimeout(ownStreamTimer);
		ownStream?.close();
		ownStream = null;
		ownStreamDelay = 1000;
		return;
	}
	if (ownStream === null) connectOwnStream();
}

function connectOwnStream() {
	if (!ownStreamWanted) return;
	const stream = api.createEventSource('mine');
	ownStream = stream;
	stream.onopen = () => {
		ownStreamDelay = 1000;
	};
	stream.onmessage = (event) => {
		if (ownStream !== stream) return;
		try {
			observe(JSON.parse(event.data) as api.StreamEvent);
		} catch {
			// A malformed event is no reason to stop listening.
		}
	};
	stream.onerror = () => {
		if (ownStream !== stream || stream.readyState !== EventSource.CLOSED) return;
		// A 401 or 502 closes an EventSource for good: open a new one later.
		ownStream = null;
		ownStreamTimer = setTimeout(connectOwnStream, ownStreamDelay);
		ownStreamDelay = Math.min(ownStreamDelay * 2, OWN_STREAM_RETRY_MAX_MS);
	};
}
