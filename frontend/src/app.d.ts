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
		}
		// interface Platform {}
	}
}

export {};
