import { expect, request as apiRequest, test, type Page } from '@playwright/test';
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

// Spec 7. The non-admin user, against everything the admin identity owns: its seed job, and
// whatever spec 2 submitted in this run or an earlier one.
test("a user never sees another identity's job titles", async ({ page, request, baseURL }) => {
	const { admin, user } = readSeed();
	// Spec 2's titles, both submitted by the admin only.
	const foreign = [admin.title, admin.trackTitle, 'Motherboard', 'Beyond'];
	// Guard against a vacuous pass: the admin's job exists and its owner sees it.
	expect(admin.title).not.toBe(user.title);
	const owner = await apiRequest.newContext({ baseURL, storageState: ADMIN_STATE });
	expect((await owner.get(`/api/jobs/${admin.jobId}`)).status()).toBe(200);
	await owner.dispose();
	expect((await request.get(`/api/jobs/${admin.jobId}`)).status()).toBe(404);

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
	await expect(
		page
			.getByRole('list', { name: 'Tracks' })
			.getByRole('button', { name: literal(user.trackTitle) })
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
