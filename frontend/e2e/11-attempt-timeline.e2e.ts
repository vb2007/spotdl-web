import { expect, test } from '@playwright/test';
import {
	ADMIN_STATE,
	USER_STATE,
	adminIdentity,
	normalizeEmail,
	readSeed,
	stackPython
} from './support/stack';
import { jobToggle, openDashboard, trackToggle } from './support/ui';

// Spec 11 (v41, the plan's case 2). The timeline needs failures that a default run can't make
// without reaching YouTube, so the admin gets one fixture track with a real-shaped history
// written straight to the dev database, a day in the past (so teardown's zero-download check,
// which counts attempts since the run started, never sees it), and deleted afterwards.
//
// Oldest first: IPv4 `other` (short), then three identical `no_output` failures carrying one
// long message over IPv6, proxy and proxy, then a terminal `lookup`. Newest first that reads as
// three entries: lookup, ×3 no_output, other.
const LONG =
	'spotdl returned no output file for this track (AudioProviderError: YT-DLP download error - ' +
	'https://www.youtube.com/watch?v=v41fixture00 <- ExtractorError: [youtube] v41fixture00: ' +
	"Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies for the " +
	'authentication. See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp ' +
	'for how to manually pass cookies. Also see https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exp ' +
	'for how to update cookies. TAIL-OF-THE-FIXTURE-MESSAGE';

const CREATE = `
import sys, uuid
from datetime import datetime, timedelta, timezone
from app.db import SessionLocal
from app.models.job import Job, JobSourceType, JobState
from app.models.track import Track, TrackState, TrackErrorType
from app.models.track_attempt import TrackAttempt, TrackAttemptOutcome, NetworkPath
from app.models.user import User

email, title, long_message = sys.argv[1:4]
db = SessionLocal()
user = db.query(User).filter(User.email == email).one()
job = Job(user_id=user.id, source_url="https://open.spotify.com/track/v41timelinefixture00",
          source_type=JobSourceType.TRACK, state=JobState.EXPANDED)
db.add(job)
db.flush()
track = Track(job_id=job.id, spotify_track_id="v41timelinefixture00",
              song_json={"name": title, "artists": ["v41 fixture"], "album_name": "v41 fixture"},
              state=TrackState.LOOKUP_FAILED, attempt_count=5, attempts_made=5, failure_count=5,
              last_error="No results found for song: v41 fixture - " + title,
              last_error_type=TrackErrorType.LOOKUP)
db.add(track)
db.flush()
base = datetime.now(timezone.utc) - timedelta(days=1)
rows = [
    (NetworkPath.DIRECT_IPV4, TrackErrorType.OTHER, "the proxy was unreachable"),
    (NetworkPath.DIRECT_IPV6, TrackErrorType.NO_OUTPUT, long_message),
    (NetworkPath.PROXY, TrackErrorType.NO_OUTPUT, long_message),
    (NetworkPath.PROXY, TrackErrorType.NO_OUTPUT, long_message),
    (NetworkPath.PROXY, TrackErrorType.LOOKUP, "No results found for song: v41 fixture - " + title),
]
for n, (path, kind, message) in enumerate(rows, start=1):
    started = base + timedelta(minutes=n)
    db.add(TrackAttempt(track_id=track.id, attempt_number=n, started_at=started,
                        finished_at=started + timedelta(seconds=4), outcome=TrackAttemptOutcome.FAILED,
                        error_type=kind, error_message=message, network_path=path))
db.commit()
print(job.id)
`;

const DELETE = `
import sys
from sqlalchemy import text
from app.db import SessionLocal
db = SessionLocal()
job = sys.argv[1]
db.execute(text("delete from track_attempts where track_id in (select id from tracks where job_id = :j)"), {"j": job})
db.execute(text("delete from tracks where job_id = :j"), {"j": job})
db.execute(text("delete from jobs where id = :j"), {"j": job})
db.commit()
`;

test.describe('admin', () => {
	test.use({ storageState: ADMIN_STATE });

	test('repeated attempts collapse and expand; a clamped error expands to its full, selectable text', async ({
		page
	}, testInfo) => {
		const title = `v41 timeline fixture ${testInfo.project.name} ${Date.now()}`;
		const jobId = stackPython(CREATE, [normalizeEmail(adminIdentity().email), title, LONG]);
		try {
			await openDashboard(page);
			await jobToggle(page, title).click();
			const track = trackToggle(page, title, title);
			await track.click();
			await expect(track).toHaveAttribute('aria-expanded', 'true');

			const timeline = page.getByRole('list', { name: 'attempt history' });
			const entries = timeline.getByRole('listitem');
			await expect(entries).toHaveCount(3);
			await expect(entries.nth(0)).toContainText('lookup');
			await expect(entries.nth(1)).toContainText('×3');
			await expect(entries.nth(1)).toContainText('no_output');
			await expect(entries.nth(2)).toContainText('direct · IPv4');

			// Collapsed repeats expand on demand into one row each, and collapse again.
			const run = entries.nth(1);
			const showRun = run.getByRole('button', { name: 'show all 3', exact: true });
			await expect(showRun).toHaveAttribute('aria-expanded', 'false');
			await showRun.click();
			const repeats = run.getByRole('list', { name: 'repeated attempts' }).getByRole('listitem');
			await expect(repeats).toHaveCount(3);
			await expect(repeats.nth(0)).toContainText('via proxy');
			await expect(repeats.nth(2)).toContainText('direct · IPv6');
			await run.getByRole('button', { name: 'hide the repeats' }).click();
			await expect(run.getByRole('list', { name: 'repeated attempts' })).toHaveCount(0);

			// The long message is clamped, and its control unclamps it to the whole text.
			const message = run.getByText(/^spotdl returned no output file/);
			const cut = await message.evaluate((el) => el.scrollHeight > el.clientHeight + 1);
			expect(cut, 'the long message is clamped').toBe(true);
			const showFull = run.getByRole('button', { name: 'show full message' });
			await expect(showFull).toHaveAttribute('aria-expanded', 'false');
			await showFull.click();
			await expect(run.getByRole('button', { name: 'show less' })).toHaveAttribute(
				'aria-expanded',
				'true'
			);
			expect(await message.evaluate((el) => el.scrollHeight <= el.clientHeight + 1)).toBe(true);

			// Selectable and copyable as the worker wrote it.
			const selected = await message.evaluate((el) => {
				const range = document.createRange();
				range.selectNodeContents(el);
				const selection = window.getSelection()!;
				selection.removeAllRanges();
				selection.addRange(range);
				return { text: selection.toString().trim(), userSelect: getComputedStyle(el).userSelect };
			});
			expect(selected.userSelect).not.toBe('none');
			expect(selected.text).toBe(LONG);
		} finally {
			stackPython(DELETE, [jobId]);
		}
	});
});

test.describe('non-admin', () => {
	test.use({ storageState: USER_STATE });

	// Master plan amendment (v39 outcome 3): attempt diagnostics are the admin's. A user's
	// expanded track shows its status and actions only -- no history in the DOM, and no
	// attempts request made.
	test('an expanded track carries no attempt diagnostics and requests none', async ({ page }) => {
		const { user } = readSeed();
		const attemptRequests: string[] = [];
		page.on('request', (r) => {
			if (/\/api\/tracks\/[^/]+\/attempts/.test(new URL(r.url()).pathname)) {
				attemptRequests.push(r.url());
			}
		});
		await openDashboard(page);
		await jobToggle(page, user.title).click();
		const track = trackToggle(page, user.title, user.trackTitle);
		await track.click();
		await expect(track).toHaveAttribute('aria-expanded', 'true');
		const detail = page.locator(`#${await track.getAttribute('aria-controls')}`);
		await expect(detail).toContainText('already downloaded earlier');
		await expect(detail.getByRole('button', { name: 'download', exact: true })).toBeVisible();
		await expect(page.getByRole('list', { name: 'attempt history' })).toHaveCount(0);
		await expect(detail).not.toContainText('attempts');
		expect(attemptRequests).toEqual([]);
	});
});
