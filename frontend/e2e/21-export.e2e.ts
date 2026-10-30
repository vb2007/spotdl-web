import { execFileSync } from 'node:child_process';
import { expect, test } from '@playwright/test';
import { ADMIN_STATE, readSeed, stackPython } from './support/stack';
import { m, t } from './support/i18n';
import { jobRow, jobToggle, openDashboard } from './support/ui';

test.use({ storageState: ADMIN_STATE, acceptDownloads: true });

/** The export's own plan for a job, read where the files are: each zip entry name the server
 * picks, with the sha256 of the file it streams for it, and the playlist's name. */
function serverExport(jobId: string): { files: Record<string, string>; playlist: string } {
	const out = stackPython(
		`
import hashlib, json, sys, uuid
from app.db import SessionLocal
from app.models import Job
from app.services import export, rollup
db = SessionLocal()
job = db.get(Job, uuid.UUID(sys.argv[1]))
plan = export.plan_export(db, job.id, rollup.job_title(db, job))
print(json.dumps({
    "files": {f.arcname: hashlib.sha256(f.path.read_bytes()).hexdigest() for f in plan.files},
    "playlist": plan.playlist_name,
}))
`,
		[jobId]
	);
	return JSON.parse(out);
}

/** Every entry of the saved zip with its sha256 (Python's zipfile: Node has no unzip). */
function zipEntries(path: string): Record<string, string> {
	const out = execFileSync(
		'python3',
		[
			'-I',
			'-c',
			`
import hashlib, json, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    assert z.testzip() is None
    print(json.dumps({n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()}))
`,
			path
		],
		{ encoding: 'utf8' }
	);
	return JSON.parse(out);
}

// Spec 21 (v64). An open job's "download all (zip)" saves a zip whose every audio entry is,
// byte for byte, the file the server holds for it, next to the job's playlist.
test('a job zip holds every present file byte for byte, plus its playlist', async ({ page }) => {
	const { admin } = readSeed();
	const server = serverExport(admin.jobId);
	expect(Object.keys(server.files).length).toBeGreaterThan(0);

	await openDashboard(page);
	await jobToggle(page, admin.title).click();
	const zipButton = jobRow(page, admin.title).getByRole('button', { name: t(m.job_export_zip) });

	const downloadEvent = page.waitForEvent('download');
	await zipButton.click();
	const download = await downloadEvent;
	expect(await download.failure()).toBeNull();
	expect(download.suggestedFilename()).toMatch(/\.zip$/);

	const entries = zipEntries(await download.path());
	expect(Object.keys(entries)).toContain(server.playlist);
	for (const [name, sha256] of Object.entries(server.files)) expect(entries[name]).toBe(sha256);
	const audio = Object.keys(entries).filter((n) => n !== server.playlist && n !== 'MISSING.txt');
	expect(audio.sort()).toEqual(Object.keys(server.files).sort());
});
