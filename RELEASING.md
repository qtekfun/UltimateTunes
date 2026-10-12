<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Releasing

Releases are manual and tag-driven, like UltimateCalendar. One version for the server and the app.

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

1. Create the branch `release/X.Y.Z` from `master`.
2. Move the `[Unreleased]` notes in `CHANGELOG.md` under `## [X.Y.Z] - YYYY-MM-DD`.
3. Set `X.Y.Z` in `VERSION`.
4. Add the app store summaries for the new version code (≤ 500 characters, for users): `fastlane/metadata/android/en-US/changelogs/<versionCode>.txt` and `es-ES/…`. CI's `store-texts` check requires them on `release/*` branches.
5. Open the PR `chore: release X.Y.Z` and merge it (squash) once the checks pass.
6. Tag the merge commit and push the tag (the author, or Claude when the author asks):
   ```sh
   git switch master && git pull
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```
7. The **Release** workflow checks that the tag matches `VERSION`, runs `./gradlew check`, builds the signed APK and the multi-arch image (`linux/amd64`, `linux/arm64`, with SBOM and provenance), pushes `ghcr.io/qtekfun/ultimatetunes-server:X.Y.Z` (and `latest` for finals), and publishes a GitHub Release with the notes, `UltimateTunes-X.Y.Z.apk` and its SHA-256. Release candidates are pre-releases and never move `latest`.
8. Phones update through [Obtainium](https://github.com/ImranR98/Obtainium) pointed at the repository. Servers: `docker compose pull && docker compose up -d` (migrations run with `ultimatetunes migrate` first).

## Store assets

`fastlane/…/images/` come from a UI test with invented artists and covers (PLAN T23), never real data. Store submission (Play, F-Droid) is out of scope for v1.
