import { expect, request, test, type APIRequestContext } from '@playwright/test';
import type { Job } from '../src/lib/api';
import { ADMIN_STATE, readSeed } from './support/stack';
import { jobRow, jobToggle, openDashboard } from './support/ui';

test.use({ storageState: ADMIN_STATE });

// Spec 8. The admin's seed job, archived and brought back. Earlier runs' archived copies share
// its title, so "show archived" can list several; the newest (this run's) sorts first.
test('archive and unarchive round trip, with show archived', async ({ page, baseURL }) => {
	const { admin } = readSeed();
	const archivedAt = async (): Promise<string | null> =>
		((await (await page.request.get(`/api/jobs/${admin.jobId}`)).json()) as Job).archived_at;
	// Every admin job with the seed's title, and whether it was archived, so the cleanup can put
	// back exactly this state even if the wrong row was clicked.
	const sameTitle = async (api: APIRequestContext): Promise<Map<string, boolean>> => {
		const q = new URLSearchParams({ q: admin.title, include_archived: 'true', limit: '1000' });
		const { items } = (await (await api.get(`/api/jobs?${q}`)).json()) as { items: Job[] };
		return new Map(
			items.filter((j) => j.title === admin.title).map((j) => [j.id, j.archived_at !== null])
		);
	};
	const initial = await sameTitle(page.request);
	expect(initial.get(admin.jobId)).toBe(false);

	try {
		await openDashboard(page);
		const row = jobRow(page, admin.title);
		await expect(row).toHaveCount(1);

		await row.getByRole('button', { name: `archive ${admin.title}`, exact: true }).click();
		await expect(jobToggle(page, admin.title)).toHaveCount(0);
		await expect.poll(archivedAt).not.toBeNull();

		const showArchived = page.getByRole('button', { name: 'show archived' });
		await showArchived.click();
		await expect(showArchived).toHaveAttribute('aria-pressed', 'true');
		const newest = row.first();
		await expect(newest).toContainText('archived');

		await newest.getByRole('button', { name: `unarchive ${admin.title}`, exact: true }).click();
		await expect.poll(archivedAt).toBeNull();
		await expect(
			newest.getByRole('button', { name: `archive ${admin.title}`, exact: true })
		).toBeVisible();

		await showArchived.click();
		await expect(showArchived).toHaveAttribute('aria-pressed', 'false');
		await expect(row).toHaveCount(1);
		await expect(
			row.getByRole('button', { name: `unarchive ${admin.title}`, exact: true })
		).toHaveCount(0);
	} finally {
		// Own context: a test-level timeout may already have closed the page's.
		const api = await request.newContext({ baseURL, storageState: ADMIN_STATE });
		const now = await sameTitle(api);
		const toArchive = [...now].filter(([id, a]) => !a && initial.get(id)).map(([id]) => id);
		const toUnarchive = [...now].filter(([id, a]) => a && !initial.get(id)).map(([id]) => id);
		if (toArchive.length) {
			const r = await api.post('/api/jobs/archive', { data: { job_ids: toArchive } });
			expect.soft(r.status(), 're-archiving rows the spec unarchived').toBe(200);
		}
		if (toUnarchive.length) {
			const r = await api.post('/api/jobs/unarchive', { data: { job_ids: toUnarchive } });
			expect.soft(r.status(), 'unarchiving rows the spec archived').toBe(200);
		}
		await api.dispose();
	}
});
