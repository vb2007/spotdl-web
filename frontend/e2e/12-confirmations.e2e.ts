import {
	expect,
	request,
	test,
	type APIRequestContext,
	type Locator,
	type Page,
	type Request,
	type Response
} from '@playwright/test';
import type { Job, Proxy, WorkerStatus } from '../src/lib/api';
import {
	ADMIN_STATE,
	expandWorkerBusy,
	ledgerMisses,
	recordHeldSubmission,
	removeTestProxy,
	restartExpandWorker,
	restoreSweepReport,
	snapshotSweepReport,
	stopExpandWorker,
	restoreWorker,
	stackPython,
	stageWorker,
	spotifyTrackUrl,
	waitForJob
} from './support/stack';
import { jobRow, jobToggle, openDashboard, trackToggle } from './support/ui';

test.use({ storageState: ADMIN_STATE });

/** Ledger tracks (AC/DC, Back In Black) no other spec submits, one pair per project so the two
 * runs never share a job title. Submitted while the worker is paused, they are held, never
 * downloaded (dedup and the pause are both decided in download_track, before any network). */
const CANCEL_TRACKS = {
	desktop: { track: '0C80GCp0mMuBzLf3EAXqxv', job: '6Th6ND8RQPywiyelecP5Lf' },
	mobile: { track: '6rAy2MsMUabbqu2VygrblP', job: '5XeMsYb1rWxQL1bUUaZajn' }
} as const;

/** Submitted while `worker-expand` is stopped, so the job stays "tuning in" (expanding) and is
 * cancelled before it is ever read: no Spotify read, no track, no download. */
const SUBMISSION_TRACKS = {
	desktop: '08mG3Y1vljYA6bvDt4Wqkj',
	mobile: '2SiXAy7TuUkycRVbbWDEpo'
} as const;

/** The suite shares the developer's stack: a worker they paused, or a real hold, is theirs.
 * A test that has to pause or hold the worker skips rather than override or release it. */
async function requireQuietWorker(admin: APIRequestContext): Promise<void> {
	const status = (await (await admin.get('/api/worker/status')).json()) as WorkerStatus;
	const holding =
		status.breaker_tripped_until !== null &&
		new Date(status.breaker_tripped_until).getTime() > Date.now();
	test.skip(status.paused || holding, 'the dev worker is paused or holding; not overriding it');
}

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

	// Whatever clear log archives is put back, even if a check after it fails: the other specs
	// (and the other project's run) look up the seed jobs.
	const archived: Promise<string[]>[] = [];
	const onResponse = (r: Response) => {
		if (!g.sends(r.request()) || !r.ok()) return;
		archived.push(r.json().then((body: { archived_ids: string[] }) => body.archived_ids));
	};
	page.on('response', onResponse);
	try {
		await confirmPerforms(page, g);
	} finally {
		page.off('response', onResponse);
		const archivedIds = (await Promise.all(archived)).flat();
		if (archivedIds.length > 0) {
			const admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
			const restored = await admin.post('/api/jobs/unarchive', { data: { job_ids: archivedIds } });
			expect.soft(restored.status(), 'unarchiving what clear log archived').toBe(200);
			await admin.dispose();
		}
	}
});

test('job cancel and cancel track ask first', async ({ page, baseURL }, testInfo) => {
	test.setTimeout(240_000);
	const ids = testInfo.project.name === 'mobile' ? CANCEL_TRACKS.mobile : CANCEL_TRACKS.desktop;
	// Before any context of its own: a skip then leaves nothing open.
	await requireQuietWorker(page.request);
	const admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
	const created: Job[] = [];
	// Held by a paused worker they never download, but only a ledger hit is safe if something
	// went wrong and one did run.
	expect(ledgerMisses([ids.track, ids.job]), 'cancel tracks are ledger hits').toEqual([]);
	stageWorker({ paused: true });
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
		// Cancel what's left *before* resuming, so no held track is dispatched after this test.
		for (const job of created) {
			const current = (await (await admin.get(`/api/jobs/${job.id}`)).json()) as Job;
			if (!['settled', 'failed', 'cancelled'].includes(current.status.lifecycle)) {
				await admin.delete(`/api/jobs/${job.id}`);
			}
		}
		restoreWorker();
		// Out of the default list, so a later run's rows of the same title are the only ones.
		if (created.length > 0) {
			await admin.post('/api/jobs/archive', { data: { job_ids: created.map((j) => j.id) } });
		}
		await admin.dispose();
	}
});

test('worker pause and breaker release ask first', async ({ page, baseURL }) => {
	// Before any context of its own: a skip then leaves nothing open.
	await requireQuietWorker(page.request);
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
		stageWorker({ paused: true });
		await confirmPerforms(page, pause);
		await expect(worker.getByText('Downloads paused', { exact: true })).toBeVisible();
		// Resuming is safe and asks nothing.
		const resumed = page.waitForResponse((r) => call('POST', '/api/worker/resume')(r.request()));
		await worker.getByRole('button', { name: 'resume downloads', exact: true }).click();
		expect((await resumed).ok()).toBe(true);
		await expect(page.getByRole('alertdialog')).toHaveCount(0);

		// A real trip needs five failed downloads in a row (GOTCHAS v42); the hold itself is
		// one column, so it is set directly and released through the page. The release zeroes
		// the failure streak, so the streak is recorded first and put back afterwards.
		const hold = new Date(Date.now() + 3_600_000).toISOString();
		// Recorded before it's written, so even a run killed right after leaves it undoable.
		stageWorker({ hold });
		const failures = Number(
			stackPython(`
from app.db import SessionLocal
from app.models.worker_state import WorkerState
print(SessionLocal().query(WorkerState).one().consecutive_failures)
`)
		);
		stageWorker({ failures });
		stackPython(
			`
import sys
from datetime import datetime
from app.db import SessionLocal
from app.models.worker_state import WorkerState
db = SessionLocal()
db.query(WorkerState).one().breaker_tripped_until = datetime.fromisoformat(sys.argv[1])
db.commit()
`,
			[hold]
		);
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
		// Back to the quiet worker this test started from (requireQuietWorker): unpaused, the
		// staged hold gone (only if it's still the staged one, never a real trip), the streak
		// as it was.
		restoreWorker();
		await admin.dispose();
	}
});

test('remove proxy asks first', async ({ page, baseURL }, testInfo) => {
	const admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
	// TEST-NET-3, switched off at once so no download could ever pick it.
	const url = `http://203.0.113.${testInfo.project.name === 'mobile' ? 44 : 43}:8080`;
	await removeTestProxy(admin, url);
	const response = await admin.post('/api/proxies', { data: { url } });
	expect(response.status(), 'creating the test proxy').toBe(201);
	const created = (await response.json()) as Proxy;
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
	// A real sweep: only with nothing waiting to be filed, so it moves no file and archives no
	// one's jobs on the shared dev stack; never when Matrix is configured, where its "sweep
	// finished" alert would reach a real room.
	const alerts = (await (await page.request.get('/api/settings/alerts')).json()) as {
		configured: boolean;
	};
	test.skip(alerts.configured, 'Matrix alerts are configured; a sweep would post to the room');
	const unfiled = Number(
		stackPython(`
from sqlalchemy import text
from app.db import SessionLocal
print(SessionLocal().execute(text("select count(*) from downloaded_tracks where not in_library")).scalar())
`)
	);
	test.skip(unfiled > 0, `${unfiled} downloads wait to be filed; a sweep would move them`);
	// The run replaces the one report row: the developer's last report is put back afterwards.
	const report = snapshotSweepReport();
	try {
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
	} finally {
		restoreSweepReport(report);
	}
});

test('cancelling an incoming submission asks first', async ({ page, baseURL }, testInfo) => {
	test.setTimeout(180_000);
	const id =
		testInfo.project.name === 'mobile' ? SUBMISSION_TRACKS.mobile : SUBMISSION_TRACKS.desktop;
	const url = spotifyTrackUrl(id);
	// Stopping it kills whatever it's doing: never while it's busy with someone's work.
	const busy = expandWorkerBusy();
	test.skip(busy.length > 0, `worker-expand is busy (${busy.join(', ')}); not stopping it`);
	// Never expanded or downloaded here, but only a ledger hit is safe if one ever were.
	expect(ledgerMisses([id]), 'submission track is a ledger hit').toEqual([]);
	const admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
	let jobId: string | null = null;
	stopExpandWorker();
	try {
		const created = await admin.post('/api/jobs', { data: { url } });
		expect(created.status()).toBe(201);
		jobId = ((await created.json()) as Job).id;
		recordHeldSubmission(jobId);

		await openDashboard(page);
		const cancel: Guarded = {
			trigger: page
				.getByRole('list', { name: 'Incoming submissions' })
				.getByRole('button', { name: `cancel ${url}`, exact: true }),
			title: 'Cancel this submission?',
			keep: 'keep it',
			confirm: 'cancel submission',
			sends: call('DELETE', `/api/jobs/${jobId}`)
		};
		await expectCancelDoesNothing(page, cancel);
		await confirmPerforms(page, cancel);
		await waitForJob(admin, jobId, (j) => j.status.lifecycle === 'cancelled', 15_000);
	} finally {
		try {
			await restartExpandWorker();
		} catch (err) {
			expect.soft(String(err), 'starting worker-expand again').toBe('');
		}
		if (jobId) {
			const job = (await (await admin.get(`/api/jobs/${jobId}`)).json()) as Job;
			if (job.status.lifecycle !== 'cancelled') await admin.delete(`/api/jobs/${jobId}`);
			await admin.post('/api/jobs/archive', { data: { job_ids: [jobId] } });
		}
		await admin.dispose();
	}
});
