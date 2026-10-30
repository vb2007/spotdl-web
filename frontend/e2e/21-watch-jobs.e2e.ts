import { expect, request, test, type APIRequestContext, type Page } from '@playwright/test';
import {
	ADMIN_STATE,
	USER_STATE,
	adminIdentity,
	normalizeEmail,
	restoreWorker,
	stackPython,
	stageWorker,
	userIdentity
} from './support/stack';
import { requireQuietWorker } from './support/guards';
import { focusedRow } from './support/keyboard';
import { TITLE, anyTitle, m, t } from './support/i18n';
import { jobRow, jobToggle, openDashboard, trackToggle } from './support/ui';

// Spec 21 (v63): a job's watch and "retry failed", on fixture jobs. The worker is paused for
// each test, so no fixture track is ever handed a real download: beat dispatches nothing while
// paused, and download_track holds a message it gets (before any network).

const FIXTURE = 'v63fixture';

interface Fixture {
	jobId: string;
	title: string;
	notFoundTrack: string;
}

/** A playlist job for `email`: two done tracks, two waiting a day out (attempt 1), one not
 * found. Newest of the identity's jobs, so it is the list's first row. */
function makeJob(email: string, title: string): Fixture {
	const out = stackPython(
		`
import json, sys
from datetime import datetime, timedelta, timezone
from app.db import SessionLocal
from app.models import Job, JobSourceType, JobState, Track, TrackState, User
db = SessionLocal()
user = db.query(User).filter(User.email == sys.argv[1]).one()
title = sys.argv[2]
now = datetime.now(timezone.utc)
job = Job(user_id=user.id, source_url=f"https://open.spotify.com/playlist/${FIXTURE}{abs(hash(title))}",
          source_type=JobSourceType.PLAYLIST, state=JobState.EXPANDED, created_at=now)
db.add(job); db.flush()
song = lambda n: {"name": f"{title} {n}", "list_name": title, "artists": ["${FIXTURE}"]}
for n in range(2):
    db.add(Track(job_id=job.id, spotify_track_id=f"${FIXTURE}d{n}", song_json=song(f"done {n}"),
                 state=TrackState.SKIPPED_DUPLICATE))
for n in range(2):
    db.add(Track(job_id=job.id, spotify_track_id=f"${FIXTURE}w{n}", song_json=song(f"waiting {n}"),
                 state=TrackState.WAITING, attempt_count=1, scheduled_at=now + timedelta(days=1)))
missing = Track(job_id=job.id, spotify_track_id=f"${FIXTURE}n0", song_json=song("not found"),
                state=TrackState.LOOKUP_FAILED)
db.add(missing); db.commit()
print(json.dumps({"jobId": str(job.id), "title": title, "notFoundTrack": str(missing.id)}))
`,
		[normalizeEmail(email), title]
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
db.execute(text(f"delete from jobs where source_url like '%${FIXTURE}%'"))
db.commit()
`);
}

/** One column of the fixture job, as the database has it. */
function jobColumn(jobId: string, column: string): string {
	return stackPython(
		`
import sys
from sqlalchemy import text
from app.db import SessionLocal
print(SessionLocal().execute(text(f"select {sys.argv[2]} from jobs where id = :id"), {"id": sys.argv[1]}).scalar())
`,
		[jobId, column]
	);
}

/** Per state, how many of the job's tracks are in it, and how many are due now. */
function trackStates(jobId: string): Record<string, number> {
	const out = stackPython(
		`
import json, sys
from sqlalchemy import text
from app.db import SessionLocal
rows = SessionLocal().execute(text(
    "select state::text || case when scheduled_at <= now() then ':due' else '' end, count(*) "
    "from tracks where job_id = :id group by 1"), {"id": sys.argv[1]}).all()
print(json.dumps({k: n for k, n in rows}))
`,
		[jobId]
	);
	return JSON.parse(out.split('\n').at(-1)!);
}

async function pauseWorker(admin: APIRequestContext): Promise<void> {
	await requireQuietWorker(admin);
	stageWorker({ paused: true });
	expect((await admin.post('/api/worker/pause')).ok()).toBe(true);
}

/** j/k onto the job's row, then Enter opens it: no mouse. */
async function openByKeyboard(page: Page, jobId: string): Promise<void> {
	await page.keyboard.press('j');
	for (let i = 0; i < 60 && (await focusedRow(page)) !== jobId; i++) {
		await page.keyboard.press('j');
	}
	expect(await focusedRow(page)).toBe(jobId);
	await page.keyboard.press('Enter');
	await expect(page.locator(`li[data-kb-row="${jobId}"] > .row > .toggle`)).toHaveAttribute(
		'aria-expanded',
		'true'
	);
}

test.describe('the watch and retry failed, keyboard only', () => {
	test.use({ storageState: USER_STATE });
	let admin: APIRequestContext;

	test.beforeEach(async ({ baseURL }) => {
		dropFixture();
		admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
	});
	test.afterEach(async () => {
		dropFixture();
		restoreWorker();
		await admin.dispose();
	});

	test('w watches and unwatches, Shift+R retries the waiting tracks', async ({ page }, info) => {
		await pauseWorker(admin);
		const job = makeJob(userIdentity().email, `${FIXTURE} ${info.project.name} keys`);
		await openDashboard(page);
		await openByKeyboard(page, job.jobId);
		const row = jobRow(page, job.title);

		await page.keyboard.press('w');
		await expect(row.getByText(anyTitle(t(m.job_watched_next, { time: TITLE })))).toBeVisible();
		await expect.poll(() => jobColumn(job.jobId, 'watch_interval_hours')).toBe('24');
		await expect(
			row.getByRole('combobox', { name: anyTitle(t(m.job_watch_of, { title: TITLE })) })
		).toHaveValue('24');
		await page.screenshot({ path: info.outputPath('watched.png') });

		await page.keyboard.press('w');
		await expect(row.getByText(t(m.job_notice_unwatched))).toBeVisible();
		await expect.poll(() => jobColumn(job.jobId, 'watch_interval_hours')).toBe('None');
		await expect(row.getByText(anyTitle(t(m.job_watched_next, { time: TITLE })))).toHaveCount(0);

		// The non-admin row offers no override of not-found's terminal rule.
		await expect(
			row.getByRole('button', {
				name: anyTitle(t(m.job_retry_not_found_label, { count: 1, n: '1', title: TITLE }))
			})
		).toHaveCount(0);

		await page.keyboard.press('Shift+R');
		await expect(row.getByText(t(m.job_notice_retried_held, { count: 2, n: '2' }))).toBeVisible();
		expect(trackStates(job.jobId)).toMatchObject({ 'waiting:due': 2, lookup_failed: 1 });
		await page.screenshot({ path: info.outputPath('retried.png') });

		// A second press in the same ladder step (v56's once-per-step rule, per track).
		await page.keyboard.press('Shift+R');
		await expect(row.getByText(t(m.job_notice_retry_cooldown))).toBeVisible();
	});

	test('the interval menu and check now, with the pointer', async ({ page }, info) => {
		await pauseWorker(admin);
		const job = makeJob(userIdentity().email, `${FIXTURE} ${info.project.name} menu`);
		await openDashboard(page);
		await jobToggle(page, job.title).click();
		const row = jobRow(page, job.title);

		await row
			.getByRole('combobox', { name: anyTitle(t(m.job_watch_of, { title: TITLE })) })
			.selectOption(String(168));
		await expect.poll(() => jobColumn(job.jobId, 'watch_interval_hours')).toBe('168');
		await expect(row.getByText(anyTitle(t(m.job_watched_next, { time: TITLE })))).toBeVisible();

		const sent = page.waitForResponse(
			(r) => r.request().method() === 'POST' && r.url().endsWith(`/api/jobs/${job.jobId}/reexpand`)
		);
		await row
			.getByRole('button', { name: anyTitle(t(m.job_check_now_label, { title: TITLE })) })
			.click();
		expect((await sent).status()).toBe(202);
		await expect(row.getByText(t(m.job_notice_checking))).toBeVisible();
		expect(jobColumn(job.jobId, 'last_expanded_at')).not.toBe('None');
		await page.screenshot({ path: info.outputPath('check-now.png') });
	});
});

test.describe("the admin's retry not found", () => {
	test.use({ storageState: ADMIN_STATE });
	let admin: APIRequestContext;

	test.beforeEach(async ({ baseURL }) => {
		dropFixture();
		admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
	});
	test.afterEach(async () => {
		dropFixture();
		restoreWorker();
		await admin.dispose();
	});

	test('asks first, then records a manual override', async ({ page }, info) => {
		await pauseWorker(admin);
		const job = makeJob(adminIdentity().email, `${FIXTURE} ${info.project.name} override`);
		await openDashboard(page);
		await openByKeyboard(page, job.jobId);
		const row = jobRow(page, job.title);
		const trigger = row.getByRole('button', {
			name: anyTitle(t(m.job_retry_not_found_label, { count: 1, n: '1', title: TITLE }))
		});
		const dialog = page.getByRole('alertdialog', { name: t(m.job_retry_not_found_title) });

		// Keyboard: Tab to it, Enter asks, Esc keeps them as they are.
		for (let i = 0; i < 12 && !(await trigger.evaluate((el) => el === document.activeElement)); i++)
			await page.keyboard.press('Tab');
		await expect(trigger).toBeFocused();
		await page.keyboard.press('Enter');
		await expect(dialog).toBeVisible();
		await page.screenshot({ path: info.outputPath('confirm.png') });
		await page.keyboard.press('Escape');
		await expect(dialog).toBeHidden();
		await expect(trigger).toBeFocused();
		expect(trackStates(job.jobId)).toMatchObject({ lookup_failed: 1 });

		await page.keyboard.press('Enter');
		await dialog
			.getByRole('button', { name: t(m.job_retry_not_found_confirm), exact: true })
			.click();
		await expect(
			row.getByText(t(m.job_notice_overridden, { count: 1, n: '1' }), { exact: false })
		).toBeVisible();
		expect(trackStates(job.jobId).lookup_failed ?? 0).toBe(0);

		// Its attempt history says what happened.
		await trackToggle(page, job.title, `${job.title} not found`).click();
		await expect(row.getByText(t(m.attempt_outcome_manual_override))).toBeVisible();
		await page.screenshot({ path: info.outputPath('history.png') });
	});
});
