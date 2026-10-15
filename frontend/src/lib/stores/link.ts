import { writable } from 'svelte/store';

/** `/`'s SSE stream: not yet open, open, or dropped and retrying (v42, F05). Only `/` holds
 * the stream, so the value means nothing on any other route. */
export type LinkState = 'connecting' | 'live' | 'reconnecting';

/** A store rather than page state because the layout reads it too: while the link is down,
 * `queue.activeTracks` may be stale, so the ambient field must not stay warm on it. */
export const link = writable<LinkState>('connecting');
