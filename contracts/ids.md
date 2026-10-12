<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Identifiers

Every id that crosses an API boundary (OpenSubsonic, `/ut/v1`, internal worker API) follows these rules. Resolution between virtual and library ids lives in one module (`server/src/ultimatetunes/ids/`, PLAN T06) and must have **100 % test coverage**.

## Library ids: UUIDv7

Every row we create (users, API keys, artists, albums, tracks, playlists, jobs, imports, audit entries, play history) gets a **UUIDv7** (RFC 9562), written as lowercase hyphenated text (36 characters):

```
0199d6a2-4c1e-7b3a-9f10-2a6c8e01b001
```

Why v7 and not v4:
- **Time-ordered.** New rows land at the end of the primary-key B-tree. Inserts stay cheap and pages stay dense on SQLite and PostgreSQL. With v4, inserts land at random positions, and a library of 50,000 tracks plus a play history that grows forever would fragment the indexes.
- **Natural creation order** for free (`ORDER BY id` ≈ `ORDER BY created_at`), handy for audit log and history paging.
- **No coordination.** Several api replicas (phase 5) and the migrator can generate ids without a sequence, which keeps the SQL portable (no `SERIAL`, no `AUTOINCREMENT`).
- The downside is that the id leaks its creation time to the millisecond. That is harmless here: ids are not secrets, and every endpoint checks authorization. Ids must never be used as capabilities.
- Python 3.13 has no `uuid.uuid7()` (it arrives in 3.14). `ids/` carries a small RFC 9562 generator (48-bit Unix ms timestamp, version `7`, variant `10`, random bits from `secrets`) that takes the injectable clock. When the server moves to 3.14, it switches to the stdlib.

**Validation.** When parsing input, accept any lowercase UUID: `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`. Uppercase input is lowercased before the lookup. Generate only v7.

`getMusicFolders` returns a single folder with the integer id `1` (OpenSubsonic types it as an integer).

## Virtual ids (YouTube Music items not in the library)

| Prefix | Item | Payload | Payload regex | Example |
| --- | --- | --- | --- | --- |
| `yt:` | song (video) | YouTube video id | `^[A-Za-z0-9_-]{11}$` | `yt:Qx7Lm2pZ0aB` |
| `ytalbum:` | album | YouTube Music album browse id (currently `MPREb_…`) | `^[A-Za-z0-9_-]{1,64}$` | `ytalbum:MPREb_k3Vd9QmT2xL` |
| `ytartist:` | artist | YouTube Music artist channel id (currently `UC` + 22 chars) | `^[A-Za-z0-9_-]{1,64}$` | `ytartist:UCq8XbV1r0LwZ5mN3tYp7kQe` |

- The prefix is case-sensitive and lowercase. Anything else (an unknown prefix, an empty payload, a payload that fails the regex, URL-encoded tricks, whitespace) is rejected **before** any lookup or subprocess call: OpenSubsonic error `70` (not found), `/ut/v1` problem `invalid_id` (HTTP 400). The video id regex is also enforced again right before yt-dlp is called (SECURITY.md).
- The album and artist regexes are deliberately generic. T03b records the forms seen in practice, and they may only be tightened in a `contracts/<topic>` PR.
- Virtual ids are accepted wherever an id is accepted: `getSong`, `getAlbum` (`ytalbum:`), `getArtist` (`ytartist:`), `stream`, `download`, `getCoverArt`, `getLyricsBySongId`, `getSimilarSongs2`, `star`/`unstar`, `scrobble`, `createPlaylist`/`updatePlaylist`, `savePlayQueue`, and `/ut/v1/tracks/{id}/…`, `/ut/v1/radio?seed=`.
- `getAlbum` of a `ytalbum:` id and `getArtist` of a `ytartist:` id are answered from YouTube Music (cached). Their songs carry `yt:` ids, or the library id when that video is already archived.
- `star` / `unstar` with a `ytalbum:` or `ytartist:` id is not supported in v1 and returns error `0` ("request the album first"). Only songs can be materialized (below).

## Materialization and aliasing

A `yt:` id becomes a library track in two steps, or is merged into one that already exists:

1. **Materialization.** On the first action that means "keep this" (`stream`, `download`, `POST /ut/v1/tracks/{id}/request`, `star`, adding to a playlist, a matched import item, a `scrobble`), the api creates a `tracks` row with a new UUIDv7, `status = pending`, the YouTube Music metadata (title, artist, album, duration, album browse id, channel id, thumbnail URL), and `yt_video_id`. It also creates the alias `track_aliases('yt:<videoId>' → <uuid>)` and, unless one already exists, the download job (deduplicated per video id: one job row per track). All of this happens in one transaction, so two concurrent requests end up with the same track and the same job.
2. **Archive** (internal worker API: register, move, complete). The worker registers the tagged file while it is still in staging. The api fills the pending track's `artist_id`, `album_id` and file columns and reserves the library path on the job. The worker moves the file into `/music`, and `complete` sets `path` and `status = ready`.
3. **Duplicate recording.** If register finds that the video is the same recording (same MusicBrainz recording id) as a `ready` track already in the library, it answers `merged: true` with the existing track, and the file never goes into `/music`. `complete` then applies the merge in **one transaction**:
   - the alias `yt:<videoId>` is pointed at the existing track (`track_aliases.track_id`);
   - the pending track's stars, playlist entries, play history, play statistics and import items move to the existing track (a user who has both keeps one star and the summed statistics);
   - the pending track becomes `status = merged` with `merged_into` = the existing track. Its row is **kept**: its job row still references it, so no job (leased or not) is ever deleted by a cascade, and `UNIQUE (kind, track_id)` on `jobs` stays valid;
   - the job becomes `ready`.
   The decision is recorded on the job at register and applied only at complete, so a job that fails after register changes nothing. Repeating `complete` with the same lease returns the stored result and does nothing else. `merged_into` always points at a track that is not itself merged.

Saving a play queue (`savePlayQueue`) and viewing search results **never** materialize anything. The queue stores raw item ids and resolves them when read.

### Resolution rules (server)
- `yt:<v>` → `track_aliases` hit → library track (any status). Miss → external item, answered from the catalog (`MusicCatalog`, cached).
- A library UUID of a `merged` track resolves to its `merged_into` track (one hop). Clients that kept the old UUID keep working.
- Responses always prefer the library id once the track is `ready`. `search3`, radio and `getAlbum(ytalbum:…)` replace a `yt:` result with the library item, so the same song never appears twice in a list. While the track is `pending`, responses keep the `yt:` id (`/ut/v1` adds `isExternal: true` and `libraryState: pending`).
- Aliases are kept forever. A `yt:` id that was ever returned keeps working, and it plays the archived file once it is ready.

### Client rules (Android and third-party clients)
- **Treat every id as an opaque string.** Never parse it, except that the Android app may check the `yt:` prefix to show "not in library yet" when `isExternal` is missing (third-party responses).
- After `GET /ut/v1/tracks/{id}/status` returns `state: ready` with a `trackId`, the app **should** replace the `yt:` id with `trackId` in its own database (favourites, offline downloads, queue). Keeping the old id still works.
- **Cache keys.** The bytes streamed while downloading (`yt:` id, the raw download, untagged) are **not** the archived file (tagged, with ReplayGain, a different size). The Media3 cache key is the id that was requested. The client never mixes byte ranges of a `yt:` entry with the library id. When it switches to the library id, it starts a new cache entry, and the old one simply ages out of the LRU.

## Cover art ids

`coverArt` values are opaque too. They are accepted by `getCoverArt` and are never file paths. In v1 `getCoverArt` may ignore `size` and return the stored image as is (no image library is approved yet).

| Form | Image |
| --- | --- |
| `al-<albumUuid>` | Album cover (`cover.jpg` next to the album in `/music`). Library songs use their album's id. |
| `ar-<artistUuid>` | Artist image |
| `pl-<playlistUuid>` | Playlist mosaic or first track's cover |
| `yt:<videoId>` | Thumbnail of the video (pending or external songs), see below |
| `ytalbum:<browseId>` | External album thumbnail |
| `ytartist:<channelId>` | External artist thumbnail |

**YouTube image hosts** (approved by the author on 2026-10-12, SPEC §11): `i.ytimg.com`, `lh3.googleusercontent.com`, `yt3.ggpht.com` and `yt3.googleusercontent.com`, over HTTPS only.
- `getCoverArt` with a virtual id (`yt:`, `ytalbum:`, `ytartist:`) fetches the thumbnail URL the catalog returned (never a URL built from client input), only over HTTPS and only if its host is on that exact list. **Redirects are not followed** (any 3xx answers error `70`); a non-`image/*` content type or a body over 5 MiB (enforced while streaming, not only from `Content-Length`) also answers error `70`.
- Fetched images are cached on disk in one dedicated directory under `/data` (owned by the api, not the staging store), keyed by the virtual id, with a TTL (default 30 days) and a total-size cap (default 512 MiB, oldest evicted first). Both are settings of the area that implements `getCoverArt` (T05).
- The worker may use the YouTube thumbnail as a cover fallback when Cover Art Archive has none, with the same rules (HTTPS, exact hosts, no redirects, image type, 5 MiB); Cover Art Archive stays first.
- No other host is ever contacted (SSRF rule, SECURITY.md).

## API key format

`utk_` + 43 characters of unpadded base64url (32 random bytes = 256 bits), e.g. `utk_EXAMPLEexampleEXAMPLEexampleEXAMPLEexampleE` (examples always use this obviously fake value). Only the SHA-256 hex digest is stored (`api_keys.key_hash`), plus the first 12 characters (`utk_` + 8) as the display `prefix`. A slow hash is unnecessary for a 256-bit random secret, and SHA-256 keeps every authenticated request cheap. The `utk_` prefix lets gitleaks and the log redactor spot leaked keys.
