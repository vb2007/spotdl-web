/** v34.2: the last progress tick seen per downloading track, kept in localStorage so a
 * hard reload can show it right away instead of 0% until the next tick lands. Progress
 * is never stored server-side -- the worker publishes ticks straight to Redis pub/sub
 * and the API only streams them -- so this browser's own last sighting is the only
 * source there is.
 *
 * An entry is trusted only for the same run it was recorded during and only while fresh,
 * so a previous run's 70% doesn't show for the next one. v62 (F10): the run is its
 * `download_started_at` (the claim's own time, on every `downloading` event and on the
 * track's REST row while it downloads). It used to be `attempt_count`, which a re-run
 * doesn't always bump (beat's stale reclaim, a redelivery), so such a run showed the
 * previous one's value. A row with no run (a server from before v62) recalls nothing.
 * Track ids, numbers and run timestamps only, never metadata. Cleared on every store reset (logout, the session-expiry
 * redirect -- the v22 rule) and on every successful login, so a new identity starts
 * empty even when the last session just expired in a closed tab. (Another still-open tab
 * of the previous identity can write its own ids back until it notices; nothing renders
 * from them, since a lookup needs the track id from this identity's own hydration.)
 * Expired entries are pruned whenever the cache is read. Every storage access is
 * guarded: localStorage can be missing or throw (private windows, blocked site data),
 * and then this silently does nothing. */

// v2 (v62): entries name their run, not an attempt number; v1's are never read, only cleared.
const KEY = 'spotdl:live-progress:v2';
const LEGACY_KEY = 'spotdl:live-progress:v1';
const MAX_AGE_MS = 30 * 60 * 1000;

interface Entry {
	progress: number;
	run: string;
	at: number;
}

type Cache = Record<string, Entry>;

function storage(): Storage | undefined {
	try {
		return globalThis.localStorage ?? undefined;
	} catch {
		return undefined;
	}
}

function read(now: number): Cache {
	try {
		const raw = storage()?.getItem(KEY);
		if (!raw) return {};
		const parsed = JSON.parse(raw) as Cache;
		const fresh: Cache = {};
		for (const [id, entry] of Object.entries(parsed)) {
			if (entry && typeof entry.progress === 'number' && now - entry.at < MAX_AGE_MS) {
				fresh[id] = entry;
			}
		}
		if (Object.keys(fresh).length !== Object.keys(parsed).length) write(fresh);
		return fresh;
	} catch {
		return {};
	}
}

function write(cache: Cache): void {
	try {
		const store = storage();
		if (!store) return;
		if (Object.keys(cache).length === 0) store.removeItem(KEY);
		else store.setItem(KEY, JSON.stringify(cache));
	} catch {
		// Quota, disabled storage: a lost cache only means 0% until the next tick.
	}
}

// v47 (F33): the backend streams every tick unthrottled, and each one was a synchronous
// read, parse and rewrite of the whole cache. Writes are now at most one a second: a tick
// after a quiet second is written at once, later ones are held and the newest per track
// goes out on the trailing edge (and when the page is hidden or left), so a reload still
// finds a recent value. Reads see the held ticks too.
const WRITE_EVERY_MS = 1000;
let held: Cache = {};
let lastWrite = 0;
let flushTimer: ReturnType<typeof setTimeout> | undefined;

function flush(): void {
	clearTimeout(flushTimer);
	flushTimer = undefined;
	if (Object.keys(held).length === 0) return;
	const now = Date.now();
	const cache = read(now);
	Object.assign(cache, held);
	held = {};
	lastWrite = now;
	write(cache);
}

try {
	globalThis.addEventListener?.('pagehide', flush);
	globalThis.document?.addEventListener('visibilitychange', () => {
		if (globalThis.document.visibilityState === 'hidden') flush();
	});
} catch {
	// No window (a unit test's import): nothing to flush on.
}

export function rememberProgress(trackId: string, progress: number, run: string): void {
	const now = Date.now();
	held[trackId] = { progress, run, at: now };
	if (now - lastWrite >= WRITE_EVERY_MS) flush();
	else if (flushTimer === undefined)
		flushTimer = setTimeout(flush, WRITE_EVERY_MS - (now - lastWrite));
}

export function forgetProgress(trackId: string): void {
	delete held[trackId];
	const now = Date.now();
	const cache = read(now);
	if (!(trackId in cache)) return;
	delete cache[trackId];
	write(cache);
}

/** The remembered progress for this exact run, or undefined. */
export function recallProgress(trackId: string, run: string | null): number | undefined {
	if (run === null) return undefined;
	const entry = held[trackId] ?? read(Date.now())[trackId];
	return entry && entry.run === run ? entry.progress : undefined;
}

export function clearProgress(): void {
	held = {};
	lastWrite = 0;
	clearTimeout(flushTimer);
	flushTimer = undefined;
	try {
		storage()?.removeItem(KEY);
		storage()?.removeItem(LEGACY_KEY);
	} catch {
		// Nothing to clear.
	}
}
