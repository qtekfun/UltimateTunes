<!-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Compatibility

Two things live here (PLAN T19): the **manual OpenSubsonic compatibility matrix** for
third-party clients, and the **canary track** the server canary downloads.

Automated checks cover the protocol itself: schemathesis runs every operation of the three
contracts against the real app with real credentials (`server/tests/contract`), and every
OpenSubsonic endpoint is replayed with real data in JSON and XML, the XML compared with the
contract's mapping rule. What only a real client can tell (does it log in, play, seek, show
covers and lyrics) is the matrix below, filled in by hand.

## OpenSubsonic compatibility matrix (manual)

### Setup

1. Start the test stack: `docker compose -f server/compose.test.yaml up --build` (fake YouTube:
   nothing reaches YouTube, external songs are 2 s of silence).
2. Put a few real files of your own in the stack's `/music` and run a scan, so library playback
   is tested with real audio.
3. Create a user and an API key in the admin panel (`/admin`), and reach the server from the
   phone (same LAN, or `tailscale serve`).
4. In the client, add a server with the URL and either:
   - the **API key** (`apiKey`, OpenSubsonic `apiKeyAuthentication`), if the client supports it;
   - otherwise the **username** and the **API key as the password** (`u` + `p`; account
     passwords are refused on `/rest` by design).
   A client that only does token auth (`t` + `s`) cannot log in: the server answers error 42
   (SPEC section 11, T02). Note the exact message the client shows.

Mark each cell **OK**, **Partial** (say what in Notes) or **Fails**, with the client version and
the date. Leave a cell empty if not tested.

### What to test

| # | Area | Steps | Endpoints involved |
|---|------|-------|--------------------|
| 1 | Login | Add the server with the API key; then with user + key as password; then with token auth if the client forces it. | `ping`, `getLicense`, `getOpenSubsonicExtensions`, `tokenInfo` |
| 2 | Library browse | Open Artists, an artist, an album; covers show. | `getMusicFolders`, `getArtists`, `getArtist`, `getAlbum`, `getCoverArt` |
| 3 | Album lists | Recently added / alphabetical / random lists fill. | `getAlbumList2`, `getRandomSongs` |
| 4 | Library playback | Play a library track; seek forward and back; next track starts. | `stream` (Range, 206) |
| 5 | Search | Search an artist name: library results first, YouTube Music results after (`yt:` ids). | `search3` |
| 6 | External playback | Play a search result that is not in the library; it starts within a few seconds; seeking is allowed only if the client handles it (growing file). | `stream` of a `yt:` id |
| 7 | Replay from disk | After the external track finished downloading (admin panel: queue empty), play it again: it now comes from the library. | `getSong`, `stream` |
| 8 | Lyrics | Open lyrics of a track that has them (synced if the client supports it). | `getLyricsBySongId` |
| 9 | Playlists | Create a playlist, add songs (library and external), reorder, remove one, delete the playlist. | `createPlaylist`, `updatePlaylist`, `getPlaylists`, `getPlaylist`, `deletePlaylist` |
| 10 | Stars | Star a song, an album and an artist; see them under favourites; unstar. | `star`, `unstar`, `getStarred2` |
| 11 | Scrobble | Play a track to the end; play counts or history update in the client. | `scrobble` |
| 12 | Radio / similar | Start a radio or "similar songs" from a track. | `getSimilarSongs2` |
| 13 | Play queue sync | Save the queue on the phone, open the client elsewhere (or reinstall), restore it. | `savePlayQueue`, `getPlayQueue` |
| 14 | Downloads / offline | Download an album for offline use in the client and play it in flight mode. | `download` |
| 15 | Errors | Revoke the key in the admin panel while the client is open: the client reports an auth error (44), it does not loop. | any |
| 16 | XML clients | If the client requests XML (no `f=json`), browsing still works. | any |

### Results

| # | Tempo (Android) | Substreamer (Android) | Symfonium (Android) | Notes |
|---|-----------------|-----------------------|---------------------|-------|
| Client version / date | | | | |
| 1 Login | | | | |
| 2 Library browse | | | | |
| 3 Album lists | | | | |
| 4 Library playback | | | | |
| 5 Search | | | | |
| 6 External playback | | | | |
| 7 Replay from disk | | | | |
| 8 Lyrics | | | | |
| 9 Playlists | | | | |
| 10 Stars | | | | |
| 11 Scrobble | | | | |
| 12 Radio / similar | | | | |
| 13 Play queue sync | | | | |
| 14 Downloads / offline | | | | |
| 15 Errors | | | | |
| 16 XML clients | | | | |

Tempo is free software (GPL-3.0) and the reference client for this matrix (PLAN T05, T19);
Substreamer and Symfonium are proprietary, listed because many people use them, and only tested
from the outside (no code of theirs is used or shipped).

## Canary track

The server canary (SPEC section 11) runs daily: in the **api**, one search, one radio, one album
page and one playlist read on YouTube Music (ytmusicapi, uncached); in the **worker**, one
download with the current yt-dlp. Results are stored in `canary_runs`, shown in the admin panel
(yt-dlp page and dashboard), and failed runs go to the admin's notification target. The admin's
"run the canary now" button triggers both sides. `ultimatetunes canary` runs the same checks
once by hand (and the manual GitHub job runs it in the image).

The download is of one fixed track whose music is released under a Creative Commons license,
uploaded by its author:

| Field | Value |
|-------|-------|
| Title | Sauropod Spotting |
| Author and channel | Kevin MacLeod (official channel, `UCSZXFhRIx6b0dFX3xS8L1yQ`, incompetech.com) |
| Video id | `6pEWHaIhxOg` (`https://www.youtube.com/watch?v=6pEWHaIhxOg`); the track is 3:45 in the incompetech.com catalogue |
| License | Creative Commons Attribution 4.0 International (CC BY 4.0), as stated by the author for his catalogue on incompetech.com and on the channel |
| Attribution | "Sauropod Spotting" Kevin MacLeod (incompetech.com), licensed under Creative Commons: By Attribution 4.0, http://creativecommons.org/licenses/by/4.0/ |
| Search query | `Kevin MacLeod Sauropod Spotting` |
| Playlist read | `PLx53r85FKaLyGUec4f9LJUXuCfrFRUV15` (a public playlist of the same channel) |

The canary download is **never kept**: it goes to `/staging/canary/<random>/`, its size is
checked, and the directory is deleted whatever happened. It is never tagged, registered or moved
to `/music`.

If the track or the playlist disappears, or YouTube's own license field for the upload ever
stops saying Creative Commons, point the canary at another CC track of the same author with
`UT_CANARY_VIDEO_ID`, `UT_CANARY_QUERY` and `UT_CANARY_PLAYLIST_ID`, and update this table.
Other settings: `UT_CANARY_ENABLED` (scheduled runs on/off; the admin button always works),
`UT_CANARY_INTERVAL_H` (24), `UT_CANARY_FIRST_DELAY_S` (120), `UT_CANARY_POLL_S` (60, api),
`UT_CANARY_TIMEOUT_S` (300), `UT_CANARY_STATE_FILE` (worker, `/opt/ytdlp/canary-state.json`).
