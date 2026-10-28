import { expect, request, test, type Page } from '@playwright/test';
import {
	ADMIN_STATE,
	USER_STATE,
	normalizeEmail,
	stackPython,
	userIdentity
} from './support/stack';
import { m, t } from './support/i18n';
import { loginViaUi, logoutViaUi, openDashboard } from './support/ui';

// Spec 20 (v62): the store and navigation fixes F1-F10, against the real stack.

const FIXTURE = 'v62fixture';

/** Creates `settled` newer jobs and `waiting` older ones for `email`, so the waiting ones sit
 * past the first page (50 rows). Returns each waiting job's id and its one waiting track's. */
function makeFixture(email: string, waiting: number): { jobId: string; trackId: string }[] {
	const out = stackPython(
		`
import json, sys
from datetime import datetime, timedelta, timezone
from app.db import SessionLocal
from app.models import Job, JobSourceType, JobState, Track, TrackState, User
db = SessionLocal()
user = db.query(User).filter(User.email == sys.argv[1]).one()
now = datetime.now(timezone.utc)
made = []
for n in range(int(sys.argv[2])):
    job = Job(user_id=user.id, source_url=f"https://open.spotify.com/track/${FIXTURE}w{n}",
              source_type=JobSourceType.TRACK, state=JobState.EXPANDED,
              created_at=now - timedelta(days=400, minutes=n))
    db.add(job); db.flush()
    track = Track(job_id=job.id, spotify_track_id=f"${FIXTURE}w{n}", song_json={"name": f"${FIXTURE} waiting {n}"},
                  state=TrackState.WAITING, scheduled_at=now + timedelta(days=1))
    db.add(track); db.flush()
    made.append({"jobId": str(job.id), "trackId": str(track.id)})
for n in range(55):
    job = Job(user_id=user.id, source_url=f"https://open.spotify.com/track/${FIXTURE}s{n}",
              source_type=JobSourceType.TRACK, state=JobState.EXPANDED,
              created_at=now - timedelta(days=300, minutes=n))
    db.add(job); db.flush()
    db.add(Track(job_id=job.id, spotify_track_id=f"${FIXTURE}s{n}", song_json={"name": f"${FIXTURE} done {n}"},
                 state=TrackState.SKIPPED_DUPLICATE))
db.commit()
# As a job created through the API has: its status on record, so its first move names what it
# left (prev_status) and the store moves the chip from the event alone.
from app.services import job_status
for item in made:
    job_status.publish_change(db, item["jobId"])
print(json.dumps(made))
`,
		[normalizeEmail(email), String(waiting)]
	);
	return JSON.parse(out.split('\n').at(-1)!);
}

function dropFixture(): void {
	stackPython(`
from sqlalchemy import text
from app.db import SessionLocal
db = SessionLocal()
ids = "select id from jobs where source_url like '%${FIXTURE}%'"
db.execute(text(f"delete from track_attempts where track_id in (select id from tracks where job_id in ({ids}))"))
db.execute(text(f"delete from tracks where job_id in ({ids})"))
gone = [str(r[0]) for r in db.execute(text(ids))]
db.execute(text(f"delete from jobs where source_url like '%${FIXTURE}%'"))
db.commit()
from app.services import job_status
for job_id in gone:
    job_status._get_client().delete(job_status._key(job_id))
`);
}

/** A status chip's count; a status with none has no chip at all. */
async function chipCount(page: Page, key: string): Promise<number> {
	const n = page.locator(`button.chip[data-kb-row="${key}"] .n`);
	if ((await n.count()) === 0) return 0;
	return Number((await n.innerText()).replace(/\D/g, ''));
}

/** The server's own counts for this identity's default view. */
async function serverCounts(baseURL: string, state: string): Promise<Record<string, number>> {
	const api = await request.newContext({ baseURL, storageState: state });
	const page = await (await api.get('/api/jobs?limit=1')).json();
	await api.dispose();
	return page.counts_by_status;
}

test.describe('F1/F2/F3: the state chips and rows stay right', () => {
	test.use({ storageState: USER_STATE });
	let targets: { jobId: string; trackId: string }[];

	test.beforeAll(() => {
		dropFixture();
		targets = makeFixture(userIdentity().email, 3);
	});
	test.afterAll(() => dropFixture());

	test('F1: a job settling on page 2 moves its chip at once', async ({ page, baseURL }, info) => {
		await openDashboard(page);
		const [target] = targets;
		await expect(page.locator(`[data-kb-row="${target.jobId}"]`)).toHaveCount(0);
		const before = {
			waiting: await chipCount(page, 'waiting'),
			partial: await chipCount(page, 'settled:partial')
		};
		await page.screenshot({ path: info.outputPath('f1-before.png') });

		const reReads: string[] = [];
		page.on('request', (r) => {
			const url = new URL(r.url());
			if (url.pathname === '/api/jobs' && url.searchParams.get('limit') === '1')
				reReads.push(r.url());
		});
		const api = await request.newContext({ baseURL, storageState: USER_STATE });
		const started = Date.now();
		expect((await api.delete(`/api/tracks/${target.trackId}`)).status()).toBe(200);
		await api.dispose();

		await expect
			.poll(
				async () => [await chipCount(page, 'waiting'), await chipCount(page, 'settled:partial')],
				{
					timeout: 2_000
				}
			)
			.toEqual([before.waiting - 1, before.partial + 1]);
		info.annotations.push({ type: 'moved after', description: `${Date.now() - started} ms` });
		// From the event's prev_status: no counts re-read was needed to place it.
		expect(reReads).toEqual([]);
		await page.screenshot({ path: info.outputPath('f1-after.png') });
		expect(await serverCounts(baseURL!, USER_STATE)).toMatchObject({
			waiting: before.waiting - 1,
			'settled:partial': before.partial + 1
		});
	});

	test('F2: "load more" read before a settle and landing after it never undoes it', async ({
		page,
		baseURL
	}) => {
		await openDashboard(page);
		const target = targets[1];
		const before = await chipCount(page, 'waiting');
		let release!: () => void;
		const held = new Promise<void>((done) => (release = done));
		await page.route(/\/api\/jobs\?.*cursor=/, async (route) => {
			// The page is read now, before the settle; it's handed over only after it.
			const response = await route.fetch();
			await held;
			await route.fulfill({ response });
		});
		await page.getByRole('button', { name: t(m.dashboard_more_jobs), exact: true }).click();
		await page.waitForTimeout(300);

		const api = await request.newContext({ baseURL, storageState: USER_STATE });
		expect((await api.delete(`/api/tracks/${target.trackId}`)).status()).toBe(200);
		await api.dispose();
		await expect.poll(() => chipCount(page, 'waiting')).toBe(before - 1);

		release();
		await expect(page.locator(`[data-kb-row="${target.jobId}"]`).first()).toBeVisible();
		await page.waitForTimeout(1_500);
		const server = await serverCounts(baseURL!, USER_STATE);
		for (const key of ['waiting', 'settled:partial', 'settled:complete', 'active', 'cancelled']) {
			expect(await chipCount(page, key), key).toBe(server[key] ?? 0);
		}
	});

	test('F3: a refresh the api can’t answer keeps the row; it updates once the api is back', async ({
		page,
		baseURL
	}) => {
		await openDashboard(page);
		await page.getByRole('button', { name: t(m.dashboard_more_jobs), exact: true }).click();
		const target = targets[2];
		const row = page.locator(`li[data-kb-row="${target.jobId}"]`);
		await expect(row).toBeVisible();
		// The api "stopped" for this job's refresh: nginx (or Vite) answers 502.
		await page.route(`**/api/jobs/${target.jobId}`, (route) =>
			route.fulfill({ status: 502, contentType: 'text/html', body: '<h1>502 Bad Gateway</h1>' })
		);
		const api = await request.newContext({ baseURL, storageState: USER_STATE });
		expect((await api.delete(`/api/tracks/${target.trackId}`)).status()).toBe(200);
		await page.waitForTimeout(2_000);
		await expect(row).toBeVisible();
		await page.unroute(`**/api/jobs/${target.jobId}`);

		// The next event (any job's) asks again.
		const other = makeFixture(userIdentity().email, 1)[0];
		// A cancel, never a retry: a retried fixture track would go to worker-dl for real.
		expect((await api.delete(`/api/tracks/${other.trackId}`)).status()).toBe(200);
		await api.dispose();
		await expect(row.getByText(t(m.status_settled_partial), { exact: false }).first()).toBeVisible({
			timeout: 5_000
		});
	});
});

test.describe('F4: a stream silent past its heartbeat starts over', () => {
	test.use({ storageState: USER_STATE });

	test('offline longer than the heartbeat, then online: reconnected and resynced within ~2s', async ({
		page,
		context
	}, info) => {
		const streams: number[] = [];
		const lists: number[] = [];
		page.on('request', (r) => {
			const path = new URL(r.url()).pathname;
			if (path === '/api/stream') streams.push(Date.now());
			if (path === '/api/jobs') lists.push(Date.now());
		});
		await openDashboard(page);
		await context.setOffline(true);
		await page.waitForTimeout(20_000);
		const online = Date.now();
		await context.setOffline(false);
		await expect.poll(() => streams.filter((at) => at >= online).length).toBeGreaterThan(0);
		await expect.poll(() => lists.filter((at) => at >= online).length).toBeGreaterThan(0);
		const reconnected = streams.find((at) => at >= online)! - online;
		const resynced = lists.find((at) => at >= online)! - online;
		info.annotations.push({
			type: 'timings',
			description: `stream +${reconnected}ms, resync +${resynced}ms`
		});
		expect(resynced).toBeLessThan(2_500);
		await expect(page.getByText(t(m.dashboard_link_live), { exact: true })).toBeVisible();
	});

	test('a "live" stream silent past the heartbeat restarts on a return to the tab', async ({
		page
	}, info) => {
		const streams: number[] = [];
		page.on('request', (r) => {
			if (new URL(r.url()).pathname === '/api/stream') streams.push(Date.now());
		});
		await openDashboard(page);
		// The last word heard from the stream, pushed back past the silence threshold: what a
		// laptop's sleep leaves (no `offline`, an OPEN EventSource that hears nothing).
		await page.clock.install();
		await page.clock.fastForward(20_000);
		const back = Date.now();
		await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
		await expect.poll(() => streams.filter((at) => at >= back).length).toBeGreaterThan(0);
		info.annotations.push({
			type: 'restart',
			description: `+${streams.find((at) => at >= back)! - back}ms`
		});
	});
});

test.describe('F5: an unknown address renders the app’s error page', () => {
	test.use({ storageState: USER_STATE });

	test('hard navigation to /does-not-exist, and home by keyboard', async ({ page }) => {
		await page.goto('/does-not-exist');
		await expect(
			page.getByRole('heading', { name: t(m.error_not_found_heading), level: 1 })
		).toBeVisible();
		const home = page.getByRole('link', { name: t(m.error_home), exact: true });
		for (let i = 0; i < 10 && !(await home.evaluate((el) => el === document.activeElement)); i++)
			await page.keyboard.press('Tab');
		await expect(home).toBeFocused();
		await page.keyboard.press('Enter');
		await expect(page).toHaveURL(/\/$/);
	});
});

test.describe('F6: unsaved edits on /settings ask before they are left', () => {
	test.use({ storageState: ADMIN_STATE });

	async function editTemplate(page: Page): Promise<string> {
		// In-app, as a user gets there: Back is then the app's own (popstate) navigation.
		await openDashboard(page);
		await page.getByRole('link', { name: t(m.nav_settings), exact: true }).click();
		await expect(page).toHaveURL(/\/settings$/);
		const field = page.locator('#output-template');
		// Loaded: a fill before the settings answer lands would be overwritten by it.
		await expect(field).not.toHaveValue('');
		const edited = `${await field.inputValue()} v62`;
		await field.fill(edited);
		return edited;
	}

	const dialog = (page: Page) =>
		page.getByRole('alertdialog', { name: t(m.unsaved_title), exact: true });

	test('a link, Back and the g d chord each ask; keep editing keeps the edit', async ({ page }) => {
		const edited = await editTemplate(page);

		// A link.
		await page.getByRole('link', { name: t(m.nav_queue), exact: true }).click();
		await expect(dialog(page)).toBeVisible();
		await expect(dialog(page).getByRole('button', { name: t(m.unsaved_keep) })).toBeFocused();
		await page.keyboard.press('Enter');
		await expect(dialog(page)).toBeHidden();
		await expect(page).toHaveURL(/\/settings$/);
		await expect(page.locator('#output-template')).toHaveValue(edited);

		// Browser Back.
		await page.goBack();
		await expect(dialog(page)).toBeVisible();
		await page.keyboard.press('Escape');
		await expect(dialog(page)).toBeHidden();
		await expect(page).toHaveURL(/\/settings$/);
		await expect(page.locator('#output-template')).toHaveValue(edited);

		// The g d chord (single keys are inert while typing: leave the field first).
		await page.locator('#output-template').blur();
		await page.keyboard.press('g');
		await page.keyboard.press('d');
		await expect(dialog(page)).toBeVisible();
		await dialog(page)
			.getByRole('button', { name: t(m.unsaved_keep) })
			.click();
		await expect(page).toHaveURL(/\/settings$/);
		await expect(page.locator('#output-template')).toHaveValue(edited);
	});

	test('a reload or closing the tab gets the browser’s own question', async ({ page }) => {
		await editTemplate(page);
		const asked: string[] = [];
		page.on('dialog', async (d) => {
			asked.push(d.type());
			await d.dismiss();
		});
		const edited = await page.locator('#output-template').inputValue();
		// Answered "stay": the reload never happens, so it times out.
		await page.reload({ timeout: 3_000 }).catch(() => {});
		expect(asked).toEqual(['beforeunload']);
		await expect(page.locator('#output-template')).toHaveValue(edited);
	});

	test('discard changes goes where the navigation was going', async ({ page }) => {
		await editTemplate(page);
		await page.goBack();
		await expect(dialog(page)).toBeVisible();
		await dialog(page)
			.getByRole('button', { name: t(m.unsaved_discard) })
			.click();
		await expect(page).toHaveURL(/\/$/);
	});
});

test.describe('F7/F8 on the real stack', () => {
	test.use({ storageState: USER_STATE });

	test('F7: /account saves a preference when it is chosen, with no save button', async ({
		page
	}) => {
		await page.goto('/account');
		const retention = page.getByRole('group', { name: t(m.account_retention_heading) });
		await expect(
			retention.getByRole('button', { name: t(m.account_retention_never) })
		).toBeEnabled();
		await expect(page.getByRole('button', { name: t(m.common_save), exact: true })).toHaveCount(0);
		const never = retention.getByRole('button', { name: t(m.account_retention_never) });
		const auto = retention.getByRole('button', { name: t(m.account_retention_auto) });
		const status = retention.getByRole('status');
		// Whatever it was, a press of the other choice is saved at once ("Saved at 14:03").
		if ((await auto.getAttribute('aria-pressed')) === 'true') {
			await never.click();
			await expect(status).toHaveText(/\d/);
		}
		await auto.click();
		await expect(auto).toHaveAttribute('aria-pressed', 'true');
		await expect(status).toHaveText(/\d/);
		// A typed number is unsaved until committed (Enter, or leaving the field).
		const days = page.locator('#retention-days');
		const typed = (await days.inputValue()) === '45' ? '46' : '45';
		await days.fill(typed);
		await expect(status).toHaveText(t(m.common_unsaved_changes));
		await days.press('Enter');
		await expect(status).toHaveText(/\d/);
		await page.reload();
		await expect(page.locator('#retention-days')).toHaveValue(typed);
		// Back to never, the identity's default.
		await page
			.getByRole('group', { name: t(m.account_retention_heading) })
			.getByRole('button', { name: t(m.account_retention_never) })
			.click();
		await expect(
			page.getByRole('group', { name: t(m.account_retention_heading) }).getByRole('status')
		).toHaveText(/\d/);
	});

	test('F7: a second choice made while the first is saving is saved after it', async ({ page }) => {
		await page.goto('/account');
		const retention = page.getByRole('group', { name: t(m.account_retention_heading) });
		const never = retention.getByRole('button', { name: t(m.account_retention_never) });
		const auto = retention.getByRole('button', { name: t(m.account_retention_auto) });
		await expect(never).toBeEnabled();
		if ((await never.getAttribute('aria-pressed')) !== 'true') {
			await never.click();
			await expect(retention.getByRole('status')).toHaveText(/\d/);
		}
		// Every save takes a second on its way, as on a slow connection.
		await page.route('**/api/settings/retention', async (route) => {
			await new Promise((done) => setTimeout(done, 1_000));
			await route.continue();
		});
		await auto.click();
		await never.click();
		await expect(never).toHaveAttribute('aria-pressed', 'true');
		await expect(retention.getByRole('status')).toHaveText(/\d/, { timeout: 10_000 });
		await page.unroute('**/api/settings/retention');
		await page.reload();
		await expect(
			page
				.getByRole('group', { name: t(m.account_retention_heading) })
				.getByRole('button', { name: t(m.account_retention_never) })
		).toHaveAttribute('aria-pressed', 'true');
	});

	test('F8: clear log is off with its reason once there is nothing to clear', async ({
		page,
		baseURL
	}, info) => {
		await openDashboard(page);
		const clear = page.getByRole('button', { name: t(m.queuectl_clear), exact: true });
		let archived: string[] = [];
		try {
			if ((await clear.getAttribute('aria-disabled')) !== 'true') {
				// The real action, on this identity's real log: every job it archives is put back
				// afterwards (the later specs read them).
				const answered = page.waitForResponse(
					(r) =>
						new URL(r.url()).pathname === '/api/jobs/archive' && r.request().method() === 'POST'
				);
				await clear.click();
				await page
					.getByRole('alertdialog')
					.getByRole('button', { name: t(m.queuectl_clear_yes), exact: true })
					.click();
				archived = (await (await answered).json()).archived_ids;
			}
			await expect(clear).toHaveAttribute('aria-disabled', 'true');
			await expect(clear).toHaveAccessibleDescription(t(m.queuectl_clear_none));
			const snapshot = await page.locator('.log-tools').ariaSnapshot();
			info.annotations.push({ type: 'aria', description: snapshot });
			await page.screenshot({ path: info.outputPath('f8-disabled.png') });
			// Still reachable by keyboard, and pressing it asks nothing.
			await clear.focus();
			await page.keyboard.press('Enter');
			await expect(page.getByRole('alertdialog')).toHaveCount(0);
		} finally {
			if (archived.length > 0) {
				const api = await request.newContext({ baseURL, storageState: USER_STATE });
				const back = await api.post('/api/jobs/unarchive', { data: { job_ids: archived } });
				expect(back.status()).toBe(200);
				await api.dispose();
			}
		}
	});
});

test.describe('F9: a sign-out reaches the other tabs at once', () => {
	test('logging out in tab A resets tab B within a second', async ({ browser }) => {
		// A fresh session of its own: the saved one the other specs use stays signed in.
		const context = await browser.newContext();
		const a = await context.newPage();
		await loginViaUi(a, userIdentity());
		const b = await context.newPage();
		await openDashboard(b);
		const bRequests: string[] = [];
		b.on('request', (r) => bRequests.push(new URL(r.url()).pathname));
		// What the fallback would have been: a 401 answer to tab B's own requests.
		const b401s: string[] = [];
		b.on('response', (r) => {
			if (r.status() === 401 && !new URL(b.url()).pathname.startsWith('/login'))
				b401s.push(new URL(r.url()).pathname);
		});

		const started = Date.now();
		await logoutViaUi(a);
		await b.waitForURL('**/login', { timeout: 1_000 });
		const took = Date.now() - started;
		// The poll's 401 didn't do it: tab B sent no worker poll in that time (5s cadence).
		expect(took).toBeLessThan(1_000);
		// The push did it: no 401 reached tab B before it left for /login.
		expect(b401s).toEqual([]);
		await expect(b.getByRole('button', { name: t(m.login_connect), exact: true })).toBeVisible();
		test.info().annotations.push({
			type: 'tab B on /login after',
			description: `${took} ms; requests: ${bRequests.join(', ')}`
		});
		await context.close();
	});
});
