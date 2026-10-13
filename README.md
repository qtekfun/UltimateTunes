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
- **Web player** at the server's home page (`/`): Listen Now, Radio, Library, Search, playlists, playlist import, synced lyrics and a queue, in any browser. You sign in with your password; no API key ever reaches the browser. See [docs/web-player.md](docs/web-player.md).
- **Admin panel** (`/admin`, LAN/Tailscale only by default): users, per-device API keys with a QR code for the app, the download queue, the library, yt-dlp status, audit log and ntfy/webhook notifications.
- **Android app**: the player for your own server, which caches every song it plays to save mobile data, with offline downloads, export to the phone, synced lyrics, radio and playlist import.
- Works with other OpenSubsonic apps that search on the server.
- Multi-user, one revocable key per device. Free software, no ads, no tracking: the app talks only to your server.

<p align="center">
  <img src="docs/images/listen_now_light.png" width="200" alt="Listen Now: stations, recently played albums and top songs">
  <img src="docs/images/album_light.png" width="200" alt="An album with its songs">
  <img src="docs/images/player_dark.png" width="200" alt="The full player, coloured after the cover">
  <img src="docs/images/lyrics_dark.png" width="200" alt="Synced lyrics with the current line highlighted">
</p>

<sub>Screenshots from the app's demo mode: every artist, song and cover is invented.</sub>

Part of the Ultimate family with [UltimateCalendar](https://github.com/qtekfun/UltimateCalendar), [UltimateTasks](https://github.com/qtekfun/UltimateTasks) and [UltimateDeck](https://github.com/qtekfun/UltimateDeck).

> Status: in development. See [SPEC.md](SPEC.md) and [PLAN.md](PLAN.md). For personal use: downloading from YouTube may be against its terms; do not offer this server to others.

## Self-host it on your homelab

UltimateTunes is meant for one household on hardware you control, reached over your LAN or a private network such as Tailscale; there is no public instance. Nothing is published yet (no images, no releases), so you build it yourself:

1. Build the server image: `docker build -f server/Dockerfile -t ghcr.io/qtekfun/ultimatetunes-server:local .`
2. Next to a copy of [`server/compose.yaml`](server/compose.yaml), write a `.env` with `UT_VERSION=local`, `UT_MUSIC_PATH=` your music folder and `UT_BIND=127.0.0.1:8044`, and two random secrets, `secrets/worker_token` and `secrets/admin_session_secret` (`openssl rand -hex 32` each). The file's header explains every setting.
3. `docker compose up -d` (migrations run first), then create the first admin once: `docker compose run --rm api bootstrap-admin <name>` asks for its password. There is no default password ([admin guide](docs/admin-guide.md#first-admin)).
4. Reach it over HTTPS from your devices, for example with `tailscale serve --bg 8044` (for the admin panel behind it, set `UT_TRUSTED_PROXIES` as [deploy/README.md](deploy/README.md) explains). Keep it off the open Internet unless you follow the exposure checklist there.
5. In the admin panel (`/admin`), create an API key for each device (it can show it as a QR code), build the app (`cd android && ./gradlew assembleDebug`, or a signed release, see [RELEASING.md](RELEASING.md)) and connect it: point the phone's camera at the key's QR code and open the link it offers (the app shows the server and asks before connecting), or type the server address and the key on the Connect screen.

More on running it:
- [docs/admin-guide.md](docs/admin-guide.md): running it day to day from the admin panel (users, device keys, the download queue, yt-dlp updates, the audit log).
- [docs/configuration.md](docs/configuration.md): every `UT_*` setting with its default.
- [docs/architecture.md](docs/architecture.md): how the containers, networks and every connection fit together.
- [deploy/README.md](deploy/README.md): reverse proxy examples (Caddy, Traefik, Traefik behind Cloudflare Tunnel with Authelia, Tailscale), trusted proxies, notifications with ntfy, backups, and what to check before exposing the server.
- [docs/web-player.md](docs/web-player.md): the web player.
- [docs/measurements.md](docs/measurements.md): measured idle RAM, search and first-sound times, and a 50,000-track library.
- [SECURITY.md](SECURITY.md): threat model, limits and how to report a vulnerability.

Without a server, a debug build of the app has a demo mode (Connect screen, "Try the demo") with invented music.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Releases: [RELEASING.md](RELEASING.md). Privacy: [PRIVACY.md](PRIVACY.md). Security: [SECURITY.md](SECURITY.md).

## License

[GPL-3.0-or-later](LICENSE).
