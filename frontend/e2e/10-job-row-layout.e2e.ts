import { expect, test } from '@playwright/test';
import { ADMIN_STATE, readSeed } from './support/stack';
import { jobRow, jobToggle, openDashboard } from './support/ui';

test.use({ storageState: ADMIN_STATE });

// Spec 10 (v39.1, F01). The ≤640px job row stacks its children in a flex column, where a
// flex-basis sizes height: the desktop `16rem` basis on the toggle made every phone job row
// 256px tall, and a `100%` basis collapsed the progress bar to its 2px border. Runs in both
// projects, so the desktop row is checked against the same bounds. Bounds, measured on the dev
// stack after the fix: toggle 23px (one line of 15px text), bar 8px (`0.5rem`), whole row
// 52px desktop / 137px stacked on mobile.
test('a job row stays compact and its progress bar visible', async ({ page }) => {
	const { admin } = readSeed();
	await openDashboard(page);
	const row = jobRow(page, admin.title);
	await expect(row).toHaveCount(1);

	// Visible first: a missing bar fails here, not as a 180s boundingBox() wait.
	const barEl = row.getByRole('img', { name: /^Track progress: / });
	await expect(barEl).toBeVisible();
	const toggle = await jobToggle(page, admin.title).boundingBox();
	const bar = await barEl.boundingBox();
	const whole = await row.boundingBox();
	expect(toggle, 'job toggle box').not.toBeNull();
	expect(bar, 'progress bar box').not.toBeNull();
	expect(whole, 'job row box').not.toBeNull();

	// Two text lines at most: the title ellipsizes rather than wrapping.
	expect.soft(toggle!.height, 'job toggle height').toBeLessThan(48);
	// The 0.5rem bar, not its 2px border alone.
	expect.soft(bar!.height, 'progress bar height').toBeGreaterThanOrEqual(6);
	expect.soft(bar!.width, 'progress bar width').toBeGreaterThan(100);
	// Toggle + bar + breakdown + actions, stacked: well under the 364px the bug produced.
	expect.soft(whole!.height, 'job row height').toBeLessThan(200);
});
