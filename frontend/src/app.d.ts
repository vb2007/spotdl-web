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
		}
		// interface Platform {}
	}
}

export {};
