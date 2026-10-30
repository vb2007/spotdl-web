import { expect, test, type Page } from '@playwright/test';
import type { Job } from '../src/lib/api';
import { m, t } from './support/i18n';
import { LEDGER_TRACKS, USER_STATE, userIdentity } from './support/stack';

// Spec 21 (v65): the installed app's share target, `/share?title&text&url` (the manifest's GET
// `share_target`). Signed out, a share goes through /login and comes back to itself; signed in,
// it shows what it would queue with "queue it" focused, and Enter queues it. `next` never leaves
// the site. A track already in the ledger, so the queued job resolves as a duplicate (no download).

const TRACK_ID = LEDGER_TRACKS.userSeed;
// The Android form: Spotify's words and the link with its ?si= in `text`, the song in `title`.
const SHARE =
	`/share?title=${encodeURIComponent('Contact')}` +
	`&text=${encodeURIComponent(`Contact · Daft Punk https://open.spotify.com/track/${TRACK_ID}?si=a1B2c3D4e5F6g7H8`)}`;

const OUTCOMES = () =>
	new RegExp(
		[m.share_queued, m.share_queued_in_library, m.dashboard_submit_already_queued]
			.map((message) => t(message).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
			.join('|')
	);

async function signIn(page: Page): Promise<void> {
	const { email, password } = userIdentity();
	await page.getByLabel(t(m.login_email), { exact: true }).fill(email);
	await page.getByLabel(t(m.login_password), { exact: true }).fill(password);
	await page.getByRole('button', { name: t(m.login_connect), exact: true }).click();
}

test.describe('signed out', () => {
	test('a share survives the login round-trip and Enter queues it', async ({ page, baseURL }) => {
		await page.goto(SHARE);
		await expect(page).toHaveURL(/\/login\?next=/);
		expect(new URL(page.url()).searchParams.get('next')).toBe(SHARE);

		await signIn(page);
		await expect(page).toHaveURL(`${baseURL}${SHARE}`);
		await expect(page.getByRole('heading', { level: 1 })).toHaveText(t(m.share_heading));
		await expect(page.getByText('Contact · Daft Punk', { exact: true })).toBeVisible();
		await expect(page.getByText(t(m.share_type_track), { exact: true })).toBeVisible();
		await expect(page.getByText(TRACK_ID, { exact: true })).toBeVisible();
		const queueIt = page.getByRole('button', { name: t(m.share_queue), exact: true });
		// Focused after the layout's own focus move: one press confirms.
		await expect(queueIt).toBeFocused();

		const created = page.waitForResponse(
			(r) => r.url().endsWith('/api/jobs') && r.request().method() === 'POST'
		);
		await page.keyboard.press('Enter');
		const response = await created;
		expect([200, 201]).toContain(response.status());
		// Only the canonical link, with the server's allowlist asked for.
		expect(response.request().postDataJSON()).toEqual({
			url: `https://open.spotify.com/track/${TRACK_ID}`
		});
		expect(response.request().headers()['x-spotdl-client']).toBe('share');
		const job = (await response.json()) as Job;

		await expect(page.locator('#share-outcome')).toHaveText(OUTCOMES());
		await expect(
			page.getByRole('link', { name: t(m.share_open_queue), exact: true })
		).toBeFocused();
		// The job is this user's own.
		expect((await page.request.get(`/api/jobs/${job.id}`)).status()).toBe(200);
	});

	test('an off-site next is refused after the login', async ({ page, baseURL }) => {
		await page.goto(`/login?next=${encodeURIComponent('//evil.example/share')}`);
		await signIn(page);
		await expect(page).toHaveURL(`${baseURL}/`);
	});
});

test.describe('signed in', () => {
	test.use({ storageState: USER_STATE });

	test('a share with no Spotify link says so and queues nothing', async ({ page }) => {
		const posts: string[] = [];
		page.on('request', (r) => {
			if (r.method() === 'POST' && new URL(r.url()).pathname.startsWith('/api/'))
				posts.push(r.url());
		});
		await page.goto(`/share?text=${encodeURIComponent('Contact · Daft Punk spotify:track:x')}`);
		await expect(page.getByText(t(m.share_none), { exact: true })).toBeVisible();
		await expect(
			page.getByText('Contact · Daft Punk spotify:track:x', { exact: true })
		).toBeVisible();
		await expect(
			page.getByRole('link', { name: t(m.share_open_queue), exact: true })
		).toBeFocused();
		expect(posts).toEqual([]);
	});

	for (const next of [
		'https://evil.example/',
		'//evil.example/share',
		'/\\evil.example',
		'javascript:alert(1)'
	]) {
		test(`/login?next=${next} goes home, not off the site`, async ({ page, baseURL }) => {
			await page.goto(`/login?next=${encodeURIComponent(next)}`);
			await expect(page).toHaveURL(`${baseURL}/`);
		});
	}

	test('/login?next=/share… goes straight on to the share', async ({ page, baseURL }) => {
		await page.goto(`/login?next=${encodeURIComponent(SHARE)}`);
		await expect(page).toHaveURL(`${baseURL}${SHARE}`);
		await expect(page.getByRole('button', { name: t(m.share_queue), exact: true })).toBeVisible();
	});
});
