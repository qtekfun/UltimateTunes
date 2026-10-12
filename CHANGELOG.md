<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Changelog

All notable changes to UltimateTunes (server and app share one version). Written by hand in the release PR: move the notes of `[Unreleased]` under `## [X.Y.Z] - YYYY-MM-DD` (see RELEASING.md). The Release workflow publishes the notes of the tagged version.

## [Unreleased]

## [0.0.1-rc.1] - 2026-10-12

First pre-release, to validate the release pipeline. Not ready for use yet: the server information endpoint the app checks first, playback, downloads to the library, Listen Now and the admin panel are still being built, so the app cannot connect to a server in this version.

### Added
- Server: Docker image (api + worker, non-root, read-only), health probes, JSON logs with secret redaction, SQLite migrations checked on PostgreSQL.
- Server: user accounts and per-device API keys (Argon2id, revocable keys, lockout, audit log, `ultimatetunes bootstrap-admin`), OpenSubsonic authentication rules.
- Server: search (library + YouTube Music), radio and synced lyrics (LRCLIB) over OpenSubsonic and `/ut/v1`.
- Server: worker image with ffmpeg, Deno and a signature-verified yt-dlp.
- Android: Apple Music-style shell with Connect, Listen Now, Radio and the full-player UI (UI only, verified against the test fake server; no playback yet).
- Signed APK and multi-arch server image published by tag.
