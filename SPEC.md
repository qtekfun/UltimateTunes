<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# UltimateTunes — Specification (SPEC)

Source: interview with the author (2026-10-11/12) and the spec document ["UltimateTunes — Especificación"](https://claude.ai/code/artifact/6083d415-7c93-4a54-8b54-94d66cd74067) (Spanish, superseded by this file where they differ). What is not here is not invented: it is asked.

## 1. Goal

A personal "Spotify" on your own hardware: you search for any song, it plays at once, and from then on it lives in **your** library, tagged and forever. A **server** in Docker answers the **OpenSubsonic** API, keeps the library and fetches from **YouTube Music** what it does not have yet; an **Android client** with an **Apple Music**-style interface caches every play to save mobile data. Free software (GPL-3.0-or-later), private, multi-user.

### Problems it solves
- Existing self-hosted servers (Navidrome & co.) only play what you already own; discovery means leaving them.
- Existing proxies (Octo, octo-fiesta, GeetHub) either only preview without keeping, or always download through paid services, and none fixes the latency of the first play or caches per play on the client.
- YouTube Music clients (Metrolist, SimpMusic) work, but every play goes to Google and nothing ends up in a library you own.

## 2. Scope and assumptions
- Users: the author and a few family members (multi-user from v1). Library: thousands of tracks; must stay smooth with 50,000.
- Source of new music: **YouTube Music only** (no plain YouTube in v1).
- Audio stored in its **original format** (Opus or M4A), never transcoded.
- Everything requested is **kept**; deletion is an explicit admin action.
- Access in the proof of concept: **Tailscale only** (HTTPS via `tailscale serve`). Public access without VPN (a VPN on the phone costs battery) is prepared at the end (T22).
- Personal use. YouTube's terms are a grey area; the server is never offered to third parties.

## 3. Architecture

```
Android client ──HTTPS + API key──▶ api (FastAPI) ──▶ SQLite (/data)
Third-party OpenSubsonic clients ─┘      │  ▲            /music (library)
                                         │  │ internal worker API (token, internal network)
                                         ▼  │
                                       worker (yt-dlp, ffmpeg, mutagen) ──▶ /staging, /music
api ──▶ YouTube Music (ytmusicapi), LRCLIB        worker ──▶ YouTube Music (yt-dlp), MusicBrainz, Cover Art Archive
```

- **api**: OpenSubsonic + `/ut/v1` + web player (`/`, `/web`) + admin panel `/admin` on the client port (8044); the internal worker API only on a second, never-published port (8045); owns the database; serves files; the only service clients reach. Containers, networks and every connection: `docs/architecture.md`.
- **worker**: claims download jobs from the api, downloads to `/staging`, tags, computes ReplayGain and moves the file to `/music`, reporting progress. **No database access**, no inbound port.
- Same image, two commands. Interfaces `TtlCache`, `JobQueue`, `RateLimiter`, `InFlight` with in-process/SQLite implementations; **Redis is not used in v1** (decision 2026-10-12, §11).

### Ready to scale on Kubernetes (after 1.0)
v1 runs with Docker Compose on one host, but is built so that moving to Kubernetes is configuration, not a rewrite:

| Concern | v1 (Compose) | Kubernetes (phase 5) |
| --- | --- | --- |
| api | 1 container, stateless | Deployment with N replicas behind an Ingress |
| worker | 1 container | Deployment scaled by queue length; jobs claimed with leases |
| Database | SQLite (WAL) on `/data` | PostgreSQL (same portable migrations, run by a Job) |
| Shared state (cache, rate limit, in-flight, queue) | in-process / SQLite behind interfaces | Redis implementations of the same interfaces |
| Library and staging files | local volumes behind `LibraryStore`/`StagingStore` | RWX volume (NFS/CephFS) or S3-compatible store |
| Config and secrets | env vars, Docker secrets | ConfigMap, Secret |
| Health | `/healthz`, `/readyz` | liveness and readiness probes |
| Packaging | `compose.yaml` | Kustomize base + overlays (or a Helm chart, decided then) |

### Play flow
1. Track in the library → file served with HTTP Range; the client caches it.
2. Track not in the library (`yt:<videoId>`) → the api asks for a job (deduplicated per video id) and **streams the growing file from `/staging` while the worker downloads it** (seek on that first play only where the container and a known size allow it; T03a). When done, the track is tagged and archived; the `yt:` id becomes an alias of the library id; later plays come from the file.

## 4. Functional requirements (v1)

### RF-01 Users and devices
Admin creates users (role admin/user). Each user creates **API keys per device** (name, created, last used, revoke). Passwords only for the admin panel and to create keys. First start: bootstrap admin from an env var or a one-time CLI command, never a default password.

### RF-02 OpenSubsonic API
Subset in `contracts/openapi/opensubsonic-subset.yaml`, JSON and XML: `ping`, `getLicense`, `getOpenSubsonicExtensions`, `tokenInfo`, `getMusicFolders`, `getArtists`, `getArtist`, `getAlbum`, `getSong`, `getAlbumList2`, `getRandomSongs`, `search3`, `getCoverArt`, `stream`, `download`, `getLyricsBySongId`, playlists (`getPlaylists`, `getPlaylist`, `createPlaylist`, `updatePlaylist`, `deletePlaylist`), `star`/`unstar`/`getStarred2`, `scrobble`, `getSimilarSongs2`, `getPlayQueue`/`savePlayQueue`. Extensions declared: `apiKeyAuthentication`, `songLyrics`, `formPost`. Authentication: `apiKey` alone (with `u` → error 43); for clients without that extension, the key is also accepted as the password (`u` + `p`/`enc:`); `t`/`s` refused with error 42 because only Argon2id hashes are kept.

### RF-03 Search
`search3` merges library results and YouTube Music results (songs, albums, artists). External items carry `yt:<videoId>` (songs) / `ytalbum:<browseId>` / `ytartist:<channelId>` ids and are marked (`isExternal` in `/ut/v1` responses; plain OpenSubsonic clients just see them as songs). Results cached with a TTL.

### RF-04 On-demand download and archive
`POST /ut/v1/tracks/{id}/request` (keep without playing) and implicit on `stream`. Job states: `queued → downloading → tagging → ready | failed` (retries with backoff, max 3). Progress at `GET /ut/v1/tracks/{id}/status`. Metadata: YouTube Music first, completed with **MusicBrainz** and **Cover Art Archive**; if the match is weak, keep YT Music data and set `needs_review`. Files: `Artist/Album/NN - Title.ext`, sanitized. **ReplayGain** (track, and album when the whole album is present) computed with ffmpeg and written as tags; exposed in OpenSubsonic `replayGain`.

### RF-05 Streaming while downloading
As in §3. Several listeners of the same pending track share one download. If the job fails mid-stream, the client gets a clean error and the track is marked failed.

### RF-06 Radio and recommendations
`GET /ut/v1/radio?seed={id}` (YT Music watch playlist, local-first: tracks already in the library come with their library id), also behind `getSimilarSongs2`. "Listen Now" in the app: recent, most played, radios from favourites.

### RF-07 Synced lyrics
From **LRCLIB** (by title, artist, album, duration), stored in the DB, served by `getLyricsBySongId` with timings (LRC). Plain lyrics when no synced ones exist.

### RF-08 Playlist import
`POST /ut/v1/imports` with a YouTube Music (or YouTube) playlist URL, or an **uploaded file** for Spotify playlists (generic CSV, Exportify CSV, Spotify data-export JSON; T03d); each track matched on YouTube Music by title, artists, album and duration (YouTube Music has no ISRC; an ISRC from the file resolves the MusicBrainz recording, whose title/artists refine the query and are passed on to tagging) and requested; progress per import; result becomes a user playlist. Importing by Spotify URL is not in v1 (T03d).

### RF-09 Favourites, playlists, history
Per user: stars, playlists, play history (scrobble), play queue saved across devices. Files are shared between users (a track is downloaded once).

### RF-10 Admin panel
`/admin`, admin role only: users (create, disable, role), API keys (list, last use, revoke), download queue (state, retry, cancel), library (space used/free, `needs_review`, delete track/album), yt-dlp (version, last canary result, update now), audit log, notifications (optional ntfy topic or webhook on failed download/canary). Jinja + vendored HTMX, en/es.

### RF-11 Android client
Connect (server URL + API key, or QR shown in the admin panel), Listen Now, Radio, Library (artists, albums, playlists, favourites, downloads), Search (one list, external items marked "not in library yet"), full player (queue, lyrics, radio), import, settings (keys, cache size, offline downloads, quality info), export to the phone (RF-14). Details in §5.

### RF-12 Client cache and offline
Every play goes through Media3 `SimpleCache` (LRU, **2 GB** default, configurable). **Prefetch**: the next track in the queue is requested on the server (so it is ready) and its first bytes preloaded. Explicit **offline downloads** (track, album, playlist) live apart from the cache and are never evicted. A playlist or album marked offline **stays in sync**: tracks added later are downloaded automatically and removed ones are freed (WorkManager, Wi-Fi only by default, configurable). Offline: only cached and downloaded content is browsable; search needs the server.

### RF-13 Notifications from the server
Optional push of failed downloads/canary to an ntfy topic or webhook configured by the admin. The app shows no server-pushed notifications: only playback (MediaSession), download/sync and export progress notifications (POST_NOTIFICATIONS on Android 13+ is the one permission this adds).

### RF-14 Export to the phone
The user can **export** tracks, albums or playlists that are fully available on the phone as **library tracks** (offline downloads, or library tracks completely in the cache; bytes cached under a `yt:` id from a first play are not exported because they predate tagging) to a folder they pick on the phone, through the system folder picker (Storage Access Framework; no broad storage permission). Files keep their original format and tags (never transcoded), named `Artist/Album/NN - Title.ext` (sanitized), with a progress notification; tracks not fully available are listed and skipped. Export is a copy for the user's own use; the app never shares files elsewhere.

### RF-15 Web player
The api serves a web player for browsers at `/` (the home page: the sign-in form, or Listen Now with a session) and under `/web` (`docs/web-player.md`). It covers:
- Listen Now, Radio (stations from favourite songs, artist radio), Library (albums, artists, playlists, favourites), and Search with library results first and YouTube Music results in their own section;
- album, artist and playlist pages with play and shuffle;
- playlists: create, rename, delete, add, remove, move;
- playlist import from a URL or a file;
- download state of `yt:` songs and "download to the library";
- a player bar plus a full-screen "now playing" view with blurred artwork and synced lyrics (tap to seek);
- a queue you can reorder, shuffle and repeat;
- Media Session controls and keyboard shortcuts;
- settings: theme light/dark/system, language en/es, change password, list and revoke your own API keys, sign out.

The look follows §5 on desktop and phone. It talks only to its own server, through the same rules and per-user limits as every client: the OpenSubsonic and `/ut/v1` handlers are called as the signed-in user. Jinja + the vendored HTMX + small own scripts, no build step, en/es.

## 5. Android client: interface (Apple Music style)
Own design inspired by Apple Music, **without** Apple logos, icons, fonts or assets.
- Bottom bar with 4 tabs: **Listen Now, Radio, Library, Search**; a **mini player** pinned above it; the full player slides up over everything like a sheet and follows the finger when dragged down to close.
- Large rounded artwork grids, bold titles, generous spacing; large-title headers that collapse on scroll.
- Full player: big artwork, **colours from the artwork** (Palette) and a blurred artwork background, scrubber, queue sheet.
- Lyrics full-screen, active line highlighted, auto-scroll, tap a line to seek (when the track is in the library).
- Light and dark themes; English and Spanish; large fonts and TalkBack.
- Gestures: swipe the mini player to skip, long-press for context menu (play next, add to playlist, download, export, go to album/artist).

## 6. Non-functional requirements
- First sound of an **external** track: target ≤ 5 s on the home connection (measured in T03 and T21). Library track: ≤ 1 s.
- `search3` with external results: ≤ 2 s p95 (TTL cache for repeated queries).
- Server idle footprint: ≤ 200 MB RAM for api + worker.
- *Result (T21, #57, 2026-10-12; method and machine in `docs/measurements.md`):*
  - **Idle RAM**, api + worker: 92 MiB just started, 143 MiB after real searches, 158 MiB after browsing a 50,000-track library (mostly reclaimable SQLite page cache). Met.
  - **`search3` with external results** (real YouTube Music, 30 searches): cold 722 ms p50 / 1,039 ms p95; TTL-cache hits 195 / 256 ms. Met.
  - **First sound, library track**: server time to first audio byte 12 ms p50 / 18 ms p95. Met on the server side.
  - **First sound, external track**: 3.0 s p50 / 3.4 s p95 server time to first audio byte, with the download modelled at T03c's 1.8 s to first byte and 1 MB/s. About 1 s of it was the idle worker's 2 s claim poll, removed by the long-poll claim (#59: enqueue → claim 1.3 ms p50). A manual first play on the Pixel 8 against a real local server sounded in about 4 s (#70); a timed phone measurement is still pending.
  - **50,000-track library**: first scan 7 min 44 s, rescan 4.3 s, 43.7 MB database. As shipped `getArtists` took ~18–20 s because SQLite had no planner statistics; after `ANALYZE` every browse endpoint was ≤ 162 ms p95 (`getArtists` 43 / 46 ms). Fixed for good by #58 (`PRAGMA optimize` in the driver; 8.3 s → 9 ms for the artist query). Met after #58.
- Approved server dependencies: fastapi, uvicorn, pydantic, pydantic-settings, httpx, ytmusicapi, yt-dlp, mutagen, argon2-cffi, jinja2, python-multipart, itsdangerous; phase 5 only: psycopg (PostgreSQL), redis; dev: pytest, pytest-cov, anyio, respx, schemathesis, openapi-spec-validator, ruff, mypy, bandit, pip-audit. System: ffmpeg, the JS runtime yt-dlp needs: **Deno** (MIT, pinned by version and SHA-256; T03c), and `gpgv` (runtime) / `gnupg` (build stage only) to verify yt-dlp releases (approved 2026-10-12). Optional, approved 2026-10-13 (D13): **bgutil-ytdlp-pot-provider** (GPL-3.0), its yt-dlp plugin zip baked into the image (pinned by version and SHA-256) and its upstream HTTP server image as the opt-in `pot-provider` container (pinned by digest, same version).
- Approved Android dependencies: the UltimateCalendar set (Compose, Material 3, Hilt, Room, DataStore, WorkManager, kotlinx-serialization, Coroutines) plus Media3 (exoplayer, session, datasource-okhttp, ui-compose if needed), OkHttp, Coil, androidx.palette. Anything else: ask.

## 7. Security
- Threat model and checklist in `SECURITY.md` (T22 completes it). Highlights: API keys hashed and revocable; Argon2id; rate limit per IP and per key with temporary lockout; audit log; strict input validation (video ids, URLs allowlist, path sanitizer); subprocesses with argument lists; worker isolated from the DB and from inbound traffic; non-root, read-only containers; secrets from env/Docker secrets; logs redact secrets.
- Transport: HTTPS everywhere outside localhost. PoC through `tailscale serve`. Public phase: reverse proxy with TLS, HSTS, request limits (examples in `deploy/`: Caddy, Traefik, Traefik behind Cloudflare Tunnel with Authelia); `/admin` stays LAN/Tailscale-only unless the admin opts in. The internal worker API listens on its own port (8045), never published (§11, T22). The web player (`/`, `/web`) signs in with a password and a signed session cookie, never with an API key in the browser (§11, web player).
- Android: API key stored encrypted with the Android Keystore; cleartext traffic forbidden in release (debug allows the emulator host only); no secrets in logs.

## 8. Quality and CI
(GitHub Actions CI is on again since the repo went public; Since 1.0.0-rc.2 the Release workflow is enabled and tags publish; Nightly stays disabled. The same gates run locally with `tools/ci-local.sh`; see §11.)
- CI on every PR: server (ruff, mypy, pytest with coverage, bandit, pip-audit), contracts (OpenAPI validation, migrations apply, schemathesis against the app), Android (`./gradlew check assembleDebug`), Docker (build, Trivy scan, `compose.test.yaml` smoke), gitleaks, store texts, PR title.
- Nightly: pip-audit, Android instrumented tests on an emulator against the test compose stack. The canary (real ytmusicapi search, radio, album and playlist read + yt-dlp download of one fixed Creative Commons track) runs **scheduled on the server** (api for ytmusicapi, worker for the download; reported in the admin panel); on GitHub it is manual only, because runner IPs get YouTube's bot wall (T03c).
- Release on tag: signed APK + multi-arch (amd64, arm64) image on GHCR, GitHub Release with notes, APK SHA-256. Updates on the phone through Obtainium.
- Coverage: ≥ 85 % server and Android core; 100 % in the critical areas listed in CLAUDE.md.

## 9. Out of scope (v1)
Android Auto, iOS client, plain YouTube as a source, transcoding, ListenBrainz/Last.fm scrobbling, OIDC/SSO, Chromecast, Play Store / F-Droid submission, public sharing links, podcasts. **Kubernetes deployment, PostgreSQL and Redis implementations** are designed for (§3) but delivered after 1.0 (PLAN phase 5).

## 10. Known risks
- **YouTube changes break yt-dlp or ytmusicapi** (PO tokens, JS challenges, IP blocks): worker isolated, yt-dlp auto-update, canary scheduled on the server with alert, `Downloader`/`MusicCatalog` interfaces to swap implementations. T03 measures the current state.
- **Streaming a growing file**: only front-indexed containers stream progressively and only an exact size lets the client cache the first play (T03a); third-party clients are still untested (manual protocol in `docs/spikes/T03a.md`).
- **MusicBrainz match quality** and its 1 req/s limit: queue with rate limit, keep YT Music data when unsure.
- **Spotify playlist reading**: decided in T03d — the Web API cannot read other users' playlists since 2026-02; v1 imports uploaded files and contacts no Spotify host.
- **Disk growth** with "keep everything": stats and alerts in the admin panel.
- **Clients that search locally** (e.g. Symfonium) never see external results: documented; our client always searches on the server.

## 11. Decisions

### Open
- License: GPL-3.0-or-later like the family, or **AGPL-3.0-or-later** for the server (it is network software)? For now GPL-3.0-or-later.
- How to treat versions of the same song (live, remix, radio edit)? For now: different tracks.
- Library shared between users with per-user state? For now: yes.

### Taken (interview 2026-10-11/12)
- Own server implementing OpenSubsonic (no Navidrome fork or proxy), **Python + FastAPI**; native **Kotlin** client written from scratch.
- First play: streaming while downloading. Keep everything. YouTube Music only. Original format.
- Metadata: YT Music + MusicBrainz + Cover Art Archive.
- Multi-user; API key per device; PoC over Tailscale, public access at the end; security first.
- v1 includes radio, synced lyrics, playlist import, **queue prefetch**, **ReplayGain** and the **admin panel**.
- Client UI in the Apple Music style.
- Tests, CI and APK release from the start; build parallelised with subagents as much as possible.
- **No Redis in v1** (2026-10-12): SQLite + in-process caches behind interfaces; Redis only if the api ever runs as several processes.
- The worker has no database access and talks to the api through an internal API (2026-10-12; fixes a contradiction in the first draft, where it read the `jobs` table directly).
- **Kubernetes-ready** (2026-10-12): stateless api, shared state behind interfaces, portable SQL checked on SQLite and PostgreSQL, storage interfaces, leased jobs, probes, migrations as a separate command. v1 ships on Compose with SQLite; Kubernetes, PostgreSQL and Redis come in phase 5.

### Taken at Checkpoint 0b (spikes, 2026-10-12)
Reports in `docs/spikes/`. Where two reports disagreed, the text below is the decision.

- **YouTube Music catalog** (T03b): `ytmusicapi` anonymously from the server (search, album/artist pages, radio, playlist reads); `requests` (Apache-2.0) comes in transitively. `MusicCatalog`: `language="en"` always (`"es"` silently breaks filtered search); three filtered searches in parallel for `search3`, library-only fallback after 1.5 s; global limit 2 req/s (burst 6); 5 s timeout, one retry, circuit breaker with admin alert on 429/403; ytmusicapi runs in the **api** (never in the download worker), one `YTMusic` instance per thread of the catalog's thread pool (thread safety of a shared `requests.Session` is not promised); SQLite TTL cache of normalised records (search 24 h, album 7 d, artist 24 h, track 30 d, radio 1 h, playlist 10 min, not-found 1 h). Several videoIds may alias one library track (ATV preferred). Unknown ids map to not-found, not to a parse error; only canary-run parse errors raise the "layout changed" alert. Tests use `FakeMusicCatalog` and parser-level fixtures (respx cannot intercept `requests`).
- **yt-dlp** (T03c): subprocess with an argument list, from the official signed zipapp in the `/opt/ytdlp` volume (pinned seed in the image; self-update: GitHub release → `gpgv` against the pinned key → SHA-256 → smoke test → atomic symlink swap). JS runtime **Deno** (MIT), pinned by version and SHA-256, no remote components. Format `251/bestaudio[acodec=opus][protocol=https]/140/bestaudio[ext=m4a][protocol=https]` with `--fixup never`; player clients from settings (`default`, falling back to `web_embedded`); no cookies in v1, and no PO-token provider by default (superseded in part on 2026-10-13: an optional, opt-in provider, D13 below). Real download timings and the on-disk layout of 251/140 are **pending** (to be measured with the author's exception, `spikes/t03c/measure_downloads.sh`); until then the ≤ 5 s first-sound target is unconfirmed.
- **Streaming while downloading** (T03a + T03c): the worker writes the raw stream sequentially to `/staging/<job-id>/` and never rewrites it; it reports the exact `expected_size` as soon as known, both the `.part` path and the final path, and `finished`; the api opens the final path once `finished` is reported. If the final size differs from `expected_size` or the format changes on a retry, open streams are aborted. api: known size → `200` with exact `Content-Length` + `Accept-Ranges`, `206` on the growing file, `416` past the size; unknown size → chunked, Range ignored; never an estimated length; end-indexed formats only once complete; failure mid-stream → abort without a terminating chunk, retries get error 70 (HTTP 404). Listeners per in-flight job are capped (default 8 per job and 4 per API key); beyond the cap the api answers HTTP 503 with `Retry-After` (OpenSubsonic error 0 envelope). The api learns about growth from the worker's progress reports (≤ 0.5 s), not from filesystem polling (works on RWX volumes later). Client: seeks on a first play only when Media3 says seekable; read timeout 20–30 s; drops `yt:` cache entries once archived or after an incomplete first play.
- **Archive format**: never transcoded. At archive time Opus/WebM is remuxed (stream copy) to Ogg/Opus (`.opus`, taggable by mutagen) and M4A is remuxed with faststart; tags and ReplayGain are written to that new file, which is moved atomically into `/music`.
- **Spotify import** (T03d): since Spotify's February 2026 development-mode changes no app we can register reads another user's or an editorial playlist. v1 imports Spotify playlists from an uploaded file (generic CSV always; Exportify CSV with ISRC, unverified under the 2026 limits and at best own/collaborative playlists; Spotify data-export JSON) and contacts no Spotify host. Uploads are capped in size and rows, decoded as UTF-8, and import reports escape spreadsheet formulas. Import by URL through Spotify login is out of v1.
- **Canary**: scheduled on the server (worker for the yt-dlp download, api for ytmusicapi), result in the admin panel and notifications; it exercises one search, one radio, one album page and one playlist read, plus one download; the GitHub job is `workflow_dispatch` only and best effort.
- **Approved by the author on 2026-10-12** (were pending; CLAUDE.md updated): (1) GitHub releases (`api.github.com` for the latest tag, `github.com`, and the asset hosts `release-assets.githubusercontent.com` / `objects.githubusercontent.com`) for yt-dlp self-updates; (2) YouTube image hosts `yt3.googleusercontent.com`, `lh3.googleusercontent.com`, `yt3.ggpht.com`, `i.ytimg.com` for cover art of external items; (3) system packages `gpgv` (runtime) and `gnupg` (build stage only). T08 may use (1) and (3); covers of external items may use (2) — the contract's "error 70 until approval" rule for virtual cover ids is lifted for T05/T06.

### Taken in T02 (contracts and stubs, 2026-10-12)
- **Ids**: library ids are **UUIDv7** (time-ordered, compact indexes, no sequences; small generator in `ids/`). An external song gets a pending `tracks` row and its `yt:` alias at the first "keep" action (stream, request, star, playlist add, import match, scrobble), so stars, playlists and history use real foreign keys; saving a play queue stores raw ids and never starts a download. Starring `ytalbum:`/`ytartist:` answers error 0 in v1.
- **Jobs**: one job row per track (retries reuse it), which deduplicates downloads in the database; states add `cancelled`, and the ut-v1 status adds `not_requested`. Each attempt writes to its own staging directory `<job>/<attempt>`, so a worker that lost its lease can never write into the next attempt's file; the api deletes staging directories after the last listener closes. `claim` takes a job with a conditional update and a row-count check (safe with several api replicas); an expired lease with its attempts used up fails the job and its track; an admin cancel is `jobs.cancel_requested`, seen by the worker on its heartbeat. `complete` and `fail` are idempotent per lease (`last_lease_id` + stored outcome). The worker's status report tells the api the yt-dlp version and canary result (`canary_runs`), and its reply carries admin commands (`worker_commands`, each delivered once).
- **Archive registration** (fixes the first T02 draft, where the file was moved before registering): the worker builds and tags the archive file in staging, calls `register` first, moves the file into `/music` only when register reserved the path (`merged: false`), then calls `complete`, which sets the track `ready`. When register finds the same recording already in the library (`merged: true`), the file never reaches `/music`, and `complete` applies the merge in one transaction: the `yt:` alias, stars, playlist entries and history move to the existing track, and the pending track is **kept** as `status = merged` with `merged_into`. No track or job row is deleted, so a leased job is never cascaded away and `UNIQUE (kind, track_id)` stays valid.
- **Streaming contract** (2026-10-12, T02 review, implements the Checkpoint 0b decision): the worker's progress carries the exact `expectedSize` (null until known), `partPath`, `finalPath`, `finished`, `formatId`, `contentType` and `progressive`; the api switches to `finalPath` once `finished`; a size mismatch at the end, or a retry with another format or size, aborts open streams, while a retry with the same format and size continues them from the new attempt's file. `/rest` may answer only 200, 206, 404 (error 70 after a failed download), 416, 429, 501 and 503 (listener cap, `Retry-After`, error 0); contracts/errors.md has the table. Listener caps are settings (`UT_MAX_LISTENERS_PER_JOB` = 8, `UT_MAX_LISTENERS_PER_KEY` = 4).
- **Covers of external items** (YouTube image hosts approved 2026-10-12): `getCoverArt` of a virtual id fetches the catalog thumbnail over HTTPS from the exact host list only, no redirects, image types only, ≤ 5 MiB, cached in a bounded disk cache under `/data`; the worker uses Cover Art Archive first and the YouTube thumbnail as a fallback (contracts/ids.md). `getCoverArt` may ignore `size` in v1 and return the stored image (no image library is approved).
- **`/rest` details**: an unknown `/rest/<name>` answers error 0 (HTTP 200, requested format) before authentication; `HEAD` is accepted on `stream`, `download` and `getCoverArt` (no body).
- **Internal worker API**: v1 serves it on the api's single listener (8044), reachable only over the internal Docker network; a missing or unconfigured token gets the same generic 401. **T22 item**: a separate internal listener (or equivalent isolation) before any public exposure. An invalid video id is the non-retryable worker error `invalid_video_id`.
- **Extension points for parallel streams** (coordinator-owned, so Wave 1 streams never edit shared files): commands come from a registry (`commands.py`, `AREAS`) filled by each area's `cli.py` (`worker/cli.py` → `worker`, `auth/cli.py` for T04's `bootstrap-admin`, `canary/cli.py` for T19's `canary`); per-area settings live in `<area>/settings.py` (`AreaSettings`, same `UT_` prefix); `app.py` calls `install(app, services)` of each area's `web.py` (auth, library, jobs, streaming, admin, canary, and the web player `web/web.py`), where an area adds routes, middleware or state. The server canary lives in `ultimatetunes/canary/` (T19). `GET /ut/v1/server` belongs to T05.
- **Small schema rules**: the rate limiter purges by last activity (`touched_at`), so a failure count lives as long as failures keep coming within the purge window; playlist and play-queue entries are rewritten by delete-and-reinsert in one transaction (positions are part of the key); `tracks.format` accepts only `opus`, `m4a`, `mp3`, `flac`, `ogg`, and the library scan skips other files. The fake downloader writes a bundled 2 s silent Ogg/Opus file (CC0, generated with FFmpeg); API keys are redacted from logs wherever `utk_` + 43 characters appear.
- **Errors**: `/rest` errors are HTTP 200 with a failed envelope, except the statuses listed in `contracts/errors.md` (429 rate limit, 501 stubs, and on binary endpoints 206/416 for ranges, 404 for error 70 after a failed download, 503 for the listener cap); ut-v1 and the worker API use RFC 9457 problems with stable codes; one mapping table in `errors.py` per `contracts/errors.md`. Token auth (`t`/`s`) answers 42 per this spec (OpenSubsonic suggests 41); the Android client treats both alike, and T19 checks a third-party client.
- **Wire conventions**: camelCase JSON in every API; API keys are `utk_` + 43 base64url characters, stored as SHA-256; timestamps are fixed-width `YYYY-MM-DDTHH:MM:SS.mmmZ`; portable SQL uses `?` placeholders (the PostgreSQL driver converts them).
- **Low RAM**: the cache and the rate-limit state live in SQLite tables (`cache_entries`, `rate_limit_buckets`), not in process memory.
- **Server layout**: shared interfaces live in `ultimatetunes/core/`; an interface owned by one stream lives in that stream's package; each `/rest` endpoint is registered in its owner's route file (`.claude/ownership.json`); authentication is a pluggable `Authenticator` that T04 replaces. `UT_FAKE_YOUTUBE=1` switches on the fake catalog and downloader (test stack).
- **Android client**: OkHttp interceptor adds credentials at send time and only for the configured server (`apiKey` on `/rest`, `X-Api-Key` on `/ut/v1`); stream, download and cover URLs carry no key, so Media3 and Coil load them through the same OkHttp client (T17). The fake server in `:core:api` test fixtures uses copies of the contract examples kept in sync by a drift test.
- **Imports**: `POST /ut/v1/imports` takes a YouTube Music/YouTube URL (JSON) or an uploaded file (multipart: generic CSV, Exportify CSV, Spotify data-export JSON; ≤ 1 MiB, ≤ 5000 rows, UTF-8); capability `fileImport` replaces `spotifyImport`.

### Taken before Wave 1 (2026-10-12)
- **Dependencies added in one coordinator PR** so parallel streams never edit shared build files. Server: argon2-cffi (MIT), ytmusicapi (MIT; pulls `requests`, Apache-2.0), mutagen (GPL-2.0-or-later), jinja2, itsdangerous (BSD-3-Clause), python-multipart (Apache-2.0); dev respx (BSD-3-Clause). yt-dlp is not a Python dependency (zipapp subprocess, T03c). Android: Coil 3 (compose, network-okhttp), palette, DataStore preferences, Media3 (exoplayer, session, datasource-okhttp; `:core:player` depends on `:core:api` so one OkHttp version ships). Also **navigation-compose** and **hilt-navigation-compose** (Apache-2.0), approved by the author on 2026-10-12. DataStore bundles protobuf, so licensee also allows BSD-3-Clause.
- **Offline playlists in sync and export to the phone** (author, 2026-10-12): RF-12 extended (playlists/albums marked offline stay in sync) and new RF-14 (export of fully available tracks to a user-picked folder via SAF, original format and tags). Implemented in T17 (download/sync engine) and T18 (UI and export).

### Taken in T04 (users, keys and auth, 2026-10-12)
- **Passwords**: Argon2id with 19 MiB memory, t = 2, p = 1 (the OWASP minimum, chosen for the RAM budget). Passwords are at least 12 characters. Usernames are lower-cased and match `[a-z0-9][a-z0-9._-]{0,63}`.
- **Lockout**: a valid API key is never refused because its IP is locked out (one stale device behind a shared home IP must not lock the household out). Defaults: 10 failures per IP, 5 per username, 15 minutes.
- **Key last use** is written at most once a minute per key and IP.
- **Disabled user** → error 50.
- **`POST /ut/v1/keys`** answers with `Cache-Control: no-store`; its body is capped at 16 KiB.

### Taken in Wave 1 — T04 users, keys and auth (#22, 2026-10-12)
- A stale or revoked key, or a key of a disabled user, does not count towards the IP lockout.
- Password checks need the client IP: a proxy in front of the api must forward it.
- OpenSubsonic auth errors carry `helpUrl` pointing to the README `#api-keys` section.

### Taken in Wave 1 — T05 library and browsing (#35, 2026-10-12)
- `unstar` of a `yt:` id never materializes (overrides the contract text: removing a star must not start a download).
- `tokenInfo` answers only with `apiKey` auth; `u` + `p` gets error 44.
- `scrobble` with `submission=false` is stored with `submission = 0`, counts nothing and never materializes.
- A star `id` that is a library album or artist UUID stars that album or artist (legacy clients).
- Another user's private playlist is error 70 (not revealed); changing someone else's public one is error 50.
- The scan never deletes a track whose file is gone (counted as `missing`); removal is an admin action (T15).
- The scan skips paths reserved by an unfinished job (`jobs.library_path`); the archive flow registers them.
- Rescans re-read only files whose size changed (no mtime column); after an in-place tag edit that keeps the size, run `ultimatetunes scan-library --full`.
- Covers: only `image/jpeg`, `image/png`, `image/webp`, `image/gif` are served or cached (`image/jpg` → jpeg), with `X-Content-Type-Options: nosniff`.
- `/ut/v1/server` reports `streamingWhileDownloading` true only once a real `PendingStreams` is wired (T16).

### Taken in Wave 1 — T06 search (#19, 2026-10-12)
- The catalog's `requests.Session` allows only `https://music.youtube.com`, sets the 5 s timeout and raises HTTP errors before ytmusicapi parses them; unknown ids are not-found, never a parse error.
- The circuit breaker opens on 429/403/gated for 5 min, doubling up to 1 h; its state lives in the cache (stateless api) and `breaker_state()` feeds the panel.
- Library results come first; external results are deduplicated through id resolution (archived videos show as the library song; pending/failed keep `yt:` and `libraryState`). A failing catalog never fails search; an empty `search3` query pages the library only.
- Text matching uses `search.text.normalize` (NFKD, accents stripped, casefold, punctuation → space); every writer of `*_norm` columns uses it.
- External albums in `search3` carry `songCount`/`duration` 0 (search gives no track count).

### Taken in Wave 1 — T07 radio and Listen Now (#28, #39, 2026-10-12)
- A radio seed is a library UUID (merged tracks followed) or a `yt:` id; `getSimilarSongs2` also accepts `ytartist:` and library artist ids and starts from the artist's first top song (a library artist without a channel uses its first library song).
- A library song seeds with its `yt_video_id`, else its oldest `yt:` alias; a song that never came from YouTube Music uses the first catalog song found for "title artist".
- `getSimilarSongs2` leaves the song seed out; `count` defaults to 50, is capped at 100, and `count=0` does not call the catalog.
- Listing a radio materializes nothing. `UT_RADIO=false` makes radio answer `FeatureDisabled`. The catalog guard returns at most 50 songs per seed.
- A `search3` query over 200 characters is `InvalidParameter` (error 0). Thumbnails are accepted only when the netloc is exactly an approved host (no port, no userinfo).
- `CatalogClientError` marks refused requests and is never retried.
- Listen Now is library-only. `favouriteRadios` holds starred songs only (as the contract says); the Android Radio tab adds one station per `mostPlayed` song after them.

### Taken in Wave 1 — T08 download worker (#24, 2026-10-12)
- Retry backoff 30 s / 2 min / 8 min ±20 %; `expectedSize` and `formatId` are fixed per attempt; the previous attempt's format and size are kept (migration `0300`) so T16 knows whether a retry changes the stream.
- A new request re-queues a `failed`/`cancelled` job with attempts reset (one track, one job per video). Request bodies are parsed only after the token check, so callers without the token always get 401.
- Worker: lease lost → work dropped without `fail`; SIGTERM → retryable release; bot wall → claiming paused 30 min, doubling to 4 h; `extractor_error` → yt-dlp update at most hourly; status report every 5 min.
- yt-dlp self-update follows hops by hand from the approved hosts only, with size caps, `gpgv` VALIDSIG against the pinned fingerprint, SHA-256, a `--version` smoke test and an atomic symlink swap; two previous releases are kept.

### Taken in Wave 1 — T09 tagging and archive (#37, 2026-10-12)
- Archive: Opus is remuxed to Ogg/Opus `.opus`, AAC to M4A with `+faststart`; source metadata dropped, `+bitexact`; any other codec is `tagging_failed`, not retried. ffmpeg/ffprobe run with `-nostdin`, `-protocol_whitelist file`, `file:<absolute path>` inputs, a minimal env and a timeout.
- ReplayGain 2.0 at -18 LUFS from ffmpeg `ebur128`; silence gets 0 dB, gains clamped to ±51 dB; album gain from the album's files concatenated (best effort); Opus files also get `R128_*` tags. Library files are retagged through a temporary copy and a rename.
- MusicBrainz: 1 req/s, User-Agent with version and repo URL, no redirects, answers ≤ 2 MiB, one retry on 503/429 (`Retry-After` ≤ 10 s). Score = 0.45 title + 0.35 artist + 0.20 duration; below `UT_MUSICBRAINZ_MIN_SCORE` (0.85) the YT Music data is kept and `needs_review` is set. Query and comparison of several artists and "feat." titles: see the 2026-10-13 MusicBrainz matching decision below (D14). A lookup failure never fails a job.
- Covers: CAA release front, then release-group front, then the YouTube thumbnail; CAA redirects followed by hand (HTTPS, `coverartarchive.org`/`archive.org`/`*.archive.org`, ≤ 3 hops); JPEG body ≤ 5 MiB; any failure means "no cover"; an existing `cover.jpg` is kept.
- Layout `AlbumArtist/Album/NN - Title.ext` (`D-NN` on later discs, `Title.ext` without a number); names NFKC, `/\:*?"<>|` → `_`, control/invisible characters dropped, leading/trailing dots and spaces stripped, Windows reserved names prefixed with `_`, ≤ 180 bytes per component. A `conflict` retries once with ` (<videoId>)`.
- **Adoption**: a file already at `libraryPath` that no track owns and whose SHA-256 matches is the job's own file from a crashed attempt; register adopts it and the worker skips the move (contracts updated).

### Taken in Wave 1 — T10 lyrics (#18, 2026-10-12)
- A `yt:` id without an alias answers an empty list and LRCLIB is not asked.
- LRC `[offset:]` and the row's `offset_ms` are applied to `start`, so `offset` is never sent.
- LRCLIB failure with nothing stored → error 0 (`UpstreamUnavailable`); with a stale negative entry → empty list.
- Settings: `UT_LYRICS_TIMEOUT_S`, `UT_LYRICS_RATE_PER_S`, `UT_LYRICS_BURST`, `UT_LYRICS_NOT_FOUND_RETRY_DAYS`, `UT_LYRICS_FAILURE_BACKOFF_S`.

### Taken in Wave 1 — T11 playlist import (#31, 2026-10-12)
- Imports run as response background tasks through `InFlight`; all state is in the database, and an active import untouched for 120 s resumes when its owner reads it.
- Matching is text-only (title, artists, album) with a hard ±3 s duration rule and a 0.7 threshold; ATV wins ties; ISRC is recorded only.
- A Spotify data-export JSON with several playlists needs `name` (case-insensitive) to pick one; the same field names the result.
- All imports share one catalog bucket (0.5 req/s, burst 1) and a user runs at most 3 at once; catalog outages pause and resume instead of failing items.
- A matched item whose track is not archived yet shows as the `yt:` external item with its `libraryState`.

### Taken in Wave 1 — T12 Android shell (#23, 2026-10-12)
- Own design system (warm red accent, system sans-serif, local vector icons shaped after Material icons); no Apple assets or fonts.
- Connect keeps the server only after `GET /ut/v1/server` and `GET /ut/v1/me` succeed; https by default.
- Coil loads covers through the `@TunesHttpClient` OkHttp client (cover URLs carry no key).

### Taken in Wave 1 — T13 Android screens (#33, 2026-10-12)
- Playback settings (cache size, offline only, Wi-Fi-only downloads) live in a Preferences DataStore (`PlaybackSettingsStore`); T17 reads it, and replaces the empty `OfflineLibrary` binding with Media3 downloads.
- "Add to playlist", long-press menus, starring from rows and capability-based hiding of import kinds are T18.

### Taken in Wave 1 — T14 release pipeline (#21, 2026-10-12)
- `release.yml` has a dry-run mode (manual dispatch and PRs touching the pipeline, release tools or `VERSION`) that builds everything, arm64 image included, and publishes nothing; only a tag push publishes.
- The image is pushed only after the APK built and was verified (signature, `versionName`, `versionCode`); release notes come from CHANGELOG via `tools/release-notes.sh`.

### Taken in Wave 1 — T15 admin panel (#38, 2026-10-12)
- Admin sessions are stateless itsdangerous-signed cookies with a password-hash fingerprint, expiry from the injected clock and the CSRF token inside; login uses a signed double-submit token.
- Default admin allowlist: loopback, RFC 1918, link-local, IPv6 ULA, Tailscale `100.64.0.0/10` and `fd7a:115c:a1e0::/48`; anything else gets 403 first.
- Notification target (ntfy or webhook, https, no credentials, never loopback, link-local, unspecified, multicast or `localhost`, checked on save and on every send) and the sweep cursor live in the `settings` table; the cursor moves by compare-and-set, so one replica sends.
- QR: own encoder (byte mode, level M, versions 1–10), payload per `contracts/ids.md`, server URL https only and ≤ 120 characters.
- Library deletes: rows first, files best effort; refused while a lease is held.

### Taken in Wave 1 — track registration (#42, integration, 2026-10-12)
- `registerTrack` merges into a `ready` track with the same MusicBrainz recording id (`merged: true`, applied by `complete`); otherwise artist and album are reused by MusicBrainz id, else YouTube id, else normalized name.
- The staging file must be inside the job's `stagingDir` and have the registered size; the answer carries the album state so the worker can compute album gain.
- `jobs.placed_path`/`placed_sha256` (migration `0301`) survive a release, so a crashed attempt is adopted on retry and a retry that merges or picks another path deletes the earlier file if still unowned and unchanged.

### Taken in Wave 1 — demo mode (#36, 2026-10-12)
- Debug builds only: "Try the demo" starts a MockWebServer on `127.0.0.1` inside the app with an invented library, reached through the real `TunesApi` stack and Connect checks; release builds have only an optional `DemoServer` hook bound to nothing.

### Taken by the coordinator in Wave 1 (2026-10-12)
- **GitHub Actions are disabled**: the author wants no spending and everything lives on the homelab. The workflows stay in the repo.
- (Superseded by the update below.) A merge needs `tools/ci-local.sh` green on the PR branch merged with master (it includes the Conventional Commit PR-title check, same rule as `pr-title.yml`), plus the independent review without blocking findings.
- No publishing to GHCR or GitHub Releases and no release tags until the author decides otherwise; releases are built locally (RELEASING.md).
- Open option: self-hosted GitHub Actions runners on the homelab.
- *Update 2026-10-12:* the repo is now **public** (gitleaks over every commit of every branch was clean first), so GitHub-hosted minutes are free: CI, PR title and Dependabot verification are on again and a merge needs GitHub CI green plus the independent review. `tools/ci-local.sh` stays as the local gate. Release and Nightly stay disabled; publishing stays paused.
- *Update 2026-10-13 (1.0.0-rc.2):* at the author's request the **Release** workflow is enabled and the first release candidate is published: signed APK as a GitHub pre-release and the server image on GHCR (public repo, no cost). Tags are pushed by the author, or by Claude when the author asks. Nightly stays disabled.

### Taken in Wave 2 — T16 streaming while downloading (#44, 2026-10-12)
- A **retryable** failure (job back to `queued`) keeps open streams waiting for the retry: the same format and size continue, others are cut. Only a final failure (`failed`/`cancelled`) cuts them at once; the client's read timeout decides how long to wait.
- Chunked listeners follow any same-format retry and are aborted if they already passed the final length; any listener is aborted if the file grows past its announced size.
- **HEAD** of a `yt:` id with no running download answers `200`, `Accept-Ranges: none` and no length; it never starts a download.
- No server-side timeout before the first byte; a client that hangs up is noticed within 1 s and frees its listener slot. Caps: 8 listeners per job, 4 per API key; past a cap HTTP 503 with `Retry-After`.
- Growth is learned from the job row (worker reports wake the process, else polling), never from the filesystem.
- Settings: `UT_LISTENER_RETRY_AFTER_S` (5), `UT_STREAM_POLL_INTERVAL_S` (0.25, ≤ 0.5), `UT_STAGING_SWEEP_INTERVAL_S` (300; 0 = off).

### Taken in Wave 2 — T17 Android playback (#47, 2026-10-12)
- Playback reads offline downloads first (read-only, separate never-evicted cache), then the play cache (`SimpleCache` with an LRU evictor resized live, 2 GB default).
- ReplayGain only attenuates (track gain, album gain when a queue neighbour is from the same album, peak-limited), applied as player volume.
- First plays of unknown size are not cached by Media3; `yt:` cache entries are dropped once archived or after an incomplete first play.
- Untrusted media controllers may control playback but not change the queue; items without a server resolve to an offline-only URI.
- The server URL and API key are sealed with an AES-256-GCM Android Keystore key and restored at start.

### Taken in Wave 2 — T18 Android features (#50, 2026-10-12)
- **Export layout** = the server's library layout and sanitizer (`D-NN` from disc 2, `Untitled`/`Unknown Artist`/`Unknown Album` stand-ins); two songs of one export never share a file (a later one gets ` (<library id>)`).
- **Export never deletes or overwrites** anything it did not write in that call: it writes a temporary `.ut-export-*.part` and renames it; a taken name is skipped as "already in the folder" (same size: an earlier export, left as is). Only library songs fully on the phone are exported, never `yt:`-keyed bytes. One export at a time.
- **History**: a song counts as played after half of it or 4 min (songs over 30 s), position-based; a song repeated in place is not counted again.
- **Queue sync**: another device's queue is restored only into an empty player and only after `getPlayQueue` succeeded; an empty queue is never saved.

### Taken in Wave 2 — T19 contract tests and canary (#45, #49, 2026-10-12)
- Contract tests run schemathesis against the real app, authenticated and anonymous, plus a real-data replay of every OpenSubsonic endpoint in JSON and XML.
- Canary: catalog checks on the api (daily or on an admin `run_canary`, one replica by compare-and-set) and a download check of one fixed CC BY 4.0 track on the worker (Kevin MacLeod, "Sauropod Spotting", `6pEWHaIhxOg`; changeable with `UT_CANARY_*`), downloaded into `/staging/canary/`, always deleted, never archived; failures go through the admin notification sweep.
- With `UT_FAKE_YOUTUBE`, lyrics come from a fake LRCLIB too, so the test stack makes no outbound call.

### Taken in Wave 2 — track request and status (#49, integration, 2026-10-12)
- `POST /ut/v1/tracks/{id}/request` checks a `yt:` id in the catalog before writing, enqueues at `keep` (or `prefetch`) priority, answers 202 (200 when `ready`); a failed or cancelled track is queued again with its attempts reset.
- `GET /ut/v1/tracks/{id}/status`: `not_requested` for an unknown `yt:` id or a pending track without a job, `ready` for a library file without a job, else the job's state; `streamable` comes from the streaming state machine.

### Taken by the author — full player transition (#64, 2026-10-12)
- The author found the shared-element close animation ugly on the Pixel 8 (the mini player expanded and the tabs reflowed under the closing player). The full player now slides fully up and down (320 ms) as a sheet that follows the finger; past 120 dp or on a fast flick it closes. The mini player keeps its place while the full player is open, which is hidden from TalkBack. The shared-element artwork transition is dropped (§5 updated); the author accepted trying it and changing it again if it does not convince.

### Taken by the coordinator — web player (#66, 2026-10-12)
1. **Web player at `/` and `/web`**, served by the api (RF-15). It uses Jinja, the admin panel's vendored HTMX (served again at `/web/static/htmx.min.js`) and its own small scripts (`theme.js`, `player.js`) and stylesheet, with no build step, CDN or new dependency. The admin panel's public landing page at `/` is removed (no contract defined it). With `UT_WEB_ENABLED=false`, `/` only says the server runs and `/web` answers 404. No public page links to `/admin`: the panel's address is not advertised to visitors (author's request, 2026-10-13).
2. **Sessions** reuse the admin machinery (itsdangerous `SessionCodec`) with the web player's own salts and a per-user epoch (`web.session_epoch.<user id>` in `settings`), for any role.
   - The cookie `ut_web_session` is `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`.
   - Its lifetime is `UT_WEB_SESSION_TTL_S`: 7 days by default, at most 30.
   - It is signed with `UT_ADMIN_SESSION_SECRET`.
   - Signing out ends every web session of the user, copies included; a new password ends them too (and re-signs-in the browser that changed it).
3. **Sign-in** (`POST /web/login`) is `AuthService.verify_password(trusted=trusted_origin(request))`, exactly like `POST /ut/v1/keys`: rate limit, and per-IP and split per-username lockout. It is not limited to the admin networks. It is audited as `web.login`/`web.logout`.
4. **CSRF** on every change: the session token as form field `csrf` or header `X-CSRF-Token` (HTMX, `player.js`), plus `Sec-Fetch-Site`. The login form uses a double-submit cookie.
5. **Headers** on `/` and `/web/*`:
   - CSP: `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'`;
   - `no-store` on pages, `nosniff`, `DENY`, `no-referrer`, COOP/CORP/COEP;
   - a 64 KiB body cap.
   - There is no inline script or style and no `innerHTML`. HTMX keeps no history snapshots, and a history miss asks the server.
6. **Media and uploads**:
   - Audio and covers go through `/web/stream/{id}` and `/web/cover/{id}`, which are the OpenSubsonic handlers behind the session cookie (Range, streaming while downloading). No API key is ever in a URL or in the browser.
   - `/web/imports/file` takes up to the imports API's cap.
   - The language choice is a cookie `ut_web_lang`. The theme and the volume live in `localStorage` (display preferences only).
   - The web player never creates API keys (a key is shown once and must not land in a page); it lists and revokes the user's own.
7. **Same rules as every client**: every page and action calls the OpenSubsonic handler, or the `/ut/v1` imports/tracks handler, in-process as the signed-in user. Ownership, stars, "keep", the per-user search bucket, the catalog budget (`set_caller`), the download gates and the listener caps all apply. Each user also gets the request rate of one API key (`web:user:<id>`). Playlist "move" rewrites the playlist (`createPlaylist` with `playlistId`), since OpenSubsonic has no move.
8. **Admin panel**: `AdminGate` covers `/admin` only. The proxies route `/` and `/web` through the client routers (`deploy/`); Authelia in front of the web player is optional.

### Taken in Wave 3 — T20 end-to-end (#52, 2026-10-12)
- The e2e suite runs on a fresh stack with its own Compose project (`ut-e2e`), image tag and port (`tools/e2e/run.sh`, overrides in `tools/e2e/compose.e2e.yaml`); `server/compose.test.yaml` is untouched. The server half runs in the manual/labelled `e2e` workflow; the device half (`adb reverse`, opt-in instrumentation arguments) is local only.
- The fake downloader can be slowed for it (`UT_FAKE_DOWNLOAD_CHUNKS`/`UT_FAKE_DOWNLOAD_DELAY_S`, defaults unchanged). The e2e pytest runs without `--cov` (the code under test runs in the containers).

### Taken in Wave 3 — T21 measurements (#57, 2026-10-12)
- An external first sound is measured as server time to first audio byte plus the client, with the download modelled at T03c's 1.8 s to first byte and 1 MB/s, until real downloads are allowed. Results in §6 and `docs/measurements.md`; the two regressions found became #54 and #55 (fixed by #58 and #59).

### Taken in Wave 3 — T22 hardening and public access (#56, 2026-10-12)
- **Two listeners, one app**: clients on 8044; 8045 (`UT_INTERNAL_PORT`, never published) serves only `/internal/v1` and `/healthz`; 8044 serves clients and `/healthz` and answers 404 for `/internal/*`. The worker's default `UT_API_URL` is `http://api:8045`. `UT_INTERNAL_HOST` can bind 8045 to the api's address on the internal network only (the deployment examples do).
- **Trusted proxies**: `X-Forwarded-For` is read (from the right) only from `UT_TRUSTED_PROXIES`, default empty. A request with forwarding headers from an untrusted peer, and any Tailscale Funnel request, is refused by `/admin`. The resolved address feeds the admin allowlist, `/readyz`, per-IP limits and lockout, and the audit log. `tailscale serve` adds `X-Forwarded-For`, so the panel needs `UT_TRUSTED_PROXIES` set to the Docker gateway behind it (`deploy/README.md`).
- `/readyz` returns its `checks` detail only to loopback and the admin allowlist, never through an untrusted proxy.
- Admin logout bumps a per-user session epoch (`admin.session_epoch.<user id>` in `settings`), so copied cookies stop working.
- The api re-hashes the staging file on `registerTrack` and refuses a mismatch.
- Per-user external-search bucket: `UT_SEARCH_USER_RATE_PER_S` 0.2, `UT_SEARCH_USER_BURST` 20; past it the answer is library-only. Api housekeeping every `UT_HOUSEKEEPING_INTERVAL_S` (600) purges expired cache entries and idle rate-limit buckets and trims the cache to `UT_CACHE_MAX_ENTRIES` (200,000) / `UT_CACHE_MAX_BYTES` (256 MiB), oldest first.
- Api-wide body cap `UT_MAX_BODY_BYTES` (4 MiB, problem+json 413); `nosniff` on every answer. `httpx`/`httpcore` log at WARNING or above (outbound URLs can carry secrets).
- ZAP baseline (`tools/zap-baseline.sh`, image pinned by digest; manual `zap.yml`) against the test stack: 0 FAIL, 0 WARN; ignored rules only with a written reason.

### Taken in Wave 3 — T23 identity and store assets (#53, 2026-10-12)
- Our own eighth-note icon (GPL) is the launcher icon (adaptive + monochrome), in-app logo and artwork placeholder. Store screenshots come from `ScreenshotsTest` against the debug demo server (invented music), opt-in (`-e screenshots true`), via `fastlane/screenshots.sh`.
- The store listing and README do not name "Apple Music" (trademark). The demo audio is FLAC with each song's real length, so demo songs can be exported.
- Export reuses an existing folder whatever its case (an exact match wins), and the first export into a folder deletes our stale `.ut-export-<uuid>.part` files there. A stopped export ends between two songs and is resumed later.

### Taken in Wave 3 — database statistics (#58, 2026-10-12)
- The SQLite driver keeps planner statistics fresh with `PRAGMA optimize` (PostgreSQL: `ANALYZE`): `migrate` ends with it, and the api's writer refreshes on first use, every 1000 write transactions and on close (which covers `scan-library` and every CLI). Stale readers are replaced by new connections after a refresh. A failed refresh is logged, never fails a request.

### Taken in Wave 3 — long-poll job claims (#59, 2026-10-12)
- Idle workers long-poll the claim (`ClaimRequest.waitSeconds`, 0–30; worker `UT_CLAIM_WAIT_S` 8, below Docker's 10 s stop grace). The api holds an empty claim up to `UT_CLAIM_MAX_WAIT_S` (25; 0 turns it off), woken by an in-process `JobSignal` and re-checking the database every `UT_CLAIM_POLL_S` (1), which keeps it correct with several replicas; then 204 with `Retry-After: 0`.
- Accepted as a coordinator integration exception to the frozen internal worker contract (backward compatible). Known limit: held claims are not capped (internal, token-protected, one per worker process).

### Taken in Wave 3 — exposure hardening (#61, 2026-10-12)
- The per-username password lockout is split by origin: `auth:user:<name>` for the admin networks (allowlist minus the worker's networks, not through an untrusted proxy or Funnel; `core.forwarded.from_trusted_network`, also used by `AdminGate`) and `auth:user-out:<name>` for everything else. Outside failures never lock trusted logins.
- uvicorn limits: `UT_LIMIT_CONCURRENCY` 128, `UT_INTERNAL_LIMIT_CONCURRENCY` 32, `UT_KEEPALIVE_TIMEOUT_S` 5, `UT_BACKLOG` 256, `UT_MAX_HEADER_BYTES` 16 KiB, h11. uvicorn has no request-header timeout, so public exposure always has a reverse proxy in front. `compose.yaml` sets memory, CPU and file limits.
- The worker's `egress` network is pinned (`UT_EGRESS_SUBNET`, default 10.213.45.0/24, bridge `ut-egress`) and listed in `UT_WORKER_NETWORKS`; host firewall rules for it are in `deploy/README.md`.
- The Caddy `/admin` rule uses explicit LAN and tailnet ranges, never `private_ranges` or loopback; the proxy examples do not route `/readyz` or `/internal`. `/readyz` caches its result for 5 s per process.
- The worker token has at least 32 characters. The bootstrap password may come from the `ut_bootstrap_admin_password` secret, and a warning is logged while it lingers. New SQLite files are created 0600 (directory 0700).
- Notification targets are resolved right before each send; loopback, link-local, unspecified and multicast addresses are refused (LAN allowed).

### Taken in Wave 3 — download limits, catalog budget and auth brakes (#63, #65, 2026-10-12)
- Download limits apply to every requester, admins included (requests without a user skip only the per-user quotas): `UT_MAX_TRACK_DURATION_S` 1800 (refused before anything is materialized; hidden from radios unless archived; unknown durations left to yt-dlp's strict `duration<=N` filter, which also refuses live streams), `UT_MAX_DOWNLOAD_BYTES` 200 MiB per file, `UT_MAX_QUEUED_JOBS_PER_USER` 200, `UT_MAX_DOWNLOAD_BYTES_PER_DAY_PER_USER` 5 GiB (rolling 24 h, charged per downloaded byte to the job's requester at that moment, migration 0700), `UT_MIN_FREE_BYTES` 2 GiB on either store (enqueue refused, claims paused, resumed above 1.1×, shown in the `/readyz` detail and notified). At most 50 downloads per keep request. Refusals map to existing errors (`InvalidParameter`, `RateLimited` + `Retry-After`, `PayloadTooLarge`); import runs pause on them without failing items.
- A queued job whose requester is over the daily allowance moves to the next requester who has allowance and is under the queued-jobs cap (#65).
- Per-user catalog budget `catalog:user:<id>` (`UT_CATALOG_USER_RATE_PER_S` 0.5, `UT_CATALOG_USER_BURST` 60) on cache misses and uncached cover images; searches keep their own bucket; imports are not charged to it.
- Auth: IPv6 counted per /64; `UT_AUTH_ARGON2_CONCURRENCY` 2 concurrent Argon2 checks per process (wait `UT_AUTH_ARGON2_WAIT_S` 2 s, then 429); global budget `UT_AUTH_MAX_FAILURES_GLOBAL_PER_MIN` 100 → `UT_AUTH_GLOBAL_LOCKOUT_S` 60 lock of outside password checks and unknown keys; valid keys and trusted-network password checks are never refused by it.

### Taken by the coordinator — architecture and deployment examples (#67, #68, 2026-10-12)
- `docs/architecture.md` is the reference for containers, networks and every connection; the internal worker contract's `servers` names `http://api:8045` (docs-only contract change).
- **Cloudflare Tunnel is a supported edge** (`deploy/traefik-cloudflared/`) only when cloudflared and Traefik have pinned addresses, Traefik trusts `X-Forwarded-For` only from cloudflared, `UT_TRUSTED_PROXIES` lists exactly those two /32s and `UT_ADMIN_ALLOWED_NETWORKS` excludes the Docker and tunnel ranges. An unpinned or untrusted tunnel stays unsupported.
- In that example `/admin` is LAN-only plus Authelia (`trustForwardHeader: false`, since cloudflared carries every Internet request); `POST /ut/v1/keys` and `/readyz` are LAN-only; `/internal` and `/healthz` are not routed.

### Taken by the coordinator — authenticated notifications (#69, 2026-10-12)
- ntfy/webhook credentials (`UT_NOTIFY_TOKEN` → Bearer, or `UT_NOTIFY_USERNAME` + `UT_NOTIFY_PASSWORD` → Basic) come only from env vars or Docker secrets: the dependency set has no AEAD, so they are never stored in the database; the panel only shows whether they are set. Revisit if an AEAD library is approved.
- They are bound to `UT_NOTIFY_HOST` (required with them) and sent only on the one non-redirected request to a matching https target; other hosts get the message without credentials and a warning. A 401/403 is reported as rejected credentials; the audit log records only the credential kind and outcome.
- Every settings class hides refused input in validation errors (`hide_input_in_errors`).

### Taken by the coordinator — Android polish (#70, 2026-10-12)
- One app-wide snackbar host, above the mini player and tab bar, or at the top of the open full player. Re-tapping the open tab pops it to its first screen. A dark window theme in dark mode (no white flash at launch).
- No R8/ProGuard rules beyond the libraries' consumer rules: a minified build was checked on the Pixel 8 (cold start 260 ms).

### Taken by the coordinator — admin panel polish (#71, 2026-10-12)
- Admin lists that grow (downloads queue, needs review, audit log) are paged at 50 rows with `?page=` (ASCII digits, at most 1000) and keep their filters; the audit log is filterable by action and actor (only known values accepted). Migration `0701_admin_list_indexes.sql` indexes `audit_log(action, occurred_at)` and `jobs(updated_at)`.
- "Mark reviewed" (`POST /admin/library/tracks/{item_id}/reviewed`, audited `track.review`) clears `needs_review`; deleting stays the other way out. No tag editing in the panel.
- Destructive panel actions ask for confirmation through `data-confirm` and the first-party `/admin/static/admin.js` (no inline scripts, CSP unchanged); without JavaScript they still work.
- `RateLimiter` gains a read-only `peek(key, limit)`, so the panel shows per-user catalog/search budgets and the shared YouTube Music budget without spending them.
- `docs/configuration.md` is the reference of every `UT_*` setting, enforced by a test against the settings classes and the compose files; `docs/admin-guide.md` describes every panel page.

### Taken by the coordinator — final audit fixes (#74, 2026-10-12)
- Outside sign-in failures per username cost a growing delay instead of a lockout: `UT_AUTH_OUTSIDE_BACKOFF_BASE_S` (1 s) doubling up to `UT_AUTH_OUTSIDE_BACKOFF_MAX_S` (300 s), reset by a success, reserved before the password hash is checked. The inside counter keeps the lockout (`UT_AUTH_MAX_FAILURES_PER_USER`, `UT_AUTH_LOCKOUT_S`); the global failure budget only holds back unknown keys and usernames with outside failures on record. Known trade-off: an outsider who knows a username can slow that user's outside password sign-in for as long as the attack lasts (sessions, API keys and LAN/Tailscale sign-in are unaffected). With several api replicas, the reservation will need a row lock or compare-and-set.
- The edge examples add a strict per-client limit on `POST /web/login` and count IPv6 per /64. Forwarded chains are walked from the right and stop at the first untrusted hop, whatever their length.
- ffmpeg/ffprobe inputs: the demuxer is forced from the extension (webm, opus, ogg, m4a, mp4 only), with format, codec and protocol whitelists.
- "Sign out every device" revokes every key and bumps both session epochs (audited `user.sign_out_all`): in the web player for one's own account, in the panel for any user.
- The api's `/tmp` is a `noexec,nosuid` 64 MiB tmpfs; the worker's stays exec until verified with yt-dlp and its JS runtime. HEAD never starts a download.
- Accepted residual risks (SECURITY.md): the panel and the web player share one origin; containers on the proxy network must be trusted; the public client address relies on the edge's `X-Forwarded-For`.

### Taken by the coordinator — QR connect through the camera app (#75, 2026-10-13)
- The app does not scan QR codes itself: the phone's camera app (or Lens) opens the `ultimatetunes://connect` link from the panel's QR code and the app handles it. No camera or barcode library (ML Kit needs Google Play services; ZXing is not approved).
- A connect link is parsed strictly and always needs an explicit confirmation showing the host and the full URL; Connect works only after the dialog has been shown unchanged for 1 s. It connects only after `/ut/v1/server` and `/ut/v1/me` succeed, and the previous connection is restored unless both succeed. `http` in a link follows the same cleartext policy as manual entry. Links replayed from Recents are ignored, and the key never goes into an intent, a `Bundle` or a log.
- While a link dialog is showing, further links are dropped (the dialog says so): the first link wins. Known trade-off: during the key check of a replacement the player queue is reset as on any reconnect; an unreachable server or one that is not UltimateTunes never touches the current connection.

### Taken by the coordinator — optional PO token provider (D13, 2026-10-13)
- Approved by the author on 2026-10-13: **bgutil-ytdlp-pot-provider** (GPL-3.0) as an **opt-in** answer to YouTube's "Sign in to confirm you're not a bot" wall. This supersedes the "no PO-token provider in v1" part of the T03c decision; still no cookies and no accounts.
- Server side: upstream's HTTP server image as the `pot-provider` service in `server/compose.yaml`, Compose profile `pot` (off by default), pinned to **2.0.0 by digest** (the newest release at least two weeks old; 1.3.2 and older carry the GHSA-qpv9-8xfj-xx9m RCE, 2.0.1/2.0.2 were younger than two weeks and only refresh the server's npm lockfiles). Hardened like our services (image's non-root user, read-only root, `noexec` `/tmp`, no capabilities, `no-new-privileges`, memory/CPU/PID/file limits, nothing published). It listens only on its pinned address on a new `internal: true` network `pot` (`UT_POT_SUBNET`, `UT_POT_PROVIDER_ADDRESS`) that only the worker shares, under the alias `bgutil` (the service name may resolve to its `egress` address), and leaves through the worker's `egress`. It contacts `www.youtube.com`, `www.google.com` (the BotGuard interpreter script) and `jnn-pa.googleapis.com` (integrity tokens), observed through a logging proxy; CLAUDE.md lists them.
- Client side: the release's plugin zip, pinned by version and SHA-256 (no upstream checksum: its files were compared with the tag's sources), is fetched at build time. `server/docker/check_plugin.py` requires exactly the reviewed entry list and the pinned version, then writes `/opt/ytdlp-plugins/bgutil-http.zip` (read-only) with only the shared base module and the HTTP provider: the script provider, which would start a JavaScript runtime itself, is never installed. The worker's allowed hosts do not grow. A test keeps the plugin and the image on one version.
- `UT_YTDLP_POT_PROVIDER_URL` (unset: yt-dlp keeps `--no-plugin-dirs` and loads nothing, exactly as before). When set, it must be a bare `http(s)://host[:port]` whose host is a single-label service name starting with a letter or an address in an explicit allowlist (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `::1` or `fc00::/7`; no IPv6 zone ids, no IPv4-mapped or 6to4 forms, no port 0), rebuilt canonically and checked again where the argv is built, so it cannot carry `,`, `;` or `%` into `--extractor-args`; anything else stops the worker at start. The command line then has `--no-plugin-dirs --plugin-dirs /opt/ytdlp-plugins` and `--extractor-args youtubepot-bgutilhttp:base_url=<url>`; the bot-wall pause and backoff are unchanged. PO tokens printed by name are redacted from worker logs; upstream's own log prints integrity tokens, so its log is kept to 1 MiB x 2 (SECURITY.md I8). yt-dlp keeps self-updating while the plugin stays pinned: a failing canary with the provider on may need a plugin and image bump.
- **2026-10-13 (same-day follow-up to D13):** bumped from **2.0.0 to 2.0.2** (image digest `sha256:d7d34108…ce8472`, plugin SHA-256 `a26b980b…e27ef`) to patch the Critical CVEs in the 2.0.0 image (perl-base, proxy-addr, found by Grype on the homelab). This release was younger than two weeks, so the author approved the under-two-weeks exception for this security patch; the image is a reputable project pinned by digest and the plugin's reviewed entry list was re-verified unchanged (still exactly the two directories and three modules, `check_plugin.py` still prunes the script provider). The 2.0.1/2.0.2 lockfile-refresh note above is superseded: 2.0.2 is now the pin.

### Taken by the coordinator — MusicBrainz matching of multi-artist and featured tracks (D14, 2026-10-13)
- On a real library 88 of 243 archived tracks were `needs_review`. Main cause: the search query sent YouTube Music's comma-joined artists (`"David Guetta, Teddy Swims, Tones And I"`) and the full title with `"(feat. X)"` as Lucene phrases, which match no MusicBrainz recording, so there was nothing to score. Second cause: the artist was compared as one string with the printed credit (`"La Fuga"` vs `"La Fuga & El Drogas"`).
- Query: the title without its "feat." parts and the **first** YouTube Music artist (MusicBrainz's `artist` field holds every credited name). If that strict query finds no candidate at or above the threshold, **one** loose query follows (the title's normalized words, any order; no Lucene specials can survive normalization) and the better candidate wins. At most two searches per track, each retried once on 503/429, all through the 1 req/s limiter.
- Artists compared as sets: YouTube Music's names (split on ", " and " & ") plus the title's featured artists against the credit's names: best similarity of the primary YouTube artist times the mean two-way coverage; the printed strings (with featured artists appended) are also compared and the better value wins. A featured artist missing from the credit (compared without accents, against both the credited and the artist's own name, or found as whole words of the printed credit) caps the artist similarity at 0.5 (total ≤ 0.825), so a solo recording does not stand in for a "feat." version. Only "feat.", "ft." and "featuring" mark featured artists, not "(with X)" ("To Sir (With Love)").
- Titles: "feat." parts are dropped before comparing; bracketed parts are ignored only when both sides name the same version markers (live/directo/vivo, remix, acoustic/acústico/unplugged, extended, instrumental, karaoke, demo), including MusicBrainz's disambiguation (which adds a marker only when the title's bracketed or " - " part does not already name it); when they differ the title similarity is capped at 0.5 (total ≤ 0.775), so a live or remixed take never matches the studio recording, however long the title.
- Weights (0.45/0.35/0.20) and the 0.85 threshold are unchanged. A track still `needs_review` after this is one MusicBrainz does not have (that version, or that length within ~6 s). No re-check of existing `needs_review` tracks in this change: the worker has no database access, so it would need a new internal worker API operation and file moves (a contract change); deleting and re-requesting the track, or "Mark reviewed", remain the way out.

### Taken by the coordinator — recommendations from your listening history (2026-10-13, feat/recommendations)
- The owner wants recommendations "based on what I listen to, from public platform lists, national radios, etc." Full design and the options table are in [`docs/recommendations.md`](docs/recommendations.md).
- **Implemented now** (no new host, no new dependency, no contract break): `GET /ut/v1/recommendations` (`server/src/ultimatetunes/radio/recommendations.py`). Seeds are the caller's own most-played songs (`user_track_stats`) and favourites (`starred_tracks`), already in the database; each seed starts the **existing** YouTube Music watch playlist (`MusicCatalog.radio`, the same call behind `/ut/v1/radio` and `getSimilarSongs2`, through the already-approved `ytmusicapi` host). The seed songs and songs the caller already plays are dropped, so the shelves are genuine discovery; everything is mapped local-first like radio. Two shelves: `recommendedForYou` (what the seed-radios agree on) and `becauseYouPlayed` (one per seed). Separate from `/ut/v1/listen-now` because that one is contractually library-only; recommendations hit YouTube Music and are charged to the caller's bucket. Switches: `UT_RECOMMENDATIONS` (on), `UT_RECOMMENDATION_SEEDS` (4); needs `UT_RADIO` on.
- **Contract**: the endpoint is **additive** and not yet in `contracts/openapi/ut-v1.yaml` (frozen per wave). Its items are the existing `TrackItem`. Proposed `Recommendations`/`RecommendationShelf` schema for the coordinator to add is in `docs/recommendations.md`. Android follow-up (Listen Now section, RF-11) is a later PLAN task. *(Contract added in the follow-up below.)*
- **Proposed, no host approval needed** — just a go-ahead to build: YouTube Music **charts and moods** via `ytmusicapi` (`get_charts(country)`, `get_mood_categories()`/`get_mood_playlists()`), the no-new-host answer to "public / national lists". Needs a small additive catalog addition. *(Built in the follow-up below, 2026-10-13.)*
- **Proposed, needs the owner to approve a new outbound host first**: ListenBrainz (`api.listenbrainz.org`, CC0 data, read-only lookups so no history is sent — note SPEC §9 lists ListenBrainz *scrobbling* as out of scope, this is read-only recommendation lookup) for similar artists/recordings; and national-radio / public-station playlist feeds (one host per station, each with its own ToS check, e.g. `api.radioparadise.com`, `somafm.com`). *(ListenBrainz approved and built in the follow-up below, 2026-10-13; SomaFM and Radio Paradise stay documented-only — see below.)*

### Taken by the coordinator — charts and external recommendation sources (2026-10-13, feat/recommendations-sources)
- The owner approved, 2026-10-13: (2) YouTube Music country charts/moods (no new host), and (3) **server-side** external recommendation sources — the app only talks to the server; the server is the one that fetches the external info. The server may contact new hosts (below); the Android app still talks only to the user's server. Full design and the source-by-source decisions are in [`docs/recommendations.md`](docs/recommendations.md).
- **Charts and moods (built, no new host)**: `GET /ut/v1/charts?country=` (the country's top chart songs) and `GET /ut/v1/moods` + `GET /ut/v1/moods/{moodId}` (YouTube Music "Moods & genres" categories and their songs), through the already-approved `ytmusicapi` (`get_charts`, `get_mood_categories`/`get_mood_playlists`). Mapped local-first like radio, charged to the caller's bucket, cached in the `GuardedCatalog`. Switches `UT_CHARTS` (on), `UT_CHARTS_COUNTRY` (`ZZ`); need `UT_RADIO` on. New `charts` capability in `/ut/v1/server`.
- **ListenBrainz (built, new host `api.listenbrainz.org`, off by default)**: `/ut/v1/recommendations` gains, when `UT_LISTENBRAINZ_RECOMMENDATIONS=true`, a shelf per favourite/most-played artist (those with a MusicBrainz id) of that artist's community-popular recordings (`GET /1/popularity/top-recordings-for-artist/<mbid>`), matched on YouTube Music and mapped local-first. **Only a public artist id is sent, never the caller's listening history.** License/ToS basis: ListenBrainz's ToS defers to the MetaBrainz social contract (factual data is public domain, non-factual data CC0; commercial use is allowed, "charging for the content itself is forbidden"), so a self-hosted, non-commercial, read-only lookup is clearly within terms. Safe-fetch rules as MusicBrainz/covers: exact constant host (no SSRF), HTTPS, `follow_redirects=False`, `trust_env=False`, no credentials, the ListenBrainz User-Agent with a contact URL, 1 req/s (`listenbrainz:global`), 1 MiB body, `UT_LISTENBRAINZ_TIMEOUT_S` 5 s; any failure degrades to no ListenBrainz shelf. Switches: `UT_LISTENBRAINZ_RECOMMENDATIONS` (off), `UT_LISTENBRAINZ_SEEDS` (1), `UT_LISTENBRAINZ_TRACKS` (6), `UT_LISTENBRAINZ_TIMEOUT_S` (5). Host added to CLAUDE.md and the `docs/architecture.md` outbound table.
- **Not wired, left as documented proposals** (verified 2026-10-13 against their live terms): **SomaFM** — its ToS (`somafm.com/contact/tos.html`) explicitly forbids third-party apps/clients, embedding, and *"automated re-posting of playlists and now playing information"*, so it is rejected, not implemented. **Radio Paradise** (`api.radioparadise.com`) — no public API terms permitting reuse of its curated now-playing/playlist feed; uncertain, so left as a proposal. A **generic admin-configurable station feed** (the admin sets a host added to a per-server allowlist) is the recommended path for national radio over hardcoding broadcasters with uncertain ToS; its design is a proposal in `docs/recommendations.md`, not built (a safe generic field-mapping/parse needs its own design).
- **Contract**: `contracts/openapi/ut-v1.yaml` now has `GET /ut/v1/recommendations` (with the `Recommendations`/`RecommendationShelf`/`SourceShelf` schemas — `shelves` added for external sources), `GET /ut/v1/charts` (`Charts`), `GET /ut/v1/moods` (`Moods`/`MoodCategory`) and `GET /ut/v1/moods/{moodId}` (`MoodTracks`), plus the `charts` capability. This closes the reviewer's note that `/ut/v1/recommendations` shipped undocumented. All conform under schemathesis.
- **Android follow-up (not in this PR)**: a "Recommended" / "Charts" section in Listen Now (RF-11), fetching `/ut/v1/recommendations` and `/ut/v1/charts` through `:core:api`, rendering the existing `TrackItem`s. Server-side is complete.
