import { afterEach, describe, expect, it } from 'vitest';
import { baseLocale, overwriteGetLocale } from '$lib/paraglide/runtime';
import {
	BINDINGS,
	GROUP_TITLE,
	HU_PHYSICAL,
	bindingHelpText,
	bindingsFor,
	chordLabel,
	isCharacter
} from './bindings';

// v45's Hungarian QWERTZ rules (plan rules 1-5), checked on the table itself so a new binding
// can't break them unnoticed.
const NAMED = [
	'Escape',
	'Enter',
	' ',
	'ArrowDown',
	'ArrowUp',
	'ArrowLeft',
	'ArrowRight',
	'Home',
	'End'
];
const ALTGR_ON_HU = ['[', ']', '{', '}', '\\', '|', '@', '#', '&', ';', '<', '>', '€', '~'];

const chords = BINDINGS.flatMap((b) => b.keys.map((k, i) => ({ binding: b, chord: k, i })));

describe('binding table', () => {
	it('never binds y or z (swapped on Hungarian)', () => {
		expect(chords.filter(({ chord }) => /^[yz]$/i.test(chord.key))).toEqual([]);
	});

	it('never binds a character that needs AltGr on Hungarian', () => {
		expect(chords.filter(({ chord }) => ALTGR_ON_HU.includes(chord.key))).toEqual([]);
	});

	it('uses only letters, unshifted digits, "-", named keys, or a Shift symbol as an alias', () => {
		for (const { binding, chord, i } of chords) {
			const plain = /^[a-z0-9-]$/.test(chord.key) || NAMED.includes(chord.key);
			if (plain) continue;
			// A symbol that needs Shift on Hungarian: known, and never the primary.
			expect(HU_PHYSICAL[chord.key], `${binding.id}: ${chord.key}`).toBeDefined();
			expect(i, `${binding.id}: ${chord.key} is the primary`).toBeGreaterThan(0);
		}
	});

	it('gives no two bindings the same chord', () => {
		// The registry takes the first match whatever the route, so a chord is one binding's
		// everywhere, even on routes where it does nothing.
		const key = (c: { binding: { prefix?: string }; chord: { key: string; shift?: boolean } }) =>
			`${c.binding.prefix ?? ''}|${c.chord.key}|${c.chord.shift ? 'S' : ''}`;
		const seen = new Map<string, string>();
		for (const c of chords) {
			const clash = seen.get(key(c));
			expect(clash === undefined || clash === c.binding.id, `${c.binding.id} vs ${clash}`).toBe(
				true
			);
			seen.set(key(c), c.binding.id);
		}
	});

	it('keeps Space, Enter, Esc and the arrows as named keys (not switched off)', () => {
		for (const key of NAMED) expect(isCharacter({ key })).toBe(false);
		expect(isCharacter({ key: 'j' })).toBe(true);
		expect(isCharacter({ key: '-' })).toBe(true);
	});

	it('filters by route and role', () => {
		const user = bindingsFor('/account', false).map((b) => b.id);
		expect(user).toContain('help');
		expect(user).toContain('go-account');
		expect(user).not.toContain('go-settings');
		expect(user).not.toContain('next');
		const admin = bindingsFor('/', true).map((b) => b.id);
		expect(admin).toContain('repeats');
		expect(bindingsFor('/', false).map((b) => b.id)).not.toContain('repeats');
		expect(bindingsFor('/login', false, false).map((b) => b.id)).toEqual(['help', 'escape']);
	});

	it('shows each symbol with its Hungarian keys', () => {
		const help = bindingHelpText(BINDINGS.find((b) => b.id === 'help')!);
		expect(help.keys).toBe('h or ? (Shift + ,)');
		const search = bindingHelpText(BINDINGS.find((b) => b.id === 'search')!);
		expect(search.keys).toBe('f or / (Shift + 6)');
		const up = bindingHelpText(BINDINGS.find((b) => b.id === 'priority-up')!);
		expect(up.keys).toBe('Shift + B or + (Shift + 3)');
		const down = bindingHelpText(BINDINGS.find((b) => b.id === 'priority-down')!);
		expect(down.keys).toBe('- (right of .)');
	});
});

// v46: the help text in Hungarian, read when shown (labels are message functions).
describe('in Hungarian', () => {
	afterEach(() => overwriteGetLocale(() => baseLocale));

	it('labels every binding and group, and names Space and the "-" key', () => {
		overwriteGetLocale(() => 'hu');
		for (const binding of BINDINGS) expect(binding.label(), binding.id).not.toBe('');
		expect(bindingHelpText(BINDINGS.find((b) => b.id === 'help')!)).toEqual({
			keys: 'h vagy ? (Shift + ,)',
			label: 'A billentyűparancsok megjelenítése vagy elrejtése'
		});
		expect(bindingHelpText(BINDINGS.find((b) => b.id === 'go-account')!).keys).toBe('g, aztán a');
		expect(GROUP_TITLE.global()).toBe('Bárhol');
		expect(chordLabel({ key: ' ' })).toBe('Szóköz');
		expect(HU_PHYSICAL['-']).toBe('a . jobb oldalán');
		overwriteGetLocale(() => baseLocale);
		expect(chordLabel({ key: ' ' })).toBe('Space');
		expect(bindingHelpText(BINDINGS.find((b) => b.id === 'go-account')!).keys).toBe('g then a');
	});
});
