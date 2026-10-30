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
		[m.share_queued, m.share_queued_in_library, m.share_already_queued]
			.map((message) => t(message).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
			.join('|')
	);

// From the page itself: Playwright's own request contexts drop the `Secure` session cookie on
// http://127.0.0.1 (global-setup.ts), the browser's fetch doesn't.
interface FetchInit {
	method?: string;
	headers?: Record<string, string>;
	body?: string;
}

function pageFetch(page: Page, path: string, init?: FetchInit) {
	return page.evaluate(
		async ({ path, init }) => {
			const response = await fetch(path, init);
			return { status: response.status, body: await response.json().catch(() => null) };
		},
		{ path, init }
	);
}

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
		// The entries this tab has here; the login replaced its own, so nothing is behind the share.
		const entries = await page.evaluate(() => history.length);
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
		const openQueue = page.getByRole('link', { name: t(m.share_open_queue), exact: true });
		await expect(openQueue).toBeFocused();
		// The viewer's own jobs, where the new one is, whatever view the dashboard was left in.
		await expect(openQueue).toHaveAttribute('href', '/?view=mine');
		// Back from the queue shows the outcome again, never a second armed "queue it".
		// The share replaced the /login entry, so the one before it is the page the share came from.
		await openQueue.click();
		// A non-admin's dashboard drops `?view=` from its URL once it's there.
		await expect(page).toHaveURL(new RegExp(`^${baseURL}/(\\?view=mine)?$`));
		await page.goBack();
		await expect(page).toHaveURL(`${baseURL}${SHARE}`);
		await expect(page.locator('#share-outcome')).toHaveText(OUTCOMES());
		await expect(page.getByRole('button', { name: t(m.share_queue), exact: true })).toHaveCount(0);
		// A reload (or a tab the phone discarded) keeps it too.
		await page.reload();
		await expect(page.locator('#share-outcome')).toHaveText(OUTCOMES());
		await expect(page.getByRole('button', { name: t(m.share_queue), exact: true })).toHaveCount(0);
		// And nothing new behind it (no /login that would bring the confirm back): only the
		// dashboard ahead of it.
		expect(await page.evaluate(() => history.length)).toBe(entries + 1);
		await page.goBack();
		await expect(page).toHaveURL(`${baseURL}${SHARE}`);
		await expect(page.getByRole('button', { name: t(m.share_queue), exact: true })).toHaveCount(0);
		// The job is this user's own.
		expect((await pageFetch(page, `/api/jobs/${job.id}`)).status).toBe(200);
		// Archived once it settles (a duplicate, at beat's next pass), so the user's seed row stays
		// the newest "Contact" for the specs that look it up by title.
		await expect
			.poll(async () => (await pageFetch(page, `/api/jobs/${job.id}`)).body?.status?.lifecycle, {
				timeout: 120_000
			})
			.toBe('settled');
		const archived = await pageFetch(page, '/api/jobs/archive', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ job_ids: [job.id] })
		});
		expect(archived.status).toBe(200);
		expect(archived.body.archived_ids).toEqual([job.id]);
	});

	test('a share whose session ends before the confirm comes back after the next sign-in', async ({
		page,
		baseURL
	}) => {
		await page.goto(SHARE);
		await signIn(page);
		await expect(page).toHaveURL(`${baseURL}${SHARE}`);
		await expect(page.getByRole('button', { name: t(m.share_queue), exact: true })).toBeFocused();
		const entries = await page.evaluate(() => history.length);
		// The session ends under the page (expired, revoked): this tab's own cookie, so the
		// saved sessions other specs use are untouched.
		expect((await pageFetch(page, '/api/auth/logout', { method: 'POST' })).status).toBe(200);
		await page.keyboard.press('Enter');
		await expect(page).toHaveURL(/\/login\?next=/);
		expect(new URL(page.url()).searchParams.get('next')).toBe(SHARE);
		await signIn(page);
		await expect(page).toHaveURL(`${baseURL}${SHARE}`);
		await expect(page.getByRole('button', { name: t(m.share_queue), exact: true })).toBeFocused();
		// The hop to /login and back replaced the share's entry each way: nothing behind it.
		expect(await page.evaluate(() => history.length)).toBe(entries);
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

	test('a spotify.link short link is looked up, and a failed look-up can be retried', async ({
		page
	}) => {
		// A real short link (Spotify's link host answered it with this playlist on 2026-10-30),
		// resolved over the real network by the real backend: if Spotify ever repoints or
		// expires the code, this fails for that reason. Shown, not queued: a playlist would expand
		// into tracks for worker-dl.
		const short = 'https://spotify.link/6tpneu0iVIb';
		// A link that leads nowhere (422) fails the same way every time: no retry, the way out.
		await page.route('**/api/links/resolve', (route) =>
			route.fulfill({
				status: 422,
				contentType: 'application/json',
				body: JSON.stringify({ detail: 'x', code: 'short_link_unresolved', params: {} })
			})
		);
		await page.goto(`/share?text=${encodeURIComponent(short)}`);
		await expect(page.getByRole('alert')).toHaveText(t(m.error_short_link_unresolved));
		await expect(page.getByRole('button', { name: t(m.share_retry), exact: true })).toHaveCount(0);
		await expect(
			page.getByRole('link', { name: t(m.share_open_queue), exact: true })
		).toBeFocused();
		await page.unroute('**/api/links/resolve');

		let fail = true;
		await page.route('**/api/links/resolve', (route) =>
			fail
				? route.fulfill({
						status: 503,
						contentType: 'application/json',
						body: JSON.stringify({
							detail: 'x',
							code: 'short_link_unavailable',
							params: { reason: 'failed' }
						})
					})
				: route.continue()
		);
		await page.goto(`/share?text=${encodeURIComponent(`Listen on Spotify ${short}`)}`);
		await expect(page.getByText(short, { exact: true })).toBeVisible();
		await expect(page.getByRole('alert')).toHaveText(t(m.error_short_link_unavailable));
		const retry = page.getByRole('button', { name: t(m.share_retry), exact: true });
		await expect(retry).toBeFocused();

		fail = false;
		await page.keyboard.press('Enter');
		await expect(page.getByText(t(m.share_type_playlist), { exact: true })).toBeVisible();
		await expect(page.getByText('432nsnOM9L55tkiOFnHbI2', { exact: true })).toBeVisible();
		await expect(page.getByRole('button', { name: t(m.share_queue), exact: true })).toBeFocused();
	});

	for (const next of [
		'https://evil.example/',
		'//evil.example/share',
		'/\\evil.example',
		'javascript:alert(1)',
		// Dot segments the URL parser collapses into `//host` (review round 1).
		'/..//evil.example',
		'/%2e%2e//evil.example/share'
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
