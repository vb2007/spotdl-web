import { expect, request as apiRequest, test, type Page } from '@playwright/test';
import type { Job } from '../src/lib/api';
import { ADMIN_STATE, USER_STATE, readSeed } from './support/stack';
import { jobToggle, literal } from './support/ui';

test.use({ storageState: USER_STATE });

async function search(page: Page, scope: 'jobs' | 'tracks', q: string): Promise<void> {
	await page
		.getByRole('group', { name: 'Search scope' })
		.getByRole('button', { name: scope })
		.click();
	await page.getByLabel(scope === 'jobs' ? 'Search jobs' : 'Search tracks').fill(q);
}

// Spec 7. The non-admin user, against every job title the admin identity owns: its seed, spec
// 2's submissions and anything earlier runs left, archived included.
test("a user never sees another identity's job titles", async ({ page, request, baseURL }) => {
	const { admin, user } = readSeed();
	const owner = await apiRequest.newContext({ baseURL, storageState: ADMIN_STATE });
	// Guard against a vacuous pass: the admin's job exists and its owner sees it.
	expect((await owner.get(`/api/jobs/${admin.jobId}`)).status()).toBe(200);
	const owned = (await (await owner.get('/api/jobs?include_archived=true&limit=1000')).json()) as {
		items: Job[];
	};
	await owner.dispose();
	expect((await request.get(`/api/jobs/${admin.jobId}`)).status()).toBe(404);

	const foreign = [...new Set([admin.trackTitle, ...owned.items.map((j) => j.title)])].filter(
		(title) => title !== user.title && title !== user.trackTitle
	);
	expect(foreign).toContain(admin.title);

	const expectNoForeignText = async () => {
		for (const title of foreign) await expect(page.getByText(literal(title))).toHaveCount(0);
	};

	await page.goto('/');
	// Jobs scope: the user's own row is there, the admin's isn't.
	await expect(jobToggle(page, user.title)).toBeVisible();
	await expectNoForeignText();

	// Tracks scope.
	await page
		.getByRole('group', { name: 'Search scope' })
		.getByRole('button', { name: 'tracks' })
		.click();
	// `.first()`: other users own tracks with this same title, so a leak shows up as a second
	// row here. Let the foreign-title check below be the one that reports it.
	await expect(
		page
			.getByRole('list', { name: 'Tracks' })
			.getByRole('button', { name: literal(user.trackTitle) })
			.first()
	).toBeVisible();
	await expectNoForeignText();

	// Search, both scopes, including archived jobs.
	await page.getByRole('button', { name: 'show archived' }).click();
	for (const scope of ['jobs', 'tracks'] as const) {
		await search(page, scope, admin.title);
		await expect(page.getByText('Nothing here.')).toBeVisible();
		await expectNoForeignText();
		// The same search does find the user's own title, so the filter isn't hiding everything.
		await search(page, scope, user.title);
		await expect(page.getByText('Nothing here.')).toHaveCount(0);
		await expect(page.getByText(literal(user.title)).first()).toBeVisible();
		await expectNoForeignText();
	}
});
