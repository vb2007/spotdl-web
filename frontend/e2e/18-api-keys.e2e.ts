import { expect, request, test, type Page } from '@playwright/test';
import type { Job } from '../src/lib/api';
import { m, t, type Lang } from './support/i18n';
import { skipUnlessStrict } from './support/guards';
import { tabTo } from './support/keyboard';
import {
	USER_STATE,
	expandWorkerBusy,
	expandWorkerRunning,
	recordHeldSubmission,
	restartExpandWorker,
	stopExpandWorker,
	userIdentity
} from './support/stack';
import { openDashboard, submitUrl } from './support/ui';

// Spec 18 (v53): /account's browser extension keys, keyboard only, in English and Hungarian:
// create (shown once), use, revoke. And the web UI's own cookie submissions, which the
// extension's Spotify allowlist must leave alone: search text still queues, and a link already
// downloading says so instead of queueing it twice.

test.use({ storageState: USER_STATE });

const KEY_RE = /^sdw_([0-9a-f]{8})_[A-Za-z0-9_-]{43}$/;

async function me(baseURL: string, key: string): Promise<number> {
	// No cookie at all: the key alone.
	const bare = await request.newContext({ baseURL });
	try {
		return (
			await bare.get('/api/auth/me', { headers: { Authorization: `Bearer ${key}` } })
		).status();
	} finally {
		await bare.dispose();
	}
}

async function keyJourney(page: Page, baseURL: string, lang: Lang, label: string): Promise<void> {
	const tr = <I>(msg: (i: I, o?: { locale?: Lang }) => string, inputs?: I) => t(msg, inputs, lang);
	await page.goto('/account');
	const section = page.getByRole('region', { name: tr(m.account_keys_heading), exact: true });
	await expect(section).toBeVisible();

	// Create: Tab to the name, type it, Enter.
	const name = section.getByLabel(tr(m.account_keys_name), { exact: true });
	await tabTo(page, name);
	await page.keyboard.type(label);
	const created = page.waitForResponse(
		(r) => r.request().method() === 'POST' && new URL(r.url()).pathname === '/api/account/api-keys'
	);
	await page.keyboard.press('Enter');
	expect((await created).status()).toBe(201);

	// Shown once, focused and selected, ready to copy.
	const fresh = section.getByLabel(tr(m.account_keys_new_label), { exact: true });
	await expect(fresh).toBeFocused();
	const key = await fresh.inputValue();
	const prefix = KEY_RE.exec(key)?.[1];
	expect(prefix, `key shape: ${key.slice(0, 13)}…`).toBeTruthy();
	expect(await me(baseURL, key)).toBe(200);

	// "done" puts it away for good; the list keeps only the prefix.
	await tabTo(page, section.getByRole('button', { name: tr(m.account_keys_done), exact: true }));
	await page.keyboard.press('Enter');
	await expect(fresh).toHaveCount(0);
	await expect(name).toBeFocused();
	const row = section.getByRole('listitem').filter({ hasText: label });
	await expect(row).toContainText(`sdw_${prefix}…`);
	expect(await page.content()).not.toContain(key);
	await page.reload();
	await expect(row).toBeVisible();
	expect(await page.content()).not.toContain(key);

	// Revoke, keyboard only: the dialog opens on its safe button; Tab to the destructive one.
	const revoke = row.getByRole('button', {
		name: tr(m.account_keys_revoke_named, { label }),
		exact: true
	});
	await tabTo(page, revoke);
	await page.keyboard.press('Enter');
	const dialog = page.getByRole('alertdialog', {
		name: tr(m.account_keys_revoke_title),
		exact: true
	});
	await expect(
		dialog.getByRole('button', { name: tr(m.account_keys_revoke_cancel), exact: true })
	).toBeFocused();
	const confirm = dialog.getByRole('button', {
		name: tr(m.account_keys_revoke_confirm),
		exact: true
	});
	await tabTo(page, confirm, { max: 4 });
	const revoked = page.waitForResponse((r) => r.request().method() === 'DELETE');
	await page.keyboard.press('Enter');
	expect((await revoked).status()).toBe(200);
	await expect(row).toHaveCount(0);
	await expect(
		section.getByRole('status').filter({ hasText: tr(m.account_keys_revoked, { label }) })
	).toBeVisible();
	await expect
		.poll(() => page.evaluate(() => document.activeElement?.tagName ?? 'none'))
		.not.toMatch(/^(BODY|none)$/);
	expect(await me(baseURL, key)).toBe(401);
}

/** Revokes this run's keys if a failure left one behind. */
async function revokeLeftovers(baseURL: string, label: string): Promise<void> {
	const user = await request.newContext({ baseURL, storageState: USER_STATE });
	try {
		const list = (await (await user.get('/api/account/api-keys')).json()) as {
			keys: { id: string; label: string }[];
		};
		for (const key of list.keys.filter((k) => k.label === label)) {
			await user.delete(`/api/account/api-keys/${key.id}`);
		}
	} finally {
		await user.dispose();
	}
}

test('a key is created, shown once, used and revoked, keyboard only', async ({
	page,
	baseURL
}, testInfo) => {
	const label = `e2e ${testInfo.project.name} ${Date.now()}`;
	try {
		await keyJourney(page, baseURL!, 'en', label);
	} finally {
		await revokeLeftovers(baseURL!, label);
	}
});

test('the keys section works in Hungarian, keyboard only', async ({
	browser,
	baseURL
}, testInfo) => {
	test.skip(testInfo.project.name !== 'desktop', 'one Hungarian pass, on desktop');
	const label = `e2e hu ${Date.now()}`;
	const context = await browser.newContext({ storageState: USER_STATE, locale: 'hu-HU' });
	try {
		const page = await context.newPage();
		await keyJourney(page, baseURL!, 'hu', label);
		expect(await page.evaluate(() => document.documentElement.lang)).toBe('hu');
	} finally {
		await context.close();
		await revokeLeftovers(baseURL!, label);
	}
});

test('the web UI still submits search text, and says when a link is already queued', async ({
	page,
	baseURL
}, testInfo) => {
	test.setTimeout(180_000);
	// The search job must never expand into a real download: worker-expand is held while it
	// exists (spec 12's pattern), and the job is cancelled before it starts again.
	skipUnlessStrict(!expandWorkerRunning(), 'worker-expand is stopped; not starting it');
	const busy = expandWorkerBusy();
	skipUnlessStrict(busy.length > 0, `worker-expand is busy (${busy.join(', ')}); not stopping it`);
	const text = `daft punk e2e ${testInfo.project.name} ${Date.now()}`;
	const user = await request.newContext({ baseURL, storageState: USER_STATE });
	let jobId: string | null = null;
	stopExpandWorker();
	try {
		await openDashboard(page);
		const job = await submitUrl(page, text);
		jobId = job.id;
		recordHeldSubmission(job.id);
		expect(job.source_type).toBe('search');
		expect(job.source_url).toBe(text);
		expect((job as Job & { hint: unknown }).hint).toBeNull();
		expect(job.owner_email.toLowerCase()).toBe(userIdentity().email.trim().toLowerCase());

		// The same text again while that job is still expanding: the same job, 200, and a
		// notice rather than a second row.
		const again = page.waitForResponse(
			(r) => r.request().method() === 'POST' && new URL(r.url()).pathname === '/api/jobs'
		);
		const input = page.getByLabel(t(m.dashboard_submit_input_label), { exact: true });
		await input.fill(text);
		await input.press('Enter');
		const answer = await again;
		expect(answer.status()).toBe(200);
		const body = (await answer.json()) as Job & { hint: string };
		expect(body.id).toBe(job.id);
		expect(body.hint).toBe('already_queued');
		await expect(page.locator('#submit-error')).toHaveText(t(m.dashboard_submit_already_queued));
	} finally {
		try {
			await restartExpandWorker();
		} catch (err) {
			expect.soft(String(err), 'starting worker-expand again').toBe('');
		}
		if (jobId) {
			const job = (await (await user.get(`/api/jobs/${jobId}`)).json()) as Job;
			if (job.status.lifecycle !== 'cancelled') await user.delete(`/api/jobs/${jobId}`);
			await user.post('/api/jobs/archive', { data: { job_ids: [jobId] } });
		}
		await user.dispose();
	}
});
