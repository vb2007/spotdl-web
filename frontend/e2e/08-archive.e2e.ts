import { expect, test } from '@playwright/test';
import type { Job } from '../src/lib/api';
import { ADMIN_STATE, readSeed } from './support/stack';
import { jobRow, jobToggle } from './support/ui';

test.use({ storageState: ADMIN_STATE });

// Spec 8. The admin's seed job, archived and brought back. Earlier runs' archived copies share
// its title, so "show archived" can list several; the newest (this run's) sorts first.
test('archive and unarchive round trip, with show archived', async ({ page }) => {
	const { admin } = readSeed();
	const archivedAt = async (): Promise<string | null> =>
		((await (await page.request.get(`/api/jobs/${admin.jobId}`)).json()) as Job).archived_at;

	try {
		await page.goto('/');
		const row = jobRow(page, admin.title);
		await expect(row).toHaveCount(1);

		await row.getByRole('button', { name: 'archive', exact: true }).click();
		await expect(jobToggle(page, admin.title)).toHaveCount(0);
		await expect.poll(archivedAt).not.toBeNull();

		const showArchived = page.getByRole('button', { name: 'show archived' });
		await showArchived.click();
		await expect(showArchived).toHaveAttribute('aria-pressed', 'true');
		const newest = row.first();
		await expect(newest).toContainText('archived');

		await newest.getByRole('button', { name: 'unarchive' }).click();
		await expect.poll(archivedAt).toBeNull();
		await expect(newest.getByRole('button', { name: 'archive', exact: true })).toBeVisible();

		await showArchived.click();
		await expect(showArchived).toHaveAttribute('aria-pressed', 'false');
		await expect(row).toHaveCount(1);
		await expect(row.getByRole('button', { name: 'unarchive' })).toHaveCount(0);
	} finally {
		if ((await archivedAt()) !== null) {
			await page.request.post('/api/jobs/unarchive', { data: { job_ids: [admin.jobId] } });
		}
	}
});
