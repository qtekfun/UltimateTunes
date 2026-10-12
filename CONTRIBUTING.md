<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Contributing

Thanks for helping! A few rules keep UltimateTunes free, safe and easy to review.

## Ground rules

- **Free software only.** No Google Play Services, Firebase, analytics, crash reporters or non-free dependencies, on the server or in the app. Before adding a dependency, open an issue: its license must be compatible with GPL-3.0-or-later.
- **No telemetry.** The app talks only to your server; the server only to the services listed in SPEC §6.
- **Security first**: read [SECURITY.md](SECURITY.md) before touching auth, files, subprocesses or the admin panel.
- **SPDX header** in every source file: `SPDX-License-Identifier: GPL-3.0-or-later`.
- Every visible app string in `strings.xml` (English `values/`, Spanish `values-es/`).

## Workflow

1. One task or fix per branch (`feat/tNN-…`, `fix/…`) from `master`; changes land only through pull requests with green checks, squash-merged.
2. The **PR title** is a [Conventional Commit](https://www.conventionalcommits.org): it becomes the squash commit.
3. Before pushing: `make -C server check` and/or `cd android && ./gradlew check`.
4. `VERSION` and `CHANGELOG.md` change only in a release PR: see RELEASING.md.
5. Contracts (`contracts/`) change in their own PR, before the code that needs them.

## Code

- Server: Python 3.13, FastAPI, uv, typed (`mypy --strict`), ruff; SQL through the repository layer, **portable** between SQLite and PostgreSQL; shared state only through the interfaces (`TtlCache`, `JobQueue`, `RateLimiter`, `InFlight`, `LibraryStore`, `StagingStore`), so the server can run as several replicas on Kubernetes later.
- Android: Kotlin, Compose, Material 3 with the Apple Music-style design system (SPEC §5), Media3; the UI never talks to the network directly.
- Subprocesses as argument lists, never through a shell; every path built from metadata goes through the path sanitizer.

## Tests

- Server: pytest, respx, fake music catalog and fake downloader; schemathesis against `contracts/`. No test reaches YouTube (only the nightly canary does).
- Android: JUnit 5, MockK, Turbine, MockWebServer with the fake server of `:core:api`; Compose UI tests for key flows. Never run `connectedDebugAndroidTest` on a phone whose data you want to keep: it uninstalls the app.
- Coverage ≥ 85 %; **100 %** on auth, rate limiting, id resolution, path sanitizer, job and streaming state machines, client cache policy and prefetch planner. A test must be able to fail for a real reason.

## Dependencies

Dependabot keeps versions up to date; do not bump them by hand. Regenerate `server/uv.lock` with `uv lock` and `android/gradle/verification-metadata.xml` from a clean Gradle home.

Android Lint runs with warnings as errors, including its network-backed version checks (`NewerVersionAvailable`, `AndroidGradlePluginVersion`, `GradleDependency`). When a new Gradle, AGP, Kotlin or library release comes out, `./gradlew check` can start failing on a branch nobody changed. That is expected: the matching Dependabot PR fixes it, so merge (or rebase onto) that PR. Do not disable these checks or add them to a baseline.

## Quality gates

`make -C server check` and `./gradlew check` run the same gates as CI:

- Coverage ≥ 85 % overall, and 100 % lines and branches on the critical areas. Server: `server/tools/critical_coverage.py` (patterns in `CRITICAL`). Android: `criticalPackages` in `android/app/build.gradle.kts` (`koverVerifyCritical`). An area with no code yet passes and is enforced from its first file. A critical file missing from the coverage report fails, and so does a coverage exclusion (`# pragma: no cover`, `# pragma: no branch`) inside one: critical code is covered by tests, never excluded.
- Forbidden dependencies. Server: `server/tools/forbidden_deps.py` reads every package in `uv.lock`. Android: `checkForbiddenDependencies` walks the shipped and test runtime classpaths of every module.
- In CI only: gitleaks over the PR's commits, Trivy on the image, and the Conventional Commit PR title.
