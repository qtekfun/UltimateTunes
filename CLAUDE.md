# UltimateTunes — instructions for Claude Code

<!-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

Self-hosted music streaming: a **server** (Python, FastAPI, Docker) that speaks the **OpenSubsonic** API, keeps a tagged music library and fetches on demand from **YouTube Music** whatever it does not have yet; and an **Android client** (Kotlin, Compose, Media3) with an **Apple Music**-style interface that caches every play. Free software (GPL-3.0-or-later). Fifth member of the Ultimate family next to [UltimateCalendar](https://github.com/qtekfun/UltimateCalendar), [UltimateTasks](https://github.com/qtekfun/UltimateTasks) and [UltimateDeck](https://github.com/qtekfun/UltimateDeck): their common pieces (Gradle and quality setup, theme, release recipe, hooks) are copied and adapted.

Always read `SPEC.md` (what to build) and `PLAN.md` (in what order, and who owns what) before starting. If anything in this file contradicts the spec, stop and ask.

## Project identity
- Name: **UltimateTunes**. Server image `ghcr.io/qtekfun/ultimatetunes-server`. Android `applicationId` `com.qtekfun.ultimatetunes`.
- Repository: `github.com/qtekfun/UltimateTunes`, **monorepo**, main branch **`master`** (only entered through a PR with GitHub CI green; by convention, there is no ruleset).
- License: **GPL-3.0-or-later**; SPDX header in every source file (py, kt, kts, yml, toml, sql, md, Dockerfile, sh).
- Languages: code, identifiers, commits and repository docs in **English**; the app UI in English (default) and Spanish, every visible string in `strings.xml` (`values/`, `values-es/`). The admin panel in English and Spanish too (Jinja catalogs).
- One version for everything: the root **`VERSION`** file (SemVer, `X.Y.Z` or `X.Y.Z-rc.N`). Gradle and `pyproject.toml` read it; nobody else writes a version.

## Layout and ownership
```
contracts/   OpenAPI (ut-v1, opensubsonic subset, internal worker API), SQL migrations, error codes, id rules
server/      Python package `ultimatetunes` (src layout), tests, Dockerfile, compose files
android/     Gradle project: :app (UI), :core:api (HTTP client + models + fake server), :core:player (Media3)
fastlane/    Store texts and screenshots (en-US, es-ES)
tools/       Repo scripts (store texts, worktrees, version code)
.claude/     Settings, hooks, subagents, ownership.json
```
- **`.claude/ownership.json` says which paths each PLAN task may write.** The `guard-files` hook enforces it on `feat/tNN-*` branches. Shared files (`PLAN.md`, `SPEC.md`, `contracts/`, `VERSION`, `CHANGELOG.md`, workflows) are written only by the coordinator session on its own branches.
- The one exception: each stream may add **new** migrations in its own number range (`contracts/db/migrations/`, ranges in `contracts/db/README.md`), portable SQL, never editing an existing one.
- **Contracts are frozen per wave.** A stream that needs a contract change stops, writes the proposal in its PR description and asks the coordinator; the coordinator changes `contracts/` in a separate `contracts/<topic>` PR first.

## Stack (do not change without asking)
### Server
- Python **3.13**, **uv** (`uv.lock` committed, `uv sync --locked`), FastAPI + uvicorn, pydantic v2 + pydantic-settings, **SQLite** (WAL) with plain SQL migrations from `contracts/db/migrations/` applied by our own small migrator. No ORM.
- `httpx` for outbound HTTP, `ytmusicapi` (search, radio, playlists), `yt-dlp` + `ffmpeg` (+ the JS runtime yt-dlp requires) **only in the worker**, `mutagen` (tags), `argon2-cffi`, `jinja2` + vendored **HTMX** for the admin panel (no CDN, no JS build step).
- Two services from **one image**: `api` and `worker`. The **worker has no database access**: it talks to the api through the internal worker API (`contracts/openapi/internal-worker.yaml`, internal Docker network, shared token). Volumes: `/data` (api only: DB, config), `/music` (library), `/staging` (partial downloads, shared), `/opt/ytdlp` (worker only: self-updating yt-dlp).
- Cache, job queue, rate limiter and in-flight registry are **interfaces** (`TtlCache`, `JobQueue`, `RateLimiter`, `InFlight`) with in-process/SQLite implementations. **No Redis in v1**; the interfaces let one be added later without touching callers.
- **Kubernetes-ready from day one** (v1 runs on Docker Compose; k8s comes after 1.0, PLAN phase 5). Rules that keep that door open:
  - 12-factor: all config from env vars; logs as JSON to stdout; no state in the container filesystem; graceful shutdown on SIGTERM.
  - The api is **stateless**: anything shared between requests goes through the interfaces above (in v1 in-process; with several replicas, Redis implementations) or the database. Admin sessions are signed cookies.
  - **Database through a repository layer** and **portable SQL** (the subset that runs on SQLite and PostgreSQL: no SQLite-only functions, types or pragmas outside the SQLite driver). CI applies every migration on both SQLite and PostgreSQL. Only SQLite ships in v1.
  - Migrations are a separate command (`ultimatetunes migrate`), so k8s can run them as a Job; the api only checks the schema version at start.
  - Files through `LibraryStore` and `StagingStore` interfaces (local filesystem in v1; a shared volume or S3-compatible store later). Never build paths outside them.
  - Workers scale horizontally: jobs are claimed with a **lease** and heartbeat, idempotent, safe to retry on another worker.
  - Probes: `/healthz` (liveness, no dependencies) and `/readyz` (database reachable, schema up to date, storage writable).
### Android
- Kotlin, Jetpack Compose, Material 3 adapted to the **Apple Music look** (SPEC §5), Media3 (ExoPlayer, `MediaSessionService`, `SimpleCache`, downloads), OkHttp + kotlinx-serialization (no Retrofit), Coil, Hilt, Room, DataStore, WorkManager.
- `minSdk` 26, `targetSdk` latest stable. Gradle KTS + version catalog, JDK 21 for Gradle, bytecode 17, same quality setup as UltimateCalendar (detekt, ktlint, Lint warnings as errors, Kover, dependency verification, licensee, forbidden-dependency check).
- The UI never talks to the network: everything goes through `:core:api` (`TunesApi`) and `:core:player`.

## Free-software and privacy rules — non-negotiable
- **Forbidden**: Firebase, Google Play Services, Crashlytics, Sentry or any crash/analytics SDK, telemetry of any kind, proprietary SDKs, non-free dependencies (server and app).
- Before adding **any** dependency: check its license (GPL-3.0-or-later compatible) and **ask the user**. Approved lists are in SPEC §6.
- The Android app talks **only to the user's server**. It never contacts YouTube, MusicBrainz, LRCLIB or anything else directly.
- The server contacts only: YouTube Music (ytmusicapi, yt-dlp), YouTube image hosts for covers of external items (`yt3.googleusercontent.com`, `lh3.googleusercontent.com`, `yt3.ggpht.com`, `i.ytimg.com`), MusicBrainz, Cover Art Archive (`coverartarchive.org` and the `archive.org` storage it redirects to, HTTPS only), LRCLIB, GitHub releases for yt-dlp self-updates only (`api.github.com`, `github.com`, `release-assets.githubusercontent.com`, `objects.githubusercontent.com`), the notification URL the admin set, and, only when the admin enables the optional PO token provider (Compose profile `pot`, decision D13), that provider container's BotGuard requests to `www.youtube.com`, `www.google.com` and `jnn-pa.googleapis.com`. Nothing else. (Spotify: no host in v1, imports come from uploaded files; SPEC §11, T03d.)

## Security rules — non-negotiable
- API keys: 256-bit random, shown once, stored only as a hash; revocable per device. Passwords: Argon2id. Token auth (`t`/`s`) is refused with error 42.
- Never log secrets, API keys, passwords, cookies, full request URLs with `apiKey`/`p` parameters, or YouTube cookies. Redact in the logging filter, with a test.
- Every subprocess (yt-dlp, ffmpeg) is called with an **argument list**, never `shell=True`, never with unvalidated input; video ids match `^[A-Za-z0-9_-]{11}$`.
- Every filesystem path built from metadata goes through the path sanitizer (100 % coverage) and must stay inside `/music` or `/staging`.
- Import URLs: allowlist of hosts (YouTube, YouTube Music); Spotify URLs are rejected in v1 (Spotify playlists come as uploaded files). No server-side request to arbitrary URLs (SSRF).
- Admin endpoints: admin role, session cookie `HttpOnly`/`Secure`/`SameSite=Strict`, CSRF token, network allowlist (LAN/Tailscale by default). Every admin endpoint has a test that a non-admin gets 403.
- Containers run as non-root with a read-only root filesystem; secrets only from env vars or Docker secrets.
- Nothing is exposed to the Internet until PLAN T22 is done. Proof of concept: Tailscale only (`tailscale serve` gives HTTPS).

## Commands
Server (from `server/`):
- Install: `uv sync --locked`
- Lint and types: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
- Tests: `uv run pytest` (unit + integration; no real network) · Contract tests: `uv run pytest tests/contract`
- Security: `uv run bandit -c pyproject.toml -r src` and `uv run pip-audit`
- Everything CI runs: `make -C server check`
- Local stack: `docker compose -f server/compose.test.yaml up --build` (fake YouTube; never real downloads in tests)

Android (from `android/`):
- Debug build: `./gradlew assembleDebug` · Unit tests: `./gradlew testDebugUnitTest`
- Everything CI runs: `./gradlew check`
- UI tests on the author's phone **without uninstalling**: `./gradlew installDebug installDebugAndroidTest` + `adb shell am instrument -w com.qtekfun.ultimatetunes.test/com.qtekfun.ultimatetunes.HiltTestRunner`. **Never** `connectedDebugAndroidTest` on the author's phone.

Repo: `tools/check-store-texts.sh` · `tools/worktree.sh <task>` (creates the worktree and branch for a PLAN task).
- Local CI (same gates before pushing; SPEC §11): `tools/ci-local.sh` runs the same gates as `ci.yml` for what changed against `origin/master`; `--all` for every gate, or name groups (`pr-title`, `secrets`, `store-texts`, `server`, `contracts`, `android`, `docker`). With no arguments it always runs the PR-title (Conventional Commit, via `gh`), secrets and store-text gates. Needs a clean tree (it tests the committed HEAD).

## Quality and tests
- A task is done only when `make -C server check` and/or `./gradlew check` (whatever it touched) are green, and GitHub CI is green on the PR (`tools/ci-local.sh` runs the same gates locally).
- Server: pytest + `anyio`, `respx` for outbound HTTP, a **fake catalog** (`FakeMusicCatalog`) and a **fake downloader** that writes a short generated audio file; `schemathesis` against the OpenAPI contracts. No test reaches YouTube except the nightly **canary**.
- Android: JUnit5 + MockK, Turbine, in-memory Room, MockWebServer with the **fake server** of `:core:api` (built from the contract examples), Compose UI tests for key flows.
- **Coverage**: server ≥ 85 % (pytest-cov), Android ≥ 85 % over `:core:*` and view models (Kover). **100 % mandatory** in: auth (API keys, passwords, OpenSubsonic auth rules), rate limiter, id resolution (`yt:` ↔ library), path sanitizer, job state machine, streaming-while-downloading state machine, client cache policy and queue prefetch planner. Never write empty or tautological tests to raise a number.
- Time through an injectable clock (`Clock` in Kotlin, a `clock` dependency in Python); never `time.time()`/`datetime.now()` directly in testable logic.
- Python: `mypy --strict`, ruff (rules in `pyproject.toml`), no bare `except`, typed errors (`TunesError` subclasses mapped to OpenSubsonic error codes in one place).
- Kotlin and Lint warnings are errors. IO errors are sealed results (`TunesResult`), not loose exceptions reaching the UI.

## Parallel work with subagents
- The coordinator is the main session. It owns `PLAN.md`, `SPEC.md`, `contracts/`, workflows and merges.
- Within a wave, the coordinator launches **one subagent per stream, all in the same message**, each in its own git worktree (`tools/worktree.sh tNN`) and branch `feat/tNN-<slug>`, using the `stream-implementer` agent definition. Subagents never touch another stream's paths (the hook blocks it) and never merge.
- Every PR is reviewed by the **`independent-reviewer`** agent, which has not seen the implementation and reads only the diff, SPEC and contracts. Its blocking findings are fixed before merging.
- The coordinator merges in dependency order (`PLAN.md` says it), re-runs local CI after each merge, and stops at the checkpoint at the end of each wave to report to the user.

## Workflow
- One PLAN task per branch (`feat/tNN-<slug>`, `fix/…`), from `master`. Start in plan mode for tasks that touch more than one area.
- Commits in **Conventional Commits**, small and atomic; **the PR title too** (squash merge).
- No `git push --force`, no history rewriting, no commits or pushes to `master`. The hooks block it; do not work around them.
- Open the PR with `gh pr create` filling in the template. Run `tools/ci-local.sh` before pushing and fix what fails on GitHub CI. When CI is green and the independent review has no blocking findings, the coordinator merges with `gh pr merge --squash`.
- When a task ends: 2-3 lines on what was done and what remains; tick it in `PLAN.md` with `*Result:*` if anything differs from the plan; record decisions in `SPEC.md` §11 with date and task.
- If the spec is ambiguous or information is missing: **ask**, do not invent.

## Versions and releases
- Manual and tag-driven, like UltimateCalendar (see `RELEASING.md`). `VERSION` and `CHANGELOG.md` change only in a release PR (`chore: release X.Y.Z`, branch `release/X.Y.Z`), which also carries the store texts `fastlane/metadata/android/{en-US,es-ES}/changelogs/<versionCode>.txt`.
- **Publishing is paused** (no tags, no GHCR, no GitHub Releases) until the author decides otherwise: releases are built locally (RELEASING.md).
- When publishing is enabled: the `vX.Y.Z` tag is pushed by the author, or by Claude when the author explicitly asks. The `Release` workflow builds the signed APK and the multi-arch server image and publishes both.

## What NOT to do
- Do not implement anything in SPEC "Out of scope".
- Do not bump dependency versions by hand (Dependabot does) and do not hand-edit `uv.lock` or `android/gradle/verification-metadata.xml` (regenerate them).
- Do not disable or relax ruff, mypy, bandit, pip-audit, detekt, ktlint, Lint, Kover, coverage thresholds, dependency verification, gitleaks, Trivy or workflows to make CI pass.
- Do not download real music in tests or CI (except the canary, one fixed Creative Commons track, scheduled on the server and manual on GitHub).
- Do not use real data in screenshots: they come from a test with invented artists and covers.
