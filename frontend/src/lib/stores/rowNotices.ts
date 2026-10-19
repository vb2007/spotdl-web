import { SvelteMap, SvelteSet } from 'svelte/reactivity';

/** v43: per-row transient feedback ("Not cancelled: …", "bumped to front"), keyed by
 * `job:<id>` / `track:<id>`. Kept outside the rows so a row remounted while its confirmation
 * was open (a stream reconnect reloads the list) still shows how that answer ended; cleared by
 * `queue.reset()` like every other module-level store (CLAUDE.md, v22). */
export const rowNotices = new SvelteMap<string, string>();
/** v47: the keys whose current notice reports a failure ("Couldn't archive: …"), shown in the
 * fail tone; every other notice ("bumped to front") keeps the waiting blue. */
export const failedRowNotices = new SvelteSet<string>();

export function showRowNotice(key: string, text: string, failed = false): void {
	rowNotices.set(key, text);
	if (failed) failedRowNotices.add(key);
	else failedRowNotices.delete(key);
	setTimeout(() => {
		if (rowNotices.get(key) !== text) return;
		rowNotices.delete(key);
		failedRowNotices.delete(key);
	}, 4000);
}

export function clearRowNotices(): void {
	rowNotices.clear();
	failedRowNotices.clear();
}
