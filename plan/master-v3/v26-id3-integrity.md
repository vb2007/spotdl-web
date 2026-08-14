# v26 — ID3 Tag Integrity

Branch: `dev-id3-integrity` → PR into `main`
Version: `3.26.0`

## Scope

Guarantee every downloaded file carries full embedded metadata — title, artist(s), album, track
number, year, and album cover art (embedded per file, even when several tracks share the same
album). spotdl normally embeds these itself; nothing currently *verifies* that it did.

This is a prerequisite for v28: the library sorter reads tags off files, so a badly-tagged file
would land in the wrong folder — or nowhere.

## Design

**The file is the source of truth for tags; the DB is the repair source.**

Reading tags back off the file (rather than trusting `song_json`) is what makes this a real check —
it verifies the artifact that actually ships, and it means the sorter also works on files that never
came through this app. `song_json` is used only to repair what's missing.

- After a successful download, before marking the track `completed`: read the file's tags back and
  compare against the required set.
- Anything missing or empty gets re-embedded from `song_json`.
- Cover art: fetch from the Spotify cover URL in `song_json` when absent. Network failure here must
  **not** fail the track — the audio is downloaded and correct; log it, record it as a tag warning,
  and move on. A retry-forever ladder driven by cover-art fetches would be absurd.
- Format-aware: mp3 (ID3v2), m4a, flac, opus and ogg all tag differently. Support what
  `get_supported_output_options()` reports, and skip cleanly (with a log line) for any format the
  tag library can't handle rather than raising.

Needs a tagging library — `mutagen` is the obvious choice (it's already an indirect dependency of
spotdl, so it's present in the image; add it as an explicit direct dependency rather than relying on
a transitive one).

Where this runs: inline in `download_track`, after `download_one` returns and after the
cancel-check, before the `completed` commit. It's fast, local, and belongs in the same transaction
boundary as the rest of the success path.

## Tasks

1. `app/services/tagging.py` — `verify_tags(path) -> set[str]` (returns missing field names) and
   `repair_tags(path, song, missing)`. Pure functions over a file path, no DB access, so they're
   testable without a stack and reusable by v28.
2. Wire into `download_track`'s success path.
3. Record the outcome so it's visible: a tag warning on the track (reuse v24's attempt row rather
   than adding a column — the attempt is exactly the right granularity).
4. A one-off admin-triggered re-tag sweep is **out of scope** here. Existing badly-tagged files are
   v28's problem to report, not v26's to fix retroactively.
5. `graphify update .`

## Done when

- A real downloaded mp3 has all six fields plus embedded cover art, verified by reading the file
  back with an independent tool (`ffprobe` or `mutagen` in a separate process) — not by trusting the
  code that wrote it.
- A track deliberately stripped of tags before the check is repaired, proving the repair path
  actually runs — the check passing on already-correct files proves nothing about the repair.
- A track whose cover-art fetch fails still completes successfully with the audio intact and a
  recorded warning.
- At least two output formats verified (mp3 plus one of flac/m4a/opus), since tag handling differs
  per container and testing only mp3 would leave the others unproven.
- An unsupported format skips with a log line instead of raising.
- `mutagen` is an explicit dependency in `pyproject.toml` and the regenerated `requirements.txt`.
- Full backend suite passes; both version files read `3.26.0`; `graphify update .`
