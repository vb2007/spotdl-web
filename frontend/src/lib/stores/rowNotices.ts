import { SvelteMap } from 'svelte/reactivity';

/** v43: per-row transient feedback ("Not cancelled: …", "bumped to front"), keyed by
 * `job:<id>` / `track:<id>`. Kept outside the rows so a row remounted while its confirmation
 * was open (a stream reconnect reloads the list) still shows how that answer ended; cleared by
 * `queue.reset()` like every other module-level store (CLAUDE.md, v22). */
export const rowNotices = new SvelteMap<string, string>();

export function showRowNotice(key: string, text: string): void {
	rowNotices.set(key, text);
	setTimeout(() => {
		if (rowNotices.get(key) === text) rowNotices.delete(key);
	}, 4000);
}

export function clearRowNotices(): void {
	rowNotices.clear();
}
