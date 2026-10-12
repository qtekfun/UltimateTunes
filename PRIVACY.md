<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Privacy

UltimateTunes has no central servers, no analytics, no ads and no telemetry. **You run the server**; your library, accounts and listening history stay on it.

## The app
- Talks **only to the server you configure**, over HTTPS. It never contacts YouTube, Google or any other service directly.
- Keeps your API key encrypted with the Android Keystore, excluded from Android backups and never written to logs.
- Caches the songs you play, and keeps the ones you download, in its own storage on the phone. Clearing the cache or uninstalling removes them.

## The server
- Stores users (password hashes only, Argon2id), API keys (hashes only), playlists, favourites, play history and the music library.
- Contacts only: **YouTube Music** (search, radio, downloads), **MusicBrainz** and **Cover Art Archive** (tags and covers), **LRCLIB** (lyrics), the **Spotify API** only if the admin configured it for playlist import, and the **notification URL** the admin set (ntfy or webhook). What it sends them: search terms, video ids, song titles/artists/durations — never user names or keys.
- Logs never contain passwords, keys, cookies or full request URLs with credentials.

## Permissions (Android)

| Permission | Why |
|---|---|
| Internet (`INTERNET`), network state | Reach your server; pause downloads without a connection. |
| Notifications (`POST_NOTIFICATIONS`) | The playback controls notification. |
| Foreground service (`FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_MEDIA_PLAYBACK`) | Keep playing with the screen off. |
| Camera (`CAMERA`, optional) | Scan the QR code from the admin panel to connect. Asked only when you tap "Scan". |

*To be reviewed against the real manifest in PLAN T22.*
