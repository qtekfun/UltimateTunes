<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# UltimateTunes — Task plan

Rules: one task per branch `feat/tNN-<slug>`, its gates green before the PR (`make -C server check` and/or `./gradlew check`), merge only through a PR with GitHub CI green (`tools/ci-local.sh` runs the same gates locally) and the independent review without blocking findings. Tick `[x]` when done, with `*Result:*` when something differs from the plan. Every task is verifiable (a test or a described manual check). Paths each task may write: `.claude/ownership.json`.

**Waves.** Tasks of the same wave and different streams run **in parallel**, one subagent each, in their own worktree. Within a stream, tasks run in order. The coordinator stops at the **checkpoint** at the end of each wave and reports to the user (what was done, what fails, what is next) before starting the next wave.

| Stream | Area | Tasks |
| --- | --- | --- |
| A | Foundations, contracts (coordinator) | T00, T01, T02 |
| S | Risk spikes | T03a, T03b, T03c, T03d |
| B | Server core: auth, library | T04, T05 |
| C | Search and radio | T06, T07 |
| D | Download worker and tagging | T08, T09 |
| H | Lyrics and imports | T10, T11 |
| F | Android UI | T12, T13 |
| I | Release pipeline | T14 |
| L | Admin panel | T15 |
| E | Streaming while downloading | T16 |
| G | Android playback | T17, T18 |
| J | Contract tests and canary | T19 |
| — | Integration and hardening (coordinator) | T20–T24 |

## Wave 0 — Foundations (coordinator, sequential)
- [x] **T00 Monorepo skeleton**: `VERSION` read by Gradle and `pyproject.toml`; `server/` (uv project, src layout, FastAPI app factory, settings from env, `/healthz` and `/readyz`, JSON logging to stdout with secret redaction + test, graceful shutdown, `ultimatetunes migrate` command, `Makefile` with `check`), `server/Dockerfile` (non-root, read-only friendly, api/worker commands), `server/compose.yaml` (example) and `server/compose.test.yaml`; `android/` copied from UltimateCalendar's Gradle setup (version catalog, Hilt, Compose, Material 3, detekt, ktlint, Lint, Kover, verification metadata, licensee, forbidden dependencies) with modules `:app`, `:core:api`, `:core:player`, en/es strings, `HiltTestRunner`, empty screen. SPDX everywhere.
  - *Verification:* `make -C server check` and `./gradlew check assembleDebug` green; `docker compose -f server/compose.test.yaml up` answers `/healthz`.
- [x] **T01 Quality and CI**: all gates wired (coverage thresholds incl. the 100 % packages as empty-but-enforced lists), workflows of `.github/` green on a test PR, Dependabot (gradle, uv, docker, actions), gitleaks, Trivy. The author creates the `UT_*` signing secrets (RELEASING.md).
  - *Result:* forbidden-dependency failures proven by banning already-present deps (`fastapi`, `androidx.core`) on throwaway PRs #8/#9, since adding Sentry or Play Services needs the author's approval; the banned names themselves are unit-tested. Secrets `UT_*` created by the author.
  - *Verification:* test PR green; a forbidden dependency (Play Services in Android, `sentry-sdk` in the server) makes CI fail; a non-conventional PR title fails; a planted fake secret is caught by gitleaks.
- [x] **T02 Contracts and stubs**: `contracts/openapi/ut-v1.yaml`, `contracts/openapi/opensubsonic-subset.yaml` (JSON + XML shapes, error codes), `contracts/openapi/internal-worker.yaml`, `contracts/db/migrations/0001_init.sql` (all v1 tables of the spec), `contracts/errors.md`, `contracts/ids.md` (`yt:`, `ytalbum:`, `ytartist:`, library UUIDs, aliasing). Migrator (portable SQL; CI applies all migrations on SQLite **and** PostgreSQL), repository layer, `LibraryStore`/`StagingStore` interfaces with filesystem implementations. **Router stubs** for every area returning "not implemented" (error 0 / 501) so streams only fill their own modules; core interfaces (`TtlCache`, `JobQueue`, `RateLimiter`, `InFlight`, `MusicCatalog`, `Downloader`, `Clock`) with in-memory implementations and fakes. `:core:api`: `TunesApi` client, models, and a **fake server** (MockWebServer dispatcher) built from the contract examples. Migration number ranges per stream in `contracts/db/README.md`.
  - *Verification:* OpenAPI files validate; migrations apply on an empty SQLite; schemathesis runs against the stubs (expected "not implemented"); the Android fake server answers every endpoint used by the UI.
- [ ] **Checkpoint 0** — report to the user and wait for approval.

## Wave 0b — Risk spikes (parallel, 4 subagents; reports only, spike code is not merged)
- [x] **T03a Streaming a growing file**: serve a file being written (chunked, no Content-Length, no Range) to ExoPlayer and to one third-party client (Tempo or Substreamer); measure time to first sound; behaviour on seek and on failure. *Verification:* report in `docs/spikes/T03a.md` + decision in SPEC §11.
  - *Result:* Media3 tested in a JVM harness, not on a device; third-party clients untested (manual protocol in the report).
- [x] **T03b YouTube Music from the server**: ytmusicapi search, watch playlist (radio), playlist read, without account, from the home IP; rate behaviour. *Verification:* report `docs/spikes/T03b.md`.
- [x] **T03c yt-dlp today**: required JS runtime, PO-token situation, best Opus/M4A format selection, time to first byte, download time per track, auto-update method inside a read-only container. *Verification:* report `docs/spikes/T03c.md` + Dockerfile changes proposed.
  - *Result:* no real download (repo hook); time to first byte and download time are estimates, pending the author's exception.
- [x] **T03d Spotify playlists**: options to read a public playlist (Web API with client credentials vs alternatives), their terms and limits. *Verification:* report `docs/spikes/T03d.md` + decision (or RF-08 Spotify stays disabled).
- [ ] **Checkpoint 0b** — report, decisions recorded in SPEC §11.

## Wave 1 — Parallel build (6 subagents, then L)
- [x] **T04 [B] Users, keys and auth**: users, roles, Argon2id; API keys (create/list/revoke, hashed, last use); OpenSubsonic auth rules (apiKey alone, key as password, `t`/`s` → 42, `apiKey`+`u` → 43); `/ut/v1/keys`; rate limiter with lockout; audit log; bootstrap admin CLI. **100 %** in `auth/`.
  - *Verification:* tests for every auth rule and lockout; no secret in logs (test).
- [x] **T05 [B] Library and browsing**: register files (scan of `/music`), artists/albums/songs, `ping`, `getLicense`, `getOpenSubsonicExtensions`, `tokenInfo`, `getMusicFolders`, `getArtists`, `getArtist`, `getAlbum`, `getSong`, `getAlbumList2`, `getRandomSongs`, `getCoverArt` (with sizes), `stream`/`download` of library files with Range, `replayGain` fields; JSON and XML.
  - *Verification:* tests per endpoint and format; Tempo plays a local track against the test stack (manual, noted in the PR).
  - *Result:* `registerTrack` (`/internal/v1/library/tracks`) was left to integration PR #42, which also landed the T09 adoption rule; Tempo playback against the test stack not done yet.
- [x] **T06 [C] Search**: `MusicCatalog` on ytmusicapi (+ fake), `search3` merging library and external results with virtual ids, `TtlCache` for queries, id resolution `yt:` ↔ library (**100 %**).
  - *Verification:* tests with the fake catalog; recorded ytmusicapi responses as fixtures.
- [x] **T07 [C] Radio**: `/ut/v1/radio`, `getSimilarSongs2`, local-first mapping. *Verification:* tests with fixtures.
  - *Result:* also delivered Listen Now (#39), library-only; `favouriteRadios` holds starred songs.
- [x] **T08 [D] Download worker**: worker loop on the internal worker API (claim with **lease** + heartbeat, progress, complete, fail; expired leases go back to the queue), `Downloader` on yt-dlp writing to `/staging` with progress, format policy (from T03c), retries with backoff, yt-dlp self-update into `/opt/ytdlp`, `canary` command; api side: job endpoints, deduplication per video id, job state machine (**100 %**).
  - *Verification:* tests with the fake downloader; a killed worker leaves a job that is retried.
  - *Result:* `/ut/v1/tracks/{id}/request|status` are still stubs (they need T06's materialization; open for integration); `canary` moves to T19.
- [x] **T09 [D] Tagging and archive**: MusicBrainz lookup (1 req/s queue) + Cover Art Archive, `needs_review`, mutagen tags for Opus and M4A, ReplayGain via ffmpeg, path sanitizer (**100 %**), atomic move to `/music`, library registration through the internal API.
  - *Verification:* golden-file tests on generated audio; malicious titles (`../`, NUL, reserved names, 300-char names) end inside `/music`.
  - *Result:* registration through the internal API landed in #42 with the adoption rule (a retry after a crash adopts its own file by SHA-256; contracts updated).
- [x] **T10 [H] Lyrics**: LRCLIB client, storage, `getLyricsBySongId` (synced + plain). *Verification:* respx fixtures.
- [x] **T11 [H] Playlist import**: YouTube Music playlists; Spotify from an uploaded file (generic CSV, Exportify CSV, data-export JSON; T03d); matching to YT Music; import jobs and progress; result as a user playlist. *Verification:* fixtures; a 50-track fixture playlist imports with a match report.
- [x] **T12 [F] Android shell (Apple Music style)**: theme and design system (§5), tabs, mini player and full player UI (no real playback), large-title headers, artwork grids, colours from artwork, Connect screen (URL + key, QR), Listen Now and Radio screens, against the fake server. *Verification:* Compose UI tests of navigation; previews; screenshots from the fake data reviewed in the PR.
  - *Result:* the QR button is a placeholder; the UI tests first ran on the author's Pixel with T13 (the phone was in fastboot during T12).
- [x] **T13 [F] Android Library, Search, Playlists, Lyrics view, Import and Settings screens** (UI + view models, fake server). *Verification:* view-model tests with Turbine; UI tests of search → result → album.
  - *Result:* add-to-playlist, context menus and starring from rows moved to T18.
- [x] **T14 [I] Release pipeline**: validate `release.yml` with a `v0.0.1-rc.1` dry run on a fork branch or with the author: signed APK, SHA-256, GHCR multi-arch image with `X.Y.Z` and `latest` tags (rc → no `latest`), `nightly.yml` skeleton, `tools/check-store-texts.sh`. *Verification:* a pre-release exists with APK and image (deleted afterwards if the author wants).
  - *Result:* pipeline verified with dry runs; publishing paused — no spending, homelab only (no `v0.0.1-rc.1` pre-release; release PR #32 was merged, so `VERSION` on master is already `0.0.1-rc.1`).
- [x] **T15 [L] Admin panel** (starts when T04 is merged): sessions, CSRF, network allowlist, users, keys (with QR for the app), downloads queue, library (space, `needs_review`, delete), yt-dlp status/update, audit log, notifications (ntfy/webhook), en/es. *Verification:* every admin route has a 403 test for non-admins and a CSRF test; HTMX vendored (no external request from the panel).
- [x] **Checkpoint 1** — report.
  - *Result:* reached 2026-10-12: T04–T15 merged; GitHub Actions disabled, merges gated by `tools/ci-local.sh` + independent review (SPEC §11).

## Wave 2 — Parallel build (3 subagents)
- [x] **T16 [E] Streaming while downloading**: `stream` of `yt:` ids tees `/staging` while the job runs (per T03a), `InFlight` registry, several listeners on one download, no seek on partial, clean error on failure, alias `yt:` → library id once archived; streaming state machine **100 %**. Depends T05, T08.
  - *Verification:* integration test with the fake downloader writing slowly; two clients on the same track; failure mid-stream.
  - *Result:* merged #44 (with #49: `/ut/v1/tracks/{id}/request|status`); streaming state machine 100 %.
- [x] **T17 [G] Android playback**: Media3 `MediaSessionService`, `SimpleCache` LRU 2 GB configurable, cache policy (**100 %**), queue **prefetch** planner (**100 %**: request next track on the server + preload), offline downloads (Media3 downloads, separate from cache; playlists/albums marked offline stay in sync via WorkManager, RF-12), first-play status polling, ReplayGain applied, real server connection with encrypted API key. Depends T12, T05.
  - *Verification:* unit tests of cache/prefetch; instrumented test against the test stack: play, cache hit on replay with network off.
  - *Result:* merged #47; instrumented playback tests green on the author's Pixel 8 (in-process server).
- [x] **T18 [G] Android features wired**: radio queue, synced lyrics with seek, favourites, playlists, play queue sync, import screen, settings, **export to the phone** (RF-14: SAF folder picker, original files with tags, progress notification, skips tracks not fully available). Depends T17. *Verification:* UI tests on the fake server; manual run on the author's phone noted in the PR.
  - *Result:* merged #50; 32 instrumented tests green on the Pixel 8; manual run against a real server moved to T20/T23.
- [x] **T19 [J] Contract tests and canary**: schemathesis against the real app for every contract, XML and JSON; OpenSubsonic compatibility checks with one third-party client (manual matrix in `docs/compat.md`); canary (one fixed Creative Commons track) scheduled on the server with alert, GitHub job manual only (T03c). Depends T05, T06.
  - *Verification:* CI job green; the server canary runs green against the test stack config (a run on GitHub is best effort: runner IPs get the bot wall).
  - *Result:* merged #45; canary wired into the api and the worker by #49; canary track license confirmation pending from the author.
- [x] **Checkpoint 2** — report.
  - *Result:* reached 2026-10-12: T16–T19 merged; the repo is public and GitHub Actions CI is back on (free minutes); Release and Nightly stay disabled.

## Wave 3 — Integration and hardening (coordinator, sequential)
- [x] **T20 End-to-end**: compose test stack + emulator: search → play external → archived → replay from disk → offline from cache; two users; worker killed mid-download. *Verification:* `e2e` workflow green.
  - *Result:* merged #52; `tools/e2e/run.sh` on a fresh stack (server e2e 3 passed, `e2e` workflow green on a labelled PR). The device half runs on the author's Pixel 8 instead of an emulator (local only, through `adb reverse`).
- [x] **T21 Measurements**: first-sound times (external and library), search p95, RAM idle, 50,000-track library browse. Results in SPEC §6. *Verification:* numbers recorded; regressions become issues.
  - *Result:* merged #57 (`docs/measurements.md`, `tools/bench/`); every target met on the server side once #54 (`getArtists` without planner statistics, fixed by #58) and #55 (worker claim poll, fixed by #59) were closed. External first sound measured with a modelled download; a timed phone measurement is pending (the Pixel 8's MediaCodec was crashing then).
- [x] **T22 Hardening and public access**: `SECURITY.md` threat model and checklist completed and reviewed by the `independent-reviewer` agent in security mode; Caddy example (TLS, HSTS, limits), admin kept LAN/Tailscale-only by default, ZAP baseline scan in CI against the test stack, dependency and image scan clean. *Verification:* checklist all ticked; scan report attached.
  - *Result:* merged #56 (separate internal listener, trusted proxies, admin logout revocation, search/cache/body limits, `deploy/`); ZAP baseline 0 FAIL / 0 WARN, as a manual workflow. A later exposure audit added #61 and #63/#65. Left to the author on the homelab: TLS certificate, rate limits through the real proxy, backup restore test; release signing waits for publishing.
- [x] **T23 Identity and store assets**: icon, screenshots from a test with invented artists and covers, store texts en/es, README images. *Verification:* `tools/check-store-texts.sh` green; images in `fastlane/`.
  - *Result:* merged #53, with the T18 export follow-ups. The manual SAF export on the phone was blocked by a system MediaProvider crash loop at the time.
- [ ] **T24 Release 1.0.0** following RELEASING.md. *Verification:* GitHub Release with APK and image; Obtainium update tested on the author's phone.
  - *Status:* release candidate 1.0.0-rc.1 prepared by the coordinator (release PR); publishing needs the author (enable the `Release` workflow and push the tag; RELEASING.md). See `docs/decisions.md` D1 and D12.
- *Wave 3 result (2026-10-12):* besides T20–T23, Wave 3 delivered: security audit fixes before exposure (#61 exposure hardening, #63 download limits, catalog budget and auth brakes, #65), performance fixes found by T21 (#58, #59), the web player at `/` (#66, RF-15), container architecture docs (#67), deployment examples (Caddy and Tailscale in #56, Traefik with Authelia in #61, Traefik behind Cloudflare Tunnel in #68), authenticated ntfy notifications (#69), and Android polish (#64 full player sheet, #70). Decisions in SPEC §11.

## Phase 5 — Kubernetes (after 1.0, when the author decides)
- [ ] **T25 PostgreSQL driver**: repository layer on psycopg; full test suite on both databases in CI; SQLite → PostgreSQL data migration command. *Verification:* CI matrix green; a copy of the real library migrated and checked.
- [ ] **T26 Shared state on Redis**: `TtlCache`, `RateLimiter`, `InFlight`, `JobQueue` implementations with the same contract tests as the in-process ones. *Verification:* two api replicas share rate limits and deduplicate downloads (integration test).
- [ ] **T27 Kubernetes packaging**: Kustomize base + overlays (or Helm, decided then): api Deployment + HPA, worker Deployment, migrate Job, Ingress with TLS, PVCs (RWX) or S3-compatible `LibraryStore`, NetworkPolicies (worker without ingress, admin internal), PodSecurity restricted. *Verification:* deployed on a kind/k3s cluster in CI and on the author's homelab; e2e suite green against it.
