import { describe, expect, it } from 'vitest';
import { offsetsOf, rangeOf } from './listWindow.svelte';

// v68 (U4): the window's arithmetic. The rendering, measuring and anchoring are covered by the
// browser suite (e2e/26-virtual-lists.e2e.ts) against the real page.

describe('offsetsOf', () => {
	it('gives each item its top and the list its height', () => {
		expect(offsetsOf([10, 20, 30])).toEqual([0, 10, 30, 60]);
		expect(offsetsOf([])).toEqual([0]);
	});
});

describe('rangeOf', () => {
	const offsets = offsetsOf([10, 10, 10, 10, 10]); // 0 10 20 30 40 50

	it('is the items overlapping the span', () => {
		expect(rangeOf(offsets, 0, 10)).toEqual([0, 1]);
		expect(rangeOf(offsets, 5, 25)).toEqual([0, 3]);
		expect(rangeOf(offsets, 10, 20)).toEqual([1, 2]);
		expect(rangeOf(offsets, 15, 35)).toEqual([1, 4]);
	});

	it('clamps a span outside the list to its first or last item', () => {
		expect(rangeOf(offsets, -100, -50)).toEqual([0, 1]);
		expect(rangeOf(offsets, 500, 600)).toEqual([4, 5]);
		expect(rangeOf(offsets, -100, 1000)).toEqual([0, 5]);
	});

	it('is empty for an empty list', () => {
		expect(rangeOf([0], 0, 100)).toEqual([0, 0]);
	});

	it('handles uneven heights (an open row)', () => {
		const uneven = offsetsOf([10, 500, 10, 10]); // 0 10 510 520 530
		expect(rangeOf(uneven, 100, 200)).toEqual([1, 2]);
		expect(rangeOf(uneven, 505, 515)).toEqual([1, 3]);
	});
});
