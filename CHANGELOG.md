<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Changelog

All notable changes to UltimateTunes (server and app share one version). Written by hand in the release PR: move the notes of `[Unreleased]` under `## [X.Y.Z] - YYYY-MM-DD` (see RELEASING.md). The Release workflow publishes the notes of the tagged version.

## [Unreleased]

## [0.0.1-rc.1] - 2026-10-12

First pre-release, to validate the release pipeline. Not ready for daily use yet: playback, downloads to the library and the admin panel are still being built.

### Added
- Server: Docker image (api + worker, non-root, read-only), health probes, JSON logs with secret redaction, SQLite migrations checked on PostgreSQL.
- Server: OpenSubsonic API skeleton with search (library + YouTube Music), radio, synced lyrics (LRCLIB) and playlist import from YouTube Music links or exported files.
- Server: worker image with ffmpeg, Deno and a signature-verified yt-dlp.
- Android: Apple Music-style shell with Connect, Listen Now, Radio and the full-player UI (no playback yet).
- Signed APK and multi-arch server image published by tag.
