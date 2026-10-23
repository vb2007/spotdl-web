# v60 — Extension Release Pipeline

Branch: `dev-extension-release` → PR into `main`
Version: **app version not bumped** (touches `extension/`, `.github/`, docs). The extension bumps
to `1.0.1` (or `1.1.0`) in `extension/manifest.json` to exercise its own pipeline.
Wave / slot: 3 / 3
Depends on: v57

## Scope

Owner decision: the extension is distributed as an **AMO-signed unlisted XPI** (self-distribution
channel), attached to a GitHub release, and installed permanently in regular Firefox, with
**auto-updates** via a self-hosted `update_url`. This version builds that pipeline and the CI
checks the extension never had (`ci.yml` lints only `frontend/`, and `check_version.py` ignores
`extension/`).

## Tasks

1. **CI** (`ci.yml`): a new `extension` job.
   - `web-ext lint`, the extension's unit tests, and the `_locales` key-parity check.
   - It runs on the self-hosted runner like the rest. It needs **no browser**: jsdom fixture tests
     only, per the master-v4 "no CI browser" decision.
   - The `summary` job includes it.
2. **Extension version check.**
   - `check_version.py` gains an independent rule: a diff touching `extension/` must bump
     `extension/manifest.json`'s `version`, strictly greater than the base's.
   - The extension version is **independent** of the app version (a locked v5 decision). It
     never needs to match.
   - Add tests for the script.
3. **The signing and release workflow** (new `.github/workflows/extension-release.yml`).
   - Triggered on `main` when `extension/manifest.json`'s version changed, after CI passes. Same
     `workflow_run` pattern as `release.yml`.
   - Runs `web-ext sign --channel unlisted --api-key "$AMO_JWT_ISSUER" --api-secret "$AMO_JWT_SECRET"`.
   - Creates a GitHub release `extension-v<ver>` with the signed `.xpi` and an `updates.json` (the
     Firefox update manifest format, listing each version's XPI URL and the min version).
   - Concurrency group, so two releases never race. Matrix notify on failure, reusing v59's
     curl-only `notify` pattern.
   - If the AMO secrets are missing, the job **fails with a clear message**. A missing signing key
     is a real failure, unlike missing Matrix config.
4. **Auto-update.**
   - `manifest.json`'s `browser_specific_settings.gecko.update_url` points at a stable URL that
     always serves the latest `updates.json`. Use GitHub's
     `releases/latest/download/updates.json`, or have the release job also update a fixed-tag
     asset. The `latest` alias collides with the app's own releases, so use a dedicated fixed
     release tag such as `extension-updates`. Record the choice.
   - The URL must be HTTPS and reachable unauthenticated.
5. **Docs:** extend `docs/EXTENSION.md` with installing the signed XPI, how updates arrive, and how
   to cut a new extension release (bump `manifest.json`, then merge). Add a short "Extension"
   paragraph to `docs/RELEASE_PIPELINE.md`.

## Files owned

`extension/manifest.json` (version and `update_url` only), `extension/package.json` scripts if
any, `.github/workflows/ci.yml` (the new `extension` job and the summary entry only; v59 owns the
rest of `ci.yml` in the same wave, so keep to separate jobs), new
`.github/workflows/extension-release.yml`, `.github/scripts/check_version.py` (plus its tests),
`docs/EXTENSION.md`, `docs/RELEASE_PIPELINE.md` (one paragraph).

## Out of scope

Listing on AMO publicly. Chrome. Changing extension behavior (v57).

## Deploy notes

The owner adds `AMO_JWT_ISSUER`/`AMO_JWT_SECRET` repository secrets **before** merging (in the
master plan's housekeeping list).

## Done when

- [ ] The CI `extension` job runs lint, tests and parity green on the PR. It fails when a
      `_locales` key is removed (scratch commit shown).
- [ ] `check_version.py`:
  - an `extension/` change without a manifest bump fails;
  - a bump passes;
  - an app-only diff is unaffected;
  - script tests pass.
- [ ] A **real signed XPI is produced**: the workflow's first run on `main` after merge (or a
      `workflow_dispatch` on the branch, if the owner prefers to prove it before merge) signs it
      via AMO unlisted and attaches `.xpi` and `updates.json` to the `extension-v<ver>` release
      (links).
- [ ] **Installs permanently in release Firefox:** install the XPI in a fresh release-channel
      profile, restart Firefox, and it's still there and working against the slot stack
      (screenshots).
- [ ] **Auto-update:** with version N installed, publishing N+1 (a trivial bump) leads Firefox's
      "Check for updates" to install N+1 (`about:addons` screenshots before and after).
- [ ] Missing AMO secrets make the release job fail with the explicit message (a dispatch with
      secrets withheld, or a fork). A failure posts the Matrix notice.
- [ ] Docs updated. `graphify update .` has been run. The app version is unchanged.
