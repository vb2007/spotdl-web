import { expect, type Locator, type Page } from '@playwright/test';
import type { Job } from '../../src/lib/api';
import type { Identity } from './stack';

/** Signs in through the real login form (real upstream) and waits for the dashboard. Already
 * on `/login` (after a logout), it stays in the same document rather than reloading it. */
export async function loginViaUi(page: Page, identity: Identity): Promise<void> {
	if (new URL(page.url()).pathname !== '/login') await page.goto('/login');
	await page.getByLabel('Email').fill(identity.email);
	await page.getByLabel('Password').fill(identity.password);
	await page.getByRole('button', { name: 'CONNECT', exact: true }).click();
	await expect(page.getByLabel('Spotify URL to submit')).toBeVisible();
}

export async function logoutViaUi(page: Page): Promise<void> {
	await page.getByRole('button', { name: 'disconnect' }).click();
	await expect(page.getByRole('button', { name: 'CONNECT', exact: true })).toBeVisible();
}

/** The expand/collapse toggle of a job row, by the title in its accessible name. */
export function jobToggle(page: Page | Locator, title: string): Locator {
	return page.getByRole('button', {
		name: new RegExp(`^(Expand|Collapse) tracks for ${escape(title)}$`)
	});
}

/** The whole job row (`<li>`), so its actions and progress can be read in scope. */
export function jobRow(page: Page, title: string): Locator {
	return page
		.getByRole('list', { name: 'Jobs' })
		.getByRole('listitem')
		.filter({ has: jobToggle(page, title) });
}

/** A track row's expand button inside an expanded job, by the track title in its name. */
export function trackToggle(page: Page, jobTitle: string, trackTitle: string): Locator {
	return jobRow(page, jobTitle)
		.getByRole('list', { name: 'Tracks' })
		.getByRole('button', { name: literal(trackTitle) });
}

/** Submits a URL through the dashboard form and returns the job the API created. */
export async function submitUrl(page: Page, url: string): Promise<Job> {
	const created = page.waitForResponse(
		(r) => r.request().method() === 'POST' && new URL(r.url()).pathname === '/api/jobs'
	);
	await page.getByLabel('Spotify URL to submit').fill(url);
	await page.getByRole('button', { name: 'SUBMIT', exact: true }).click();
	const response = await created;
	expect(response.status()).toBe(201);
	return (await response.json()) as Job;
}

/** Matches `text` literally anywhere in an accessible name. */
export function literal(text: string): RegExp {
	return new RegExp(escape(text));
}

function escape(text: string): string {
	return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
