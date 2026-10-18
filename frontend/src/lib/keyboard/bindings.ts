/**
 * v45: every keyboard binding the app has, as data. The one listener (`registry.ts`) matches
 * events against this table and the help overlay is rendered from it, so the two can't drift.
 * Pure data with no Svelte or `$app` import: the e2e suite imports it to compare the overlay
 * against it.
 *
 * Designed for **Hungarian QWERTZ** first (plan v45, rules 1-5): no binding needs AltGr, `y`
 * and `z` (swapped against US) are never bound, keys are matched on `event.key`, and a symbol
 * that needs Shift on Hungarian (`?`, `/`, `+`) is only ever an alias for a letter or unshifted
 * key.
 */

export type BindingGroup = 'global' | 'go' | 'list' | 'queue';

export interface KeyChord {
	/** `event.key`, lower-case for a letter (Shift is `shift`), as produced for a symbol. */
	key: string;
	/** Letters only: Shift must be held (`Shift+B`). A symbol's Shift is part of producing it. */
	shift?: boolean;
}

export interface Binding {
	id: string;
	/** The first is the primary; the rest are aliases. */
	keys: KeyChord[];
	/** A chord's first key (`g`): `keys` is then the second key. */
	prefix?: string;
	/** What it does, as the help overlay says it. */
	label: string;
	group: BindingGroup;
	/** Route ids it works on; absent means every signed-in route. */
	routes?: string[];
	adminOnly?: boolean;
	/** Handled by the browser itself (Enter/Space on a focused button): listed, never dispatched. */
	native?: boolean;
}

const DASHBOARD = ['/'];

export const BINDINGS: Binding[] = [
	// Global
	{
		id: 'help',
		keys: [{ key: 'h' }, { key: '?' }],
		label: 'Show or hide these shortcuts',
		group: 'global'
	},
	{
		id: 'search',
		keys: [{ key: 'f' }, { key: '/' }],
		label: 'Search the queue',
		group: 'global',
		routes: DASHBOARD
	},
	{
		id: 'submit',
		keys: [{ key: 'i' }],
		label: 'Paste a link (the submit field)',
		group: 'global',
		routes: DASHBOARD
	},
	{
		id: 'escape',
		keys: [{ key: 'Escape' }],
		label: 'Close a dialog, collapse the row, or clear the search',
		group: 'global'
	},

	// Go to (`g`, then a letter)
	{ id: 'go-dashboard', prefix: 'g', keys: [{ key: 'd' }], label: 'Queue', group: 'go' },
	{
		id: 'go-settings',
		prefix: 'g',
		keys: [{ key: 's' }],
		label: 'Settings',
		group: 'go',
		adminOnly: true
	},
	{
		id: 'go-library',
		prefix: 'g',
		keys: [{ key: 'l' }],
		label: 'Library',
		group: 'go',
		adminOnly: true
	},
	{ id: 'go-account', prefix: 'g', keys: [{ key: 'a' }], label: 'Account', group: 'go' },
	{
		id: 'go-stats',
		prefix: 'g',
		keys: [{ key: 't' }],
		label: 'Stats',
		group: 'go',
		adminOnly: true
	},

	// Lists: jobs, tracks, and the tracks of an open job
	{
		id: 'next',
		keys: [{ key: 'j' }, { key: 'ArrowDown' }],
		label: 'Next row',
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'prev',
		keys: [{ key: 'k' }, { key: 'ArrowUp' }],
		label: 'Previous row',
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'first',
		keys: [{ key: 'Home' }],
		label: 'First row',
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'last',
		keys: [{ key: 'End' }],
		label: 'Last row; on the last row, load more',
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'load-more',
		keys: [{ key: 'g', shift: true }],
		label: 'Load more rows',
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'toggle',
		keys: [{ key: 'Enter' }, { key: ' ' }],
		label: 'Open or close the row',
		group: 'list',
		routes: DASHBOARD,
		native: true
	},
	{
		id: 'expand',
		keys: [{ key: 'ArrowRight' }, { key: 'o' }],
		label: 'Open the row; on an open job, move into its tracks',
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'collapse',
		keys: [{ key: 'ArrowLeft' }],
		label: 'Close the row, or go back from a track to its job',
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'retry',
		keys: [{ key: 'r' }],
		label: 'Retry the track now',
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'download',
		keys: [{ key: 'd' }],
		label: 'Download the track’s file',
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'cancel',
		keys: [{ key: 'x' }],
		label: 'Cancel the job or track (asks first)',
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'archive',
		keys: [{ key: 'a' }],
		label: 'Archive or unarchive the job',
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'bump',
		keys: [{ key: 'b' }],
		label: 'Bump the job to the front',
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'priority-up',
		keys: [{ key: 'b', shift: true }, { key: '+' }],
		label: 'Raise the job’s priority by one',
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'priority-down',
		keys: [{ key: '-' }],
		label: 'Lower the job’s priority by one',
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'repeats',
		keys: [{ key: 'e' }],
		label: 'Open the track’s history and show or hide every repeat',
		group: 'list',
		routes: DASHBOARD,
		adminOnly: true
	},

	// Queue controls
	{
		id: 'scope-jobs',
		keys: [{ key: '1' }],
		label: 'Show jobs',
		group: 'queue',
		routes: DASHBOARD
	},
	{
		id: 'scope-tracks',
		keys: [{ key: '2' }],
		label: 'Show tracks',
		group: 'queue',
		routes: DASHBOARD
	},
	{
		id: 'filters',
		keys: [{ key: 'f', shift: true }],
		label: 'Go to the filters (arrows move, Space toggles)',
		group: 'queue',
		routes: DASHBOARD
	},
	{
		id: 'sort',
		keys: [{ key: 's' }],
		label: 'Next sort order',
		group: 'queue',
		routes: DASHBOARD
	},
	{
		id: 'archived',
		keys: [{ key: 'a', shift: true }],
		label: 'Show or hide archived jobs',
		group: 'queue',
		routes: DASHBOARD
	}
];

export const GROUP_TITLE: Record<BindingGroup, string> = {
	global: 'Anywhere',
	go: 'Go to',
	list: 'In a list',
	queue: 'Queue controls'
};

/** A single printable character, which the per-user switch turns off (WCAG 2.1.4). Space,
 * like Enter, Esc and the arrows, is a named key and keeps working. */
export function isCharacter(chord: KeyChord): boolean {
	return chord.key.length === 1 && chord.key !== ' ';
}

/** The bindings that apply to a viewer on `routeId`. Signed out (`/login`), only the help and
 * Esc remain: there is nowhere to go yet. */
export function bindingsFor(routeId: string | null, isAdmin: boolean, signedIn = true): Binding[] {
	return BINDINGS.filter(
		(b) =>
			(!b.adminOnly || isAdmin) &&
			(signedIn || b.group === 'global') &&
			(b.routes === undefined || b.routes.includes(routeId ?? ''))
	);
}

/** How a Hungarian QWERTZ user produces a symbol (plan rule 5). Letters, digits and the named
 * keys sit where they're labelled, so they need no hint. */
export const HU_PHYSICAL: Record<string, string> = {
	'?': 'Shift + ,',
	'/': 'Shift + 6',
	'+': 'Shift + 3',
	// Unshifted on both, but not where US has it: the key right of `.`.
	'-': 'right of .'
};

const NAMED: Record<string, string> = {
	Escape: 'Esc',
	ArrowDown: '↓',
	ArrowUp: '↑',
	ArrowLeft: '←',
	ArrowRight: '→',
	' ': 'Space',
	Enter: 'Enter',
	Home: 'Home',
	End: 'End'
};

/** The keycap text for one chord: `j`, `Shift + B`, `?`, `↓`. */
export function chordLabel(chord: KeyChord): string {
	const name = NAMED[chord.key] ?? chord.key;
	return chord.shift ? `Shift + ${name.toUpperCase()}` : name;
}

/** The help overlay's text for one chord, symbols with their Hungarian combination:
 * `? (Shift + ,)`. */
export function chordHelp(chord: KeyChord): string {
	const hu = HU_PHYSICAL[chord.key];
	return hu ? `${chordLabel(chord)} (${hu})` : chordLabel(chord);
}

/** One binding as the help overlay lists it: its keys (alternatives joined by " or ", a chord
 * prefixed "g then"), and its label. The e2e suite renders the same text from this table. */
export function bindingHelpText(binding: Binding): { keys: string; label: string } {
	const keys = binding.keys.map(chordHelp).join(' or ');
	return { keys: binding.prefix ? `${binding.prefix} then ${keys}` : keys, label: binding.label };
}
