<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Changelog

All notable changes to UltimateTunes (server and app share one version). Written by hand in the release PR: move the notes of `[Unreleased]` under `## [X.Y.Z] - YYYY-MM-DD` (see RELEASING.md). The Release workflow publishes the notes of the tagged version.

## [Unreleased]

## [1.0.0-rc.4] - 2026-10-13

Release candidate of 1.0: the web player and the admin panel now carry the app's icon. The app is unchanged since 1.0.0-rc.1.

### Changed
- Web player and admin panel: the logo, favicon and empty-state note are the app's launcher icon (same gradient and note), shown next to the name in the sidebar, the phone top bar and both sign-in pages.

## [1.0.0-rc.3] - 2026-10-13

Release candidate of 1.0 with better MusicBrainz matching. The app is unchanged since 1.0.0-rc.1.

### Fixed
- Server: far fewer songs end up "needs review". The MusicBrainz search no longer sends YouTube Music's comma-joined artists and the "(feat. X)" part of the title as exact phrases (it often found nothing); it searches the title without "feat." and the first artist, then one looser search if needed.
- Server: artists are compared as a set, featured artists included (found even when their accents differ), so "A, B" matches a credit "A & B" or "A feat. B".

### Changed
- Server: with the default threshold, a live, remix or acoustic take never matches the studio recording (and the other way round), and a "feat." version never matches a solo recording; both stay "needs review" instead of getting the wrong tags. Remasters, radio edits and original mixes still match.

### Security
- The repository's command guard lets the coordinator push release tags, but only the tag of the current `VERSION`, from `master`; it refuses deleting, moving or forcing tags (covered by `tools/tests/guard-bash.test.sh`).

## [1.0.0-rc.2] - 2026-10-13

First published release candidate of 1.0. It contains everything listed under 1.0.0-rc.1 (never published) plus the changes below. The app is unchanged since 1.0.0-rc.1; the server gains an optional PO token provider against YouTube's bot check.

### Added
- Server: optional PO token provider for yt-dlp (`pot` Compose profile, `UT_YTDLP_POT_PROVIDER_URL`) against YouTube's "Sign in to confirm you're not a bot". Off by default; only the worker can reach it; the plugin is pinned in the image with only its HTTP provider.
- Docs: step-by-step Tailscale deployment (`deploy/tailscale/`) with a Compose overlay and `.env.example`; a "First admin" section (there is no default account or password).

### Changed
- One-off commands run inside the running api (`docker compose exec api ultimatetunes bootstrap-admin <name>`); `docker compose run --rm api ...` clashes with the api's pinned internal address.

### Security
- Public pages no longer link to the admin panel.
- The Caddy example refuses password sign-in for device keys (`POST /ut/v1/keys`) from outside the LAN and tailnet, like the Traefik examples.
- File secrets in the deployment guides stay readable by the containers (uid 10001) inside an owner-only folder.

## [1.0.0-rc.1] - 2026-10-13

First release candidate of 1.0: the server, the web player, the admin panel and the Android app work end to end. Install it, deploy it and run the SECURITY.md checklist; 1.0.0 will follow from the same code.

### Added
- Server: library scan, browsing and streaming over OpenSubsonic (JSON and XML, Range, cover art sizes, ReplayGain fields, per-user favourites and play counts).
- Server: external YouTube Music tracks stream while they download, then are tagged (MusicBrainz, Cover Art Archive), archived into the library with safe paths, and served from disk afterwards; `needs review` for uncertain tags.
- Server: Listen Now shelves, local-first radio and `getSimilarSongs2`; track request and status endpoints; `ultimatetunes scan-library`.
- Server: download limits per file and per user (track length, file size, queued jobs, bytes per day), a per-user catalog budget, a minimum free disk space that pauses downloads, and notifications when it runs low.
- Server: notifications to ntfy or a webhook, with optional token or basic-auth credentials from environment variables or Docker secrets.
- Web player at `/`: Listen Now, Radio, Library, Search, playlist imports, settings and a now-playing view, with its own sign-in (session cookie; the API key never reaches the browser). `UT_WEB_ENABLED=false` turns it off.
- Admin panel: users and roles, per-device API keys with a QR code, downloads queue, needs-review list, audit log, notifications, yt-dlp update and canary; overview of what needs attention, disk space and budgets; paged and filterable lists; confirmations for destructive actions; English and Spanish.
- "Sign out every device" in the web player (own account) and the admin panel (any user).
- Android: Library, Search, playlists, synced lyrics, imports and settings; Media3 playback with a client cache, queue prefetch and offline downloads; export of songs to the phone; the full player slides as a sheet that follows the finger.
- Android: connect by scanning the admin panel's QR code with the phone's camera app; the app always asks before connecting.
- Deployment examples: Caddy, Traefik, Tailscale, and Traefik behind Cloudflare Tunnel with Authelia.
- Docs: admin guide, configuration reference of every `UT_*` setting, architecture and connections, web player, measurements.

### Changed
- Workers long-poll for jobs, so new downloads start at once.
- SQLite planner statistics are kept fresh automatically.
- Android: one message area above the player, re-tapping a tab returns to its first screen, no white flash at launch in dark mode; new launcher icon and store assets.

### Security
- Hardening for public access: threat model and checklist in SECURITY.md, admin panel limited to the admin networks, split password lockout for admin networks and outside, connection and header limits, pinned egress network for the worker, internal listener bound to the internal network.
- Outside sign-in failures per username cost a growing delay (1 s doubling to 5 min) instead of a lockout; global failure budget and limited concurrent password checks; IPv6 counted per /64.
- Forwarded client addresses are read from the right and stop at the first untrusted hop.
- ffmpeg only accepts the expected containers and codecs; the api's `/tmp` is `noexec`; HEAD requests never start a download.
- Notification targets on loopback, link-local or multicast addresses are refused, and credentials are only sent to the configured host.

## [0.0.1-rc.1] - 2026-10-12

First pre-release, to validate the release pipeline. Not ready for use yet: the server information endpoint the app checks first, playback, downloads to the library, Listen Now and the admin panel are still being built, so the app cannot connect to a server in this version.

### Added
- Server: Docker image (api + worker, non-root, read-only), health probes, JSON logs with secret redaction, SQLite migrations checked on PostgreSQL.
- Server: user accounts and per-device API keys (Argon2id, revocable keys, lockout, audit log, `ultimatetunes bootstrap-admin`), OpenSubsonic authentication rules.
- Server: search (library + YouTube Music), radio and synced lyrics (LRCLIB) over OpenSubsonic and `/ut/v1`.
- Server: worker image with ffmpeg, Deno and a signature-verified yt-dlp.
- Android: Apple Music-style shell with Connect, Listen Now, Radio and the full-player UI (UI only, verified against the test fake server; no playback yet).
- Signed APK and multi-arch server image published by tag.
