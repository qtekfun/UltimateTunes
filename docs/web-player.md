<!-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Web player

The api serves a web player for browsers. Open the server's address (`https://music.example.org/`) and sign in with your account; nothing to install. It is a client like the Android app: it talks only to your server, and plays, searches, downloads and edits through the same rules (`server/src/ultimatetunes/web/`).

## What it does

- **Listen Now** (the home page `/`): recently played and recently added albums, your most played songs and one station per favourite song.
- **Radio**: your stations, and a radio for any artist of the library. Any song's menu (···) also starts a radio from that song.
- **Library**: albums (paged), artists (by letter), playlists, favourites.
- **Search**: your library first, then YouTube Music in its own section. A song that is not in your library yet shows its download state ("Not downloaded", "Queued", "Downloading", "In your library", "Download failed"). Playing it fetches it while it plays (streaming while downloading); "Download to the library" in its menu keeps it without playing.
- **Album, artist and playlist pages**: play, shuffle and favourite; artist radio; a song's menu has play next, play later, start radio, download, add to a playlist, go to album and go to artist.
- **Playlists**: create, rename, delete, add a song, remove one, move one up or down (only the owner; public playlists of others are read-only).
- **Import a playlist**: a YouTube Music or YouTube playlist link, or a file (CSV with title and artist, Exportify CSV, Spotify JSON; up to 1 MiB). The page follows the import until the playlist is ready.
- **Player**:
  - a bar pinned at the bottom with play/pause, previous/next, seek, volume, shuffle the queue and repeat (off, all, one);
  - the full-screen **now playing** view with large artwork on a blurred background;
  - **lyrics**: synced lines follow the song; tap a line to jump to it;
  - **up next**: the queue, reordered by dragging or with the arrows, with remove and clear;
  - lock-screen and media-key controls (Media Session API).
  - The music keeps playing while you move between pages.
- **Settings**:
  - theme: light, dark or the system's, kept in this browser;
  - language: English or Spanish, or the browser's;
  - change your password (signs out your other devices);
  - your API keys, listed and revoked (new keys are created in the app or by an administrator; the browser never sees a key);
  - sign out, or sign out every device (every API key revoked and every session ended).

### Keyboard shortcuts

| Key | Action |
| --- | --- |
| Space | Play or pause |
| ← / → | Seek 5 seconds |
| Shift + ← / → | Previous or next song |
| ↑ / ↓ | Volume |
| `/` | Search |
| F | Now playing |
| L | Lyrics |
| Q | Up next |
| Esc | Close the panel or the now-playing view |

Shortcuts are off while you type in a field.

## Security

- **Sign-in**: username and password at `POST /web/login`, checked by `AuthService.verify_password` exactly like `POST /ut/v1/keys`: rate limit and lockout per IP, and per username a lockout for the admin's networks and a growing delay for everyone else (1 s doubling to 5 min, never a lockout), the two counters kept apart. The Traefik examples put a strict per-client rate limit on the form (1/s, burst 5). The web player is not limited to the admin networks.
- **Session**: a signed cookie `ut_web_session`, sent only by this site:
  - flags `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`; lifetime `UT_WEB_SESSION_TTL_S`, 7 days by default;
  - signed with `UT_ADMIN_SESSION_SECRET` under its own salt, so an admin cookie is never a web cookie;
  - "Sign out" ends every web session of the user, copies included (a per-user epoch); a new password ends them too.
  - "Sign out every device" (Settings, after a confirmation box) also revokes every API key of the user and ends its admin sessions; the panel offers the same per user (Users).
- **No API key in the browser**: audio and covers (`/web/stream/{id}`, `/web/cover/{id}`) use the session cookie. Nothing secret is kept in `localStorage` (only the volume and the theme).
- **CSRF**: every change carries the session's token (form field or `X-CSRF-Token` header) and must come from this site (`Sec-Fetch-Site`).
- **Headers** on `/` and `/web/*`:
  - a strict Content Security Policy: scripts, styles, images, audio and connections only from this server; no inline script or style; no framing;
  - `no-store` on pages, `nosniff`, no referrer;
  - a 64 KiB body cap (1 MiB plus the form for playlist files).
- **Same rules as every client**: every page and action calls the OpenSubsonic handler, or the `/ut/v1` one, as the signed-in user. Ownership of playlists and imports, stars, the per-user search and catalog budgets, the download gates and the listener caps all apply. Each user also has a request rate, the same as one API key.
- Templates escape everything. `player.js` writes text with `textContent` only.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `UT_WEB_ENABLED` | `true` | Serve the web player. Off, `/web` answers 404 and `/` only says the server runs. |
| `UT_WEB_SESSION_TTL_S` | `604800` (7 days) | Lifetime of a web session (300 s to 30 days). |
| `UT_ADMIN_SESSION_SECRET` | random per start | Key that signs the cookies (shared with the admin panel). Set it, or sessions end on every restart. |

The session cookie needs HTTPS: `tailscale serve`, Caddy or Traefik in front of the api (`deploy/README.md`). Behind Traefik, `/` and `/web` go through the client routers. You can also put them behind Authelia or keep them on your LAN.

## How it is built

- Server-rendered Jinja templates (`templates/web/`), the vendored HTMX of the admin panel for navigation, and two small scripts with no build step (`static/web/theme.js`, `static/web/player.js`) plus one stylesheet (`static/web/web.css`). No CDN, no external fonts or images.
- Navigation swaps only `#content`. The player and its `<audio>` element sit outside it, so music keeps playing. HTMX keeps no page snapshots, and going back asks the server.
- Code (`server/src/ultimatetunes/web/`):
  - `routes.py`: sessions, CSRF, errors and rendering;
  - `pages.py`: pages;
  - `actions.py`: playlists and stars;
  - `api.py`: the player's JSON calls and media;
  - `account.py`: settings;
  - `importing.py`: imports;
  - `backend.py`: OpenSubsonic handlers called in-process;
  - `security.py`: cookies and headers.
- Tests: `server/tests/web/`.
