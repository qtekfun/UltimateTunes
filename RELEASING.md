<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Releasing

Releases are manual and tag-driven, like UltimateCalendar. One version for the server and the app.

## Publishing is paused

Nothing is published yet: no `v*` tags, no GHCR image, no GitHub Release. The repository is public, so CI runs on GitHub at no cost, but the **Release** and **Nightly** workflows are still disabled (SPEC §11).

- **To publish**, the author enables the Release workflow (`gh workflow enable release.yml`) and pushes the tag of a merged release PR (step 7 below). Signing uses the existing `UT_*` repository secrets.
- **Local signed builds** (`./gradlew assembleRelease`) need the four `UT_*` variables in the environment (`UT_KEYSTORE_FILE`, `UT_KEYSTORE_PASSWORD`, `UT_KEY_ALIAS`, `UT_KEY_PASSWORD`); without `UT_KEYSTORE_FILE` the APK is unsigned, and with the file but a missing password or alias the signing step fails. The server image can be built locally with `docker build -f server/Dockerfile .` and run with Compose; migrations first with `ultimatetunes migrate`.
- `VERSION`, `CHANGELOG.md` and the store changelogs still change only in a release PR, as below.

## Versions

- The version lives in one place: the root `VERSION` file, SemVer (`1.2.3`) or `1.2.3-rc.N` for a release candidate. `android/` and `server/pyproject.toml` read it.
- The Android version code is derived from it, never set by hand (`tools/version-code.sh`): `(MAJOR*10000 + MINOR*100 + PATCH) * 100 + N`, with `N = 99` for a final release. `1.0.0-rc.1` is `1000001`, `1.0.0` is `1000099`.
- Before 1.0.0 everything is `0.x`.

## Signing (one time, by the author)

1. Create the key and keep the file and passwords **backed up** (if it is lost, users must uninstall to update). Claude never handles key material.
   ```sh
   keytool -genkeypair -v -keystore ultimatetunes-release.jks -alias ultimatetunes \
     -keyalg RSA -keysize 4096 -validity 10000
   ```
2. Repository secrets (Settings → Secrets and variables → Actions):
   - `UT_KEYSTORE_BASE64`: `base64 -w0 ultimatetunes-release.jks`
   - `UT_KEYSTORE_PASSWORD`, `UT_KEY_ALIAS` (`ultimatetunes`), `UT_KEY_PASSWORD`
3. The server image goes to GHCR with the workflow's own token (`packages: write`); no secret needed. Make the package public or keep it private and `docker login ghcr.io` on the server.

Without the `UT_*` variables, `./gradlew assembleRelease` builds an unsigned APK.

## Making a release

The coordinator prepares the release PR; the author pushes the tag (Claude only when the author asks). Worked example: the first pre-release, `0.0.1-rc.1`, whose versionCode is `101`.

1. Compute the version code and branch from an up-to-date `master`:
   ```sh
   git switch master && git pull
   tools/version-code.sh 0.0.1-rc.1        # prints 101
   git switch -c release/0.0.1-rc.1
   ```
2. `VERSION`: exactly `0.0.1-rc.1` (one line).
3. `CHANGELOG.md`: move the `[Unreleased]` notes under `## [0.0.1-rc.1] - YYYY-MM-DD` (today's date) and leave an empty `## [Unreleased]` above it. The Release workflow publishes exactly that section (`tools/release-notes.sh 0.0.1-rc.1` prints it) and fails if it is missing or empty.
4. Store summaries for that version code (≤ 500 characters, plain user-facing text): `fastlane/metadata/android/en-US/changelogs/101.txt` and `fastlane/metadata/android/es-ES/changelogs/101.txt`.
5. Check locally, commit, push and open the PR:
   ```sh
   tools/tests/run.sh
   tools/check-store-texts.sh --release
   tools/release-notes.sh 0.0.1-rc.1
   git add VERSION CHANGELOG.md fastlane/metadata/android/*/changelogs/101.txt
   git commit -m "chore: release 0.0.1-rc.1"
   git push -u origin release/0.0.1-rc.1
   gh pr create --title "chore: release 0.0.1-rc.1" --body "Release 0.0.1-rc.1 (versionCode 101), see RELEASING.md."
   ```
   On a `release/*` PR, CI's `store-texts` job and the **Release** workflow's dry run (it runs on PRs that change `VERSION`) require the CHANGELOG section and both store changelogs; the dry run also builds the APK and the amd64 + arm64 image without publishing anything.
6. Merge the PR (squash) once every check is green.
7. **The author** tags the squash commit on `master` and pushes the tag:
   ```sh
   git switch master && git pull
   git tag -a v0.0.1-rc.1 -m "UltimateTunes 0.0.1-rc.1"
   git push origin v0.0.1-rc.1
   ```
8. The **Release** workflow, on the tag: checks that the tag is `v` + `VERSION` and that the notes and store changelogs exist, runs the tools' tests, runs `./gradlew check assembleRelease` with the `UT_*` secrets, verifies the APK signature, `versionName` and `versionCode`, builds the multi-arch image (`linux/amd64`, `linux/arm64`, SBOM and provenance) and pushes `ghcr.io/qtekfun/ultimatetunes-server:0.0.1-rc.1`, then publishes the GitHub Release with the notes, `UltimateTunes-0.0.1-rc.1.apk` and `UltimateTunes-0.0.1-rc.1.apk.sha256`. A `-rc.N` is a **pre-release** and never moves `latest`; a final `X.Y.Z` also gets the image tag `latest` and becomes the latest Release.
9. If the workflow fails, never move a pushed tag: fix on `master` and release the next candidate (`0.0.1-rc.2`). The image is pushed only after the APK built, and the Release is created last.
10. Phones update through [Obtainium](https://github.com/ImranR98/Obtainium) pointed at the repository (enable pre-releases to get candidates). Servers: `docker compose pull && docker compose up -d` (migrations run with `ultimatetunes migrate` first).

### Dry run

Before tagging, or after changing the pipeline, run everything without publishing on any branch:

```sh
gh workflow run release.yml --ref <branch> -f dry_run=true
gh run list --workflow release.yml --branch <branch> --limit 1
```

A dry run builds and checks the APK (unsigned when the signing secrets are not available, such as on Dependabot PRs) and the amd64 + arm64 image, keeps the APK and the notes as workflow artifacts for 7 days, and never logs in to GHCR or creates a Release. Outside `release/*` it only warns about missing notes and store changelogs. A manual run is always a dry run; publishing needs the tag push.

The release tools have plain bash tests: `tools/tests/run.sh`.

## Store assets

`fastlane/…/images/` come from a UI test with invented artists and covers (PLAN T23), never real data. Store submission (Play, F-Droid) is out of scope for v1.
