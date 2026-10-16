import { expect, request, test, type Locator, type Page, type Request } from '@playwright/test';
import type { Job, Proxy } from '../src/lib/api';
import { ADMIN_STATE, stackPython, spotifyTrackUrl, waitForJob } from './support/stack';
import { jobRow, jobToggle, openDashboard, trackToggle } from './support/ui';

test.use({ storageState: ADMIN_STATE });

/** Ledger tracks (AC/DC, Back In Black) no other spec submits, one pair per project so the two
 * runs never share a job title. Submitted while the worker is paused, they are held, never
 * downloaded (dedup and the pause are both decided in download_track, before any network). */
const CANCEL_TRACKS = {
	desktop: { track: '0C80GCp0mMuBzLf3EAXqxv', job: '6Th6ND8RQPywiyelecP5Lf' },
	mobile: { track: '6rAy2MsMUabbqu2VygrblP', job: '5XeMsYb1rWxQL1bUUaZajn' }
} as const;

interface Guarded {
	/** The control that opens the question. */
	trigger: Locator;
	/** The dialog's accessible name (its title). */
	title: string;
	keep: string;
	confirm: string;
	/** The request the action sends, and only that one. */
	sends: (r: Request) => boolean;
}

function call(method: string, path: string | RegExp): (r: Request) => boolean {
	return (r) => {
		if (r.method() !== method) return false;
		const actual = new URL(r.url()).pathname;
		return typeof path === 'string' ? actual === path : path.test(actual);
	};
}

/** v43 (F08): the keyboard-only round trip (focus moves in to the safe button, Esc closes,
 * focus returns to the trigger), then the pointer's safe button. Neither sends the request. */
async function expectCancelDoesNothing(page: Page, g: Guarded): Promise<void> {
	const sent: string[] = [];
	const onRequest = (r: Request) => {
		if (g.sends(r)) sent.push(`${r.method()} ${r.url()}`);
	};
	page.on('request', onRequest);
	try {
		const dialog = page.getByRole('alertdialog', { name: g.title });

		await g.trigger.focus();
		await page.keyboard.press('Enter');
		await expect(dialog).toBeVisible();
		await expect(dialog.getByRole('button', { name: g.keep, exact: true })).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(dialog).toBeHidden();
		await expect(g.trigger).toBeFocused();

		await g.trigger.click();
		await expect(dialog).toBeVisible();
		await dialog.getByRole('button', { name: g.keep, exact: true }).click();
		await expect(dialog).toBeHidden();
		await expect(g.trigger).toBeFocused();

		// A request fired on cancel would leave within a tick; give it room to show up.
		await page.waitForTimeout(750);
		expect(sent, `${g.title}: cancelling sent nothing`).toEqual([]);
	} finally {
		page.off('request', onRequest);
	}
}

/** The destructive button performs the action: its request goes out and succeeds. */
async function confirmPerforms(page: Page, g: Guarded): Promise<void> {
	const response = page.waitForResponse((r) => g.sends(r.request()));
	await g.trigger.click();
	await page
		.getByRole('alertdialog', { name: g.title })
		.getByRole('button', { name: g.confirm, exact: true })
		.click();
	expect((await response).ok(), `${g.title}: confirming performed it`).toBe(true);
	await expect(page.getByRole('alertdialog')).toHaveCount(0);
	// The action may remove or disable its own trigger; focus must land somewhere, not <body>.
	await expect
		.poll(() => page.evaluate(() => document.activeElement?.tagName ?? 'none'), {
			message: `${g.title}: focus after confirming`
		})
		.not.toMatch(/^(BODY|none)$/);
}

test('clear log asks first', async ({ page, baseURL }) => {
	await openDashboard(page);
	const g: Guarded = {
		trigger: page.getByRole('button', { name: 'clear log', exact: true }),
		title: 'Clear the log?',
		keep: 'keep log',
		confirm: 'clear log',
		sends: call('POST', '/api/jobs/archive')
	};
	await expectCancelDoesNothing(page, g);

	const archived = page.waitForResponse((r) => g.sends(r.request()));
	await confirmPerforms(page, g);
	const { archived_ids } = (await (await archived).json()) as { archived_ids: string[] };
	// Put the log back: the other specs (and the other project's run) look up the seed jobs.
	if (archived_ids.length > 0) {
		const admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
		const restored = await admin.post('/api/jobs/unarchive', { data: { job_ids: archived_ids } });
		expect.soft(restored.status(), 'unarchiving what clear log archived').toBe(200);
		await admin.dispose();
	}
});

test('job cancel and cancel track ask first', async ({ page, baseURL }, testInfo) => {
	test.setTimeout(240_000);
	const ids = testInfo.project.name === 'mobile' ? CANCEL_TRACKS.mobile : CANCEL_TRACKS.desktop;
	const admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
	const created: Job[] = [];
	expect((await admin.post('/api/worker/pause')).ok()).toBe(true);
	try {
		for (const id of [ids.track, ids.job]) {
			const response = await admin.post('/api/jobs', { data: { url: spotifyTrackUrl(id) } });
			expect(response.status()).toBe(201);
			created.push((await response.json()) as Job);
		}
		// Expanded (a real Spotify read), each with one track the paused worker holds
		// (`pending`/`queued`, or `waiting` once download_track's pause gate has held it).
		const [trackJob, cancelJob] = await Promise.all(
			created.map((job) =>
				waitForJob(admin, job.id, (j) => ['active', 'waiting'].includes(j.status.lifecycle), 90_000)
			)
		);

		await openDashboard(page);

		// Job cancel: the row's own "cancel <title>".
		const jobGuard: Guarded = {
			trigger: jobRow(page, cancelJob.title).getByRole('button', {
				name: `cancel ${cancelJob.title}`,
				exact: true
			}),
			title: 'Cancel this job?',
			keep: 'keep job',
			confirm: 'cancel job',
			sends: call('DELETE', `/api/jobs/${cancelJob.id}`)
		};
		await expectCancelDoesNothing(page, jobGuard);
		await confirmPerforms(page, jobGuard);
		await waitForJob(admin, cancelJob.id, (j) => j.status.lifecycle === 'cancelled', 15_000);

		// Cancel track: inside the expanded track of the other job.
		await jobToggle(page, trackJob.title).click();
		await trackToggle(page, trackJob.title, trackJob.title).click();
		const tracksResponse = await admin.get(`/api/jobs/${trackJob.id}/tracks`);
		const trackId = ((await tracksResponse.json()) as { items: { id: string }[] }).items[0].id;
		const trackGuard: Guarded = {
			trigger: jobRow(page, trackJob.title).getByRole('button', {
				name: 'cancel track',
				exact: true
			}),
			title: 'Cancel this track?',
			keep: 'keep track',
			confirm: 'cancel track',
			sends: call('DELETE', `/api/tracks/${trackId}`)
		};
		await expectCancelDoesNothing(page, trackGuard);
		await confirmPerforms(page, trackGuard);
		await waitForJob(
			admin,
			trackJob.id,
			(j) => !['active', 'waiting'].includes(j.status.lifecycle),
			15_000
		);
	} finally {
		const resumed = await admin.post('/api/worker/resume');
		expect.soft(resumed.ok(), 'resuming the worker').toBe(true);
		for (const job of created) {
			const current = (await (await admin.get(`/api/jobs/${job.id}`)).json()) as Job;
			if (!['settled', 'failed', 'cancelled'].includes(current.status.lifecycle)) {
				await admin.delete(`/api/jobs/${job.id}`);
			}
		}
		// Out of the default list, so a later run's rows of the same title are the only ones.
		if (created.length > 0) {
			await admin.post('/api/jobs/archive', { data: { job_ids: created.map((j) => j.id) } });
		}
		await admin.dispose();
	}
});

test('worker pause and breaker release ask first', async ({ page, baseURL }) => {
	const admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
	try {
		await page.goto('/settings');
		const worker = page.getByRole('region', { name: 'Worker control' });

		const pause: Guarded = {
			trigger: worker.getByRole('button', { name: 'pause downloads', exact: true }),
			title: 'Pause all downloads?',
			keep: 'keep running',
			confirm: 'pause downloads',
			sends: call('POST', '/api/worker/pause')
		};
		await expectCancelDoesNothing(page, pause);
		await confirmPerforms(page, pause);
		await expect(worker.getByText('Downloads paused', { exact: true })).toBeVisible();
		// Resuming is safe and asks nothing.
		const resumed = page.waitForResponse((r) => call('POST', '/api/worker/resume')(r.request()));
		await worker.getByRole('button', { name: 'resume downloads', exact: true }).click();
		expect((await resumed).ok()).toBe(true);
		await expect(page.getByRole('alertdialog')).toHaveCount(0);

		// A real trip needs five failed downloads in a row (GOTCHAS v42); the hold itself is
		// one column, so it is set directly and released through the page.
		stackPython(`
from datetime import datetime, timedelta, timezone
from app.db import SessionLocal
from app.models.worker_state import WorkerState
db = SessionLocal()
state = db.query(WorkerState).one()
state.breaker_tripped_until = datetime.now(timezone.utc) + timedelta(hours=1)
db.commit()
`);
		const release: Guarded = {
			trigger: worker.getByRole('button', { name: 'release now', exact: true }),
			title: 'Release the hold now?',
			keep: 'keep holding',
			confirm: 'release now',
			sends: call('POST', '/api/worker/breaker/release')
		};
		await expect(release.trigger).toBeVisible({ timeout: 10_000 });
		await expectCancelDoesNothing(page, release);
		await confirmPerforms(page, release);
		await expect(release.trigger).toHaveCount(0);
	} finally {
		await admin.post('/api/worker/resume');
		await admin.post('/api/worker/breaker/release');
		await admin.dispose();
	}
});

test('remove proxy asks first', async ({ page, baseURL }, testInfo) => {
	const admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
	// TEST-NET-3, switched off at once so no download could ever pick it.
	const url = `http://203.0.113.${testInfo.project.name === 'mobile' ? 44 : 43}:8080`;
	const created = (await (await admin.post('/api/proxies', { data: { url } })).json()) as Proxy;
	try {
		expect(
			(await admin.patch(`/api/proxies/${created.id}`, { data: { enabled: false } })).ok()
		).toBe(true);
		await page.goto('/settings#proxies');
		const remove: Guarded = {
			trigger: page.getByRole('button', { name: `remove ${created.url}`, exact: true }),
			title: 'Remove this proxy?',
			keep: 'keep proxy',
			confirm: 'remove proxy',
			sends: call('DELETE', `/api/proxies/${created.id}`)
		};
		await expectCancelDoesNothing(page, remove);
		await confirmPerforms(page, remove);
		await expect(remove.trigger).toHaveCount(0);
		const left = (await (await admin.get('/api/proxies')).json()) as Proxy[];
		expect(left.some((p) => p.id === created.id)).toBe(false);
	} finally {
		await admin.delete(`/api/proxies/${created.id}`);
		await admin.dispose();
	}
});

test('start sweep asks first', async ({ page }) => {
	await page.goto('/library');
	const start: Guarded = {
		trigger: page.getByRole('button', { name: 'start sweep', exact: true }),
		title: 'Start a library sweep?',
		keep: 'not now',
		confirm: 'start sweep',
		sends: call('POST', '/api/library/sort')
	};
	await expect(start.trigger).toBeEnabled();
	await expectCancelDoesNothing(page, start);
	await confirmPerforms(page, start);
	// The run reports back over the stream; with nothing new to move it finishes at once, and
	// the page must land on the finished report even when the stream beat the POST's answer.
	await expect(page.getByText(/^Last sweep finished/)).toBeVisible({ timeout: 30_000 });
	await expect(start.trigger).toBeEnabled();
});
