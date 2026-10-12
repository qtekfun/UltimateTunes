<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# UltimateTunes

[![CI](https://github.com/qtekfun/UltimateTunes/actions/workflows/ci.yml/badge.svg)](https://github.com/qtekfun/UltimateTunes/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/qtekfun/UltimateTunes?include_prereleases)](https://github.com/qtekfun/UltimateTunes/releases)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)

Your own music streaming service, on your own hardware. Search for any song and it plays at once; from then on it lives in **your** library, tagged with proper metadata and cover art.

- **Server** (Docker): speaks the [OpenSubsonic](https://opensubsonic.netlify.app/) API, keeps a tagged library, and fetches from YouTube Music whatever it does not have yet, streaming it while it downloads.
- **Android app**: an Apple Music-style player that caches every song it plays to save mobile data, with offline downloads, synced lyrics, radio and playlist import.
- Works with other OpenSubsonic apps that search on the server.
- Multi-user, one revocable key per device, admin panel. Free software, no ads, no tracking.

Part of the Ultimate family with [UltimateCalendar](https://github.com/qtekfun/UltimateCalendar), [UltimateTasks](https://github.com/qtekfun/UltimateTasks) and [UltimateDeck](https://github.com/qtekfun/UltimateDeck).

> Status: in development. See [SPEC.md](SPEC.md) and [PLAN.md](PLAN.md). For personal use: downloading from YouTube may be against its terms; do not offer this server to others.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Releases: [RELEASING.md](RELEASING.md). Privacy: [PRIVACY.md](PRIVACY.md). Security: [SECURITY.md](SECURITY.md).

## License

[GPL-3.0-or-later](LICENSE).
