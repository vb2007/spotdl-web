/** v34.2: the last progress tick seen per downloading track, kept in localStorage so a
 * hard reload can show it right away instead of 0% until the next tick lands. Progress
 * is never stored server-side -- the worker publishes ticks straight to Redis pub/sub
 * and the API only streams them -- so this browser's own last sighting is the only
 * source there is.
 *
 * An entry is trusted only for the same attempt it was recorded during (`attempt`
 * mirrors the track's `attempt_count`, which the backend bumps on every failure) and
 * only while fresh, so a previous attempt's 70% never shows for a retry. Track ids and
 * numbers only, never metadata, and `clear()` runs on every store reset (logout, session
 * expiry -- the v22 rule) like every other piece of queue state. Every storage access is
 * guarded: localStorage can be missing or throw (private windows, blocked site data),
 * and then this silently does nothing. */

const KEY = 'spotdl:live-progress:v1';
const MAX_AGE_MS = 30 * 60 * 1000;

interface Entry {
	progress: number;
	attempt: number;
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

export function rememberProgress(trackId: string, progress: number, attempt: number): void {
	const now = Date.now();
	const cache = read(now);
	cache[trackId] = { progress, attempt, at: now };
	write(cache);
}

export function forgetProgress(trackId: string): void {
	const now = Date.now();
	const cache = read(now);
	if (!(trackId in cache)) return;
	delete cache[trackId];
	write(cache);
}

/** The remembered progress for this exact attempt, or undefined. */
export function recallProgress(trackId: string, attempt: number): number | undefined {
	const entry = read(Date.now())[trackId];
	return entry && entry.attempt === attempt ? entry.progress : undefined;
}

export function clearProgress(): void {
	try {
		storage()?.removeItem(KEY);
	} catch {
		// Nothing to clear.
	}
}
