import { expect, request as apiRequest, test, type Page } from '@playwright/test';
import type { Job, Track } from '../src/lib/api';
import { ADMIN_STATE, USER_STATE, normalizeEmail, readSeed, userIdentity } from './support/stack';
import { jobToggle, literal, openDashboard } from './support/ui';

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

	// The user's own row legitimately shows its title, artists and album: an admin job titled
	// like one of those (an album job, say) isn't foreign text.
	const ownTracks = (await (await request.get(`/api/jobs/${user.jobId}/tracks`)).json()) as {
		items: Track[];
	};
	// Every job the user owns counts as its own, archived included, not only this run's seed.
	// Filtered by owner: this is the listing under test, and a leak would otherwise make the
	// admin's titles look like the user's own.
	const listed = (await (
		await request.get('/api/jobs?include_archived=true&limit=1000')
	).json()) as { items: Job[] };
	const ownJobs = listed.items.filter(
		(j) => normalizeEmail(j.owner_email) === normalizeEmail(userIdentity().email)
	);
	const ownText = new Set([
		...ownTracks.items.flatMap((t) => [t.title, t.album, ...(t.artists ?? [])]),
		...ownJobs.map((j) => j.title)
	]);
	const foreign = [...new Set([admin.trackTitle, ...owned.items.map((j) => j.title)])].filter(
		(title) => !ownText.has(title)
	);
	expect(foreign).toContain(admin.title);

	const expectNoForeignText = async () => {
		// Exact: a title renders as its own element (job title, track title, group header,
		// Waterfall lane), and a substring match would also hit chrome like "done".
		for (const title of foreign) {
			await expect(page.getByText(title, { exact: true })).toHaveCount(0);
		}
	};

	await openDashboard(page);
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
		// v42 (F26): a search miss names itself ("No jobs match …") instead of "Nothing here.".
		await expect(page.getByRole('heading', { name: /^No (jobs|tracks) match/ })).toBeVisible();
		await expectNoForeignText();
		// The same search does find the user's own title, so the filter isn't hiding everything.
		await search(page, scope, user.title);
		await expect(page.getByRole('heading', { name: /^No (jobs|tracks) match/ })).toHaveCount(0);
		await expect(page.getByText(literal(user.title)).first()).toBeVisible();
		await expectNoForeignText();
	}
});
