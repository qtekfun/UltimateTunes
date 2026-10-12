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

- **api**: OpenSubsonic + `/ut/v1` + admin panel `/admin`; owns the database; serves files; the only service clients reach.
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
2. Track not in the library (`yt:<videoId>`) → the api asks for a job (deduplicated per video id) and **streams the growing file from `/staging` while the worker downloads it** (no seek on that first play). When done, the track is tagged and archived; the `yt:` id becomes an alias of the library id; later plays come from the file.

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
`POST /ut/v1/imports` with a YouTube Music or Spotify playlist URL; each track matched on YouTube Music and requested; progress per import; result becomes a user playlist. Spotify needs credentials configured by the admin (T03 decides the method); without them the option is hidden.

### RF-09 Favourites, playlists, history
Per user: stars, playlists, play history (scrobble), play queue saved across devices. Files are shared between users (a track is downloaded once).

### RF-10 Admin panel
`/admin`, admin role only: users (create, disable, role), API keys (list, last use, revoke), download queue (state, retry, cancel), library (space used/free, `needs_review`, delete track/album), yt-dlp (version, last canary result, update now), audit log, notifications (optional ntfy topic or webhook on failed download/canary). Jinja + vendored HTMX, en/es.

### RF-11 Android client
Connect (server URL + API key, or QR shown in the admin panel), Listen Now, Radio, Library (artists, albums, playlists, favourites, downloads), Search (one list, external items marked "not in library yet"), full player (queue, lyrics, radio), import, settings (keys, cache size, offline downloads, quality info). Details in §5.

### RF-12 Client cache and offline
Every play goes through Media3 `SimpleCache` (LRU, **2 GB** default, configurable). **Prefetch**: the next track in the queue is requested on the server (so it is ready) and its first bytes preloaded. Explicit **offline downloads** (track, album, playlist) live apart from the cache and are never evicted. Offline: only cached and downloaded content is browsable; search needs the server.

### RF-13 Notifications from the server
Optional push of failed downloads/canary to an ntfy topic or webhook configured by the admin. The app shows playback notification only (MediaSession).

## 5. Android client: interface (Apple Music style)
Own design inspired by Apple Music, **without** Apple logos, icons, fonts or assets.
- Bottom bar with 4 tabs: **Listen Now, Radio, Library, Search**; a **mini player** pinned above it that expands into the full player with a shared-element transition.
- Large rounded artwork grids, bold titles, generous spacing; large-title headers that collapse on scroll.
- Full player: big artwork, **colours from the artwork** (Palette) and a blurred artwork background, scrubber, queue sheet.
- Lyrics full-screen, active line highlighted, auto-scroll, tap a line to seek (when the track is in the library).
- Light and dark themes; English and Spanish; large fonts and TalkBack.
- Gestures: swipe the mini player to skip, long-press for context menu (play next, add to playlist, download, go to album/artist).

## 6. Non-functional requirements
- First sound of an **external** track: target ≤ 5 s on the home connection (measured in T03 and T21). Library track: ≤ 1 s.
- `search3` with external results: ≤ 2 s p95 (TTL cache for repeated queries).
- Server idle footprint: ≤ 200 MB RAM for api + worker.
- Approved server dependencies: fastapi, uvicorn, pydantic, pydantic-settings, httpx, ytmusicapi, yt-dlp, mutagen, argon2-cffi, jinja2, python-multipart, itsdangerous; phase 5 only: psycopg (PostgreSQL), redis; dev: pytest, pytest-cov, anyio, respx, schemathesis, openapi-spec-validator, ruff, mypy, bandit, pip-audit. System: ffmpeg and the JS runtime yt-dlp needs (T03 confirms which).
- Approved Android dependencies: the UltimateCalendar set (Compose, Material 3, Hilt, Room, DataStore, WorkManager, kotlinx-serialization, Coroutines) plus Media3 (exoplayer, session, datasource-okhttp, ui-compose if needed), OkHttp, Coil, androidx.palette. Anything else: ask.

## 7. Security
- Threat model and checklist in `SECURITY.md` (T22 completes it). Highlights: API keys hashed and revocable; Argon2id; rate limit per IP and per key with temporary lockout; audit log; strict input validation (video ids, URLs allowlist, path sanitizer); subprocesses with argument lists; worker isolated from the DB and from inbound traffic; non-root, read-only containers; secrets from env/Docker secrets; logs redact secrets.
- Transport: HTTPS everywhere outside localhost. PoC through `tailscale serve`. Public phase: reverse proxy (Caddy example) with TLS, HSTS, request limits; `/admin` stays LAN/Tailscale-only unless the admin opts in.
- Android: API key stored encrypted with the Android Keystore; cleartext traffic forbidden in release (debug allows the emulator host only); no secrets in logs.

## 8. Quality and CI
- CI on every PR: server (ruff, mypy, pytest with coverage, bandit, pip-audit), contracts (OpenAPI validation, migrations apply, schemathesis against the app), Android (`./gradlew check assembleDebug`), Docker (build, Trivy scan, `compose.test.yaml` smoke), gitleaks, store texts, PR title.
- Nightly: canary (real ytmusicapi search + yt-dlp download of one fixed Creative Commons track), pip-audit, Android instrumented tests on an emulator against the test compose stack.
- Release on tag: signed APK + multi-arch (amd64, arm64) image on GHCR, GitHub Release with notes, APK SHA-256. Updates on the phone through Obtainium.
- Coverage: ≥ 85 % server and Android core; 100 % in the critical areas listed in CLAUDE.md.

## 9. Out of scope (v1)
Android Auto, iOS client, plain YouTube as a source, transcoding, ListenBrainz/Last.fm scrobbling, OIDC/SSO, Chromecast, Play Store / F-Droid submission, public sharing links, podcasts. **Kubernetes deployment, PostgreSQL and Redis implementations** are designed for (§3) but delivered after 1.0 (PLAN phase 5).

## 10. Known risks
- **YouTube changes break yt-dlp or ytmusicapi** (PO tokens, JS challenges, IP blocks): worker isolated, yt-dlp auto-update, nightly canary with alert, `Downloader`/`MusicCatalog` interfaces to swap implementations. T03 measures the current state.
- **Streaming a growing file**: no seek on the first play; clients that insist on Range on an unknown length must not break (T03 tests ExoPlayer and one third-party client).
- **MusicBrainz match quality** and its 1 req/s limit: queue with rate limit, keep YT Music data when unsure.
- **Spotify playlist reading** depends on Spotify's developer API rules: T03 decides; the feature can stay disabled.
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
