// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		interface PageState {
			/** v47: `/login` reached because the session ended mid-page (a 401), so it says why. */
			sessionEnded?: boolean;
			/** v54: `/`'s admin view this history entry was left in, so a Back restores it. */
			view?: 'mine' | 'all' | 'others';
			/** v65: `/share`'s link was queued from this history entry (with the answer's hint), so a
			 * Back to it shows the outcome rather than offering "queue it" again. */
			shareQueued?: {
				url: string;
				type: 'track' | 'album' | 'artist' | 'playlist';
				id: string;
				hint: 'already_queued' | 'in_library' | null;
				/** Whose it is: another identity signing in on this tab never takes it as theirs. */
				viewer: string;
			};
		}
		// interface Platform {}
	}
}

export {};
