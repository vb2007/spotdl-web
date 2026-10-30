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
 *
 * v46: every text here is a message function, called when it's shown (a string built at import
 * would freeze in the language it was built in). Imported relatively, not via `$lib`, so the
 * e2e suite can still import this module under Playwright's own loader.
 */

import * as m from '../paraglide/messages.js';

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
	/** What it does, as the help overlay says it (v46: a message, called at render). */
	label: () => string;
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
		label: m.kbd_help,
		group: 'global'
	},
	{
		id: 'search',
		keys: [{ key: 'f' }, { key: '/' }],
		label: m.kbd_search,
		group: 'global',
		routes: DASHBOARD
	},
	{
		id: 'submit',
		keys: [{ key: 'i' }],
		label: m.kbd_submit,
		group: 'global',
		routes: DASHBOARD
	},
	{
		id: 'escape',
		keys: [{ key: 'Escape' }],
		label: m.kbd_escape,
		group: 'global'
	},

	// Go to (`g`, then a letter)
	{ id: 'go-dashboard', prefix: 'g', keys: [{ key: 'd' }], label: m.kbd_go_dashboard, group: 'go' },
	{
		id: 'go-settings',
		prefix: 'g',
		keys: [{ key: 's' }],
		label: m.kbd_go_settings,
		group: 'go',
		adminOnly: true
	},
	{
		id: 'go-library',
		prefix: 'g',
		keys: [{ key: 'l' }],
		label: m.kbd_go_library,
		group: 'go',
		adminOnly: true
	},
	{ id: 'go-account', prefix: 'g', keys: [{ key: 'a' }], label: m.kbd_go_account, group: 'go' },
	{
		id: 'go-stats',
		prefix: 'g',
		keys: [{ key: 't' }],
		label: m.kbd_go_stats,
		group: 'go'
	},

	// Lists: jobs, tracks, and the tracks of an open job
	{
		id: 'next',
		keys: [{ key: 'j' }, { key: 'ArrowDown' }],
		label: m.kbd_next,
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'prev',
		keys: [{ key: 'k' }, { key: 'ArrowUp' }],
		label: m.kbd_prev,
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'first',
		keys: [{ key: 'Home' }],
		label: m.kbd_first,
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'last',
		keys: [{ key: 'End' }],
		label: m.kbd_last,
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'load-more',
		keys: [{ key: 'g', shift: true }],
		label: m.kbd_load_more,
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'toggle',
		keys: [{ key: 'Enter' }, { key: ' ' }],
		label: m.kbd_toggle,
		group: 'list',
		routes: DASHBOARD,
		native: true
	},
	{
		id: 'expand',
		keys: [{ key: 'ArrowRight' }, { key: 'o' }],
		label: m.kbd_expand,
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'collapse',
		keys: [{ key: 'ArrowLeft' }],
		label: m.kbd_collapse,
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'retry',
		keys: [{ key: 'r' }],
		label: m.kbd_retry,
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'download',
		keys: [{ key: 'd' }],
		label: m.kbd_download,
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'cancel',
		keys: [{ key: 'x' }],
		label: m.kbd_cancel,
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'archive',
		keys: [{ key: 'a' }],
		label: m.kbd_archive,
		group: 'list',
		routes: DASHBOARD
	},
	{
		id: 'bump',
		keys: [{ key: 'b' }],
		label: m.kbd_bump,
		group: 'list',
		routes: DASHBOARD,
		// v47 (owner's call): the queue's order is operator detail, like v39's outcome 3.
		adminOnly: true
	},
	{
		id: 'priority-up',
		keys: [{ key: 'b', shift: true }, { key: '+' }],
		label: m.kbd_priority_up,
		group: 'list',
		routes: DASHBOARD,
		// v47 (owner's call): the queue's order is operator detail, like v39's outcome 3.
		adminOnly: true
	},
	{
		id: 'priority-down',
		keys: [{ key: '-' }],
		label: m.kbd_priority_down,
		group: 'list',
		routes: DASHBOARD,
		// v47 (owner's call): the queue's order is operator detail, like v39's outcome 3.
		adminOnly: true
	},
	{
		id: 'repeats',
		keys: [{ key: 'e' }],
		label: m.kbd_repeats,
		group: 'list',
		routes: DASHBOARD,
		adminOnly: true
	},

	// Queue controls
	{
		id: 'scope-jobs',
		keys: [{ key: '1' }],
		label: m.kbd_scope_jobs,
		group: 'queue',
		routes: DASHBOARD
	},
	{
		id: 'scope-tracks',
		keys: [{ key: '2' }],
		label: m.kbd_scope_tracks,
		group: 'queue',
		routes: DASHBOARD
	},
	{
		id: 'filters',
		keys: [{ key: 'f', shift: true }],
		label: m.kbd_filters,
		group: 'queue',
		routes: DASHBOARD
	},
	{
		id: 'sort',
		keys: [{ key: 's' }],
		label: m.kbd_sort,
		group: 'queue',
		routes: DASHBOARD
	},
	{
		id: 'archived',
		keys: [{ key: 'a', shift: true }],
		label: m.kbd_archived,
		group: 'queue',
		routes: DASHBOARD
	},
	{
		// v54: mine -> all users -> other users. Shift+V, as plain `v` is free but a scope
		// change reloads the whole list, so it takes the deliberate Shift like `Shift+A`.
		id: 'view-cycle',
		keys: [{ key: 'v', shift: true }],
		label: m.kbd_view_cycle,
		group: 'queue',
		routes: DASHBOARD,
		adminOnly: true
	}
];

export const GROUP_TITLE: Record<BindingGroup, () => string> = {
	global: m.kbd_group_global,
	go: m.kbd_group_go,
	list: m.kbd_group_list,
	queue: m.kbd_group_queue
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
	// Unshifted on both, but not where US has it: the key right of `.`. A getter, so it's read
	// in the language shown at the time.
	get '-'() {
		return m.kbd_hu_right_of_dot();
	}
};

// Keycaps as printed (Esc, Enter, Home and End are printed so on Hungarian keyboards too); only
// Space, which has no printed name, is a word.
const NAMED: Record<string, string> = {
	Escape: 'Esc',
	ArrowDown: '↓',
	ArrowUp: '↑',
	ArrowLeft: '←',
	ArrowRight: '→',
	get ' '() {
		return m.kbd_key_space();
	},
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
	const keys = binding.keys.map(chordHelp).join(` ${m.kbd_or()} `);
	return {
		keys: binding.prefix ? m.kbd_chord_then({ prefix: binding.prefix, keys }) : keys,
		label: binding.label()
	};
}
