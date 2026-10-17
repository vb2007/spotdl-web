import { writable, get } from 'svelte/store';
import { BINDINGS, isCharacter, type Binding, type KeyChord } from './bindings';

/**
 * v45: the one keyboard listener. Every shortcut is a row of `BINDINGS`; what it does is a
 * handler registered under its id by whoever owns the behavior (the layout for the global
 * keys, `/` for the queue, `lists.ts` for the rows). Nothing else in the tree listens to
 * `keydown` for a shortcut.
 */

export type Handler = (event: KeyboardEvent) => boolean | void;

/** The per-user switch (`/account`, stored server-side). Off: single characters do nothing;
 * Tab, the arrows, Home/End, Enter, Space and Esc keep working (WCAG 2.1.4). */
export const shortcutsEnabled = writable(true);

/** The help overlay's open state (HelpOverlay.svelte renders it). */
export const helpOpen = writable(false);

/** `g` has been pressed and the next key picks a page; the indicator shows meanwhile. */
export const chordPending = writable<string | null>(null);

const CHORD_TIMEOUT_MS = 1500;
const REPEATABLE = new Set(['next', 'prev']);
let chordTimer: ReturnType<typeof setTimeout> | undefined;

function setChord(prefix: string | null): void {
	clearTimeout(chordTimer);
	chordPending.set(prefix);
	if (prefix !== null) chordTimer = setTimeout(() => chordPending.set(null), CHORD_TIMEOUT_MS);
}

const handlers = new Map<string, Handler[]>();

/** Registers handlers by binding id; the newest registration of an id wins until it's removed.
 * Returns the removal. */
export function registerHandlers(entries: Record<string, Handler>): () => void {
	for (const [id, fn] of Object.entries(entries)) {
		if (!BINDINGS.some((b) => b.id === id)) throw new Error(`unknown binding ${id}`);
		handlers.set(id, [...(handlers.get(id) ?? []), fn]);
	}
	return () => {
		for (const [id, fn] of Object.entries(entries)) {
			handlers.set(
				id,
				(handlers.get(id) ?? []).filter((h) => h !== fn)
			);
		}
	};
}

function run(id: string, event: KeyboardEvent): boolean {
	const stack = handlers.get(id);
	const fn = stack?.[stack.length - 1];
	if (!fn) return false;
	return fn(event) !== false;
}

/** Text entry of any kind: a shortcut there would eat what the user types. */
export function isTypingTarget(target: EventTarget | null): boolean {
	if (!(target instanceof HTMLElement)) return false;
	if (target.isContentEditable) return true;
	if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
	if (target instanceof HTMLInputElement) {
		// A checkbox or radio takes Space, not text; every other input type is typed into.
		return !['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color'].includes(
			target.type
		);
	}
	return false;
}

/** AltGr is never a shortcut (plan rule 3). Windows reports it as Ctrl+Alt, so a Hungarian `@`
 * (AltGr+V) or `{` arrives with both set; Linux and macOS report the AltGraph modifier. */
export function isAltGr(event: KeyboardEvent): boolean {
	return event.getModifierState?.('AltGraph') || (event.ctrlKey && event.altKey);
}

function matches(chord: KeyChord, event: KeyboardEvent): boolean {
	if (chord.key.length === 1 && /[a-z]/i.test(chord.key)) {
		// A letter: compared case-free, with Shift as its own flag, so Caps Lock never turns
		// `j` into `Shift+J`.
		return event.key.toLowerCase() === chord.key && event.shiftKey === (chord.shift ?? false);
	}
	return event.key === chord.key;
}

function find(event: KeyboardEvent, prefix: string | null): Binding | undefined {
	return BINDINGS.find(
		(b) => !b.native && (b.prefix ?? null) === prefix && b.keys.some((k) => matches(k, event))
	);
}

function chordFor(binding: Binding, event: KeyboardEvent): KeyChord {
	return binding.keys.find((k) => matches(k, event)) ?? binding.keys[0];
}

/** The open modal, if any: a confirmation or the help overlay. */
function openModal(): HTMLDialogElement | null {
	return document.querySelector<HTMLDialogElement>('dialog[open]:modal');
}

export function onKeydown(event: KeyboardEvent): void {
	if (event.defaultPrevented || event.isComposing || event.key === 'Dead') return;
	if (event.key === 'Process' || event.key === 'Unidentified') return;
	// Browser and OS chords (Ctrl+F, Ctrl+L, Cmd+K, Alt+←) are never shadowed, and AltGr
	// characters never fire anything: only bare keys and Shift+key are shortcuts.
	if (isAltGr(event) || event.ctrlKey || event.metaKey || event.altKey) {
		setChord(null);
		return;
	}

	const enabled = get(shortcutsEnabled);
	const modal = openModal();
	if (modal) {
		// A dialog owns the keyboard (Tab stays inside it, Esc is its own `cancel`); only the
		// help key reaches through, so `h` closes the overlay it opened.
		const help = find(event, null);
		if (modal.dataset.kbHelp !== undefined && help?.id === 'help' && enabled) {
			event.preventDefault();
			run('help', event);
		}
		return;
	}

	const pending = get(chordPending);
	if (pending !== null) {
		// Whatever comes next ends the chord; only a listed second key goes somewhere.
		setChord(null);
		if (event.key === 'Shift') return setChord(pending);
		const target = find(event, pending);
		if (target && run(target.id, event)) event.preventDefault();
		else if (event.key === 'Escape') event.preventDefault();
		return;
	}

	const typing = isTypingTarget(event.target);
	if (typing && event.key !== 'Escape') return;

	const binding = find(event, null);
	if (!binding) {
		const chords = BINDINGS.some((b) => b.prefix === 'g' && handlers.get(b.id)?.length);
		// Case-free like every letter binding, so Caps Lock doesn't take the chords away.
		if (enabled && chords && !typing && event.key.toLowerCase() === 'g' && !event.shiftKey) {
			event.preventDefault();
			setChord('g');
		}
		return;
	}
	if (!enabled && isCharacter(chordFor(binding, event))) return;
	// A held letter repeats only moving through a list; holding `a` or `x` must never archive
	// or cancel row after row as focus moves on. Named keys (arrows, Home, End) repeat as usual.
	if (event.repeat && isCharacter(chordFor(binding, event)) && !REPEATABLE.has(binding.id)) {
		event.preventDefault();
		return;
	}
	if (run(binding.id, event)) event.preventDefault();
}

/** Drops a pending chord (a navigation or a session change). */
export function resetKeyboard(): void {
	setChord(null);
	helpOpen.set(false);
	// The next identity's own value arrives with its session (the layout sets it).
	shortcutsEnabled.set(true);
}
